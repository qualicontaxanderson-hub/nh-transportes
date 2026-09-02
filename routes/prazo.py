"""PRAZO — Fase 1: enxergar o fiado e o combustivel da propria frota.

Le as vendas migradas (`vendas_xml`) filtrando a forma de pagamento a prazo,
junta por CPF/CNPJ do cliente, e cruza com o que ja entrou no banco
(`bank_transactions` marcado com a forma de recebimento do cliente).

Por que a tela existe
---------------------
As duas metades ja existiam e nunca se falaram:

  a VENDA  conhece o cliente pelo CPF/CNPJ (`vendas_xml.cliente_doc`, 100%
           preenchido nas 747 notas a prazo)
  o RECEBIMENTO conhece o cliente pelo NOME de uma forma de recebimento
           ("CLIENTE A PRAZO - X"), com R$ 1,7 milhao ja conciliado desde 2025

Falta a ponte. Casar por nome NAO serve — testado contra producao, pegou
"IRON BRAZ PARREIRA" no lugar de COMERCIAL E LOGISTICA BRAZ e "EMERSON A
CARMO" no lugar de EMERSON DIVINO REZENDE. Entao a ponte e feita a mao, uma
vez por cliente, e fica guardada em `prazo_cliente` — a UNICA tabela que esta
tela cria. Apagar essa tabela devolve a tela ao estado de so-leitura sem o
sistema perder nada.

Duas coisas diferentes moram sob a palavra "prazo", e a tela separa:

  a receber  — cliente de fora comprou fiado e vai pagar
  custo      — o proprio posto abastecendo a frota do grupo; nao se cobra
               boleto de si mesmo, o que importa e litro, real e km por placa

Tres abas:
  clientes — quem deve quanto, e onde vincular a forma de recebimento
  frota    — abastecimento por placa, com km/L de leituras seguidas
  conferir — km impossivel, cliente sem vinculo, placa fora do cadastro

Nao emite boleto e nao da baixa: isso e Fase 2, e depende de os clientes
estarem cadastrados em `clientes` (hoje 2 de 31 estao).
"""

import logging
import re
from datetime import date, datetime

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from utils.db import get_db_connection
from utils.fuso import hoje_brasilia

bp = Blueprint('prazo', __name__)

# A venda migrada comeca aqui. Antes disso nao existe nota no banco, entao
# nao da pra reconstituir saldo anterior — e a tela diz isso em vez de fingir
# que o cliente comecou do zero.
_INICIO_VENDA = date(2026, 5, 26)

# O que o SGA grava quando a venda e fiado. Sao varias grafias porque a base
# mudou de nome ao longo do tempo; todas convivem hoje.
_ONDE_PRAZO = ("(v.forma_pagamento LIKE '%Prazo%'"
               " OR v.forma_pagamento LIKE '%redito Loja%'"
               " OR v.forma_pagamento LIKE '%rédito Loja%')")

# Leitura de hodometro fora disto e dedo no teclado, nao quilometragem. Vem
# de olhar os dados: o RDT7H76 tem leituras indo de 6.941 a 1.587.741.
_KM_MIN_INTERVALO = 1
_KM_MAX_INTERVALO = 5000

_CORES = ['#1D63A5', '#7a6bab', '#17963C', '#c98a2b', '#a32d2d', '#0f7d8c',
          '#8a5a00', '#5c6bc0']

_tabela_pronta = False


def _f(v):
    """Decimal do MySQL vira float. Sem isto, dividir no Jinja estoura."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _so_digitos(s):
    return re.sub(r'\D', '', s or '')


def _garante_tabela():
    """Cria `prazo_cliente` — a ponte entre a venda e o recebimento.

    Uma linha por CPF/CNPJ que compra a prazo. Guarda com qual forma de
    recebimento aquele documento casa, se ele existe no cadastro de clientes,
    e se e empresa do grupo (que nao paga, so consome).

    Nao encosta em `vendas_xml`, `bank_transactions`, `formas_recebimento` nem
    `clientes`. Some sem deixar rastro.
    """
    global _tabela_pronta
    if _tabela_pronta:
        return
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prazo_cliente (
                id                   INT AUTO_INCREMENT PRIMARY KEY,
                cliente_doc          VARCHAR(14)  NOT NULL,
                forma_recebimento_id INT          NULL,
                cliente_id           INT          NULL,
                eh_grupo             TINYINT(1)   NOT NULL DEFAULT 0,
                observacao           VARCHAR(200) NULL,
                ajustado_por         VARCHAR(80)  NULL,
                ajustado_em          DATETIME     NOT NULL,
                UNIQUE KEY uq_prazo_cliente (cliente_doc)
            )
        """)
        conn.commit()
        _tabela_pronta = True
    except Exception:
        logging.getLogger(__name__).exception('[prazo] falha criando prazo_cliente')
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _vinculos(cur):
    """O de-para ja feito, por CPF/CNPJ."""
    cur.execute("""SELECT cliente_doc, forma_recebimento_id, cliente_id,
                          eh_grupo, observacao
                     FROM prazo_cliente""")
    return {r['cliente_doc']: r for r in cur.fetchall()}


