"""
Conferência de Fornecedores × Compras DFe.

O relatório antigo (routes/conf_fornecedores.py) tira a dívida do PEDIDO, que
é digitado por gente. Aqui a dívida vem da NOTA que a SEFAZ entregou — o que
foi comprado de verdade. O lado do pagamento continua sendo o do usuário
(bank_transactions DEBIT vindas do OFX, com fornecedor_id apontado à mão),
porque acontece de pagar para um CNPJ e a nota vir de outro: o usuário pendura
o pagamento no fornecedor certo e aqui os dois lados se encontram.

SINAL DO SALDO (o mesmo do relatório antigo, pra ler igual):
  positivo = crédito nosso  -> pagamos e a nota ainda não veio (adiantado)
  negativo = dívida nossa   -> a nota veio e ainda não pagamos

O fluxo normal da casa é pagar primeiro e a nota sair depois (no mesmo dia ou
dias à frente), então saldo positivo é rotina, não erro. Por isso o saldo é
ACUMULADO: o que ficou de trás entra como saldo anterior, senão todo
adiantamento viraria diferença falsa a cada período.

Rota:
  GET /relatorios/conf_fornecedores_dfe
"""
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_fornecedores_dfe', __name__, url_prefix='/relatorios')


# ──────────────────────────────────────────────────────────────────────────────
# Pedaços de SQL reaproveitados
# ──────────────────────────────────────────────────────────────────────────────

# O CNPJ do cadastro vem de formulário e pode ter máscara; o da nota vem do XML
# e é só dígito. Normaliza os dois lados antes de comparar.
_CNPJ_FORN = "LPAD(REPLACE(REPLACE(REPLACE(REPLACE(f.cnpj,'.',''),'/',''),'-',''),' ',''),14,'0')"
_CNPJ_NOTA = "LPAD(d.emit_cnpj,14,'0')"


def _raiz_de(alias):
    """Os 8 primeiros dígitos do CNPJ do cadastro `alias` — a raiz da empresa."""
    return ("LEFT(LPAD(REPLACE(REPLACE(REPLACE(REPLACE({a}.cnpj,'.',''),'/',''),"
            "'-',''),' ',''),14,'0'),8)").format(a=alias)


# ─── RAIZ E GRUPO ─────────────────────────────────────────────────────────────
# Casar pelo CNPJ inteiro separava matriz de filial: a nota saía da filial e o
# pagamento estava pendurado na matriz, então o MESMO fornecedor aparecia duas
# vezes — devendo em cima, adiantado embaixo. Media na base: ALE (/0010 contra
# /0001), INTEGRACAO (/0011 contra /0005) e NEXTA (/0006 contra /0013), R$ 543
# mil parados por isso. A comparação passa a ser pela RAIZ: matriz e filiais
# viram um só cadastro na conferência.
#
# Raiz diferente é outra doença, e a raiz nunca a cura: paga-se para a RODOIL e
# o produto vem da TOWER; paga-se a RODOBRAS COMERCIALIZADORA e a nota vem da
# DISTRIBUIDORA RODOBRAS (raízes 57.370.381 e 33.777.842). Para esses,
# fornecedor_grupo_raiz aponta cada raiz do grupo para um fornecedor TITULAR e
# o relatório trata o grupo inteiro como um fornecedor só.
_RAIZ_FORN = _raiz_de('f')
_RAIZ_NOTA = "LEFT(%s,8)" % _CNPJ_NOTA

# Mapa raiz -> fornecedor que representa o grupo, usado como tabela derivada em
# todas as consultas. MIN(id) elege um dono para a raiz (sem isso, matriz e
# filial cadastradas duplicariam a nota no JOIN e inflariam o total); o LEFT
# JOIN troca esse dono pelo titular quando a raiz pertence a um grupo.
#
# As raízes vêm de DOIS lugares e o UNION é obrigatório: só o cadastro deixaria
# de fora a raiz que ninguém cadastrou — justamente a DISTRIBUIDORA RODOBRAS,
# que emite a nota enquanto o dinheiro sai para a irmã cadastrada.
_MAPA = """(
        SELECT r.raiz AS raiz, COALESCE(g.titular_id, r.id) AS forn_id
          FROM (SELECT u.raiz AS raiz, MIN(u.id) AS id
                  FROM (SELECT LEFT(LPAD(REPLACE(REPLACE(REPLACE(REPLACE(fz.cnpj,'.',''),
                                     '/',''),'-',''),' ',''),14,'0'),8) AS raiz,
                               fz.id AS id
                          FROM fornecedores fz
                         WHERE fz.cnpj IS NOT NULL AND fz.cnpj <> ''
                        UNION ALL
                        SELECT gz.raiz AS raiz, gz.titular_id AS id
                          FROM fornecedor_grupo_raiz gz) u
                 GROUP BY u.raiz) r
          LEFT JOIN fornecedor_grupo_raiz g ON g.raiz = r.raiz
      ) m"""

# Junta o mapa ao cadastro titular. Vem depois de uma tabela que já exponha a
# raiz a comparar — por isso cada consulta diz com o que `m.raiz` casa.
_JOIN_TITULAR = "JOIN fornecedores f ON f.id = m.forn_id"

_DDL_GRUPO = """
CREATE TABLE IF NOT EXISTS fornecedor_grupo_raiz (
    raiz       CHAR(8)   NOT NULL PRIMARY KEY,
    titular_id INT       NOT NULL,
    criado_em  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por INT       NULL,
    KEY ix_titular (titular_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


# ─── NOTA INCLUÍDA À MÃO ──────────────────────────────────────────────────────
# A captura da SEFAZ só entrega de 07/07 em diante, mas o pagamento de dentro do
# período às vezes quita nota de ANTES — a MAX pagou R$ 9.090,00 em 07/07 pela
# NF-e 446307 de 27/06, que a SEFAZ nunca entregou. Sem a nota, o fornecedor
# fica eternamente "adiantado" no valor dela.
#
# `entrada_manual = 1` marca a nota que o usuário trouxe pelo XML: ela IGNORA o corte e
# entra na conferência mesmo sendo mais antiga. Só essas — as 7 notas de junho
# que a captura pegou por acaso continuam de fora, porque o pagamento delas
# também está fora e incluí-las inventaria dívida.
def _tag(el):
    """Nome da tag sem o namespace (o XML da NF-e vem todo com xmlns)."""
    t = el.tag
    return t.rsplit('}', 1)[-1] if '}' in t else t


def _txt(pai, nome):
    if pai is None:
        return None
    for el in pai.iter():
        if _tag(el) == nome:
            return (el.text or '').strip() or None
    return None


def _no(raiz, nome):
    for el in raiz.iter():
        if _tag(el) == nome:
            return el
    return None


def _so_digitos(v):
    return ''.join(c for c in (v or '') if c.isdigit())


def _dh_para_mysql(s):
    """'2026-06-27T07:16:26-03:00' -> '2026-06-27 07:16:26'."""
    if not s:
        return None
    s = s.strip().replace('T', ' ')
    return s[:19] if len(s) >= 19 else None


def _ler_nfe(xml_txt):
    """Lê o essencial de uma NF-e do XML, só com a biblioteca padrão.

    Não usa o parser de scripts/processa_dfe.py de propósito: aquele importa
    consulta_sefaz, que valida variáveis de ambiente já no import e derrubaria
    esta rota por um motivo que não é dela. Aqui o XML é o único insumo.
    """
    root = ET.fromstring(xml_txt.encode('utf-8'))

    inf = _no(root, 'infNFe')
    chave = _so_digitos((inf.get('Id') if inf is not None else '') or '')
    if len(chave) != 44:
        chave = _so_digitos(_txt(root, 'chNFe'))
    if len(chave) != 44:
        raise ValueError('não achei a chave de 44 dígitos (infNFe/chNFe)')

    ide = _no(root, 'ide')
    emit = _no(root, 'emit')
    dest = _no(root, 'dest')
    tot = _no(root, 'ICMSTot')
    prot = _no(root, 'protNFe')

    cstat = _txt(prot, 'cStat') if prot is not None else None
    situacao = 'denegada' if cstat in ('110', '301', '302', '303') else 'autorizado'

    itens = []
    for det in root.iter():
        if _tag(det) != 'det':
            continue
        prod = _no(det, 'prod')
        if prod is None:
            continue
        itens.append({
            'n_item': int(det.get('nItem') or (len(itens) + 1)),
            'produto_xml': (_txt(prod, 'xProd') or '')[:160] or None,
            'cprod_fornecedor': (_txt(prod, 'cProd') or '')[:60] or None,
            'cean': (_txt(prod, 'cEAN') or '')[:20] or None,
            'cod_anp': _txt(prod, 'cProdANP'),
            'ncm': _txt(prod, 'NCM'),
            'unidade': (_txt(prod, 'uCom') or '')[:6] or None,
            'quantidade': _txt(prod, 'qCom'),
            'valor_unitario': _txt(prod, 'vUnCom'),
            'valor_total': _txt(prod, 'vProd'),
        })

    # Duplicata (vencimento por parcela). Combustível quase nunca traz <dup> —
    # lista vazia é caso normal, não erro.
    dups = []
    for dup in root.iter():
        if _tag(dup) != 'dup':
            continue
        venc = (_txt(dup, 'dVenc') or '')[:10] or None
        dups.append({'n_dup': (_txt(dup, 'nDup') or '')[:60] or None,
                     'vencimento': venc, 'valor': _txt(dup, 'vDup')})
    for i, d in enumerate(dups, 1):
        if not d['n_dup']:
            d['n_dup'] = '%03d' % i

    nome_emit = _txt(emit, 'xNome')
    return {
        'chave': chave,
        'modelo': _txt(ide, 'mod'),
        'numero': _txt(ide, 'nNF'),
        'serie': _txt(ide, 'serie'),
        'dh_emissao': _dh_para_mysql(_txt(ide, 'dhEmi')),
        'emit_cnpj': _so_digitos(_txt(emit, 'CNPJ')) or None,
        'emit_nome': nome_emit[:160] if nome_emit else None,
        'dest_cnpj': (_so_digitos(_txt(dest, 'CNPJ') or _txt(dest, 'CPF'))
                      or None),
        'valor_total': _txt(tot, 'vNF') if tot is not None else _txt(root, 'vNF'),
        'situacao': situacao,
        'itens': itens,
        'duplicatas': dups,
    }


_SQL_ITEM_MANUAL = (
    "INSERT INTO dfe_itens "
    "(documento_id, n_item, produto_xml, cprod_fornecedor, cean, cod_anp, "
    " ncm, unidade, quantidade, valor_unitario, valor_total) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  produto_xml=VALUES(produto_xml), cprod_fornecedor=VALUES(cprod_fornecedor), "
    "  cean=VALUES(cean), cod_anp=VALUES(cod_anp), ncm=VALUES(ncm), "
    "  unidade=VALUES(unidade), quantidade=VALUES(quantidade), "
    "  valor_unitario=VALUES(valor_unitario), valor_total=VALUES(valor_total)"
)

_SQL_DUP_MANUAL = (
    "INSERT INTO dfe_duplicatas (documento_id, n_dup, vencimento, valor) "
    "VALUES (%s,%s,%s,%s) "
    "ON DUPLICATE KEY UPDATE vencimento=VALUES(vencimento), valor=VALUES(valor)"
)


def _garante_coluna_manual(conn):
    """Cria dfe_documentos.entrada_manual se faltar. Só adiciona; default 0.

    O nome NAO e `manual`: virou palavra reservada no MySQL 8.0.31 e o ALTER
    morre com erro de sintaxe que nao diz o motivo.
    """
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = 'dfe_documentos'
                      AND column_name = 'entrada_manual'""")
    if not cur.fetchone()[0]:
        cur.execute("ALTER TABLE dfe_documentos "
                    "ADD COLUMN entrada_manual TINYINT(1) NOT NULL DEFAULT 0")
        conn.commit()
    cur.close()


