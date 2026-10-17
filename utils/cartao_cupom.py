# -*- coding: utf-8 -*-
"""Casa a venda da operadora de cartao com o cupom fiscal (NFC-e) emitido.

A venda da operadora vem do arquivo dela (utils/cartao_arquivo); o cupom vem
de vendas_xml. Casados, as duas telas se completam: a Conferencia de Cartoes
mostra o numero do cupom de cada venda, e Vendas Migradas mostra se o cupom
de cartao foi pago pela operadora -- e qual cupom de cartao nao tem venda na
operadora (forma de pagamento errada no PDV, venda que nao passou).

Como casa, medido em set/2026:
  X7       o Excel traz o numero da NF-e                         3 de 3
  Baratao  a autorizacao do cupom (5 caracteres, ex. "31C2F") e o
           FINAL do codigo do cupom do Baratao ("...62831c2f")    140 de 164
  SIPAG    valor + bandeira + debito/credito + horario: quase
           sempre no mesmo minuto. Cupom de cartao sem bandeira
           no XML (lancamento manual) casa sem a bandeira.        ~83%
           Ate ago/2026 o PDV gravava o cupom de cartao com bandeira
           "Outros" (a do PIX): uma 3a passada, de 5 min, aceita.

A ligacao fica em cartao_cupom_vinculo e e refeita por janela de datas
(refazer): o cupom pode chegar depois do arquivo, e o arquivo depois do
cupom. Nada nas tabelas de origem e alterado.
"""
from collections import defaultdict
from datetime import datetime, timedelta