def _clientes_a_prazo(cur, de, ate):
    """Quem comprou fiado no periodo, com quanto e quantas notas."""
    cur.execute("""
        SELECT v.cliente_doc,
               MAX(v.cliente_nome)                       AS nome,
               COUNT(*)                                  AS notas,
               SUM(v.valor_total)                        AS valor,
               MIN(DATE(v.dh_emissao))                   AS primeira,
               MAX(DATE(v.dh_emissao))                   AS ultima,
               COUNT(DISTINCT NULLIF(REPLACE(v.placa,'-',''), '')) AS placas,
               SUM(v.placa IS NOT NULL AND v.placa <> '')          AS com_placa
          FROM vendas_xml v
         WHERE """ + _ONDE_PRAZO + """
           AND DATE(v.dh_emissao) BETWEEN %s AND %s
           AND v.cliente_doc IS NOT NULL AND v.cliente_doc <> ''
         GROUP BY v.cliente_doc
         ORDER BY SUM(v.valor_total) DESC
    """, (de, ate))
    return cur.fetchall()


def _litros_por_cliente(cur, de, ate):
    """Litros de combustivel por cliente — so o que e combustivel mesmo."""
    cur.execute("""
        SELECT v.cliente_doc, COALESCE(SUM(i.quantidade), 0) AS litros
          FROM vendas_xml v
          JOIN vendas_xml_itens i ON i.venda_id = v.id AND i.eh_combustivel = 1
         WHERE """ + _ONDE_PRAZO + """
           AND DATE(v.dh_emissao) BETWEEN %s AND %s
         GROUP BY v.cliente_doc
    """, (de, ate))
    return {r['cliente_doc']: _f(r['litros']) for r in cur.fetchall()}


def _recebido(cur, formas, de, ate):
    """Quanto entrou no banco por cada forma de recebimento, no periodo.

    So credito (valor > 0). O periodo e o MESMO da venda de proposito: o
    recebimento existe desde 2025, e somar tudo daria um saldo negativo que
    nao quer dizer nada.
    """
    if not formas:
        return {}
    marc = ','.join(['%s'] * len(formas))
    cur.execute("""
        SELECT forma_recebimento_id AS fid, COUNT(*) AS n,
               COALESCE(SUM(valor), 0) AS valor, MAX(DATE(data_transacao)) AS ultimo
          FROM bank_transactions
         WHERE valor > 0
           AND forma_recebimento_id IN (""" + marc + """)
           AND DATE(data_transacao) BETWEEN %s AND %s
         GROUP BY forma_recebimento_id
    """, tuple(formas) + (de, ate))
    return {r['fid']: r for r in cur.fetchall()}


def _formas_disponiveis(cur, de, ate):
    """As formas de recebimento que servem de destino do vinculo, COM a prova.

    Vem todas, e nao so as que tem PRAZO no nome: um cliente pode ser pago por
    boleto do banco, e essa forma se chama outra coisa.

    Cada forma vem acompanhada de quanto ela recebeu no periodo. Isso nao e
    enfeite: sao 93 formas no cadastro, 28 delas duplicatas desativadas, e o
    nome sozinho ja escolheu errado nesta base. O dinheiro e a evidencia que
    confirma o nome -- o cliente comprou R$ 132 mil e a forma recebeu R$ 89
    mil, entao e essa. Sem esse numero a escolha e um chute.
    """
    cur.execute("""
        SELECT f.id, f.nome, f.ativo,
               COUNT(b.id)                        AS creditos,
               ROUND(COALESCE(SUM(b.valor), 0), 2) AS valor,
               MAX(DATE(b.data_transacao))        AS ultimo
          FROM formas_recebimento f
          LEFT JOIN bank_transactions b
                 ON b.forma_recebimento_id = f.id
                AND b.valor > 0
                AND DATE(b.data_transacao) BETWEEN %s AND %s
         GROUP BY f.id, f.nome, f.ativo
         ORDER BY (f.nome LIKE '%%PRAZO%%') DESC, f.ativo DESC, f.nome
    """, (de, ate))
    return cur.fetchall()