def _garante_coluna_pago_antes(conn):
    """Cria as colunas do "antes do corte" se faltarem. So adiciona.

    pago_antes_corte = 1: a nota INTEIRA foi paga antes do corte — sai da
    conta (lista, saldo, contadores) mas fica registrada e da pra desfazer.

    quitado_pre_corte = R$: so uma PARTE (parcelas pagas antes do corte).
    A nota fica na tela — ela ancora os pagamentos de dentro do periodo —
    mas esse valor conta como ja resolvido: abate falta, saldo e comprado.
    """
    cur = conn.cursor()
    for coluna, ddl in (
            ('pago_antes_corte', "TINYINT(1) NOT NULL DEFAULT 0"),
            ('quitado_pre_corte', "DECIMAL(12,2) NOT NULL DEFAULT 0")):
        cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                        WHERE table_schema = DATABASE()
                          AND table_name = 'dfe_documentos'
                          AND column_name = %s""", (coluna,))
        if not cur.fetchone()[0]:
            cur.execute("ALTER TABLE dfe_documentos ADD COLUMN %s %s"
                        % (coluna, ddl))
            conn.commit()
    cur.close()


def _garante_tabela_pg_pre_corte(conn):
    """Cria dfe_pagamento_pre_corte se faltar. Tabela propria de proposito:
    bank_transactions e do modulo do banco inteiro — esta marca ("liquidou
    compra anterior ao corte, fora desta conta") e so desta tela."""
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS dfe_pagamento_pre_corte (
                     transacao_id BIGINT NOT NULL PRIMARY KEY,
                     criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                   )""")
    conn.commit()
    cur.close()


def _pagamentos_ocultos(conn, empresa_ids, fornecedor_ids):
    """Os pagamentos que o usuario tirou da conta, por fornecedor (rodape
    cinza com desfazer)."""
    where = ["bt.tipo = 'DEBIT'", "bt.fornecedor_id IS NOT NULL",
             """EXISTS (SELECT 1 FROM dfe_pagamento_pre_corte pc
                         WHERE pc.transacao_id = bt.id)"""]
    params = []
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id AS fornecedor_id, bt.id, bt.data_transacao,
               COALESCE(bt.valor,0) AS valor, bt.descricao
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores fp  ON fp.id = bt.fornecedor_id
          JOIN %s ON m.raiz = %s
         WHERE %s
         ORDER BY bt.data_transacao
    """ % (_MAPA, _raiz_de('fp'), " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    saida = defaultdict(list)
    for r in rows:
        saida[r['fornecedor_id']].append({
            'id': r['id'], 'valor': float(r['valor'] or 0),
            'descricao': (r['descricao'] or '')[:60],
            'data': _dia(r['data_transacao'])})
    return dict(saida)


def _notas_ocultas(conn, empresa_ids, fornecedor_ids):
    """As notas que o usuario tirou da conta, por fornecedor (pro rodape
    cinza com o desfazer — sem isso a nota sumiria sem rastro)."""
    where = ["d.tipo = 'NFe'", "d.situacao = 'autorizado'",
             "COALESCE(d.pago_antes_corte, 0) = 1"]
    params = []
    _em("d.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id AS fornecedor_id, d.id, d.numero, d.serie,
               COALESCE(d.valor_total,0) AS valor, d.dh_emissao
          FROM dfe_documentos d
          JOIN %s ON m.raiz = %s
         WHERE %s
         ORDER BY d.dh_emissao
    """ % (_MAPA, _RAIZ_NOTA, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    saida = defaultdict(list)
    for r in rows:
        saida[r['fornecedor_id']].append({
            'id': r['id'], 'numero': r['numero'], 'serie': r['serie'],
            'valor': float(r['valor'] or 0), 'data': _dia(r['dh_emissao'])})
    return dict(saida)


def _garante_tabela_grupo(conn):
    """Cria fornecedor_grupo_raiz se faltar. Só cria — não altera nem apaga."""
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = 'fornecedor_grupo_raiz'""")
    if not cur.fetchone()[0]:
        cur.execute(_DDL_GRUPO)
        conn.commit()
    cur.close()

# O que conta como compra nossa:
#   - NF-e (CT-e mora em dfe_cte e é frete, não compra);
#   - autorizada (cancelada/denegada não gera dívida);
#   - não pode ser 100% "ignorar" (a marcação de "esta nota não é nossa").
# Resumo (resNFe) não tem item nenhum e PASSA de propósito: ele já traz o valor
# total e portanto já é dívida, mesmo antes do XML completo chegar.
_FILTRO_NOTA = """
        d.tipo = 'NFe'
    AND d.situacao = 'autorizado'
    AND COALESCE(d.pago_antes_corte, 0) = 0
    AND NOT EXISTS (
          SELECT 1 FROM dfe_itens i
           WHERE i.documento_id = d.id
          HAVING SUM(CASE WHEN i.categoria = 'ignorar' THEN 0 ELSE 1 END) = 0
        )
"""

# ─── CORTE ────────────────────────────────────────────────────────────────────
# A captura DFe só tem nota desta data em diante; o OFX tem pagamento de muito
# antes. Sem corte, o saldo acumulado somaria meses de pagamento contra ZERO
# nota e todo fornecedor apareceria com um adiantamento gigante e falso.
# Os DOIS lados são cortados aqui — nota e pagamento — pra a conta fechar.
#
# 07/07/2026 é onde a série de notas fica CONTÍNUA, medido na base:
#   - primeira linha gravada em dfe_documentos: 08/07/2026 17:52
#   - a SEFAZ entregou notas a partir de 07/07
#   - antes disso só existem 7 notas soltas (1 e 2 de junho) e um vazio de
#     03/06 a 06/07 — período em que o pagamento apareceria sem a nota.
#
# NÃO copie daqui o corte da tela "Pendente pra Descer" (01/08): aquele é de
# outro assunto (estoque) e usar ele aqui escondia as 88 notas de julho
# enquanto mostrava os pagamentos de julho, inventando ~R$ 27 mil de dívida.
DATA_CORTE_DFE = '2026-07-07'

# Quantos dias ANTES do corte olhar em busca de pagamento que provavelmente
# cobre nota de depois do corte (a casa paga e a nota sai dias à frente).
# Esses pagamentos NÃO entram no saldo — entrariam sem a nota correspondente
# do outro lado e o erro só inverteria de sinal. Aparecem como aviso no card
# do fornecedor, pra quem confere bater no olho e decidir.
JANELA_ANTES_CORTE = 60


def _periodo_padrao():
    """Do corte até hoje — "de agosto em diante".

    Não é o mês corrente de propósito: como se paga antes da nota sair, fechar
    no dia 1º cortaria o pagamento de um lado e a nota do outro. Enquanto a
    captura for curta, ver tudo de uma vez é o que dá o controle real.
    """
    return DATA_CORTE_DFE, date.today().isoformat()


def _ids(chave):
    """Lê uma lista de ids do querystring, descartando o que não for número."""
    return [v for v in request.args.getlist(chave) if v.isdigit()]


def _em(campo, valores, where, params):
    if valores:
        where.append("%s IN (%s)" % (campo, ','.join(['%s'] * len(valores))))
        params.extend(valores)


# ──────────────────────────────────────────────────────────────────────────────
# Consultas
# ──────────────────────────────────────────────────────────────────────────────

def _empresas(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("""SELECT id, COALESCE(nome_fantasia, razao_social) AS nome
                     FROM clientes ORDER BY nome""")
    rows = cur.fetchall()
    cur.close()
    return rows


def _fornecedores(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("""SELECT id, razao_social, cnpj FROM fornecedores
                    ORDER BY razao_social""")
    rows = cur.fetchall()
    cur.close()
    return rows


def _mapa_cadastros(conn):
    """Como cada cadastro entra na conferência.

    Devolve (canonico, nomes, raizes):
      canonico[fornecedor_id] = id do fornecedor que representa o grupo
      nomes[canonico_id]      = razões sociais do grupo, titular primeiro
      raizes[canonico_id]     = raízes que caem nesse grupo
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT f.id, f.razao_social, f.cnpj, m.forn_id, m.raiz
          FROM fornecedores f
          JOIN __MAPA__ ON m.raiz = __RAIZ_F__
         ORDER BY (f.id = m.forn_id) DESC, f.razao_social
    """.replace('__MAPA__', _MAPA).replace('__RAIZ_F__', _RAIZ_FORN))
    rows = cur.fetchall()
    cur.close()

    canonico, nomes, raizes = {}, defaultdict(list), defaultdict(set)
    for r in rows:
        canonico[r['id']] = r['forn_id']
        nome = (r['razao_social'] or '').strip()
        if nome and nome not in nomes[r['forn_id']]:
            nomes[r['forn_id']].append(nome)
        raizes[r['forn_id']].add(r['raiz'])

    # Raiz agrupada que não tem cadastro nenhum (a nota órfã que você pendurou
    # num fornecedor): o nome vem da própria nota, senão o card esconderia
    # quem de fato emitiu.
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT g.raiz, g.titular_id,
               (SELECT d.emit_nome FROM dfe_documentos d
                 WHERE LEFT(LPAD(d.emit_cnpj,14,'0'),8) = g.raiz
                 ORDER BY d.dh_emissao DESC LIMIT 1) AS emit_nome
          FROM fornecedor_grupo_raiz g
         WHERE NOT EXISTS (SELECT 1 FROM fornecedores f
                            WHERE __RAIZ_F__ = g.raiz)
    """.replace('__RAIZ_F__', _RAIZ_FORN))
    for r in cur.fetchall():
        nome = (r['emit_nome'] or '').strip()
        raizes[r['titular_id']].add(r['raiz'])
        if nome and nome not in nomes[r['titular_id']]:
            nomes[r['titular_id']].append(nome)
    cur.close()

    return canonico, dict(nomes), {k: sorted(v) for k, v in raizes.items()}


def _cnpjs_duplicados(conn):
    """Dois fornecedores com o mesmo CNPJ fariam a nota entrar duas vezes no
    JOIN e inflar o total. Melhor avisar do que entregar número errado."""
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT %s AS cnpj, COUNT(*) AS n,
               GROUP_CONCAT(f.razao_social SEPARATOR ' | ') AS nomes
          FROM fornecedores f
         WHERE f.cnpj IS NOT NULL AND f.cnpj <> ''
         GROUP BY %s
        HAVING COUNT(*) > 1
    """ % (_CNPJ_FORN, _CNPJ_FORN))
    rows = cur.fetchall()
    cur.close()
    return rows


def _notas_anteriores(conn, data_ini, empresa_ids, fornecedor_ids):
    """Notas entre o CORTE e o início do período (é o saldo de trás)."""
    # Nota trazida à mão NUNCA entra aqui: ela aparece como linha no período
    # (mesmo sendo mais velha). Contar nos dois lugares dobraria a dívida.
    where = [_FILTRO_NOTA, "d.entrada_manual = 0", "d.dh_emissao >= %s", "d.dh_emissao < %s"]
    params = [DATA_CORTE_DFE + " 00:00:00", data_ini + " 00:00:00"]
    _em("d.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id AS fornecedor_id, COALESCE(SUM(d.valor_total),0) AS total
          FROM dfe_documentos d
          JOIN %s ON m.raiz = %s
         WHERE %s
         GROUP BY m.forn_id
    """ % (_MAPA, _RAIZ_NOTA, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return {r['fornecedor_id']: float(r['total'] or 0) for r in rows}


def _pagamentos_anteriores(conn, data_ini, empresa_ids, fornecedor_ids):
    where = ["bt.tipo = 'DEBIT'", "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao >= %s", "bt.data_transacao < %s",
             """NOT EXISTS (SELECT 1 FROM dfe_pagamento_pre_corte pc
                             WHERE pc.transacao_id = bt.id)"""]
    params = [DATA_CORTE_DFE, data_ini]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id AS fornecedor_id, COALESCE(SUM(bt.valor),0) AS total
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores fp  ON fp.id = bt.fornecedor_id
          JOIN %s ON m.raiz = %s
         WHERE %s
         GROUP BY m.forn_id
    """ % (_MAPA, _raiz_de('fp'), " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return {r['fornecedor_id']: float(r['total'] or 0) for r in rows}


def _notas_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids):
    # A nota trazida à mão entra mesmo sendo anterior ao início do período — é
    # exatamente para isso que ela foi trazida: o pagamento dela está aqui
    # dentro e sem ela o fornecedor fica adiantado para sempre.
    where = [_FILTRO_NOTA,
             "(d.dh_emissao BETWEEN %s AND %s"
             " OR (d.entrada_manual = 1 AND d.dh_emissao < %s))"]
    params = [data_ini + " 00:00:00", data_fim + " 23:59:59",
              data_ini + " 00:00:00"]
    _em("d.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id                                  AS fornecedor_id,
               f.razao_social                             AS fornecedor_nome,
               f.cnpj                                     AS fornecedor_cnpj,
               d.id                                       AS doc_id,
               d.chave, d.numero, d.serie, d.dh_emissao,
               COALESCE(d.valor_total,0)                  AS valor,
               COALESCE(d.quitado_pre_corte,0)            AS quitado_pre,
               d.resumo, d.conferido, d.entrada_manual,
               COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome,
               -- Vencimento: informação, não regra. Só 1 em cada 5 notas traz
               -- o bloco de cobrança (as distribuidoras de combustível nunca
               -- mandam), então o rateio continua pela data; isto é para o
               -- olho e para o contas a pagar futuro.
               -- CUIDADO: este SQL passa por formatação de string; sinal de
               -- porcentagem em comentário vira marcador e quebra a query.
               (SELECT MIN(v.vencimento) FROM dfe_duplicatas v
                 WHERE v.documento_id = d.id)               AS vencimento,
               (SELECT COUNT(*) FROM dfe_duplicatas v
                 WHERE v.documento_id = d.id)               AS n_parcelas
          FROM dfe_documentos d
          JOIN %s ON m.raiz = %s
          %s
          LEFT JOIN clientes emp ON emp.id = d.cliente_id
         WHERE %s
         ORDER BY d.dh_emissao, d.id
    """ % (_MAPA, _RAIZ_NOTA, _JOIN_TITULAR, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _pagamentos_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids):
    where = ["bt.tipo = 'DEBIT'", "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao BETWEEN %s AND %s",
             """NOT EXISTS (SELECT 1 FROM dfe_pagamento_pre_corte pc
                             WHERE pc.transacao_id = bt.id)"""]
    params = [data_ini, data_fim]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT bt.id, m.forn_id AS fornecedor_id, bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0)                       AS valor,
               f.razao_social                             AS fornecedor_nome,
               f.cnpj                                     AS fornecedor_cnpj,
               COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores fp  ON fp.id = bt.fornecedor_id
          JOIN %s ON m.raiz = %s
          %s
          LEFT JOIN clientes emp ON emp.id = ba.cliente_id
         WHERE %s
         ORDER BY bt.data_transacao, bt.id
    """ % (_MAPA, _raiz_de('fp'), _JOIN_TITULAR, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _devolucoes_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids):
    """Creditos conciliados como devolucao do fornecedor: dinheiro que VOLTOU
    (estorno, deposito em duplicidade). Entram como pagamento negativo."""
    where = ["bt.tipo = 'CREDIT'",
             "bt.tipo_conciliacao = 'devolucao_fornecedor'",
             "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao BETWEEN %s AND %s"]
    params = [data_ini, data_fim]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT bt.id, m.forn_id AS fornecedor_id, bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0)                       AS valor,
               f.razao_social                             AS fornecedor_nome,
               f.cnpj                                     AS fornecedor_cnpj
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores fp  ON fp.id = bt.fornecedor_id
          JOIN %s ON m.raiz = %s
          %s
         WHERE %s
         ORDER BY bt.data_transacao, bt.id
    """ % (_MAPA, _raiz_de('fp'), _JOIN_TITULAR, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _devolucoes_anteriores(conn, data_ini, empresa_ids, fornecedor_ids):
    """Devolucao entre o corte e o inicio do periodo abate o pago de tras."""
    where = ["bt.tipo = 'CREDIT'",
             "bt.tipo_conciliacao = 'devolucao_fornecedor'",
             "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao >= %s", "bt.data_transacao < %s"]
    params = [DATA_CORTE_DFE, data_ini]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id AS fornecedor_id, COALESCE(SUM(bt.valor),0) AS total
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores fp  ON fp.id = bt.fornecedor_id
          JOIN %s ON m.raiz = %s
         WHERE %s
         GROUP BY m.forn_id
    """ % (_MAPA, _raiz_de('fp'), " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return {r['fornecedor_id']: float(r['total'] or 0) for r in rows}


_DDL_VINCULO = """
CREATE TABLE IF NOT EXISTS dfe_pagamento_nota (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    documento_id  INT            NOT NULL,
    transacao_id  INT            NOT NULL,
    valor         DECIMAL(14,2)  NOT NULL,
    criado_em     TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por    INT            NULL,
    UNIQUE KEY uq_doc_tx (documento_id, transacao_id),
    KEY ix_doc (documento_id),
    KEY ix_tx (transacao_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _garante_tabela_vinculo(conn):
    """Cria a tabela do vínculo se ainda não existir.

    Ela também tem script próprio (scripts/alter_dfe_pagamento_nota.py), mas
    depender do script trava o recurso pra quem está no celular. Só cria — não
    altera nem apaga nada — e o IF NOT EXISTS deixa repetir sem efeito.
    """
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = 'dfe_pagamento_nota'""")
    existe = bool(cur.fetchone()[0])
    if not existe:
        cur.execute(_DDL_VINCULO)
        conn.commit()
    cur.close()
    return True


def _tem_tabela_vinculo(conn):
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = 'dfe_pagamento_nota'""")
    ok = bool(cur.fetchone()[0])
    cur.close()
    return ok


def _canonico_do_cnpj(conn, cnpj):
    """Qual fornecedor representa este CNPJ (pela raiz, respeitando o grupo)."""
    if not cnpj:
        return None
    cur = conn.cursor()
    cur.execute("""SELECT m.forn_id FROM __MAPA__
                    WHERE m.raiz = LEFT(LPAD(%s,14,'0'),8)"""
                .replace('__MAPA__', _MAPA), (cnpj,))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def _vinculos(conn, doc_ids):
    """Vínculos manuais das notas em tela: doc_id -> lista de pagamentos.

    Também devolve quanto de cada pagamento já está comprometido, pra não
    deixar amarrar o mesmo dinheiro em duas notas.
    """
    if not doc_ids:
        return {}, {}
    ph = ','.join(['%s'] * len(doc_ids))

    sql = """
        SELECT v.id, v.documento_id, v.transacao_id, v.valor,
               bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0) AS valor_pagamento
          FROM dfe_pagamento_nota v
          JOIN bank_transactions bt ON bt.id = v.transacao_id
         WHERE v.documento_id IN (__IDS__)
         ORDER BY bt.data_transacao, v.id
    """.replace('__IDS__', ph)

    cur = conn.cursor(dictionary=True)
    cur.execute(sql, list(doc_ids))
    rows = cur.fetchall()

    # O comprometido é de TODAS as notas, não só das que estão em tela — senão
    # um pagamento já usado noutro período apareceria livre.
    cur.execute("SELECT transacao_id, SUM(valor) AS usado "
                "FROM dfe_pagamento_nota GROUP BY transacao_id")
    usado = {r['transacao_id']: float(r['usado'] or 0) for r in cur.fetchall()}
    cur.close()

    por_doc = defaultdict(list)
    for r in rows:
        por_doc[r['documento_id']].append({
            'id': r['id'],
            'transacao_id': r['transacao_id'],
            'valor': float(r['valor'] or 0),
            'data': _dia(r['data_transacao']),
            'descricao': (r['descricao'] or '')[:60],
        })
    return dict(por_doc), usado


def _vinculos_por_pagamento(conn, tx_ids):
    """transacao_id -> vinculos [{id, valor, numero, serie}] (linha do extrato)."""
    if not tx_ids:
        return {}
    ph = ','.join(['%s'] * len(tx_ids))
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT v.id, v.transacao_id, v.valor, d.numero, d.serie
          FROM dfe_pagamento_nota v
          JOIN dfe_documentos d ON d.id = v.documento_id
         WHERE v.transacao_id IN (__IDS__)
         ORDER BY v.id
    """.replace('__IDS__', ph), list(tx_ids))
    saida = defaultdict(list)
    for r in cur.fetchall():
        saida[r['transacao_id']].append({
            'id': r['id'], 'valor': float(r['valor'] or 0),
            'numero': r['numero'], 'serie': r['serie']})
    cur.close()
    return dict(saida)


def _pagamentos_vinculados_fora(conn, doc_ids, data_ini, data_fim):
    """Pagamentos amarrados a estas notas mas com data FORA do período.

    É o coração do caso "paguei em julho, a nota saiu em agosto": sem trazer
    esse pagamento para dentro, a nota ficaria coberta mas o fornecedor
    continuaria aparecendo devendo.
    """
    if not doc_ids:
        return []
    ph = ','.join(['%s'] * len(doc_ids))
    params = list(doc_ids) + [data_ini, data_fim]

    # Monta a lista de ids por substituição de marcador, NÃO com o operador %:
    # a query tem outros %s (as datas) que são placeholders do driver, e o %
    # tentaria formatá-los também.
    sql = """
        SELECT DISTINCT bt.id, m.forn_id AS fornecedor_id, bt.data_transacao,
               bt.descricao,
               COALESCE(bt.valor,0)                          AS valor,
               f.razao_social                                AS fornecedor_nome,
               f.cnpj                                        AS fornecedor_cnpj,
               COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
          FROM dfe_pagamento_nota v
          JOIN bank_transactions bt ON bt.id = v.transacao_id
          JOIN bank_accounts ba     ON ba.id = bt.account_id
          JOIN fornecedores fp      ON fp.id = bt.fornecedor_id
          JOIN __MAPA__ ON m.raiz = __RAIZ_FP__
          __JOIN_TITULAR__
          LEFT JOIN clientes emp    ON emp.id = ba.cliente_id
         WHERE v.documento_id IN (__IDS__)
           AND (bt.data_transacao < %s OR bt.data_transacao > %s)
         ORDER BY bt.data_transacao, bt.id
    """.replace('__IDS__', ph).replace('__MAPA__', _MAPA) \
       .replace('__RAIZ_FP__', _raiz_de('fp')) \
       .replace('__JOIN_TITULAR__', _JOIN_TITULAR)

    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        r['fora_periodo'] = True
    return rows


def _pagamentos_antes_do_corte(conn, empresa_ids, fornecedor_ids):
    """Pagamentos na janela imediatamente ANTES do corte, por fornecedor.

    Não entram no saldo — só respondem a pergunta que sempre aparece: "esse
    fornecedor está devendo ou já pagamos isso no mês passado?".
    """
    inicio = (date.fromisoformat(DATA_CORTE_DFE)
              - timedelta(days=JANELA_ANTES_CORTE)).isoformat()
    where = ["bt.tipo = 'DEBIT'", "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao >= %s", "bt.data_transacao < %s"]
    params = [inicio, DATA_CORTE_DFE]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("m.forn_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.forn_id AS fornecedor_id, bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0) AS valor
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores fp  ON fp.id = bt.fornecedor_id
          JOIN %s ON m.raiz = %s
         WHERE %s
         ORDER BY bt.data_transacao DESC, bt.id DESC
    """ % (_MAPA, _raiz_de('fp'), " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()

    por_forn = defaultdict(lambda: {'total': 0.0, 'lancamentos': []})
    for r in rows:
        alvo = por_forn[r['fornecedor_id']]
        alvo['total'] += float(r['valor'] or 0)
        alvo['lancamentos'].append({
            'data': _dia(r['data_transacao']),
            'valor': float(r['valor'] or 0),
            'descricao': (r['descricao'] or '')[:60],
        })
    return dict(por_forn), inicio


def _janela_captura(conn):
    """Primeira e última nota que a captura DFe tem. Serve pra conferir se o
    corte está no lugar certo — se a 1ª nota for depois do corte, o corte está
    solto e vai deixar pagamento sem nota do outro lado."""
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT MIN(d.dh_emissao) AS primeira, MAX(d.dh_emissao) AS ultima,
               COUNT(*) AS notas
          FROM dfe_documentos d
         WHERE d.tipo = 'NFe' AND d.situacao = 'autorizado'
    """)
    row = cur.fetchone() or {}
    cur.close()
    return row


def _notas_sem_fornecedor(conn, data_ini, data_fim, empresa_ids):
    """Nota que entrou pela SEFAZ e cujo emitente não está no cadastro. É o
    achado mais útil do relatório: compra que nenhum controle enxerga."""
    where = [_FILTRO_NOTA, "d.dh_emissao BETWEEN %s AND %s", "m.forn_id IS NULL"]
    params = [data_ini + " 00:00:00", data_fim + " 23:59:59"]
    _em("d.cliente_id", empresa_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT d.emit_cnpj, d.emit_nome,
               COUNT(*)                    AS notas,
               COALESCE(SUM(d.valor_total),0) AS total,
               MAX(d.dh_emissao)           AS ultima
          FROM dfe_documentos d
          LEFT JOIN %s ON m.raiz = %s
         WHERE %s
         GROUP BY d.emit_cnpj, d.emit_nome
         ORDER BY total DESC
    """ % (_MAPA, _RAIZ_NOTA, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Montagem
# ──────────────────────────────────────────────────────────────────────────────

def _dia(v):
    """Normaliza date/datetime/str para date (pra ordenar sem explodir)."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(v[:19], fmt).date()
            except ValueError:
                pass
    return date.min


def _aloca_fifo(linhas, saldo_anterior):
    """Aplica cada pagamento nas notas em aberto mais ANTIGAS primeiro.

    Não existe amarração de pagamento com nota em lugar nenhum do sistema — o
    usuário paga o fornecedor, não a nota. Então a ordem de data é o palpite
    honesto: serve pra enxergar o que ainda está descoberto, e é isso que faz
    o caso "paguei R$ 180 a mais" se resolver sozinho quando a próxima nota
    entrar (a sobra come o pedaço que faltar).

    Marca cada nota com `falta` (0 = coberta) e devolve (sobra, descoberto).
    Invariante: sobra − descoberto == saldo do período + saldo anterior.
    """
    # Saldo anterior positivo é dinheiro disponível; negativo é nota velha em
    # aberto que não está na lista (fora do período), mas precisa continuar
    # contando — senão a sobra apareceria maior do que é.
    caixa = max(saldo_anterior, 0.0)
    descoberto_antigo = max(-saldo_anterior, 0.0)

    abertas = []
    for l in linhas:
        if l['tipo'] == 'devolucao':
            # Dinheiro que voltou. Se casou com um pagamento (valor exato), o
            # livre daquele pagamento já foi zerado — aqui não faz nada. Sem
            # par, sai do caixa; o que o caixa não cobrir vira descoberto.
            if not l.get('abatida_de'):
                tira = min(caixa, l['valor'])
                caixa -= tira
                descoberto_antigo += l['valor'] - tira
            continue
        if l['tipo'] == 'pagamento':
            # Só a parte LIVRE do pagamento entra no rateio automático: o que
            # já foi amarrado à mão tem dono — e o que foi devolvido, também.
            caixa += max(l['valor'] - l.get('usado', 0.0)
                         - l.get('dev_abatido', 0.0), 0.0)
            # Primeiro tapa o buraco velho, depois as notas em aberto.
            usa = min(caixa, descoberto_antigo)
            caixa -= usa
            descoberto_antigo -= usa
            for n in abertas:
                if caixa <= 0.005:
                    break
                usa = min(caixa, n['falta'])
                n['falta'] -= usa
                caixa -= usa
            abertas = [n for n in abertas if n['falta'] > 0.005]
        else:
            # A nota já entra abatida do que foi vinculado à mão e do
            # que foi quitado antes do corte.
            l['falta'] = max(l['valor'] - l.get('vinc_total', 0.0)
                             - l.get('quitado_pre', 0.0), 0.0)
            usa = min(caixa, l['falta'])
            l['falta'] -= usa
            caixa -= usa
            if l['falta'] > 0.005:
                abertas.append(l)

    for l in linhas:
        if l['tipo'] == 'nota':
            l['coberta'] = l['falta'] <= 0.005
            l['parcial'] = (not l['coberta']) and l['falta'] < l['valor'] - 0.005

    descoberto = descoberto_antigo + sum(n['falta'] for n in abertas)
    return caixa, descoberto


def _monta(notas, pagamentos, notas_ant, pagos_ant, pre_corte=None,
           vinculos=None, usado=None, nomes=None, devolucoes=None):
    """Uma linha do tempo por fornecedor, com saldo corrente.

    Ordem: por data; empatou, pagamento antes da nota — é a sequência real
    (paga de manhã, nota sai à tarde) e deixa o saldo do dia legível.
    """
    vinculos = vinculos or {}
    usado = usado or {}
    nomes = nomes or {}
    por_forn = defaultdict(lambda: {'nome': '', 'cnpj': '', 'eventos': []})

    for n in notas:
        f = por_forn[n['fornecedor_id']]
        f['nome'] = n['fornecedor_nome']
        f['cnpj'] = n['fornecedor_cnpj']
        f['eventos'].append({
            'tipo': 'nota',
            'data': _dia(n['dh_emissao']),
            'ordem': 1,
            'id': n['doc_id'],
            'valor': float(n['valor'] or 0),
            'rotulo': 'NF-e nº %s%s' % (n['numero'] or '—',
                                        ('/%s' % n['serie']) if n['serie'] else ''),
            'detalhe': n['empresa_nome'] or '',
            'resumo': bool(n['resumo']),
            'conferido': bool(n['conferido']),
            'manual': bool(n.get('entrada_manual')),
            'chave': n['chave'],
            'vinculos': vinculos.get(n['doc_id'], []),
            'vinc_total': sum(v['valor'] for v in vinculos.get(n['doc_id'], [])),
            'vencimento': n.get('vencimento'),
            'n_parcelas': int(n.get('n_parcelas') or 0),
            'quitado_pre': float(n.get('quitado_pre') or 0),
        })

    for p in pagamentos:
        f = por_forn[p['fornecedor_id']]
        f['nome'] = f['nome'] or p['fornecedor_nome']
        f['cnpj'] = f['cnpj'] or p['fornecedor_cnpj']
        f['eventos'].append({
            'tipo': 'pagamento',
            'data': _dia(p['data_transacao']),
            'ordem': 0,
            'id': p['id'],
            'valor': float(p['valor'] or 0),
            'rotulo': 'Pagamento',
            'detalhe': (p['descricao'] or '')[:60],
            'resumo': False,
            'conferido': None,          # o OK é da nota; pagamento não tem
            'chave': None,
            'usado': usado.get(p['id'], 0.0),
            'fora_periodo': bool(p.get('fora_periodo')),
        })

    for dv in (devolucoes or []):
        f = por_forn[dv['fornecedor_id']]
        f['nome'] = f['nome'] or dv['fornecedor_nome']
        f['cnpj'] = f['cnpj'] or dv['fornecedor_cnpj']
        f['eventos'].append({
            'tipo': 'devolucao',
            'data': _dia(dv['data_transacao']),
            'ordem': 0,
            'id': dv['id'],
            'valor': float(dv['valor'] or 0),
            'rotulo': 'Devolução',
            'detalhe': (dv['descricao'] or '')[:60],
            'resumo': False,
            'conferido': None,
            'chave': None,
        })

    # Fornecedor que só tem saldo de trás (nenhum movimento no período) também
    # precisa aparecer — é justamente onde mora pendência esquecida.
    for fid in set(list(notas_ant.keys()) + list(pagos_ant.keys())):
        por_forn[fid]

    saida = []
    for fid, f in por_forn.items():
        saldo = pagos_ant.get(fid, 0.0) - notas_ant.get(fid, 0.0)
        saldo_anterior = saldo

        f['eventos'].sort(key=lambda e: (e['data'], e['ordem'], e['id']))

        linhas, comprado, pago = [], 0.0, 0.0
        for ev in f['eventos']:
            if ev['tipo'] == 'pagamento':
                saldo += ev['valor']
                pago += ev['valor']
            elif ev['tipo'] == 'devolucao':
                # Dinheiro que voltou: abate o pago — nao e compra nem receita.
                saldo -= ev['valor']
                pago -= ev['valor']
            else:
                # O que foi quitado antes do corte nao corre NESTA conta —
                # abate aqui, senao viraria divida falsa pra sempre.
                efetivo = ev['valor'] - ev.get('quitado_pre', 0.0)
                saldo -= efetivo
                comprado += efetivo
            linhas.append(dict(ev, saldo=saldo))

        if not linhas and abs(saldo_anterior) < 0.005:
            continue                      # zerado e parado: não polui a tela

        # Devolução casa com o pagamento de LIVRE igual (valor exato, mesmo
        # fornecedor): o par se fecha sozinho. Igual leitura, nada gravado —
        # sem par exato, a devolução fica "em aberto" e só abate o total.
        pags_l = [l for l in linhas if l['tipo'] == 'pagamento']
        for dv in linhas:
            if dv['tipo'] != 'devolucao':
                continue
            alvo = next(
                (p for p in pags_l
                 if not p.get('devolucao')
                 and abs((p['valor'] - p.get('usado', 0.0)) - dv['valor']) <= 0.005),
                None)
            if alvo:
                alvo['devolucao'] = {'data': dv['data'], 'descricao': dv['detalhe'],
                                     'valor': dv['valor'], 'tx_id': dv['id']}
                alvo['dev_abatido'] = dv['valor']
                dv['abatida_de'] = alvo['data']

        sobra, descoberto = _aloca_fifo(linhas, saldo_anterior)
        notas_lin = [l for l in linhas if l['tipo'] == 'nota']

        # Pagamento de antes do corte só interessa quando o fornecedor aparece
        # DEVENDO: é a suspeita de "isso já foi pago no mês passado".
        antes = (pre_corte or {}).get(fid)
        if antes and saldo >= -0.005:
            antes = None

        # Um grupo mostra TODAS as razões sociais: na web uma ao lado da outra,
        # no celular uma embaixo da outra (o template decide) — quem confere
        # precisa ver que ali estão duas empresas, não uma.
        lista_nomes = nomes.get(fid) or [f['nome'] or '(fornecedor %s)' % fid]

        saida.append({
            'fornecedor_id': fid,
            'nome': ' / '.join(lista_nomes),
            'nomes': lista_nomes,
            'cnpj': f['cnpj'] or '',
            'saldo_anterior': saldo_anterior,
            'comprado': comprado,
            'pago': pago,
            'saldo_final': saldo,
            'linhas': linhas,
            'notas_total': len(notas_lin),
            # Conferida = 100%% vinculada a pagamento (padrao novo).
            'notas_ok': sum(
                1 for l in notas_lin
                if sum(v['valor'] for v in (l.get('vinculos') or []))
                   + l.get('quitado_pre', 0.0) >= l['valor'] - 0.005),
            'sobra': sobra,
            'descoberto': descoberto,
            'notas_abertas': sum(1 for l in notas_lin if not l['coberta']),
            'antes': antes,
            # Quanto sobraria da dívida se esses pagamentos de antes do corte
            # forem mesmo destas notas. Só uma hipótese — o saldo não muda.
            'saldo_com_antes': (saldo + antes['total']) if antes else None,
        })

    # Quem tem a maior diferença primeiro — é o que precisa de olho.
    return sorted(saida, key=lambda x: (-abs(x['saldo_final']), x['nome']))


# ──────────────────────────────────────────────────────────────────────────────
# Rota
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_fornecedores_dfe')
@login_required
@admin_required
def conf_fornecedores_dfe():
    d_ini_pad, d_fim_pad = _periodo_padrao()
    data_ini = (request.args.get('data_inicio') or d_ini_pad).strip()
    data_fim = (request.args.get('data_fim') or d_fim_pad).strip()
    empresa_ids = _ids('cliente_ids[]')
    fornecedor_ids = _ids('fornecedor_ids[]')

    # Pedir data antes do corte não é erro do usuário — mas antes do corte só
    # existe um dos lados (pagamento), então o começo é puxado pro corte e a
    # tela diz que fez isso.
    puxou_pro_corte = data_ini < DATA_CORTE_DFE
    if puxou_pro_corte:
        data_ini = DATA_CORTE_DFE

    conn = get_db_connection()
    try:
        _garante_tabela_grupo(conn)
        _garante_coluna_manual(conn)
        _garante_coluna_pago_antes(conn)
        _garante_tabela_pg_pre_corte(conn)
        empresas = _empresas(conn)
        fornecedores = _fornecedores(conn)
        duplicados = _cnpjs_duplicados(conn)
        janela = _janela_captura(conn)

        canonico, nomes, raizes = _mapa_cadastros(conn)
        # O filtro traz o id que o usuário escolheu na lista; quem manda nas
        # consultas é o representante do grupo. Sem traduzir, filtrar pela
        # filial devolveria tela vazia.
        if fornecedor_ids:
            fornecedor_ids = sorted({str(canonico.get(int(i), int(i)))
                                     for i in fornecedor_ids})

        notas_ant = _notas_anteriores(conn, data_ini, empresa_ids, fornecedor_ids)
        pagos_ant = _pagamentos_anteriores(conn, data_ini, empresa_ids, fornecedor_ids)
        for fid, v in _devolucoes_anteriores(conn, data_ini, empresa_ids,
                                             fornecedor_ids).items():
            pagos_ant[fid] = pagos_ant.get(fid, 0.0) - v
        notas = _notas_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids)
        pagamentos = _pagamentos_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids)
        devolucoes = _devolucoes_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids)
        orfas = _notas_sem_fornecedor(conn, data_ini, data_fim, empresa_ids)
        ocultas = _notas_ocultas(conn, empresa_ids, fornecedor_ids)
        pagos_ocultos = _pagamentos_ocultos(conn, empresa_ids, fornecedor_ids)
        pre_corte, pre_corte_ini = _pagamentos_antes_do_corte(
            conn, empresa_ids, fornecedor_ids)

        doc_ids = [n['doc_id'] for n in notas]
        vinculo_pronto = _garante_tabela_vinculo(conn)
        vinculos, usado = ({}, {})
        if vinculo_pronto:
            vinculos, usado = _vinculos(conn, doc_ids)
            # Pagamento amarrado a uma destas notas mas de outra data entra na
            # conta assim mesmo — é o que fecha o caso "paguei antes do corte".
            pagamentos += _pagamentos_vinculados_fora(conn, doc_ids, data_ini, data_fim)
        vinc_pag = _vinculos_por_pagamento(conn, [p['id'] for p in pagamentos])
    finally:
        conn.close()

    dados = _monta(notas, pagamentos, notas_ant, pagos_ant, pre_corte,
                   vinculos, usado, nomes, devolucoes)
    for d in dados:
        d['ocultas'] = ocultas.get(d['fornecedor_id'], [])
        d['pagos_ocultos'] = pagos_ocultos.get(d['fornecedor_id'], [])

    pag_aberto = sum(
        max(0.0, l['valor'] - l.get('usado', 0.0) - l.get('dev_abatido', 0.0))
        for d in dados for l in d['linhas'] if l['tipo'] == 'pagamento')
    totais = {
        'pag_aberto': pag_aberto,
        'comprado': sum(d['comprado'] for d in dados),
        'pago':     sum(d['pago'] for d in dados),
        'saldo':    sum(d['saldo_final'] for d in dados),
        'orfas':    sum(float(o['total'] or 0) for o in orfas),
        'notas':    sum(d['notas_total'] for d in dados),
        'notas_ok': sum(d['notas_ok'] for d in dados),
        'descoberto': sum(d['descoberto'] for d in dados),
        'sobra':      sum(d['sobra'] for d in dados),
    }

    # Sem CNPJ no cadastro o fornecedor nunca casa com nota nenhuma.
    sem_cnpj = [f for f in fornecedores if not (f['cnpj'] or '').strip()]

    return render_template(
        'relatorios/conf_fornecedores_dfe.html',
        dados=dados, totais=totais, orfas=orfas,
        duplicados=duplicados, sem_cnpj=sem_cnpj,
        empresas=empresas, fornecedores=fornecedores,
        data_inicio=data_ini, data_fim=data_fim,
        cliente_ids=empresa_ids, fornecedor_ids=fornecedor_ids,
        corte=DATA_CORTE_DFE, puxou_pro_corte=puxou_pro_corte, janela=janela,
        vinc_pag=vinc_pag,
        pre_corte_ini=pre_corte_ini, vinculo_pronto=vinculo_pronto,
    )


