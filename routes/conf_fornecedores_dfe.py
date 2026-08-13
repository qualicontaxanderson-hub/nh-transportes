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

# O que conta como compra nossa:
#   - NF-e (CT-e mora em dfe_cte e é frete, não compra);
#   - autorizada (cancelada/denegada não gera dívida);
#   - não pode ser 100% "ignorar" (a marcação de "esta nota não é nossa").
# Resumo (resNFe) não tem item nenhum e PASSA de propósito: ele já traz o valor
# total e portanto já é dívida, mesmo antes do XML completo chegar.
_FILTRO_NOTA = """
        d.tipo = 'NFe'
    AND d.situacao = 'autorizado'
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
# É o mesmo corte da tela "Pendente pra Descer" (estoque.DATA_CORTE_PENDENTE).
# Ajuste aqui se a captura for reprocessada mais para trás.
DATA_CORTE_DFE = '2026-08-01'

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
    where = [_FILTRO_NOTA, "d.dh_emissao >= %s", "d.dh_emissao < %s"]
    params = [DATA_CORTE_DFE + " 00:00:00", data_ini + " 00:00:00"]
    _em("d.cliente_id", empresa_ids, where, params)
    _em("f.id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT f.id AS fornecedor_id, COALESCE(SUM(d.valor_total),0) AS total
          FROM dfe_documentos d
          JOIN fornecedores f ON %s = %s
         WHERE %s
         GROUP BY f.id
    """ % (_CNPJ_FORN, _CNPJ_NOTA, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return {r['fornecedor_id']: float(r['total'] or 0) for r in rows}


def _pagamentos_anteriores(conn, data_ini, empresa_ids, fornecedor_ids):
    where = ["bt.tipo = 'DEBIT'", "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao >= %s", "bt.data_transacao < %s"]
    params = [DATA_CORTE_DFE, data_ini]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("bt.fornecedor_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT bt.fornecedor_id, COALESCE(SUM(bt.valor),0) AS total
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
         WHERE %s
         GROUP BY bt.fornecedor_id
    """ % " AND ".join(where), params)
    rows = cur.fetchall()
    cur.close()
    return {r['fornecedor_id']: float(r['total'] or 0) for r in rows}


def _notas_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids):
    where = [_FILTRO_NOTA, "d.dh_emissao BETWEEN %s AND %s"]
    params = [data_ini + " 00:00:00", data_fim + " 23:59:59"]
    _em("d.cliente_id", empresa_ids, where, params)
    _em("f.id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT f.id                                       AS fornecedor_id,
               f.razao_social                             AS fornecedor_nome,
               f.cnpj                                     AS fornecedor_cnpj,
               d.id                                       AS doc_id,
               d.chave, d.numero, d.serie, d.dh_emissao,
               COALESCE(d.valor_total,0)                  AS valor,
               d.resumo, d.conferido,
               COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
          FROM dfe_documentos d
          JOIN fornecedores f ON %s = %s
          LEFT JOIN clientes emp ON emp.id = d.cliente_id
         WHERE %s
         ORDER BY d.dh_emissao, d.id
    """ % (_CNPJ_FORN, _CNPJ_NOTA, " AND ".join(where)), params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _pagamentos_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids):
    where = ["bt.tipo = 'DEBIT'", "bt.fornecedor_id IS NOT NULL",
             "bt.data_transacao BETWEEN %s AND %s"]
    params = [data_ini, data_fim]
    _em("ba.cliente_id", empresa_ids, where, params)
    _em("bt.fornecedor_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT bt.id, bt.fornecedor_id, bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0)                       AS valor,
               f.razao_social                             AS fornecedor_nome,
               f.cnpj                                     AS fornecedor_cnpj,
               COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN fornecedores f   ON f.id = bt.fornecedor_id
          LEFT JOIN clientes emp ON emp.id = ba.cliente_id
         WHERE %s
         ORDER BY bt.data_transacao, bt.id
    """ % " AND ".join(where), params)
    rows = cur.fetchall()
    cur.close()
    return rows


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


def _vinculos(conn, doc_ids):
    """Vínculos manuais das notas em tela: doc_id -> lista de pagamentos.

    Também devolve quanto de cada pagamento já está comprometido, pra não
    deixar amarrar o mesmo dinheiro em duas notas.
    """
    if not doc_ids:
        return {}, {}
    ph = ','.join(['%s'] * len(doc_ids))

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT v.id, v.documento_id, v.transacao_id, v.valor,
               bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0) AS valor_pagamento
          FROM dfe_pagamento_nota v
          JOIN bank_transactions bt ON bt.id = v.transacao_id
         WHERE v.documento_id IN (%s)
         ORDER BY bt.data_transacao, v.id
    """ % ph, list(doc_ids))
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

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT DISTINCT bt.id, bt.fornecedor_id, bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0)                          AS valor,
               f.razao_social                                AS fornecedor_nome,
               f.cnpj                                        AS fornecedor_cnpj,
               COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
          FROM dfe_pagamento_nota v
          JOIN bank_transactions bt ON bt.id = v.transacao_id
          JOIN bank_accounts ba     ON ba.id = bt.account_id
          JOIN fornecedores f       ON f.id = bt.fornecedor_id
          LEFT JOIN clientes emp    ON emp.id = ba.cliente_id
         WHERE v.documento_id IN (%s)
           AND (bt.data_transacao < %s OR bt.data_transacao > %s)
         ORDER BY bt.data_transacao, bt.id
    """ % ph, params)
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
    _em("bt.fornecedor_id", fornecedor_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT bt.fornecedor_id, bt.data_transacao, bt.descricao,
               COALESCE(bt.valor,0) AS valor
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
         WHERE %s
         ORDER BY bt.data_transacao DESC, bt.id DESC
    """ % " AND ".join(where), params)
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
    where = [_FILTRO_NOTA, "d.dh_emissao BETWEEN %s AND %s", "f.id IS NULL"]
    params = [data_ini + " 00:00:00", data_fim + " 23:59:59"]
    _em("d.cliente_id", empresa_ids, where, params)

    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT d.emit_cnpj, d.emit_nome,
               COUNT(*)                    AS notas,
               COALESCE(SUM(d.valor_total),0) AS total,
               MAX(d.dh_emissao)           AS ultima
          FROM dfe_documentos d
          LEFT JOIN fornecedores f ON %s = %s
         WHERE %s
         GROUP BY d.emit_cnpj, d.emit_nome
         ORDER BY total DESC
    """ % (_CNPJ_FORN, _CNPJ_NOTA, " AND ".join(where)), params)
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
        if l['tipo'] == 'pagamento':
            # Só a parte LIVRE do pagamento entra no rateio automático: o que
            # já foi amarrado à mão tem dono.
            caixa += max(l['valor'] - l.get('usado', 0.0), 0.0)
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
            # A nota já entra abatida do que foi vinculado à mão.
            l['falta'] = max(l['valor'] - l.get('vinc_total', 0.0), 0.0)
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
           vinculos=None, usado=None):
    """Uma linha do tempo por fornecedor, com saldo corrente.

    Ordem: por data; empatou, pagamento antes da nota — é a sequência real
    (paga de manhã, nota sai à tarde) e deixa o saldo do dia legível.
    """
    vinculos = vinculos or {}
    usado = usado or {}
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
            'chave': n['chave'],
            'vinculos': vinculos.get(n['doc_id'], []),
            'vinc_total': sum(v['valor'] for v in vinculos.get(n['doc_id'], [])),
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
            else:
                saldo -= ev['valor']
                comprado += ev['valor']
            linhas.append(dict(ev, saldo=saldo))

        if not linhas and abs(saldo_anterior) < 0.005:
            continue                      # zerado e parado: não polui a tela

        sobra, descoberto = _aloca_fifo(linhas, saldo_anterior)
        notas_lin = [l for l in linhas if l['tipo'] == 'nota']

        # Pagamento de antes do corte só interessa quando o fornecedor aparece
        # DEVENDO: é a suspeita de "isso já foi pago no mês passado".
        antes = (pre_corte or {}).get(fid)
        if antes and saldo >= -0.005:
            antes = None

        saida.append({
            'fornecedor_id': fid,
            'nome': f['nome'] or '(fornecedor %s)' % fid,
            'cnpj': f['cnpj'] or '',
            'saldo_anterior': saldo_anterior,
            'comprado': comprado,
            'pago': pago,
            'saldo_final': saldo,
            'linhas': linhas,
            'notas_total': len(notas_lin),
            'notas_ok': sum(1 for l in notas_lin if l['conferido']),
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
        empresas = _empresas(conn)
        fornecedores = _fornecedores(conn)
        duplicados = _cnpjs_duplicados(conn)
        janela = _janela_captura(conn)

        notas_ant = _notas_anteriores(conn, data_ini, empresa_ids, fornecedor_ids)
        pagos_ant = _pagamentos_anteriores(conn, data_ini, empresa_ids, fornecedor_ids)
        notas = _notas_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids)
        pagamentos = _pagamentos_periodo(conn, data_ini, data_fim, empresa_ids, fornecedor_ids)
        orfas = _notas_sem_fornecedor(conn, data_ini, data_fim, empresa_ids)
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
    finally:
        conn.close()

    dados = _monta(notas, pagamentos, notas_ant, pagos_ant, pre_corte,
                   vinculos, usado)

    totais = {
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
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT d.id, d.numero, d.serie, d.dh_emissao, d.emit_cnpj,
                   COALESCE(d.valor_total,0) AS valor,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.documento_id = d.id), 0) AS vinculado
              FROM dfe_documentos d WHERE d.id = %s
        """, (doc_id,))
        nota = cur.fetchone()
        if not nota:
            cur.close()
            return jsonify(ok=False, erro='nota não encontrada'), 404

        cur.execute("""
            SELECT bt.id, bt.data_transacao, bt.descricao,
                   COALESCE(bt.valor,0) AS valor,
                   COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v
                              WHERE v.transacao_id = bt.id), 0) AS usado
              FROM bank_transactions bt
              JOIN fornecedores f ON f.id = bt.fornecedor_id
             WHERE bt.tipo = 'DEBIT'
               AND bt.fornecedor_id IS NOT NULL
               AND %s = LPAD(%s,14,'0')
             ORDER BY ABS(DATEDIFF(bt.data_transacao, %s)), bt.data_transacao DESC
             LIMIT 40
        """ % (_CNPJ_FORN, '%s', '%s'),
            (nota['emit_cnpj'] or '', nota['dh_emissao']))
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

    falta = float(nota['valor'] or 0) - float(nota['vinculado'] or 0)
    return jsonify(ok=True, falta=round(max(falta, 0.0), 2),
                   nota='NF-e nº %s%s' % (nota['numero'] or '—',
                                          ('/%s' % nota['serie']) if nota['serie'] else ''),
                   candidatos=livres)


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
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT COALESCE(d.valor_total,0) AS valor, d.emit_cnpj,
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
                   %s AS cnpj_forn
              FROM bank_transactions bt
              JOIN fornecedores f ON f.id = bt.fornecedor_id
             WHERE bt.id = %%s AND bt.tipo = 'DEBIT'
        """ % ('%s', _CNPJ_FORN), (doc_id, tx_id))
        pg = cur.fetchone()
        if not pg:
            cur.close()
            return jsonify(ok=False, erro='pagamento não encontrado'), 404

        # O pagamento tem de ser do fornecedor da nota — o usuário já concilia
        # o lançamento no fornecedor certo, então isto é só uma trava.
        if (pg['cnpj_forn'] or '') != (nota['emit_cnpj'] or '').rjust(14, '0'):
            cur.close()
            return jsonify(ok=False,
                           erro='esse pagamento está conciliado noutro fornecedor'), 400

        falta = float(nota['valor']) - float(nota['outros'])
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