def _formas_para_tela(formas, clientes):
    """Empacota as formas para o JavaScript da gaveta.

    Junta o dono: se a forma ja e de outro cliente, a gaveta avisa em vermelho.
    Dois clientes na mesma forma misturam o saldo dos dois -- e a tela existe
    justamente para impedir esse erro, entao ela precisa saber quem ja tem.
    """
    dono = {}
    for c in clientes:
        if c.get('forma_id'):
            dono[c['forma_id']] = c
    saida = []
    for f in formas:
        d = dono.get(f['id'])
        saida.append({
            'id': f['id'],
            'nome': f['nome'],
            'ativo': int(f['ativo'] or 0),
            'valor': _f(f['valor']),
            'creditos': int(f['creditos'] or 0),
            'ultimo': f['ultimo'].strftime('%d/%m/%Y') if f['ultimo'] else None,
            'dono_doc': d['doc'] if d else None,
            'dono_nome': d['nome'] if d else None,
        })
    return saida


def _monta_clientes(cur, de, ate):
    """Junta compra + recebimento + vinculo numa linha por cliente."""
    linhas = _clientes_a_prazo(cur, de, ate)
    litros = _litros_por_cliente(cur, de, ate)
    vinc = _vinculos(cur)

    formas = [v['forma_recebimento_id'] for v in vinc.values()
              if v['forma_recebimento_id']]
    receb = _recebido(cur, formas, de, ate)

    cur.execute("SELECT id, nome FROM formas_recebimento")
    nome_forma = {r['id']: r['nome'] for r in cur.fetchall()}

    saida = []
    for i, r in enumerate(linhas):
        doc = r['cliente_doc']
        v = vinc.get(doc) or {}
        fid = v.get('forma_recebimento_id')
        rec = receb.get(fid) if fid else None
        comprou = _f(r['valor'])
        recebeu = _f(rec['valor']) if rec else 0.0
        grupo = bool(v.get('eh_grupo'))

        saida.append({
            'doc': doc,
            'doc_fmt': _doc_bonito(doc),
            'nome': r['nome'] or '(sem nome)',
            'cor': _CORES[i % len(_CORES)],
            'notas': r['notas'],
            'litros': litros.get(doc, 0.0),
            'comprou': comprou,
            'recebeu': recebeu,
            # Grupo nao gera saldo: o posto nao cobra de si mesmo.
            'saldo': 0.0 if grupo else round(comprou - recebeu, 2),
            'primeira': r['primeira'],
            'ultima': r['ultima'],
            'placas': r['placas'] or 0,
            'com_placa': int(r['com_placa'] or 0),
            'forma_id': fid,
            'forma_nome': nome_forma.get(fid),
            'cliente_id': v.get('cliente_id'),
            'eh_grupo': grupo,
            'observacao': v.get('observacao'),
            'recebimentos': rec['n'] if rec else 0,
            'ultimo_receb': rec['ultimo'] if rec else None,
            'estado': ('grupo' if grupo
                       else 'sem_vinculo' if not fid
                       else 'quitado' if comprou - recebeu <= 0.01
                       else 'devendo'),
        })
    return saida


def _doc_bonito(doc):
    d = _so_digitos(doc)
    if len(d) == 14:
        return '%s.%s.%s/%s-%s' % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])
    if len(d) == 11:
        return '%s.%s.%s-%s' % (d[:3], d[3:6], d[6:9], d[9:])
    return doc