@bp.route('/conf_fornecedores_dfe/candidatos/<int:doc_id>')
@login_required
@admin_required
def candidatos(doc_id):
    """Pagamentos do MESMO fornecedor que ainda têm dinheiro livre.

    Sem recorte de data de propósito: o pagamento que fecha a conta costuma
    ser de antes do corte da captura — é justamente esse que o automático não
    alcança. Os mais próximos da data da nota vêm primeiro.
    """
    conn = get_db_connection()
    try:
        _garante_tabela_vinculo(conn)
        _garante_tabela_grupo(conn)
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT d.id, d.numero, d.serie, d.dh_emissao, d.emit_cnpj,
                   COALESCE(d.valor_total,0) AS valor,
                   COALESCE(d.quitado_pre_corte,0) AS quitado_pre,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.documento_id = d.id), 0) AS vinculado
              FROM dfe_documentos d WHERE d.id = %s
        """, (doc_id,))
        nota = cur.fetchone()
        if not nota:
            cur.close()
            return jsonify(ok=False, erro='nota não encontrada'), 404

        # Candidato é pagamento do MESMO grupo (raiz, ou grupo montado à mão) —
        # não do mesmo CNPJ. É o que faz o pagamento da matriz aparecer para a
        # nota da filial, e o da RODOIL para a nota da TOWER.
        canonico = _canonico_do_cnpj(conn, nota['emit_cnpj'] or '')
        cur.execute("""
            SELECT bt.id, bt.data_transacao, bt.descricao,
                   COALESCE(bt.valor,0) AS valor,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.transacao_id = bt.id), 0) AS usado
              FROM bank_transactions bt
              JOIN fornecedores fp ON fp.id = bt.fornecedor_id
              JOIN __MAPA__ ON m.raiz = __RAIZ_FP__
             WHERE bt.tipo = 'DEBIT'
               AND bt.fornecedor_id IS NOT NULL
               AND m.forn_id = %s
             ORDER BY ABS(DATEDIFF(bt.data_transacao, %s)), bt.data_transacao DESC
             LIMIT 40
        """.replace('__MAPA__', _MAPA).replace('__RAIZ_FP__', _raiz_de('fp')),
            (canonico, nota['dh_emissao']))
        pagos = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    livres = []
    for p in pagos:
        livre = float(p['valor'] or 0) - float(p['usado'] or 0)
        if livre <= 0.005:
            continue
        livres.append({
            'id': p['id'],
            'data': _dia(p['data_transacao']).strftime('%d/%m/%Y'),
            'descricao': (p['descricao'] or '')[:60],
            'valor': float(p['valor'] or 0),
            'livre': livre,
        })

    falta = (float(nota['valor'] or 0) - float(nota['vinculado'] or 0)
             - float(nota['quitado_pre'] or 0))
    return jsonify(
        ok=True,
        falta=round(max(falta, 0.0), 2),
        nota='NF-e nº %s%s' % (nota['numero'] or '—',
                               ('/%s' % nota['serie']) if nota['serie'] else ''),
        candidatos=livres,
        # Diagnóstico: sem isto, lista vazia é indistinguível de consulta que
        # não achou nada, e não dá pra saber onde o caminho quebrou.
        diag={
            'doc_id': doc_id,
            'cnpj_nota': nota['emit_cnpj'],
            'pagamentos_do_fornecedor': len(pagos),
            'com_valor_livre': len(livres),
        })


@bp.route('/conf_fornecedores_dfe/notas_candidatas/<int:tx_id>')
@login_required
@admin_required
def notas_candidatas(tx_id):
    """Notas em aberto do fornecedor DESTE pagamento — pra usar o dinheiro
    livre nelas (1 pagamento cobrindo varias notas). Espelho do candidatos."""
    conn = get_db_connection()
    try:
        _garante_tabela_vinculo(conn)
        _garante_tabela_grupo(conn)
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT bt.id, bt.data_transacao, bt.descricao,
                   COALESCE(bt.valor,0) AS valor,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.transacao_id = bt.id), 0) AS usado,
                   m.forn_id AS canonico
              FROM bank_transactions bt
              JOIN fornecedores fp ON fp.id = bt.fornecedor_id
              JOIN __MAPA__ ON m.raiz = __RAIZ_FP__
             WHERE bt.id = %s AND bt.tipo = 'DEBIT'
        """.replace('__MAPA__', _MAPA).replace('__RAIZ_FP__', _raiz_de('fp')),
            (tx_id,))
        pg = cur.fetchone()
        if not pg:
            cur.close()
            return jsonify(ok=False, erro='pagamento não encontrado (ou sem fornecedor conciliado)'), 404

        cur.execute("""
            SELECT d.id, d.numero, d.serie, d.dh_emissao, d.cliente_id,
                   COALESCE(NULLIF(emp.nome_fantasia, ''), emp.razao_social)
                       AS empresa_nome,
                   COALESCE(d.valor_total,0) AS valor,
                   COALESCE(d.quitado_pre_corte,0) AS quitado_pre,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.documento_id = d.id), 0) AS vinculado
              FROM dfe_documentos d
              LEFT JOIN clientes emp ON emp.id = d.cliente_id
              JOIN __MAPA__ ON m.raiz = LEFT(LPAD(d.emit_cnpj,14,'0'),8)
             WHERE d.tipo = 'NFe' AND COALESCE(d.pago_antes_corte,0) = 0
               AND m.forn_id = %s
             ORDER BY ABS(DATEDIFF(d.dh_emissao, %s)), d.dh_emissao DESC
             LIMIT 80
        """.replace('__MAPA__', _MAPA),
            (pg['canonico'], pg['data_transacao']))
        docs = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    livre = float(pg['valor'] or 0) - float(pg['usado'] or 0)
    notas = []
    for n in docs:
        falta = (float(n['valor'] or 0) - float(n['vinculado'] or 0)
                 - float(n['quitado_pre'] or 0))
        if falta <= 0.005:
            continue
        notas.append({
            'doc_id': n['id'],
            'rotulo': 'NF %s/%s' % (n['numero'] or '?', n['serie'] or '?'),
            'data': _dia(n['dh_emissao']).strftime('%d/%m/%Y') if n['dh_emissao'] else '—',
            'valor': float(n['valor'] or 0),
            'falta': falta,
            'empresa_id': n['cliente_id'],
            'empresa': n['empresa_nome'] or '—',
        })
    return jsonify(ok=True, pagamento={
        'id': pg['id'],
        'data': _dia(pg['data_transacao']).strftime('%d/%m/%Y'),
        'descricao': (pg['descricao'] or '')[:60],
        'valor': float(pg['valor'] or 0),
        'livre': livre,
    }, notas=notas)


