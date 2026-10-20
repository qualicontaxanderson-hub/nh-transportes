"""
utils/dashboard_cards.py
========================

Os dados dos nove cards do carrossel da inicial (templates/dashboard.html):
Vendas, Acrescimo a prazo, Cartoes x operadora, Estoque, Ao vivo,
Recebimento, Descargas, Compras e Perdas. SOMENTE LEITURA.

Cada bloco tem o seu try/except e devolve vazio quando falha: a inicial
nunca cai por causa de um card. O resultado vai para o template como JSON e
o JavaScript desenha os cards -- o mesmo desenho da previa aprovada em
19/10/2026 (preview-dashboard-novo.html).

O card Cartoes x operadora e o unico pesado (le os arquivos das operadoras
pelo motor do Conf. Cartoes), entao fica num endpoint proprio com cache de
15 minutos: /api/dashboard/cartoes.
"""
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from utils.db import get_db_connection
from utils.fuso import hoje_brasilia, janelas_dia_mes
from utils.pagamentos import classificar_recebimento
from routes.vendas import _grupo_forma

# Os quatro combustiveis conciliaveis (mesma tabela de routes/estoque.py).
PROD = {2: ('Gasolina', '#BA7517'), 1: ('Etanol', '#639922'),
        4: ('S-500', '#185FA5'), 5: ('S-10', '#534AB7')}
PROD_IDS = (1, 2, 4, 5)
CLIENTE_POSTO = 1          # Posto NH: o unico com leitura de tanque e descarga


def _f(v):
    return float(v or 0)


def _iso(d):
    return d.isoformat() if d else None


def coletar(hoje, onda1):
    """O JSON dos cards (menos Cartoes x operadora, que e async)."""
    ini_dia, fim_dia, ini_mes, fim_mes = janelas_dia_mes(hoje)
    out = {'hoje': hoje.isoformat(), 'onda1': {'dia': onda1.get('dia'), 'mes': onda1.get('mes')},
           'receb': onda1.get('recebimento') or [], 'receb_total': onda1.get('recebimento_total') or 0.0,
           'formas': {}, 'prazo': {'dia': [], 'mes': []}, 'band': {'dia': {}, 'mes': {}},
           'estoque': [], 'descargas': {'ultimas': [], 'tot': {}}, 'compras': {'ultimas': [], 'tot': {}},
           'perdas': {}}
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        for nome, fn in (('formas', _formas), ('prazo', _prazo), ('band', _band),
                         ('estoque', _estoque), ('descargas', _descargas),
                         ('compras', _compras), ('perdas', _perdas)):
            try:
                out[nome] = fn(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes)
            except Exception:
                from flask import current_app
                current_app.logger.exception('[dashboard] card %s falhou', nome)
    except Exception:
        pass
    finally:
        for c in (cur, conn):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
    return out