def _frota(cur, de, ate):
    """Abastecimento por placa, com km/L de leituras seguidas.

    O km/L sai so de intervalos plausiveis. Leitura que anda pra tras ou pula
    mais de 5.000 km entre dois abastecimentos e erro de digitacao e fica de
    fora da conta — mas aparece contada, pra ninguem achar que sumiu.
    """
    cur.execute("""
        SELECT UPPER(REPLACE(REPLACE(v.placa,'-',''),' ','')) AS placa,
               MAX(v.cliente_nome) AS cliente, v.cliente_doc,
               COUNT(*) AS abastecimentos,
               SUM(v.valor_total) AS valor,
               COALESCE(SUM((SELECT SUM(i.quantidade) FROM vendas_xml_itens i
                              WHERE i.venda_id = v.id AND i.eh_combustivel = 1)), 0) AS litros,
               MIN(DATE(v.dh_emissao)) AS primeiro, MAX(DATE(v.dh_emissao)) AS ultimo
          FROM vendas_xml v
         WHERE """ + _ONDE_PRAZO + """
           AND DATE(v.dh_emissao) BETWEEN %s AND %s
           AND v.placa IS NOT NULL AND v.placa <> ''
         GROUP BY placa, v.cliente_doc
         ORDER BY SUM(v.valor_total) DESC
    """, (de, ate))
    placas = cur.fetchall()

    # leituras de km, por placa, em ordem
    cur.execute("""
        SELECT UPPER(REPLACE(REPLACE(v.placa,'-',''),' ','')) AS placa,
               DATE(v.dh_emissao) AS dia, v.km,
               (SELECT SUM(i.quantidade) FROM vendas_xml_itens i
                 WHERE i.venda_id = v.id AND i.eh_combustivel = 1) AS litros
          FROM vendas_xml v
         WHERE """ + _ONDE_PRAZO + """
           AND DATE(v.dh_emissao) BETWEEN %s AND %s
           AND v.placa IS NOT NULL AND v.placa <> ''
           AND v.km IS NOT NULL AND v.km > 0
         ORDER BY placa, v.dh_emissao
    """, (de, ate))
    leituras = {}
    for r in cur.fetchall():
        leituras.setdefault(r['placa'], []).append(r)

    cur.execute("""SELECT UPPER(REPLACE(REPLACE(placa,'-',''),' ','')) AS p
                     FROM veiculos WHERE placa IS NOT NULL AND placa <> ''""")
    frota_cad = set(r['p'] for r in cur.fetchall())
    cur.execute("""SELECT UPPER(REPLACE(REPLACE(placa_carreta,'-',''),' ','')) AS p
                     FROM veiculos WHERE placa_carreta IS NOT NULL AND placa_carreta <> ''""")
    frota_cad |= set(r['p'] for r in cur.fetchall())

    saida = []
    total_valor = sum(_f(p['valor']) for p in placas) or 1.0
    for i, p in enumerate(placas):
        seq = leituras.get(p['placa'], [])
        km_ok = 0.0
        litros_ok = 0.0
        descartadas = 0
        ant = None
        for r in seq:
            if ant is not None:
                dif = (r['km'] or 0) - ant
                if _KM_MIN_INTERVALO <= dif <= _KM_MAX_INTERVALO and r['litros']:
                    km_ok += dif
                    litros_ok += _f(r['litros'])
                else:
                    descartadas += 1
            ant = r['km'] or 0
        litros = _f(p['litros'])
        valor = _f(p['valor'])
        saida.append({
            'placa': p['placa'],
            'cliente': p['cliente'] or '(sem nome)',
            'doc': p['cliente_doc'],
            'cor': _CORES[i % len(_CORES)],
            'abastecimentos': p['abastecimentos'],
            'litros': litros,
            'valor': valor,
            'primeiro': p['primeiro'],
            'ultimo': p['ultimo'],
            'leituras': len(seq),
            'km_rodado': km_ok,
            'descartadas': descartadas,
            'km_litro': round(km_ok / litros_ok, 2) if litros_ok else None,
            'custo_km': round(valor / km_ok, 2) if km_ok else None,
            'preco_litro': round(valor / litros, 3) if litros else None,
            'na_frota': p['placa'] in frota_cad,
            'pct': round(valor / total_valor * 100, 1),
        })
    return saida