@bp.route('/conf_fornecedores_dfe/vincular_lote', methods=['POST'])
@login_required
@admin_required
def vincular_lote():
    """Varios vinculos numa acao so (1 pagamento -> N notas, N pagamentos ->
    1 nota). Valida TUDO antes de gravar — contando o que o proprio lote ja
    reservou de cada pagamento e de cada nota — e grava de uma vez."""
    dados = request.get_json(silent=True) or {}
    itens = dados.get('itens') or []
    if not itens or len(itens) > 40:
        return jsonify(ok=False, erro='lote vazio ou grande demais'), 400
    try:
        itens = [{'doc_id': int(i.get('doc_id')),
                  'transacao_id': int(i.get('transacao_id')),
                  'valor': round(float(i.get('valor')), 2)} for i in itens]
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='dados inválidos'), 400
    if any(i['valor'] <= 0 for i in itens):
        return jsonify(ok=False, erro='todo valor tem de ser maior que zero'), 400

    extra_doc = defaultdict(float)
    extra_tx = defaultdict(float)
    conn = get_db_connection()
    try:
        _garante_tabela_vinculo(conn)
        _garante_tabela_grupo(conn)
        cur = conn.cursor(dictionary=True)
        for it in itens:
            cur.execute("""
                SELECT COALESCE(d.valor_total,0) AS valor,
                       COALESCE(d.quitado_pre_corte,0) AS quitado_pre,
                       d.emit_cnpj, d.numero,
                       COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                                  WHERE v.documento_id = d.id
                                    AND v.transacao_id <> %s), 0) AS outros
                  FROM dfe_documentos d WHERE d.id = %s
            """, (it['transacao_id'], it['doc_id']))
            nota = cur.fetchone()
            if not nota:
                cur.close()
                return jsonify(ok=False, erro='nota não encontrada'), 404
            cur.execute("""
                SELECT COALESCE(bt.valor,0) AS valor,
                       COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                                  WHERE v.transacao_id = bt.id
                                    AND v.documento_id <> %s), 0) AS outros,
                       m.forn_id AS canonico
                  FROM bank_transactions bt
                  JOIN fornecedores fp ON fp.id = bt.fornecedor_id
                  JOIN __MAPA__ ON m.raiz = __RAIZ_FP__
                 WHERE bt.id = %s AND bt.tipo = 'DEBIT'
            """.replace('__MAPA__', _MAPA).replace('__RAIZ_FP__', _raiz_de('fp')),
                (it['doc_id'], it['transacao_id']))
            pg = cur.fetchone()
            if not pg:
                cur.close()
                return jsonify(ok=False, erro='pagamento não encontrado'), 404
            if pg['canonico'] != _canonico_do_cnpj(conn, nota['emit_cnpj'] or ''):
                cur.close()
                return jsonify(ok=False,
                               erro='pagamento conciliado noutro fornecedor'), 400
            falta = (float(nota['valor']) - float(nota['outros'])
                     - float(nota['quitado_pre'] or 0)
                     - extra_doc[it['doc_id']])
            livre = (float(pg['valor']) - float(pg['outros'])
                     - extra_tx[it['transacao_id']])
            if it['valor'] > falta + 0.005:
                cur.close()
                return jsonify(ok=False, erro='a NF %s só tem R$ %.2f em aberto'
                               % (nota['numero'], max(falta, 0))), 400
            if it['valor'] > livre + 0.005:
                cur.close()
                return jsonify(ok=False, erro='o pagamento só tem R$ %.2f livre'
                               % max(livre, 0)), 400
            extra_doc[it['doc_id']] += it['valor']
            extra_tx[it['transacao_id']] += it['valor']
        cur.close()

        cur = conn.cursor()
        for it in itens:
            cur.execute("""
                INSERT INTO dfe_pagamento_nota (documento_id, transacao_id, valor, criado_por)
                     VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE valor = VALUES(valor), criado_por = VALUES(criado_por)
            """, (it['doc_id'], it['transacao_id'], it['valor'],
                  getattr(current_user, 'id', None)))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify(ok=True, gravados=len(itens))


