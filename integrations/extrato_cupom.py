"""
PIX recebido no extrato (API do banco) ⇄ cupom da venda (vendas_xml, NFC-e).

SÓ LEITURA e SÓ EM MEMÓRIA: nada é gravado. É o "comprovante daquele
abastecimento" do Extrato On-Line — o PIX do banco com o cupom que ele pagou.

As regras são as do utils/cartao_cupom._casar_pix (Conferência de Cartões),
do mais certo para o menos:

  1. nome  — no PIX "via chave" o frentista digita o nome do pagador na
             autorização do cupom ("ROSA MARIA 1410"): a primeira palavra da
             autorização está no nome que o banco mandou, mesmo valor, mesmo dia;
  2. hora  — mesmo valor e até 10 min de diferença (quando o banco dá a hora:
             o Cora dá; o Sicoob, se mandar);
  3. dia   — sem hora: mesmo valor no mesmo dia. Um candidato só casa; mais
             de um fica como "possíveis", para a pessoa escolher.

Cupom de PIX = bandeira "Outros" no XML (é como o PDV grava o PIX), fora o
repasse do Baratão. Um cupom serve a um PIX só.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from utils.cartao_cupom import BARATAO_CNPJ, _palavras, _vendedor

JANELA_HORA = timedelta(minutes=10)
JANELA_NOME = timedelta(hours=2)


def _cupons(ini, fim):
    """Cupons de PIX autorizados no período, com os itens de combustível."""
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, numero, serie, dh_emissao, valor_total, card_autorizacao,
                   card_credenciadora, vendedor_raw, cliente_nome, placa, km
              FROM vendas_xml
             WHERE dh_emissao >= %s AND dh_emissao < %s
               AND card_bandeira = 'Outros' AND situacao = 'autorizada'
               AND COALESCE(cliente_doc, '') <> %s
             ORDER BY dh_emissao""",
            (datetime.combine(ini, datetime.min.time()),
             datetime.combine(fim + timedelta(days=1), datetime.min.time()), BARATAO_CNPJ))
        cupons = cur.fetchall()
        if cupons:
            ids = [c['id'] for c in cupons]
            itens = defaultdict(list)
            for i in range(0, len(ids), 500):
                fatia = ids[i:i + 500]
                cur.execute(f"""
                    SELECT venda_id, produto_xml, quantidade, unidade, eh_combustivel
                      FROM vendas_xml_itens WHERE venda_id IN ({','.join(['%s'] * len(fatia))})
                     ORDER BY venda_id, n_item""", tuple(fatia))
                for r in cur.fetchall():
                    itens[r['venda_id']].append(r)
            for c in cupons:
                its = itens.get(c['id'], [])
                comb = [i for i in its if i['eh_combustivel']] or its
                c['itens'] = ' + '.join(
                    f"{(i['produto_xml'] or '').strip().title()} {float(i['quantidade'] or 0):,.2f} {(i['unidade'] or '').upper()}"
                    .replace(',', 'X').replace('.', ',').replace('X', '.') for i in comb[:2])
                c['vendedor'] = _vendedor(c['vendedor_raw'])
    finally:
        cur.close()
        conn.close()
    return cupons