def _conferencia(cur, de, ate, clientes, frota):
    """O que esta estranho. Mostra e deixa a pessoa julgar — nao corrige nada."""
    pontos = []

    sem_vinc = [c for c in clientes if c['estado'] == 'sem_vinculo']
    if sem_vinc:
        pontos.append({
            'titulo': 'Cliente a prazo sem forma de recebimento vinculada',
            'n': len(sem_vinc),
            'gravidade': 'alerta',
            'porque': ('Sem o vinculo nao da pra saber quanto ja foi pago. '
                       'E o de-para que voce arruma aos poucos, aqui mesmo.'),
            'itens': [{'texto': c['nome'], 'detalhe': '%s · %d notas' % (c['doc_fmt'], c['notas']),
                       'valor': c['comprou'], 'doc': c['doc']} for c in sem_vinc[:20]],
        })

    ruins = [p for p in frota if p['descartadas']]
    if ruins:
        pontos.append({
            'titulo': 'Leitura de km impossivel',
            'n': sum(p['descartadas'] for p in ruins),
            'gravidade': 'alerta',
            'porque': ('Hodometro que anda pra tras ou pula mais de 5.000 km entre '
                       'dois abastecimentos. Ficam de fora do km/L, mas o valor '
                       'em reais continua contando.'),
            'itens': [{'texto': p['placa'], 'detalhe': '%s · %d de %d leituras'
                       % (p['cliente'][:28], p['descartadas'], p['leituras']),
                       'valor': p['valor'], 'doc': None} for p in ruins[:20]],
        })

    fora = [p for p in frota if not p['na_frota']]
    if fora:
        pontos.append({
            'titulo': 'Placa que abastece a prazo e nao esta no cadastro de veiculos',
            'n': len(fora),
            'gravidade': 'aviso',
            'porque': ('Normal para caminhao de cliente. Vira problema quando e '
                       'veiculo do proprio grupo: sem cadastro, nao entra em '
                       'nenhum outro relatorio do app.'),
            'itens': [{'texto': p['placa'], 'detalhe': p['cliente'][:34],
                       'valor': p['valor'], 'doc': None} for p in fora[:20]],
        })

    sem_cad = [c for c in clientes if not c['cliente_id'] and not c['eh_grupo']]
    if sem_cad:
        pontos.append({
            'titulo': 'Cliente a prazo sem cadastro em Clientes',
            'n': len(sem_cad),
            'gravidade': 'aviso',
            'porque': ('A tela funciona sem isso — usa o CPF/CNPJ da propria nota. '
                       'Mas emitir boleto exige o cadastro.'),
            'itens': [{'texto': c['nome'], 'detalhe': c['doc_fmt'],
                       'valor': c['comprou'], 'doc': c['doc']} for c in sem_cad[:20]],
        })

    negativos = [c for c in clientes if c['saldo'] < -0.01]
    if negativos:
        pontos.append({
            'titulo': 'Recebido a mais do que foi comprado no periodo',
            'n': len(negativos),
            'gravidade': 'alerta',
            'porque': ('Quase sempre quer dizer que o dinheiro pagou compra '
                       'anterior a %s, que e onde a venda migrada comeca — nao '
                       'que ha erro.' % _INICIO_VENDA.strftime('%d/%m/%Y')),
            'itens': [{'texto': c['nome'], 'detalhe': 'comprou %.2f, recebeu %.2f'
                       % (c['comprou'], c['recebeu']),
                       'valor': c['saldo'], 'doc': c['doc']} for c in negativos[:20]],
        })

    return pontos


@bp.route('/prazo/', methods=['GET'])
@login_required
def index():
    _garante_tabela()
    modo = request.args.get('modo', 'clientes')
    if modo not in ('clientes', 'frota', 'conferir'):
        modo = 'clientes'

    hoje = hoje_brasilia()
    try:
        de = datetime.strptime(request.args.get('de', ''), '%Y-%m-%d').date()
    except ValueError:
        de = _INICIO_VENDA
    try:
        ate = datetime.strptime(request.args.get('ate', ''), '%Y-%m-%d').date()
    except ValueError:
        ate = hoje

    conn = cur = None
    ctx = {'modo': modo, 'de': de, 'ate': ate, 'hoje': hoje,
           'inicio_venda': _INICIO_VENDA, 'clientes': [], 'frota': [],
           'pontos': [], 'formas': [], 'totais': {}, 'erro': None}
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        clientes = _monta_clientes(cur, de, ate)
        frota = _frota(cur, de, ate)
        ctx['clientes'] = clientes
        ctx['frota'] = frota
        ctx['formas'] = _formas_para_tela(_formas_disponiveis(cur, de, ate),
                                          clientes)
        ctx['pontos'] = _conferencia(cur, de, ate, clientes, frota)

        externos = [c for c in clientes if not c['eh_grupo']]
        grupo = [c for c in clientes if c['eh_grupo']]
        ctx['totais'] = {
            'clientes': len(externos),
            'comprou': round(sum(c['comprou'] for c in externos), 2),
            'recebeu': round(sum(c['recebeu'] for c in externos), 2),
            'saldo': round(sum(c['saldo'] for c in externos if c['saldo'] > 0), 2),
            'sem_vinculo': len([c for c in clientes if c['estado'] == 'sem_vinculo']),
            'grupo_valor': round(sum(c['comprou'] for c in grupo), 2),
            'grupo_n': len(grupo),
            'frota_valor': round(sum(p['valor'] for p in frota), 2),
            'frota_litros': round(sum(p['litros'] for p in frota), 0),
            'frota_km': round(sum(p['km_rodado'] for p in frota), 0),
            'problemas': sum(p['n'] for p in ctx['pontos'] if p['gravidade'] == 'alerta'),
        }
    except Exception as exc:
        logging.getLogger(__name__).exception('[prazo] falha montando a tela')
        ctx['erro'] = str(exc)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return render_template('prazo/index.html', **ctx)