@bp.route('/conf_fornecedores_dfe/vincular', methods=['POST'])
@login_required
@admin_required
def vincular():
    """Amarra um pagamento a uma nota, por um valor.

    Recusa passar do que falta na nota ou do que sobra no pagamento — deixar
    amarrar o mesmo dinheiro duas vezes transformaria o relatório em ficção.
    """
    dados = request.get_json(silent=True) or {}
    try:
        doc_id = int(dados.get('doc_id'))
        tx_id = int(dados.get('transacao_id'))
        valor = round(float(dados.get('valor')), 2)
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='dados inválidos'), 400
    if valor <= 0:
        return jsonify(ok=False, erro='o valor tem de ser maior que zero'), 400

    conn = get_db_connection()
    try:
        _garante_tabela_vinculo(conn)
        _garante_tabela_grupo(conn)
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT COALESCE(d.valor_total,0) AS valor,
                   COALESCE(d.quitado_pre_corte,0) AS quitado_pre,
                   d.emit_cnpj,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.documento_id = d.id AND v.transacao_id <> %s), 0) AS outros
              FROM dfe_documentos d WHERE d.id = %s
        """, (tx_id, doc_id))
        nota = cur.fetchone()
        if not nota:
            cur.close()
            return jsonify(ok=False, erro='nota não encontrada'), 404

        cur.execute("""
            SELECT COALESCE(bt.valor,0) AS valor, bt.fornecedor_id,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.transacao_id = bt.id AND v.documento_id <> %s), 0) AS outros,
                   m.forn_id AS canonico
              FROM bank_transactions bt
              JOIN fornecedores fp ON fp.id = bt.fornecedor_id
              JOIN __MAPA__ ON m.raiz = __RAIZ_FP__
             WHERE bt.id = %s AND bt.tipo = 'DEBIT'
        """.replace('__MAPA__', _MAPA).replace('__RAIZ_FP__', _raiz_de('fp')),
            (doc_id, tx_id))
        pg = cur.fetchone()
        if not pg:
            cur.close()
            return jsonify(ok=False, erro='pagamento não encontrado'), 404

        # O pagamento tem de ser do MESMO GRUPO da nota — matriz, filial ou
        # empresa irmã agrupada à mão. O usuário já concilia o lançamento no
        # fornecedor certo, então isto é só uma trava.
        if pg['canonico'] != _canonico_do_cnpj(conn, nota['emit_cnpj'] or ''):
            cur.close()
            return jsonify(ok=False,
                           erro='esse pagamento está conciliado noutro fornecedor'), 400

        falta = (float(nota['valor']) - float(nota['outros'])
                 - float(nota['quitado_pre'] or 0))
        livre = float(pg['valor']) - float(pg['outros'])
        if valor > falta + 0.005:
            cur.close()
            return jsonify(ok=False, erro='a nota só tem R$ %.2f em aberto' % falta), 400
        if valor > livre + 0.005:
            cur.close()
            return jsonify(ok=False, erro='esse pagamento só tem R$ %.2f livre' % livre), 400

        cur.close()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dfe_pagamento_nota (documento_id, transacao_id, valor, criado_por)
                 VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE valor = VALUES(valor), criado_por = VALUES(criado_por)
        """, (doc_id, tx_id, valor, getattr(current_user, 'id', None)))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/desvincular', methods=['POST'])