# ---------------------------------------------------------------- vendas
def _formas(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    """Acrescimo e desconto por forma de pagamento, dia e mes."""
    cur.execute(
        "SELECT forma_pagamento f, DATE(dh_emissao) d, COUNT(*) n, "
        "SUM(vlr_acrescimo>0.004) na, SUM(vlr_acrescimo) a, "
        "SUM(vlr_desconto>0.004) nd, SUM(vlr_desconto) ds, SUM(valor_total) v "
        "FROM vendas_xml WHERE situacao<>'cancelada' AND dh_emissao>=%s AND dh_emissao<%s "
        "GROUP BY 1,2", (ini_mes, fim_mes))
    vz = lambda: {k: dict(n=0, na=0, a=0.0, nd=0, ds=0.0, v=0.0)
                  for k in ('credito', 'prazo', 'debito', 'misto', 'outros')}
    F = {'dia': vz(), 'mes': vz()}
    for r in cur.fetchall():
        k = _grupo_forma(r['f'])
        for per in (('mes', 'dia') if r['d'] == hoje else ('mes',)):
            x = F[per][k]
            x['n'] += int(r['n']); x['na'] += int(r['na'] or 0); x['a'] += _f(r['a'])
            x['nd'] += int(r['nd'] or 0); x['ds'] += _f(r['ds']); x['v'] += _f(r['v'])
    return F


def _prazo(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    """Clientes a prazo com o acrescimo que pagaram (e os que nao pagaram)."""
    def lista(ini, fim):
        cur.execute(
            "SELECT COALESCE(NULLIF(cliente_nome,''),cliente_doc) cli, COUNT(*) n, "
            "SUM(vlr_acrescimo) a, SUM(valor_total) v, SUM(vlr_acrescimo>0.004) na "
            "FROM vendas_xml WHERE situacao<>'cancelada' AND dh_emissao>=%s AND dh_emissao<%s "
            "AND forma_pagamento LIKE 'Cr%%dito Loja%%' GROUP BY 1 ORDER BY a DESC", (ini, fim))
        return [dict(cli=r['cli'] or '—', n=int(r['n']), na=int(r['na'] or 0), a=_f(r['a']), v=_f(r['v']))
                for r in cur.fetchall()]
    return {'dia': lista(ini_dia, fim_dia), 'mes': lista(ini_mes, fim_mes)}


def _band(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    """Acrescimo do cartao por bandeira do cupom (credito / debito)."""
    def por(ini, fim):
        cur.execute(
            "SELECT forma_pagamento f, COALESCE(card_bandeira,'(sem)') b, COUNT(*) n, "
            "SUM(vlr_acrescimo) a, SUM(valor_total) v FROM vendas_xml "
            "WHERE situacao<>'cancelada' AND dh_emissao>=%s AND dh_emissao<%s "
            "AND forma_pagamento IN ('Cartao Credito','Cartao Debito','Cartão Crédito','Cartão Débito') "
            "GROUP BY 1,2", (ini, fim))
        o = {'credito': {}, 'debito': {}}
        for r in cur.fetchall():
            k = _grupo_forma(r['f'])
            if k in o:
                o[k][r['b']] = dict(n=int(r['n']), a=_f(r['a']), v=_f(r['v']))
        return o
    return {'dia': por(ini_dia, fim_dia), 'mes': por(ini_mes, fim_mes)}


# --------------------------------------------------------------- estoque
def _estoque(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    """Saldo agora (routes/estoque.dados_tempo_real) + capacidade e venda media."""
    from routes.estoque import dados_tempo_real
    tr = dados_tempo_real(cur, cliente_id=CLIENTE_POSTO)
    cur.execute(
        "SELECT produto_id pid, SUM(capacidade) cap FROM leitura_tanque_diaria "
        "WHERE cliente_id=%s AND UPPER(TRIM(titulo))='ABERTURA' AND DATE(data_leitura) = "
        " (SELECT MAX(DATE(data_leitura)) FROM leitura_tanque_diaria "
        "   WHERE cliente_id=%s AND UPPER(TRIM(titulo))='ABERTURA') "
        "GROUP BY produto_id", (CLIENTE_POSTO, CLIENTE_POSTO))
    cap = {r['pid']: _f(r['cap']) for r in cur.fetchall()}
    cur.execute(
        "SELECT i.produto_id pid, SUM(i.quantidade)/COUNT(DISTINCT DATE(v.dh_emissao)) med "
        "FROM vendas_xml_itens i JOIN vendas_xml v ON v.id=i.venda_id "
        "WHERE v.situacao<>'cancelada' AND v.dh_emissao>=%s AND v.dh_emissao<%s AND i.unidade='L' "
        "GROUP BY 1", (ini_mes, fim_mes))
    med = {r['pid']: _f(r['med']) for r in cur.fetchall()}
    for t in tr:
        t['cap'] = cap.get(t['pid'], 0.0)
        t['med_dia'] = med.get(t['pid'], 0.0)
    return tr


# ------------------------------------------------------------- descargas
def _descargas(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    ini_m = hoje.replace(day=1)
    cur.execute(
        "SELECT d.id, d.produto_id pid, d.total_descarga l, d.data_inicial di, d.data_final df, "
        "COALESCE(d.data_descarga, DATE(d.data_final), DATE(d.data_inicial)) dia, "
        "d.tanque, d.volume_inicial vi, d.volume_final vf, d.status, d.origem, "
        "doc.numero nf, doc.emit_nome forn, doc.transp_placa placa, dn.litros l_nota "
        "FROM descargas_pendentes d "
        "LEFT JOIN descarga_nota dn ON dn.descarga_id = d.id "
        "LEFT JOIN dfe_documentos doc ON doc.id = dn.documento_id "
        "WHERE d.cliente_id = %s AND d.produto_id IN (1,2,4,5) "
        "ORDER BY COALESCE(d.data_descarga, DATE(d.data_final), DATE(d.data_inicial)) DESC, "
        "d.data_inicial DESC, d.id DESC LIMIT 10", (CLIENTE_POSTO,))
    ultimas = []
    for r in cur.fetchall():
        nome, cor = PROD[r['pid']]
        ultimas.append(dict(
            id=r['id'], pid=r['pid'], produto=nome, cor=cor, litros=_f(r['l']), dia=_iso(r['dia']),
            hi=r['di'].strftime('%H:%M') if r['di'] else '', hf=r['df'].strftime('%H:%M') if r['df'] else '',
            tanque=r['tanque'], vi=_f(r['vi']), vf=_f(r['vf']), status=r['status'], origem=r['origem'],
            nf=r['nf'], forn=r['forn'], placa=r['placa'], l_nota=_f(r['l_nota']) if r['l_nota'] else None))
    cur.execute(
        "SELECT COALESCE(d.data_descarga, DATE(d.data_final), DATE(d.data_inicial)) dia, d.produto_id pid, "
        "COUNT(*) n, SUM(d.total_descarga) l FROM descargas_pendentes d "
        "WHERE d.cliente_id = %s AND d.produto_id IN (1,2,4,5) "
        "AND COALESCE(d.data_descarga, DATE(d.data_final), DATE(d.data_inicial)) >= %s GROUP BY 1,2",
        (CLIENTE_POSTO, ini_m))
    tot = {'dia': {'n': 0, 'l': 0.0, 'prod': {}}, 'mes': {'n': 0, 'l': 0.0, 'prod': {}}}
    for r in cur.fetchall():
        for per in (('mes', 'dia') if r['dia'] == hoje else ('mes',)):
            t = tot[per]; t['n'] += int(r['n']); t['l'] += _f(r['l'])
            nome = PROD[r['pid']][0]
            t['prod'][nome] = t['prod'].get(nome, 0.0) + _f(r['l'])
    return {'ultimas': ultimas, 'tot': tot}


# --------------------------------------------------------------- compras
_SQL_COMPRA_BASE = (
    "FROM dfe_documentos d JOIN dfe_itens i ON i.documento_id = d.id "
    "WHERE d.cliente_id = %s AND d.tipo = 'NFe' AND d.situacao = 'autorizado' "
    "AND (i.categoria IS NULL OR i.categoria <> 'ignorar') AND i.unidade = 'L' "
    "AND COALESCE(i.classificado_produto_id, i.produto_id) IN (1,2,4,5) ")


def _compras(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    ini_m = hoje.replace(day=1)
    cur.execute(
        "SELECT d.id, d.numero, d.dh_emissao, d.emit_nome forn, d.transp_placa placa, d.valor_total vnf, "
        "COALESCE(i.classificado_produto_id, i.produto_id) pid, i.quantidade l, i.valor_unitario pu, "
        "i.valor_total vt " + _SQL_COMPRA_BASE +
        "ORDER BY d.dh_emissao DESC, d.id DESC, i.n_item LIMIT 10", (CLIENTE_POSTO,))
    ultimas = []
    for r in cur.fetchall():
        nome, cor = PROD[r['pid']]
        ultimas.append(dict(nf=r['numero'], dh=_iso(r['dh_emissao']), forn=r['forn'] or '', placa=r['placa'],
                            pid=r['pid'], produto=nome, cor=cor, litros=_f(r['l']), pu=_f(r['pu']),
                            vt=_f(r['vt']), vnf=_f(r['vnf'])))
    cur.execute(
        "SELECT DATE(d.dh_emissao) dia, COALESCE(i.classificado_produto_id, i.produto_id) pid, "
        "COUNT(DISTINCT d.id) n, SUM(i.quantidade) l, SUM(i.valor_total) v " + _SQL_COMPRA_BASE +
        "AND d.dh_emissao >= %s GROUP BY 1,2", (CLIENTE_POSTO, ini_m))
    tot = {'dia': {'n': 0, 'l': 0.0, 'v': 0.0, 'prod': {}}, 'mes': {'n': 0, 'l': 0.0, 'v': 0.0, 'prod': {}}}
    for r in cur.fetchall():
        for per in (('mes', 'dia') if r['dia'] == hoje else ('mes',)):
            t = tot[per]; t['n'] += int(r['n']); t['l'] += _f(r['l']); t['v'] += _f(r['v'])
            p = t['prod'].setdefault(PROD[r['pid']][0], {'l': 0.0, 'v': 0.0})
            p['l'] += _f(r['l']); p['v'] += _f(r['v'])
    return {'ultimas': ultimas, 'tot': tot}


# ---------------------------------------------------------------- perdas
def _perdas(cur, hoje, ini_dia, fim_dia, ini_mes, fim_mes):
    """A conciliacao da aba Estoque, resumida: final - (inicial + descarga - venda).

    Um dia esta "fechado" quando tem leitura de abertura nele e no seguinte.
    Dia = o ultimo fechado; mes = todos os fechados do mes. A perda em reais
    usa o custo medio de compra do mes de cada produto.
    """
    ini_m = hoje.replace(day=1)
    cur.execute(
        "SELECT DATE(data_leitura) dia, produto_id pid, SUM(volume_atual) l FROM leitura_tanque_diaria "
        "WHERE cliente_id = %s AND UPPER(TRIM(titulo)) = 'ABERTURA' AND produto_id IN (1,2,4,5) "
        "AND DATE(data_leitura) >= %s GROUP BY 1,2", (CLIENTE_POSTO, ini_m))
    leit = {(r['dia'], r['pid']): _f(r['l']) for r in cur.fetchall()}
    cur.execute(
        "SELECT DATE(v.dh_emissao) dia, i.produto_id pid, SUM(i.quantidade) l "
        "FROM vendas_xml_itens i JOIN vendas_xml v ON v.id = i.venda_id "
        "JOIN clientes cl ON REPLACE(REPLACE(REPLACE(REPLACE(cl.cnpj,'.',''),'/',''),'-',''),' ','') = v.cnpj_emitente "
        "WHERE cl.id = %s AND i.produto_id IN (1,2,4,5) AND i.unidade = 'L' AND v.situacao <> 'cancelada' "
        "AND v.dh_emissao >= %s GROUP BY 1,2", (CLIENTE_POSTO, ini_m))
    ven = {(r['dia'], r['pid']): _f(r['l']) for r in cur.fetchall()}
    cur.execute(
        "SELECT COALESCE(d.data_descarga, DATE(d.data_final), DATE(d.data_inicial)) dia, d.produto_id pid, "
        "SUM(d.total_descarga) l FROM descargas_pendentes d WHERE d.cliente_id = %s AND d.produto_id IN (1,2,4,5) "
        "AND COALESCE(d.data_descarga, DATE(d.data_final), DATE(d.data_inicial)) >= %s GROUP BY 1,2",
        (CLIENTE_POSTO, ini_m))
    rec = {(r['dia'], r['pid']): _f(r['l']) for r in cur.fetchall()}
    cur.execute(
        "SELECT COALESCE(i.classificado_produto_id, i.produto_id) pid, SUM(i.quantidade) l, SUM(i.valor_total) v "
        + _SQL_COMPRA_BASE + "AND d.dh_emissao >= %s GROUP BY 1", (CLIENTE_POSTO, ini_m))
    custo = {}
    for r in cur.fetchall():
        custo[PROD[r['pid']][0]] = (_f(r['v']) / _f(r['l'])) if _f(r['l']) else 0.0

    dias_fech, d = [], ini_m
    while d < hoje:
        if any((d, p) in leit for p in PROD) and any((d + timedelta(days=1), p) in leit for p in PROD):
            dias_fech.append(d)
        d += timedelta(days=1)

    def conc(dias):
        out = {}
        for pid, (nome, cor) in PROD.items():
            x = {'nome': nome, 'cor': cor, 'perda': 0.0, 'ven': 0.0, 'rec': 0.0, 'dias': 0}
            for dd in dias:
                a, f = leit.get((dd, pid)), leit.get((dd + timedelta(days=1), pid))
                if a is None or f is None:
                    continue
                v, r = ven.get((dd, pid), 0.0), rec.get((dd, pid), 0.0)
                x['perda'] += f - (a + r - v); x['ven'] += v; x['rec'] += r; x['dias'] += 1
            x['rs'] = x['perda'] * custo.get(nome, 0.0)
            out[nome] = x
        return out

    ult = dias_fech[-1] if dias_fech else None
    serie = []
    for dd in dias_fech:
        c = conc([dd])
        serie.append({'d': dd.isoformat(), **{n: round(c[n]['perda'], 1) for n in c}})
    return {'ultimo_dia': _iso(ult), 'n_dias': len(dias_fech),
            'dia': conc([ult]) if ult else {}, 'mes': conc(dias_fech), 'custo': custo, 'serie': serie}


# ------------------------------------------------------------- ao vivo
def ultimas_vendas(cur, n=20):
    """As ultimas N vendas (nao canceladas), com o item principal e a classe
    de recebimento. E o que o card Ao vivo desenha, um quadradinho por venda."""
    cur.execute(
        "SELECT v.id, v.dh_emissao, v.numero, v.serie, v.forma_pagamento, v.card_bandeira, "
        "v.card_credenciadora, v.card_autorizacao, v.tef_terminal, v.cliente_doc, v.cliente_nome, "
        "COALESCE(NULLIF(TRIM(v.vendedor_raw),''),'—') vendedor, v.valor_total, v.vlr_acrescimo "
        "FROM vendas_xml v WHERE v.situacao<>'cancelada' "
        "ORDER BY v.dh_emissao DESC, v.id DESC LIMIT %s", (int(n),))
    notas = cur.fetchall()
    if not notas:
        return []
    ids = [x['id'] for x in notas]
    cur.execute(
        "SELECT i.venda_id, i.produto_xml, i.quantidade, i.unidade, i.valor_total, p.nome pn "
        "FROM vendas_xml_itens i LEFT JOIN produto p ON p.id=i.produto_id "
        "WHERE i.venda_id IN (%s) ORDER BY i.venda_id, i.valor_total DESC" % ",".join(['%s'] * len(ids)), ids)
    itens = defaultdict(list)
    for it in cur.fetchall():
        itens[it['venda_id']].append(it)
    saida = []
    for x in notas:
        its = itens.get(x['id'], [])
        it = its[0] if its else {}
        saida.append(dict(
            id=x['id'], hora=x['dh_emissao'].strftime('%H:%M') if x['dh_emissao'] else '',
            dia=x['dh_emissao'].strftime('%d/%m') if x['dh_emissao'] else '',
            numero=x['numero'], serie=x['serie'],
            produto=it.get('pn') or it.get('produto_xml') or '—', litros=_f(it.get('quantidade')),
            unidade=it.get('unidade') or '', extra=max(0, len(its) - 1),
            valor=_f(x['valor_total']), acr=_f(x['vlr_acrescimo']), vendedor=x['vendedor'],
            cliente=x['cliente_nome'] or '',
            classe=classificar_recebimento(x['forma_pagamento'], x['card_bandeira'], x['card_credenciadora'],
                                           x['card_autorizacao'], x['tef_terminal'], x['cliente_doc'])))
    return saida


# ------------------------------------------------ cartoes x operadora
_CACHE = {'quando': 0.0, 'chave': None, 'dados': None}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 15 * 60


def cartoes_operadora(hoje=None):
    """Os numeros do Conf. Cartoes (aba Operadora) do mes corrente, por tipo
    e por bandeira: vendido, taxa retida, % e o que ainda nao caiu. Cache de
    15 min: o motor le os arquivos de todas as operadoras."""
    hoje = hoje or hoje_brasilia()
    ini = hoje.replace(day=1).isoformat()
    fim = hoje.isoformat()
    chave = (ini, fim)
    with _CACHE_LOCK:
        if _CACHE['dados'] is not None and _CACHE['chave'] == chave \
                and time.time() - _CACHE['quando'] < _CACHE_TTL:
            return _CACHE['dados']
    from routes.conf_cartoes import _get_bandeiras
    from utils import cartao_arquivo
    conn = get_db_connection()
    try:
        bandeiras = _get_bandeiras(conn)
        vinculos = defaultdict(list)
        for b in bandeiras:
            for v in b.get('vinculos', []):
                vinculos[b['id']].append(v['forma_recebimento_id'])
        bandeiras, desde, _ciclos = cartao_arquivo.ciclos_operadora(conn, bandeiras, vinculos, ini, fim)
        vinculos = defaultdict(list, {b['id']: vinculos.get(b['id'], []) for b in bandeiras})
        ops = cartao_arquivo.pagamentos_operadora(conn, bandeiras, vinculos, desde, ini, fim)
    finally:
        conn.close()

    saida = {}
    for tipo in ('credito', 'debito'):
        saida[tipo] = {'vendido': 0.0, 'recebido': 0.0, 'taxa': 0.0, 'pct': None, 'nao_caiu': 0.0, 'band': {}}
    for b in bandeiras:
        op = ops.get(b['id'])
        if not op:
            continue
        tipo = 'debito' if (b.get('tipo') or '').upper() == 'DEBITO' else 'credito'
        s = saida[tipo]
        vendido, taxa = _f(op['vendido']), _f(op['taxa'])
        nao_caiu = round(vendido - _f(op['vendido_pago']), 2)
        s['vendido'] += vendido; s['recebido'] += _f(op['liquido']); s['taxa'] += taxa; s['nao_caiu'] += nao_caiu
        nome = (b.get('nome') or '').strip().upper()
        chave_b = {'MASTERCARD': 'Mastercard', 'VISA': 'Visa', 'ELO': 'Elo'}.get(nome.split(' ')[0], 'Outras')
        bd = s['band'].setdefault(chave_b, {'vendido': 0.0, 'taxa': 0.0, 'pago': 0.0, 'nomes': []})
        bd['vendido'] += vendido; bd['taxa'] += taxa; bd['pago'] += _f(op['vendido_pago'])
        bd['nomes'].append(b.get('nome'))
    for s in saida.values():
        pago = s['vendido'] - s['nao_caiu']
        s['pct'] = (s['taxa'] / pago * 100) if pago else None
        for bd in s['band'].values():
            bd['pct'] = (bd['taxa'] / bd['pago'] * 100) if bd['pago'] else None
    dados = {'ini': ini, 'fim': fim, 'tipos': saida}
    with _CACHE_LOCK:
        _CACHE.update(quando=time.time(), chave=chave, dados=dados)
    return dados