@bp.route('/prazo/vincular', methods=['POST'])
@login_required
def vincular():
    """Guarda o de-para de UM cliente. E o unico gravar desta tela.

    Nao toca em venda, em extrato nem em cobranca — so diz "este CPF/CNPJ
    corresponde a esta forma de recebimento". Refazer o vinculo e seguro:
    o saldo e recalculado na leitura, nada fica congelado.
    """
    _garante_tabela()
    dados = request.get_json(silent=True) or {}
    doc = _so_digitos(dados.get('doc'))
    if not doc:
        return jsonify({'ok': False, 'erro': 'sem CPF/CNPJ'}), 400

    forma = dados.get('forma_id')
    forma = int(forma) if str(forma or '').isdigit() else None
    cliente = dados.get('cliente_id')
    cliente = int(cliente) if str(cliente or '').isdigit() else None
    grupo = 1 if dados.get('eh_grupo') else 0
    obs = (dados.get('observacao') or '').strip()[:200] or None

    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO prazo_cliente
                   (cliente_doc, forma_recebimento_id, cliente_id, eh_grupo,
                    observacao, ajustado_por, ajustado_em)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                   forma_recebimento_id = VALUES(forma_recebimento_id),
                   cliente_id           = VALUES(cliente_id),
                   eh_grupo             = VALUES(eh_grupo),
                   observacao           = VALUES(observacao),
                   ajustado_por         = VALUES(ajustado_por),
                   ajustado_em          = NOW()
        """, (doc, forma, cliente, grupo, obs,
              getattr(current_user, 'nome_completo', None) or 'sistema'))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as exc:
        logging.getLogger(__name__).exception('[prazo] falha no vinculo de %s', doc)
        return jsonify({'ok': False, 'erro': str(exc)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@bp.route('/prazo/notas', methods=['GET'])
@login_required
def notas():
    """As notas de um cliente — usado pela gaveta, sem recarregar a tela."""
    doc = _so_digitos(request.args.get('doc'))
    if not doc:
        return jsonify({'ok': False, 'erro': 'sem CPF/CNPJ'}), 400
    try:
        de = datetime.strptime(request.args.get('de', ''), '%Y-%m-%d').date()
    except ValueError:
        de = _INICIO_VENDA
    try:
        ate = datetime.strptime(request.args.get('ate', ''), '%Y-%m-%d').date()
    except ValueError:
        ate = hoje_brasilia()

    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT v.id, v.numero, DATE(v.dh_emissao) AS dia, v.placa, v.km,
                   v.valor_total, v.forma_pagamento,
                   (SELECT SUM(i.quantidade) FROM vendas_xml_itens i
                     WHERE i.venda_id = v.id AND i.eh_combustivel = 1) AS litros,
                   (SELECT GROUP_CONCAT(DISTINCT i.produto_xml SEPARATOR ', ')
                      FROM vendas_xml_itens i WHERE i.venda_id = v.id) AS produtos
              FROM vendas_xml v
             WHERE """ + _ONDE_PRAZO + """
               AND v.cliente_doc = %s
               AND DATE(v.dh_emissao) BETWEEN %s AND %s
             ORDER BY v.dh_emissao DESC
             LIMIT 300
        """, (doc, de, ate))
        linhas = []
        for r in cur.fetchall():
            linhas.append({
                'numero': r['numero'],
                'dia': r['dia'].strftime('%d/%m/%Y') if r['dia'] else '',
                'placa': r['placa'] or '',
                'km': r['km'] or 0,
                'litros': _f(r['litros']),
                'valor': _f(r['valor_total']),
                'produtos': (r['produtos'] or '')[:80],
            })
        return jsonify({'ok': True, 'notas': linhas,
                        'total': round(sum(x['valor'] for x in linhas), 2)})
    except Exception as exc:
        logging.getLogger(__name__).exception('[prazo] falha listando notas de %s', doc)
        return jsonify({'ok': False, 'erro': str(exc)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