BARATAO_CNPJ = '41524064000179'
_BANDEIRAS = ('Visa', 'Mastercard', 'Elo', 'Amex', 'Cabal', 'Hipercard')
#: Quanto o cupom pode sair antes ou depois da transacao do cartao.
_JANELA_SIPAG = timedelta(minutes=15)
#: Para o cupom com bandeira "Outros" a janela e curta: e a bandeira do PIX.
_JANELA_OUTROS = timedelta(minutes=5)


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_cupom_vinculo (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            operadora      VARCHAR(20) NOT NULL,
            ref_id         INT         NOT NULL,
            vendas_xml_id  INT         NOT NULL,
            metodo         VARCHAR(30) NOT NULL,
            atualizado_em  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_ref (operadora, ref_id),
            UNIQUE KEY uk_cupom (vendas_xml_id),
            KEY ix_cupom (vendas_xml_id)
        )""")
    conn.commit()
    cur.close()


def _tipo(forma_pagamento):
    f = (forma_pagamento or '').lower()
    return 'D' if 'debito' in f or 'débito' in f else ('C' if 'credito' in f or 'crédito' in f else None)


def _cupons(cur, ini, fim, extra=''):
    cur.execute(f"""
        SELECT id, numero, serie, dh_emissao, valor_total, forma_pagamento,
               card_bandeira, card_autorizacao, cliente_doc
          FROM vendas_xml
         WHERE situacao = 'autorizada' AND dh_emissao >= %s AND dh_emissao < %s {extra}""",
        (ini, fim))
    return cur.fetchall()


def _casar_x7(cur, ini, fim, presos):
    cur.execute("""
        SELECT id, nfe, dt_operacao, bruto - desconto_lote AS valor
          FROM cartao_arquivo_vendas
         WHERE operadora='X7' AND dt_operacao >= %s AND dt_operacao < %s
           AND nfe IS NOT NULL AND nfe <> ''""", (ini, fim))
    vendas = cur.fetchall()
    if not vendas:
        return []
    nums = sorted({str(v['nfe']) for v in vendas})
    ph = ','.join(['%s'] * len(nums))
    cur.execute(f"""
        SELECT id, numero, dh_emissao, valor_total FROM vendas_xml
         WHERE situacao='autorizada' AND numero IN ({ph})""", nums)
    por_num = defaultdict(list)
    for c in cur.fetchall():
        por_num[str(c['numero'])].append(c)
    pares = []
    for v in vendas:
        # o numero pode repetir em outra serie: vale o do mesmo dia e mesmo valor
        cs = [c for c in por_num.get(str(v['nfe']), [])
              if c['id'] not in presos
              and abs((c['dh_emissao'] - v['dt_operacao']).total_seconds()) <= 86400
              and abs(float(c['valor_total']) - float(v['valor'])) < 0.05]
        if cs:
            c = min(cs, key=lambda c: abs((c['dh_emissao'] - v['dt_operacao']).total_seconds()))
            presos.add(c['id'])
            pares.append(('X7', v['id'], c['id'], 'nfe'))
    return pares


def _casar_baratao(cur, ini, fim, presos):
    cur.execute("""
        SELECT id, cupom, dt_abastecimento FROM cartao_baratao_cupons
         WHERE dt_abastecimento >= %s AND dt_abastecimento < %s""", (ini, fim))
    vendas = cur.fetchall()
    if not vendas:
        return []
    cupons = _cupons(cur, ini - timedelta(days=1), fim + timedelta(days=1),
                     "AND cliente_doc = '%s'" % BARATAO_CNPJ)
    por_aut = defaultdict(list)
    for c in cupons:
        a = (c['card_autorizacao'] or '').strip().upper()
        if len(a) >= 4:
            por_aut[a].append(c)
    pares = []
    for v in vendas:
        cod = (v['cupom'] or '').upper()
        cs = []
        for n in range(4, 9):          # a autorizacao tem 5 caracteres, as vezes mais
            cs += [c for c in por_aut.get(cod[-n:], []) if c['id'] not in presos]
        cs = [c for c in cs if abs((c['dh_emissao'] - v['dt_abastecimento']).total_seconds()) <= 86400]
        if cs:
            c = min(cs, key=lambda c: abs((c['dh_emissao'] - v['dt_abastecimento']).total_seconds()))
            presos.add(c['id'])
            pares.append(('BARATAO', v['id'], c['id'], 'autorizacao'))
    return pares


def _casar_sipag(cur, ini, fim, presos):
    cur.execute("""
        SELECT id, dt_transacao, bruto, bandeira, forma FROM cartao_sipag_transacoes
         WHERE nsu <> '0' AND arq_realizadas IS NOT NULL
           AND dt_transacao >= %s AND dt_transacao < %s
         ORDER BY dt_transacao""", (ini, fim))
    vendas = cur.fetchall()
    if not vendas:
        return []
    cupons = [c for c in _cupons(cur, ini - timedelta(hours=1), fim + timedelta(hours=1))
              if c['cliente_doc'] != BARATAO_CNPJ and _tipo(c['forma_pagamento'])
              and (c['card_bandeira'] in _BANDEIRAS or c['card_bandeira'] == 'Outros'
                   or not (c['card_bandeira'] or '').strip())]
    por_valor = defaultdict(list)
    for c in cupons:
        por_valor[round(float(c['valor_total']), 2)].append(c)
    pares = []
    # 1a passada: com a bandeira; 2a: cupom sem bandeira no XML (lancamento
    # manual); 3a: cupom com bandeira "Outros" (o PDV ate ago/2026), janela
    # curta. Todas pelo valor exato, pelo debito/credito e pelo horario.
    passadas = (
        ('valor+bandeira+hora', _JANELA_SIPAG, lambda c, v: c['card_bandeira'] == v['bandeira']),
        ('valor+hora', _JANELA_SIPAG, lambda c, v: not (c['card_bandeira'] or '').strip()),
        ('valor+hora (Outros)', _JANELA_OUTROS, lambda c, v: c['card_bandeira'] == 'Outros'),
    )
    for metodo, janela, bandeira_ok in passadas:
        for v in vendas:
            if v.get('_ok'):
                continue
            t = 'D' if (v['forma'] or '').startswith('D') else 'C'
            cs = [c for c in por_valor.get(round(float(v['bruto']), 2), [])
                  if c['id'] not in presos and _tipo(c['forma_pagamento']) == t
                  and abs(c['dh_emissao'] - v['dt_transacao']) <= janela
                  and bandeira_ok(c, v)]
            if cs:
                c = min(cs, key=lambda c: abs((c['dh_emissao'] - v['dt_transacao']).total_seconds()))
                presos.add(c['id'])
                v['_ok'] = True
                pares.append(('SIPAG', v['id'], c['id'], metodo))
    return pares


def refazer(conn, data_inicio, data_fim):
    """Refaz a ligacao das vendas da operadora com dt de venda em
    [data_inicio, data_fim]. Devolve {operadora: n_casadas}."""
    ensure_table(conn)
    ini = datetime.strptime(str(data_inicio)[:10], '%Y-%m-%d')
    fim = datetime.strptime(str(data_fim)[:10], '%Y-%m-%d') + timedelta(days=1)
    cur = conn.cursor(dictionary=True)
    try:
        # apaga a ligacao das vendas da janela, para refazer do zero
        for op, tab, col in (('X7', 'cartao_arquivo_vendas', 'dt_operacao'),
                             ('BARATAO', 'cartao_baratao_cupons', 'dt_abastecimento'),
                             ('SIPAG', 'cartao_sipag_transacoes', 'dt_transacao')):
            cur.execute(f"""
                DELETE v FROM cartao_cupom_vinculo v JOIN {tab} t ON t.id = v.ref_id
                 WHERE v.operadora = %s AND t.{col} >= %s AND t.{col} < %s""", (op, ini, fim))
        # cupom ja preso a venda de fora da janela nao pode ser reusado
        cur.execute("SELECT vendas_xml_id FROM cartao_cupom_vinculo")
        presos = {r['vendas_xml_id'] for r in cur.fetchall()}
        pares = (_casar_x7(cur, ini, fim, presos) + _casar_baratao(cur, ini, fim, presos)
                 + _casar_sipag(cur, ini, fim, presos))
        if pares:
            cur.executemany("""
                INSERT INTO cartao_cupom_vinculo (operadora, ref_id, vendas_xml_id, metodo)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE vendas_xml_id=VALUES(vendas_xml_id), metodo=VALUES(metodo)""",
                pares)
        conn.commit()
    finally:
        cur.close()
    out = defaultdict(int)
    for p in pares:
        out[p[0]] += 1
    return dict(out)


def cupons_das_vendas(conn, operadora, ref_ids):
    """{ref_id: {id, numero, serie, dh_emissao, valor_total}} das vendas casadas."""
    if not ref_ids:
        return {}
    ensure_table(conn)
    ph = ','.join(['%s'] * len(ref_ids))
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"""
            SELECT v.ref_id, x.id, x.numero, x.serie, x.dh_emissao, x.valor_total
              FROM cartao_cupom_vinculo v JOIN vendas_xml x ON x.id = v.vendas_xml_id
             WHERE v.operadora = %s AND v.ref_id IN ({ph})""", [operadora] + list(ref_ids))
        return {r['ref_id']: r for r in cur.fetchall()}
    finally:
        cur.close()


# ── o que Vendas Migradas mostra em cada cupom ───────────────────────────────

#: Classes de recebimento (utils.pagamentos) que sao venda de cartao -- e
#: que, por isso, tem de aparecer no arquivo de alguma operadora.
_CLASSES_CARTAO = ('Débito APP', 'Débito Manual', 'Crédito APP', 'Crédito Manual', 'Operadora')
#: A SIPAG assumiu as maquininhas em 15/07/2026 (utils/cartao_arquivo._sipag_desde).
_SIPAG_DESDE = datetime(2026, 7, 15)


def situacao_dos_cupons(conn, notas):
    """{vendas_xml_id: {txt, cls, title}} para a lista de Vendas Migradas.

    notas: os dicts da pagina (id, dh_emissao, recebimento, cliente_doc).
    - cupom casado: a operadora e se ja pagou ("SIPAG ✓ pago 02/10") ou
      quando paga ("SIPAG · a receber 19/10");
    - cupom de cartao sem venda na operadora, num dia que o arquivo dela ja
      cobre: "não achado na operadora" -- forma de pagamento errada no PDV,
      ou venda que nao passou na maquininha.
    """
    ids = [n['id'] for n in notas]
    if not ids:
        return {}
    try:
        ensure_table(conn)
    except Exception:
        return {}
    ph = ','.join(['%s'] * len(ids))
    out = {}
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"""
            SELECT v.vendas_xml_id AS cid, t.dt_pagamento AS pago, t.dt_prevista AS prev
              FROM cartao_cupom_vinculo v JOIN cartao_sipag_transacoes t ON t.id = v.ref_id
             WHERE v.operadora = 'SIPAG' AND v.vendas_xml_id IN ({ph})""", ids)
        sip = {r['cid']: r for r in cur.fetchall()}
        cur.execute(f"""
            SELECT v.vendas_xml_id AS cid, t.dt_liquidacao AS pago, t.dt_previsao AS prev
              FROM cartao_cupom_vinculo v JOIN cartao_arquivo_vendas t ON t.id = v.ref_id
             WHERE v.operadora = 'X7' AND v.vendas_xml_id IN ({ph})""", ids)
        x7 = {r['cid']: r for r in cur.fetchall()}
        cur.execute(f"""
            SELECT v.vendas_xml_id AS cid FROM cartao_cupom_vinculo v
             WHERE v.operadora = 'BARATAO' AND v.vendas_xml_id IN ({ph})""", ids)
        bar = {r['cid'] for r in cur.fetchall()}
        cur.execute("SELECT MAX(dt_transacao) AS m FROM cartao_sipag_transacoes "
                    "WHERE arq_realizadas IS NOT NULL")
        sip_ate = (cur.fetchone() or {}).get('m')
        cur.execute("SELECT MIN(dt_abastecimento) AS a, MAX(dt_abastecimento) AS m "
                    "FROM cartao_baratao_cupons")
        r = cur.fetchone() or {}
        bar_de, bar_ate = r.get('a'), r.get('m')
    except Exception:
        return {}
    finally:
        cur.close()

    def pago_txt(nome, r):
        if r['pago']:
            return {'txt': '%s ✓ pago %s' % (nome, r['pago'].strftime('%d/%m')), 'cls': 'ok',
                    'title': 'a operadora pagou esta venda em %s' % r['pago'].strftime('%d/%m/%Y')}
        prev = (' %s' % r['prev'].strftime('%d/%m')) if r['prev'] else ''
        return {'txt': '%s · a receber%s' % (nome, prev), 'cls': 'esp',
                'title': 'venda no arquivo da operadora, ainda não paga'}

    for n in notas:
        i = n['id']
        if i in sip:
            out[i] = pago_txt('SIPAG', sip[i])
        elif i in x7:
            out[i] = pago_txt('X7', x7[i])
        elif i in bar:
            out[i] = {'txt': 'Baratão ✓', 'cls': 'ok',
                      'title': 'venda no arquivo do Baratão (o pagamento é por dia, na Conferência de Cartões)'}
        elif n.get('recebimento') in _CLASSES_CARTAO and n.get('dh_emissao'):
            dt = n['dh_emissao']
            if n.get('cliente_doc') == BARATAO_CNPJ:
                cobre = bar_de and bar_ate and bar_de <= dt <= bar_ate - timedelta(hours=2)
            elif n.get('recebimento') == 'Operadora':
                cobre = False      # X7 e outras: o cupom e da frota, sem como saber
            else:
                cobre = sip_ate and _SIPAG_DESDE <= dt <= sip_ate - timedelta(hours=2)
            if cobre:
                out[i] = {'txt': 'não achado na operadora', 'cls': 'neg',
                          'title': 'cupom de cartão sem venda no arquivo da operadora: '
                                   'forma de pagamento errada no PDV, ou venda que não passou'}
    return out