@login_required
@admin_required
def desvincular():
    dados = request.get_json(silent=True) or {}
    try:
        vinc_id = int(dados.get('vinculo_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='vínculo inválido'), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dfe_pagamento_nota WHERE id = %s", (vinc_id,))
        conn.commit()
        apagou = cur.rowcount
        cur.close()
    finally:
        conn.close()

    if not apagou:
        return jsonify(ok=False, erro='vínculo não encontrado'), 404
    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/pago_antes_corte', methods=['POST'])
@login_required
@admin_required
def pago_antes_corte():
    """Marca (ou desmarca) a nota como paga por deposito ANTERIOR ao corte.

    Marcada, ela sai da conta inteira — lista, saldo, contadores e ate das
    candidatas do vinculo. Nota com vinculo nao pode ser marcada: primeiro
    desfaz o vinculo, senao o pagamento ficaria usando dinheiro em nota
    invisivel."""
    dados = request.get_json(silent=True) or {}
    try:
        doc_id = int(dados.get('doc_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='nota inválida'), 400
    marcar = 1 if dados.get('marcar') else 0

    conn = get_db_connection()
    try:
        _garante_coluna_pago_antes(conn)
        cur = conn.cursor()
        if marcar:
            cur.execute("""SELECT COALESCE(SUM(valor),0) FROM dfe_pagamento_nota
                            WHERE documento_id = %s""", (doc_id,))
            if float(cur.fetchone()[0] or 0) > 0.005:
                cur.close()
                return jsonify(ok=False, erro='esta nota tem vínculo com pagamento — '
                                              'desfaça o vínculo antes de ocultar'), 400
        cur.execute("UPDATE dfe_documentos SET pago_antes_corte = %s WHERE id = %s",
                    (marcar, doc_id))
        conn.commit()
        achou = cur.rowcount
        cur.close()
    finally:
        conn.close()

    if not achou and marcar:
        return jsonify(ok=False, erro='nota não encontrada'), 404
    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/desfazer_devolucao', methods=['POST'])
@login_required
@admin_required
def desfazer_devolucao():
    """Desconcilia a devolucao: o credito volta a "pendente" no conciliador
    do banco e o pagamento recupera o livre. So mexe em transacao que esteja
    conciliada exatamente como devolucao_fornecedor."""
    dados = request.get_json(silent=True) or {}
    try:
        tx_id = int(dados.get('tx_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='transação inválida'), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""UPDATE bank_transactions
                       SET status='pendente', fornecedor_id=NULL,
                           tipo_conciliacao=NULL,
                           conciliado_em=NULL, conciliado_por=NULL
                     WHERE id = %s
                       AND tipo_conciliacao = 'devolucao_fornecedor'""",
                    (tx_id,))
        conn.commit()
        achou = cur.rowcount
        cur.close()
    finally:
        conn.close()

    if not achou:
        return jsonify(ok=False, erro='essa transação não está conciliada '
                                      'como devolução'), 404
    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/pagamento_pre_corte', methods=['POST'])
@login_required
@admin_required
def pagamento_pre_corte():
    """Marca (ou desmarca) o pagamento como liquidacao de compra ANTERIOR
    ao corte — sai da conta inteira (lista, Pago, saldo).

    Caso Biegai: boletos pagos em 13 e 14/07 eram de compras de antes de
    07/07; a captura nunca vai ter essas notas. Pagamento com vinculo nao
    pode ser marcado: primeiro desfaz, senao a nota ficaria usando
    dinheiro invisivel."""
    dados = request.get_json(silent=True) or {}
    try:
        tx_id = int(dados.get('tx_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='pagamento inválido'), 400
    marcar = 1 if dados.get('marcar') else 0

    conn = get_db_connection()
    try:
        _garante_tabela_pg_pre_corte(conn)
        cur = conn.cursor()
        if marcar:
            cur.execute("""SELECT COALESCE(SUM(valor),0) FROM dfe_pagamento_nota
                            WHERE transacao_id = %s""", (tx_id,))
            if float(cur.fetchone()[0] or 0) > 0.005:
                cur.close()
                return jsonify(ok=False, erro='este pagamento tem vínculo com nota — '
                                              'desfaça o vínculo antes de ocultar'), 400
            cur.execute("""INSERT IGNORE INTO dfe_pagamento_pre_corte (transacao_id)
                            VALUES (%s)""", (tx_id,))
        else:
            cur.execute("DELETE FROM dfe_pagamento_pre_corte WHERE transacao_id = %s",
                        (tx_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/quitar_pre_corte', methods=['POST'])
@login_required
@admin_required
def quitar_pre_corte():
    """Da o RESTO da nota como quitado antes do corte (ou desfaz).

    Caso Supremo: nota de 29/04 em 5 parcelas — 3 pagas antes de 07/07
    (fora da captura), 2 pagas dentro e ja vinculadas. O resto nao vai
    aparecer nunca; quitar fecha a nota sem inventar pagamento.
    O valor gravado e a falta DAQUELE momento (valor - vinculado); se um
    vinculo for desfeito depois, a diferenca reaparece como falta."""
    dados = request.get_json(silent=True) or {}
    try:
        doc_id = int(dados.get('doc_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='nota inválida'), 400
    marcar = 1 if dados.get('marcar') else 0

    conn = get_db_connection()
    try:
        _garante_coluna_pago_antes(conn)
        cur = conn.cursor(dictionary=True)
        if marcar:
            cur.execute("""
                SELECT COALESCE(d.valor_total,0) AS valor,
                       COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                                  WHERE v.documento_id = d.id), 0) AS vinculado
                  FROM dfe_documentos d WHERE d.id = %s""", (doc_id,))
            nota = cur.fetchone()
            if not nota:
                cur.close()
                return jsonify(ok=False, erro='nota não encontrada'), 404
            falta = float(nota['valor'] or 0) - float(nota['vinculado'] or 0)
            if falta <= 0.005:
                cur.close()
                return jsonify(ok=False, erro='a nota não tem falta nenhuma'), 400
            cur.execute("""UPDATE dfe_documentos SET quitado_pre_corte = %s
                            WHERE id = %s""", (round(falta, 2), doc_id))
        else:
            cur.execute("""UPDATE dfe_documentos SET quitado_pre_corte = 0
                            WHERE id = %s""", (doc_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/importar_nota', methods=['POST'])
@login_required
@admin_required
def importar_nota():
    """Traz uma NF-e pelo XML, para conferência, mesmo anterior ao corte.

    O caso que pediu isto: a MAX foi paga em 07/07 (R$ 9.090,00) por uma nota
    de 27/06 que a SEFAZ nunca entregou — a captura começa em 07/07. Sem a
    nota, aquele pagamento fica para sempre como adiantamento.

    A nota entra marcada com manual=1 e passa a valer na conferência apesar da
    data. É o XML autêntico da SEFAZ que manda: número, valor, emitente e
    itens saem dele, ninguém digita valor.
    """
    dados = request.get_json(silent=True) or {}
    xml_txt = (dados.get('xml') or '').strip()
    if not xml_txt:
        return jsonify(ok=False, erro='cole o XML da nota'), 400
    if '<' not in xml_txt:
        return jsonify(ok=False, erro='isso não parece um XML'), 400

    try:
        nota = _ler_nfe(xml_txt)
    except Exception as e:
        return jsonify(ok=False, erro='XML inválido: %s' % e), 400

    # Modelo 55 = NF-e. 57 e CT-e (frete, mora noutro lugar); 65 e cupom.
    if (nota.get('modelo') or '55') != '55':
        return jsonify(ok=False,
                       erro='só NF-e (modelo 55) entra aqui — este é modelo '
                            '%s' % nota.get('modelo')), 400
    if nota.get('situacao') == 'denegada':
        return jsonify(ok=False, erro='nota denegada não vira dívida'), 400
    if not nota.get('valor_total'):
        return jsonify(ok=False, erro='o XML não traz o valor total (vNF)'), 400

    conn = get_db_connection()
    try:
        _garante_coluna_manual(conn)
        cur = conn.cursor(dictionary=True)

        # O destinatário tem de ser UMA DAS SUAS empresas — senão qualquer XML
        # de qualquer um entraria na conferência da casa.
        cur.execute("""
            SELECT id, COALESCE(nome_fantasia, razao_social) AS nome
              FROM clientes
             WHERE REPLACE(REPLACE(REPLACE(cnpj,'.',''),'/',''),'-','') = %s
             LIMIT 1
        """, (nota.get('dest_cnpj') or '',))
        emp = cur.fetchone()
        if not emp:
            cur.close()
            return jsonify(ok=False,
                           erro='o destinatário da nota (%s) não é uma empresa '
                                'sua' % (nota.get('dest_cnpj') or '—')), 400

        cur.execute("SELECT id, entrada_manual FROM dfe_documentos WHERE chave = %s",
                    (nota['chave'],))
        ja = cur.fetchone()

        cur.close()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dfe_documentos
                (cliente_id, chave, tipo, schema_dfe, resumo, numero, serie,
                 modelo, dh_emissao, emit_cnpj, emit_nome, dest_cnpj,
                 valor_total, situacao, entrada_manual)
            VALUES (%s,%s,'NFe','manual',0,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            ON DUPLICATE KEY UPDATE
                numero=VALUES(numero), serie=VALUES(serie),
                dh_emissao=VALUES(dh_emissao), emit_cnpj=VALUES(emit_cnpj),
                emit_nome=VALUES(emit_nome), valor_total=VALUES(valor_total),
                resumo=0, entrada_manual=1
        """, (emp['id'], nota['chave'], nota['numero'], nota['serie'],
              nota['modelo'], nota['dh_emissao'], nota['emit_cnpj'],
              nota['emit_nome'], nota['dest_cnpj'], nota['valor_total'],
              nota['situacao']))

        cur.execute("SELECT id FROM dfe_documentos WHERE chave = %s",
                    (nota['chave'],))
        doc_id = cur.fetchone()[0]

        for it in nota.get('itens') or []:
            cur.execute(_SQL_ITEM_MANUAL, (
                doc_id, it['n_item'], it['produto_xml'], it['cprod_fornecedor'],
                it['cean'], it['cod_anp'], it['ncm'], it['unidade'],
                it['quantidade'], it['valor_unitario'], it['valor_total'],
            ))
        for dup in nota.get('duplicatas') or []:
            cur.execute(_SQL_DUP_MANUAL, (
                doc_id, dup['n_dup'], dup['vencimento'], dup['valor'],
            ))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify(
        ok=True,
        ja_existia=bool(ja),
        doc_id=doc_id,
        numero=nota['numero'],
        emitente=nota['emit_nome'],
        valor=float(nota['valor_total']),
        emissao=(nota['dh_emissao'] or '')[:10],
        empresa=emp['nome'],
        itens=len(nota.get('itens') or []),
    )


def _raizes_do_fornecedor(conn, fid):
    """Raiz do cadastro + as raízes que ele já titulariza (se for um grupo)."""
    cur = conn.cursor()
    cur.execute("SELECT %s FROM fornecedores f WHERE f.id = %%s" % _RAIZ_FORN,
                (fid,))
    row = cur.fetchone()
    raizes = {row[0]} if row and row[0] else set()
    cur.execute("SELECT raiz FROM fornecedor_grupo_raiz WHERE titular_id = %s",
                (fid,))
    raizes |= {r[0] for r in cur.fetchall()}
    cur.close()
    return raizes


@bp.route('/conf_fornecedores_dfe/agrupar', methods=['POST'])
@login_required
@admin_required
def agrupar():
    """Junta dois cadastros de raízes diferentes num fornecedor só.

    É o caso RODOIL/TOWER: paga-se para um CNPJ e o produto vem de outro, de
    empresa irmã. A raiz nunca resolve isso — matriz e filial ela já junta
    sozinha, mas raiz diferente é outra empresa. Aqui as duas (ou mais) passam
    a responder por um titular e o relatório soma nota e pagamento no mesmo
    card, mostrando as duas razões sociais.
    """
    dados = request.get_json(silent=True) or {}
    try:
        titular_id = int(dados.get('titular_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='fornecedor inválido'), 400

    # Duas entradas: outro CADASTRO (RODOIL + TOWER, os dois cadastrados) ou uma
    # RAIZ solta — a nota órfã, cujo emitente não está em fornecedores. É o caso
    # da DISTRIBUIDORA RODOBRAS: quem recebe o dinheiro está cadastrado, quem
    # emite a nota não, e sem isto o grupo seria impossível de montar.
    raiz_solta = ''.join(c for c in str(dados.get('raiz') or '') if c.isdigit())[:8]
    outro_id = None
    if not raiz_solta:
        try:
            outro_id = int(dados.get('fornecedor_id'))
        except (TypeError, ValueError):
            return jsonify(ok=False, erro='fornecedor inválido'), 400
        if titular_id == outro_id:
            return jsonify(ok=False, erro='escolha um fornecedor diferente'), 400
    elif len(raiz_solta) < 8:
        return jsonify(ok=False, erro='CNPJ do emitente inválido'), 400

    conn = get_db_connection()
    try:
        _garante_tabela_grupo(conn)
        raizes = _raizes_do_fornecedor(conn, titular_id)
        raizes |= ({raiz_solta} if raiz_solta
                   else _raizes_do_fornecedor(conn, outro_id))
        if not raizes:
            return jsonify(ok=False,
                           erro='esses cadastros não têm CNPJ — sem CNPJ não há '
                                'raiz para agrupar'), 400

        cur = conn.cursor()
        for raiz in sorted(raizes):
            cur.execute("""
                INSERT INTO fornecedor_grupo_raiz (raiz, titular_id, criado_por)
                     VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE titular_id = VALUES(titular_id),
                                        criado_por = VALUES(criado_por)
            """, (raiz, titular_id, getattr(current_user, 'id', None)))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify(ok=True, raizes=sorted(raizes))


@bp.route('/conf_fornecedores_dfe/desagrupar', methods=['POST'])
@login_required
@admin_required
def desagrupar():
    """Desfaz o grupo: cada raiz volta a responder por si (a raiz continua
    juntando matriz e filiais — isso não é grupo, é a mesma empresa)."""
    dados = request.get_json(silent=True) or {}
    try:
        titular_id = int(dados.get('titular_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='fornecedor inválido'), 400

    conn = get_db_connection()
    try:
        _garante_tabela_grupo(conn)
        cur = conn.cursor()
        cur.execute("DELETE FROM fornecedor_grupo_raiz WHERE titular_id = %s",
                    (titular_id,))
        conn.commit()
        apagou = cur.rowcount
        cur.close()
    finally:
        conn.close()

    if not apagou:
        return jsonify(ok=False, erro='esse fornecedor não é um grupo'), 404
    return jsonify(ok=True)


@bp.route('/conf_fornecedores_dfe/conferir', methods=['POST'])
@login_required
@admin_required
def conferir():
    """Marca/desmarca o "OK" de UMA nota (dfe_documentos.conferido).

    A coluna já existia na tabela desde a criação e estava sem uso — nada de
    migração. É só o visto de quem olhou a compra; não altera valor nem saldo.
    """
    dados = request.get_json(silent=True) or {}
    try:
        doc_id = int(dados.get('doc_id'))
    except (TypeError, ValueError):
        return jsonify(ok=False, erro='documento inválido'), 400
    marcar = 1 if dados.get('ok') else 0

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dfe_documentos SET conferido = %s WHERE id = %s",
                    (marcar, doc_id))
        if cur.rowcount == 0:
            cur.close()
            return jsonify(ok=False, erro='nota não encontrada'), 404
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify(ok=True, conferido=bool(marcar))