def _extrato_pix(banco, ini, fim):
    """Os PIX do "Extrato Pix" importado no período, com o cupom já ligado."""
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT p.id, p.dt, p.valor, p.pagador, v.vendas_xml_id
              FROM pix_extrato p
              LEFT JOIN cartao_cupom_vinculo v ON v.operadora = 'PIX' AND v.ref_id = p.id
             WHERE p.banco = %s AND p.dt >= %s AND p.dt < %s
             ORDER BY p.dt""",
            (banco, datetime.combine(ini, datetime.min.time()),
             datetime.combine(fim + timedelta(days=1), datetime.min.time())))
        return cur.fetchall()
    except Exception:
        return []                       # tabela ainda não existe
    finally:
        cur.close()
        conn.close()


def _quando(tx):
    """datetime do PIX, se o banco deu a hora; senão None."""
    if not tx.get('hora'):
        return None
    h, m = tx['hora'].split(':')
    return datetime.combine(tx['data_transacao'], datetime.min.time()).replace(hour=int(h), minute=int(m))


def _dias(tx):
    """Os dias em que o PIX pode ter entrado: tx['dias'] quando o banco lançou
    em outro dia útil (fim de semana/feriado, ver banco_api.dias_possiveis)."""
    return tx.get('dias') or [tx['data_transacao']]


def _dia_real(tx, d, fonte):
    """Vários dias possíveis e o cupom/Extrato Pix achado diz qual foi."""
    if len(_dias(tx)) > 1:
        tx['data_transacao'] = d
        tx['dia_pelo_cupom'] = fonte


def _pela_ordem(pix, out, livres, usados):
    """Os PIX vêm do banco na ordem em que entraram (o OFX do Sicoob, do mais
    novo para o mais antigo: 540 de 540 em 16-21/10/2026, contra a hora do
    Extrato Pix). Um PIX com vários cupons possíveis entrou entre os vizinhos
    que já casaram: se só um dos candidatos cai nessa janela, é ele -- "quase
    certo", não 100%. A direção sai dos próprios casados (a API pode não usar
    a do OFX); ordem confusa -> não chuta.

    Por data do banco: a lista vem ordenada por dia, e a ordem do banco só
    vale dentro do mesmo dia."""
    grupos = defaultdict(list)
    for tx in pix:
        grupos[tx.get('data_banco') or tx['data_transacao']].append(tx)

    def hora_cupom(tx):
        o = out.get(id(tx))
        return o['cupom']['dh_emissao'] if o and o['cupom'] else None

    for txs in grupos.values():
        ancoras = [h for h in map(hora_cupom, txs) if h]
        if len(ancoras) < 3:
            continue
        sobe = sum(1 for a, b in zip(ancoras, ancoras[1:]) if b > a)
        desce = sum(1 for a, b in zip(ancoras, ancoras[1:]) if b < a)
        if max(sobe, desce) < 0.9 * (sobe + desce):
            continue                    # ordem não é a do relógio
        novo_antes = desce > sobe       # do mais novo para o mais antigo
        mudou = True
        while mudou:
            mudou = False
            for i, tx in enumerate(txs):
                if out[id(tx)]['status'] != 'possiveis':
                    continue
                antes = next((h for h in map(hora_cupom, reversed(txs[:i])) if h), None)
                depois = next((h for h in map(hora_cupom, txs[i + 1:]) if h), None)
                lo, hi = (depois, antes) if novo_antes else (antes, depois)
                cs = [c for c in livres(tx)
                      if (lo is None or c['dh_emissao'] >= lo - JANELA_HORA)
                      and (hi is None or c['dh_emissao'] <= hi + JANELA_HORA)]
                if len(cs) == 1:
                    c = cs[0]
                    usados.add(c['id'])
                    _dia_real(tx, c['dh_emissao'].date(), 'cupom')
                    out[id(tx)] = {'status': 'provavel', 'metodo': 'ordem', 'cupom': c,
                                   'candidatos': [], 'minutos': None,
                                   'janela': (lo, hi)}
                    mudou = True
        # A hora que o banco não deu: a do cupom (o PIX entra minutos antes
        # da nota sair) ou, sem cupom, entre os vizinhos que têm.
        for i, tx in enumerate(txs):
            if tx.get('hora'):
                continue
            h = hora_cupom(tx)
            if h:
                tx['hora_aprox'] = h.strftime('%H:%M')
                continue
            antes = next((h for h in map(hora_cupom, reversed(txs[:i])) if h), None)
            depois = next((h for h in map(hora_cupom, txs[i + 1:]) if h), None)
            lo, hi = (depois, antes) if novo_antes else (antes, depois)
            if lo and hi and lo.date() == hi.date():
                tx['hora_entre'] = (lo.strftime('%H:%M'), hi.strftime('%H:%M'))
            elif lo or hi:
                tx['hora_entre'] = (lo.strftime('%H:%M') if lo else None,
                                    hi.strftime('%H:%M') if hi else None)


def casar(pix, ini, fim, credenciadora=None):
    """pix: transações (formato do adapter) de PIX RECEBIDO.

    status: 'casou' (100%), 'provavel' (pela ordem do banco, quase certo),
    'possiveis' (vários, a pessoa escolhe) ou 'sem'.
    Devolve ({id(tx): {'status', 'metodo', 'cupom', 'candidatos', 'minutos'}},
             cupons_sem_pix). cupons_sem_pix só faz sentido para o banco que
    liquida o PIX do cupom (credenciadora) — para os outros volta [].
    """
    ini = min([ini] + [_dias(tx)[0] for tx in pix])
    cupons = _cupons(ini, fim)
    usados, out = set(), {}

    def mesmo_valor(c, tx):
        return abs(float(c['valor_total']) - float(tx['valor'])) < 0.005

    def livres(tx):
        return [c for c in cupons if c['id'] not in usados and mesmo_valor(c, tx)
                and c['dh_emissao'].date() in _dias(tx)]

    def liga(tx, c, metodo):
        usados.add(c['id'])
        _dia_real(tx, c['dh_emissao'].date(), 'cupom')
        q = _quando(tx)
        out[id(tx)] = {'status': 'casou', 'metodo': metodo, 'cupom': c, 'candidatos': [],
                       'minutos': (round((q - c['dh_emissao']).total_seconds() / 60) if q else None)}

    def preferido(cs, tx):
        """O mais perto na hora; do mesmo banco primeiro."""
        q = _quando(tx)
        return min(cs, key=lambda c: ((credenciadora and (c['card_credenciadora'] or '') not in ('', credenciadora)),
                                      abs((c['dh_emissao'] - q).total_seconds()) if q else 0))

    # 0) o MESMO PIX no "Extrato Pix" importado (utils/pix_extrato): ele tem a
    #    hora ao segundo e o cupom já ligado pela Conferência de Cartões (TxID,
    #    nome, valor+hora — 85% dos PIX de 14 a 21/10/2026). O extrato da API
    #    não traz hora; herdá-la daqui é o que faz o resto casar direito.
    from utils.pix_extrato import CREDENCIADORA
    banco_pix = CREDENCIADORA.get(credenciadora or '')
    if banco_pix:
        por_id = {c['id']: c for c in cupons}
        extrato = _extrato_pix(banco_pix, ini, fim)
        presos = set()
        for tx in pix:
            if tx.get('hora'):
                continue
            nomes = set(_palavras(tx.get('quem')))
            cs = [p for p in extrato if p['id'] not in presos and p['dt'].date() in _dias(tx)
                  and abs(float(p['valor']) - float(tx['valor'])) < 0.005]
            pelo_nome = [p for p in cs if nomes and _palavras(p['pagador'])[:1]
                         and _palavras(p['pagador'])[0] in nomes]
            if len(pelo_nome) >= 1:
                cs = pelo_nome
            if len(cs) != 1 and not (pelo_nome and len(set(p['pagador'] for p in pelo_nome)) == 1):
                continue                # ambíguo: não chuta a hora
            p = min(cs, key=lambda p: p['dt'])
            presos.add(p['id'])
            _dia_real(tx, p['dt'].date(), 'Extrato Pix')
            tx['hora'] = p['dt'].strftime('%H:%M')
            tx['hora_fonte'] = 'Extrato Pix'
            c = por_id.get(p['vendas_xml_id'])
            if c and c['id'] not in usados:
                liga(tx, c, 'extrato')

    # 1) nome digitado na autorização
    for tx in pix:
        if id(tx) in out:
            continue
        nomes = set(_palavras(tx.get('quem')))
        q = _quando(tx)
        cs = [c for c in livres(tx)
              if _palavras(c['card_autorizacao'])[:1] and _palavras(c['card_autorizacao'])[0] in nomes
              and (q is None or abs(c['dh_emissao'] - q) <= JANELA_NOME)]
        if cs:
            liga(tx, preferido(cs, tx), 'nome')
    # 2) valor + hora
    for tx in pix:
        q = _quando(tx)
        if id(tx) in out or q is None:
            continue
        cs = [c for c in livres(tx) if abs(c['dh_emissao'] - q) <= JANELA_HORA]
        if cs:
            liga(tx, preferido(cs, tx), 'hora')
    # 3) valor + dia: só um candidato casa; vários ficam para escolher
    for tx in pix:
        if id(tx) in out:
            continue
        cs = livres(tx)
        if _quando(tx) is None and len(cs) == 1:
            liga(tx, cs[0], 'dia')
        else:
            out[id(tx)] = {'status': 'possiveis' if cs else 'sem', 'metodo': None, 'cupom': None,
                           'candidatos': cs[:3], 'minutos': None}

    # 4) ordem do banco: o PIX sem hora fica entre os vizinhos que já casaram.
    _pela_ordem(pix, out, livres, usados)

    em_aberto = set()                   # cupons que são candidatos de algum PIX
    for tx in pix:
        if out[id(tx)]['status'] == 'possiveis':
            em_aberto.update(c['id'] for c in livres(tx))

    # "Cupom PIX sem PIX" é só o que nenhum PIX do período pode ter pago — o
    # cupom que é candidato de um PIX com vários possíveis não entra.
    sem_pix = []
    if credenciadora:
        sem_pix = [c for c in cupons if c['id'] not in usados and c['id'] not in em_aberto
                   and (c['card_credenciadora'] or '') == credenciadora]
    return out, sem_pix
