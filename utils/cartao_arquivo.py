# -*- coding: utf-8 -*-
"""Arquivo da operadora de cartao: a venda contada por quem cobrou.

Hoje a Conferencia de Cartoes parte do caixa, e o caixa e digitado a mao --
um VISA de 120,00 lancado como 102,00 vira "taxa" no Relatorio de Despesas.
O arquivo da operadora traz cada venda, a taxa e o dia em que o dinheiro
caiu. Ele monta uma conferencia PARALELA: arquivo x extrato (a operadora
pagou o que disse que pagaria?) e arquivo x caixa (o lancamento bateu?).
As entradas sao as mesmas do extrato -- as formas ja vinculadas a bandeira.

Caminho: o Miguel salva o "X7....xls" na pasta que o NH-Robo vigia; o robo
manda para /BANCOS/OFX/NOVO no Dropbox (a mesma dos OFX -- o importador de
extrato so le .ofx e nao enxerga este); o agendador abaixo le, grava e move
para /BANCOS/OFX/IMPORTADOS. Sem botao de proposito.

Hoje: X7 BANK (nome "X7..."), Baratao (nome "Baratao...") e SIPAG (os dois
relatorios com o nome que o portal da: "vendas_realizadas_relatorio_detalhado_"
e "relatorio_vendas_recebidas_detalhadas_" -- ver a secao SIPAG no fim).

O "xls" da X7 e HTML com cara de planilha: um bloco por dia de previsao
(o lote: bruto, descontos, taxas, liquido) e as vendas do lote logo abaixo,
cada uma com a Dt. Liquidacao -- o dia em que o lote caiu no banco. Em
17/10/2026, 36 de 37 dias de liquidacao bateram no centavo com o extrato.

O do Baratao e CSV (;) com um abastecimento por linha -- cupom, frentista,
produto, litros, rebate, taxa, repasse --, e SEM data de pagamento. O
Baratao paga um PIX por dia de abastecimento, a soma do repasse do dia, uns
2 dias uteis depois (204 de 230 dias casam no centavo; o resto difere por
centavos de arredondamento). A conferencia acha o PIX de cada dia.
"""
import hashlib
import csv
import html as _html
import io
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import combinations

from utils.db import get_db_connection

_log = logging.getLogger(__name__)

#: Prefixo do nome do arquivo -> operadora. O nome e a unica coisa que o
#: Miguel controla, entao e por ele que se decide quem le o arquivo.
OPERADORAS = {
    # "Gestao_X7Bank.xlsx" e o nome que o portal da X7 da a lista de pagamentos
    'X7': {'nome': 'X7 BANK', 'bandeira_like': 'X7%', 'tipo': 'CREDITO',
           'extensoes': ('.xls', '.xlsx', '.html', '.htm'),
           'prefixos': ('X7', 'GESTAO_X7BANK', 'GESTAO X7BANK')},
    # A taxa do Baratao mora aqui, e nao na bandeira: preencher a bandeira
    # mudaria tambem a conferencia pelo caixa. Os 2% comecaram em fev/2026 --
    # a conferencia so cobra a taxa a partir do primeiro cupom que a teve.
    'BARATAO': {'nome': 'BARATÃO', 'bandeira_like': 'BARAT%', 'tipo': 'CREDITO',
                'extensoes': ('.csv',), 'taxa': 2.0,
                # O cupom do caixa sai pelo preco da BOMBA e o Baratao paga pelo
                # do app: o caixa fica de 0% a ~9% acima, todo dia (jan-out/2026:
                # 200 de 229 dias). Fora desta faixa e venda faltando, sobrando
                # ou lancada em outro dia.
                'cupom_acima': (-0.5, 10.0)},
    # A SIPAG atende varias bandeiras do cadastro; o nome do arquivo e o que o
    # portal gera, e os dois relatorios sao lidos (um audita o outro).
    'SIPAG': {'nome': 'SIPAG', 'extensoes': ('.csv',),
              'prefixos': ('VENDAS_REALIZADAS', 'RELATORIO_VENDAS_RECEBIDAS'),
              'bandeiras': ('VISA', 'MASTERCARD', 'ELO', 'AMEX', 'CABAL')},
    # O extrato PIX do banco (utils/pix_extrato) vem pelo mesmo caminho, mas
    # nao e operadora de cartao: nao tem bandeira nem entra na Conferencia.
    'PIX': {'nome': 'PIX', 'extensoes': ('.xlsx',), 'so_arquivo': True},
    # O Sicredi (maquininha ate 13/07/2026) atende as MESMAS bandeiras da
    # SIPAG: entra dentro delas, antes do dia em que a SIPAG assumiu. O nome
    # do arquivo e livre ("Cartao Abril a junho - Sicredi.xlsx"): basta ter
    # Sicredi no nome. Vem depois do PIX: "PIX ... Sicredi" e extrato PIX.
    'SICREDI': {'nome': 'SICREDI', 'extensoes': ('.xlsx',), 'contem': 'SICREDI',
                'dentro_de': 'SIPAG'},
}

EXTENSOES = tuple(sorted({e for o in OPERADORAS.values() for e in o['extensoes']}))

_TOL = 0.02


# ── leitura ───────────────────────────────────────────────────────────────────

def _sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '')
                   if not unicodedata.combining(c))


def operadora_do_nome(nome):
    """'X7 17-10.xls' -> 'X7'; 'Baratão 17-10.csv' -> 'BARATAO'."""
    n = _sem_acento(nome).strip().upper()
    for prefixo, o in OPERADORAS.items():
        nome_ok = (o['contem'] in n) if 'contem' in o else n.startswith(o.get('prefixos', (prefixo,)))
        if nome_ok and n.lower().endswith(o['extensoes']):
            return prefixo
    return None


def _txt(cel):
    s = _html.unescape(re.sub(r'<[^>]+>', '', cel)).strip()
    # O relatorio da X7 traz parte do texto em UTF-8 lido como Latin-1
    # ("CARTÃ\x83O FROTA"). Desfaz quando da; quando nao da, fica como veio.
    if 'Ã' in s or 'Â' in s:
        try:
            s = s.encode('latin-1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return s


def _num(s):
    s = (s or '').replace('R$', '').strip()
    if s in ('', '-'):
        return 0.0
    return float(s.replace('.', '').replace(',', '.'))


def _data(s):
    s = (s or '').strip()
    if not s or s == '-':
        return None
    return datetime.strptime(s[:10], '%d/%m/%Y').date()


def _decodificar(conteudo):
    if isinstance(conteudo, str):
        return conteudo
    if conteudo[:2] == b'PK':
        raise ValueError('arquivo .xlsx de verdade (zip): o leitor da X7 '
                         'espera o "xls" que o portal exporta (HTML)')
    try:
        return conteudo.decode('utf-8')
    except UnicodeDecodeError:
        return conteudo.decode('latin-1')


def ler_x7(conteudo):
    """(lotes, vendas) do "Relatorio Recebiveis Sinteticos" da X7.

    A leitura e pelo CABECALHO de cada bloco, nao pela posicao: a linha que
    vem depois de "DT. Previsao" e lote, a que vem depois de "Cod.Transacao"
    e venda. Linha de uma celula so e o estabelecimento.
    """
    if isinstance(conteudo, bytes) and conteudo[:2] == b'PK':
        return _ler_x7_xlsx(conteudo)
    texto = _decodificar(conteudo)
    linhas = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', texto, re.S | re.I):
        linhas.append([_txt(c) for c in
                       re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S | re.I)])

    lotes, vendas = [], []
    estab, modo, lote = '', None, None
    for cs in linhas:
        cs_ = [c for c in cs if c]
        if not cs_:
            continue
        primeiro = cs[0].lower()
        if primeiro.startswith('dt. previs'):
            modo = 'lote'
            continue
        if primeiro.startswith('cod.transa'):
            modo = 'venda'
            continue
        if len(cs) == 1:
            if not cs[0].lower().startswith('relat'):
                estab = cs[0]
            modo = None
            continue
        if modo == 'lote' and len(cs) >= 10 and _data(cs[0]):
            lote = {
                'estabelecimento': estab, 'dt_previsao': _data(cs[0]),
                'qtd': int(_num(cs[1])), 'bruto': _num(cs[2]),
                'descontos': _num(cs[3]), 'taxas': _num(cs[5]),
                'liquido': _num(cs[8]), 'status': cs[9],
                'dt_liquidacao': None, 'cods': [], 'vendas': [],
            }
            lotes.append(lote)
        elif modo == 'venda' and len(cs) >= 12 and cs[0].strip().isdigit():
            op = cs[2].strip()
            v = {
                'estabelecimento': estab,
                'dt_previsao': lote['dt_previsao'] if lote else None,
                'cod_transacao': cs[0].strip(), 'nfe': cs[1].strip(),
                'dt_operacao': datetime.strptime(op[:16], '%d/%m/%Y %H:%M')
                               if len(op) >= 16 else datetime.strptime(op[:10], '%d/%m/%Y'),
                'dt_liquidacao': _data(cs[3]), 'cliente': cs[4],
                'bruto': _num(cs[5]), 'desconto': _num(cs[6]),
                'taxa_pct': _num(cs[7]), 'liquido_est': _num(cs[8]),
                'forma_pagamento': cs[9], 'parcela': cs[10].strip(),
                'status': cs[11],
            }
            vendas.append(v)
            if lote:
                lote['cods'].append(v['cod_transacao'] + '/' + v['parcela'])
                lote['vendas'].append(v)
            # O lote cai no banco no dia da liquidacao das vendas dele. Se
            # vierem datas diferentes no mesmo lote, vale a mais tardia --
            # e so nela que o lote inteiro ja caiu.
            if lote and v['dt_liquidacao']:
                if not lote['dt_liquidacao'] or v['dt_liquidacao'] > lote['dt_liquidacao']:
                    lote['dt_liquidacao'] = v['dt_liquidacao']
    # O lote nao tem numero, e o mesmo dia de previsao pode ter varios (em
    # 06/07/2026 foram quatro, pagos em tres dias diferentes). Quem o
    # identifica sao as vendas dele -- cada venda esta em um lote so.
    for l in lotes:
        base = '|'.join(sorted(l.pop('cods'))) or ('%s|%s' % (l['dt_previsao'], l['bruto']))
        l['chave'] = hashlib.sha1(base.encode('utf-8')).hexdigest()
        # O "Descontos" do lote e o abatimento dado ao cliente do Cartao
        # Frota (~4,3%): o caixa lanca o que o cliente pagou, bruto MENOS
        # desconto (03/08: 81,02 - 3,55 = 77,47 no caixa). Ele so vem no
        # lote; com mais de uma venda, reparte pelo bruto, e o centavo que
        # sobra do arredondamento vai na ultima.
        vs = l.pop('vendas')
        tot = sum(v['bruto'] for v in vs)
        resto = round(l['descontos'], 2)
        for i, v in enumerate(vs):
            parte = resto if i == len(vs) - 1 else (
                round(l['descontos'] * v['bruto'] / tot, 2) if tot else 0.0)
            v['desconto_lote'] = parte
            resto = round(resto - parte, 2)
    if not lotes:
        raise ValueError('nenhum lote encontrado: nao parece o relatorio '
                         '"Recebiveis Sinteticos" da X7')
    return lotes, vendas


def _ler_x7_xlsx(conteudo):
    """(lotes, []) da LISTA DE PAGAMENTOS que o portal da X7 exporta em .xlsx
    desde 19/10/2026 ("Gestao_X7Bank.xlsx": Posto, DT. Previsao/Pag, Qtd.,
    Valor Bruto, Descontos, Cashback, Taxas, ..., Valor Liquido, Status).

    Ela nao traz as vendas, entao o lote nao tem as vendas para se identificar:
    quem o acha de novo e gravar(), pelos valores (lote['por_valor']). A data
    e a da previsao enquanto "A Pagar" e a do pagamento depois de "Pago" --
    o mesmo lote muda de dia (21/10 A Pagar -> 22/10 Pago).

    O .xlsx de UMA venda (Cod.Transacao, Nfe, ...) nao diz quando foi paga:
    e recusado com o motivo, para nao entrar venda sem pagamento."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    try:
        linhas = [list(r) for r in wb.active.iter_rows(values_only=True)]
    finally:
        wb.close()

    def txt(c):
        return _sem_acento(str(c)).strip().lower() if c is not None else ''

    def valor(c):
        if c is None or c == '':
            return 0.0
        if isinstance(c, (int, float)):
            return float(c)
        return _num(str(c))

    cab = None
    for i, r in enumerate(linhas):
        t = [txt(c) for c in r]
        if t and t[0].startswith('cod.transa'):
            raise ValueError('arquivo de UMA venda da X7 (sem a data do pagamento): baixe a '
                             'lista de pagamentos do portal (Posto / DT. Previsao/Pag)')
        if t and t[0] == 'posto' and len(t) > 1 and t[1].startswith('dt. previs'):
            cab = (i, t)
            break
    if not cab:
        raise ValueError('nao parece a lista de pagamentos da X7 (falta o cabecalho '
                         '"Posto / DT. Previsao/Pag")')
    i0, t = cab
    col = {nome: t.index(nome) for nome in ('qtd.', 'valor bruto', 'descontos',
                                            'valor liquido', 'status') if nome in t}
    if len(col) < 5:
        raise ValueError('lista de pagamentos da X7 sem as colunas esperadas: %s' % t)
    lotes = []
    for r in linhas[i0 + 1:]:
        if not r or r[0] is None or txt(r[0]) == 'totais':
            continue
        try:
            d = _data(str(r[1])) if not isinstance(r[1], (date, datetime)) else (
                r[1].date() if isinstance(r[1], datetime) else r[1])
        except ValueError:
            continue
        if not d:
            continue
        bruto = round(valor(r[col['valor bruto']]), 2)
        desc = round(valor(r[col['descontos']]), 2)
        liq = round(valor(r[col['valor liquido']]), 2)
        status = str(r[col['status']] or '').strip()
        lotes.append({
            'estabelecimento': str(r[0]).strip(), 'dt_previsao': d,
            'dt_liquidacao': d if txt(status).startswith('pago') else None,
            'qtd': int(valor(r[col['qtd.']])), 'bruto': bruto, 'descontos': desc,
            # A coluna Taxas vem em centavos (277 = 2,77) ou em texto, conforme
            # o dia; o que nunca falha e a conta do proprio lote.
            'taxas': round(bruto - desc - liq, 2), 'liquido': liq,
            'status': status, 'chave': None, 'por_valor': True,
        })
    if not lotes:
        raise ValueError('lista de pagamentos da X7 sem nenhum pagamento')
    return lotes, []


def _lote_por_valor(cur, operadora, l, usados):
    """O id do lote ja gravado que e este (lista .xlsx, sem vendas): mesma
    quantidade, bruto e liquido, ate 7 dias de distancia -- o lote do .xls
    antigo (chave pelas vendas) e o da previsao que virou pagamento."""
    cur.execute("""
        SELECT id FROM cartao_arquivo_lotes
         WHERE operadora=%s AND qtd=%s AND bruto=%s AND liquido=%s
           AND ABS(DATEDIFF(COALESCE(dt_liquidacao, dt_previsao), %s)) <= 7
         ORDER BY ABS(DATEDIFF(COALESCE(dt_liquidacao, dt_previsao), %s)), id""",
        (operadora, l['qtd'], l['bruto'], l['liquido'], l['dt_previsao'], l['dt_previsao']))
    for (i,) in cur.fetchall():
        if i not in usados:
            return i
    return None


def _x7_depois_da_lista(cur, operadora, arquivo, lotes, usados):
    """Depois de gravar a lista .xlsx (que nao traz as vendas):

    1. A previsao antiga que a lista refez some. O .xls de 17/10 previa
       19/10 como UM lote de 269,86; a lista pagou DOIS (148,93 + 120,94).
       Lote ainda nao pago, dentro das datas da lista e que ela nao trouxe,
       e previsao velha -- deixa-lo contaria o dia em dobro.
    2. A venda que ja estava gravada (do .xls) ganha a data do pagamento:
       a do lote pago cujo bruto e a soma de `qtd` vendas ainda sem
       pagamento, de ate 45 dias antes. O desconto do lote e repartido pelo
       bruto, como no .xls."""
    datas = [l['dt_previsao'] for l in lotes]
    ini, fim = min(datas), max(datas)
    cur.execute("""
        SELECT id FROM cartao_arquivo_lotes
         WHERE operadora=%s AND dt_liquidacao IS NULL
           AND dt_previsao BETWEEN %s AND %s""", (operadora, ini, fim))
    velhos = [i for (i,) in cur.fetchall() if i not in usados]
    if velhos:
        _log.info('[cartao_arq] %s: %d previsao(oes) antiga(s) da X7 refeita(s) pela lista',
                  arquivo, len(velhos))
        cur.execute("DELETE FROM cartao_arquivo_lotes WHERE id IN (%s)"
                    % ','.join(['%s'] * len(velhos)), velhos)
    for l in sorted(lotes, key=lambda x: x['dt_previsao']):
        d = l['dt_liquidacao']
        if not d or not l['qtd']:
            continue
        cur.execute("""
            SELECT id, bruto FROM cartao_arquivo_vendas
             WHERE operadora=%s AND dt_liquidacao IS NULL
               AND dt_operacao >= %s AND dt_operacao < %s
             ORDER BY dt_operacao""",
            (operadora, d - timedelta(days=45), d + timedelta(days=1)))
        cands = [(i, float(b)) for i, b in cur.fetchall()][:12]
        achou = next((c for c in combinations(cands, l['qtd'])
                      if abs(sum(b for _, b in c) - l['bruto']) < _TOL), None)
        if not achou:
            continue
        resto = round(l['descontos'], 2)
        for k, (i, b) in enumerate(achou):
            parte = resto if k == len(achou) - 1 else (
                round(l['descontos'] * b / l['bruto'], 2) if l['bruto'] else 0.0)
            resto = round(resto - parte, 2)
            cur.execute("""
                UPDATE cartao_arquivo_vendas
                   SET dt_liquidacao=%s, dt_previsao=%s, desconto_lote=%s, status=%s
                 WHERE id=%s""", (d, l['dt_previsao'], parte, l['status'][:80], i))
    x7_vendas_pelo_cupom(cur, operadora, arquivo, lotes)


# CNPJ da X7 no cartao do cupom (card_credenciadora da NF-e/NFC-e)
_X7_CNPJ = '45179094000146'


def x7_vendas_pelo_cupom(cur, operadora, arquivo, lotes, gravar=True):
    """3. O pagamento da lista que nao tem venda nenhuma gravada ganha a venda
    pelo CUPOM FISCAL: o cupom X7 autorizado, de ate 10 dias antes, ainda sem
    venda, cujo valor e o bruto MENOS o desconto do lote (o que o cliente
    pagou). So quando UMA combinacao de `qtd` cupons fecha -- duas, nao grava.
    A venda leva o numero do cupom na NF-e, e o casamento por NF-e
    (cartao_cupom) a liga ao cupom como as do .xls.

    Devolve [(lote, cupons ou None, motivo)] -- com gravar=False so mede."""
    out = []
    # o dia de cada pagamento: a liquidacao, ou a previsao enquanto A Pagar
    por_dia = defaultdict(list)
    for l in lotes:
        if l['qtd']:
            por_dia[(l['dt_liquidacao'], None if l['dt_liquidacao'] else l['dt_previsao'])].append(l)
    usados = set()
    for (liq, prev), ls in sorted(por_dia.items(), key=lambda x: x[0][0] or x[0][1]):
        if liq:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(bruto),0) FROM cartao_arquivo_vendas "
                        "WHERE operadora=%s AND dt_liquidacao=%s", (operadora, liq))
        else:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(bruto),0) FROM cartao_arquivo_vendas "
                        "WHERE operadora=%s AND dt_liquidacao IS NULL AND dt_previsao=%s",
                        (operadora, prev))
        n, soma = cur.fetchone()
        if n:
            # o dia ja tem as vendas (do .xls ou de uma lista anterior);
            # parte delas e ambiguo demais para completar
            motivo = ('ja tem venda' if abs(float(soma) - sum(l['bruto'] for l in ls)) < _TOL
                      else 'dia com parte das vendas')
            out.extend((l, None, motivo) for l in ls)
            continue
        dia = liq or prev
        cur.execute("""
            SELECT x.id, x.numero, x.dh_emissao, x.valor_total, x.cliente_nome
              FROM vendas_xml x
             WHERE x.situacao='autorizada' AND x.card_credenciadora=%s
               AND x.dh_emissao >= %s AND x.dh_emissao < %s
               AND NOT EXISTS (SELECT 1 FROM cartao_cupom_vinculo v WHERE v.vendas_xml_id=x.id)
               AND NOT EXISTS (SELECT 1 FROM cartao_arquivo_vendas a
                                WHERE a.operadora=%s AND a.nfe=CAST(x.numero AS CHAR))
             ORDER BY x.dh_emissao""",
            (_X7_CNPJ, dia - timedelta(days=10), dia + timedelta(days=1), operadora))
        cupons = [c for c in cur.fetchall() if c[0] not in usados][:12]
        for l in ls:
            alvo = round(l['bruto'] - l['descontos'], 2)
            achou = []
            for comb in combinations([c for c in cupons if c[0] not in usados], l['qtd']):
                if abs(sum(float(c[3]) for c in comb) - alvo) < 0.005:
                    achou.append(comb)
                    if len(achou) > 1:
                        break
            if len(achou) != 1:
                out.append((l, None, 'nenhum cupom com %.2f' % alvo if not achou
                            else 'mais de um cupom com %.2f' % alvo))
                continue
            comb = achou[0]
            usados.update(c[0] for c in comb)
            out.append((l, comb, 'casado'))
            if not gravar:
                continue
            # o desconto e o liquido do lote, repartidos pelo valor do cupom
            resto_d, resto_l = round(l['descontos'], 2), round(l['liquido'], 2)
            for k, (cid, num, dh, val, cli) in enumerate(comb):
                ult = k == len(comb) - 1
                parte = resto_d if ult else round(l['descontos'] * float(val) / alvo, 2)
                liq_v = resto_l if ult else round(l['liquido'] * float(val) / alvo, 2)
                resto_d, resto_l = round(resto_d - parte, 2), round(resto_l - liq_v, 2)
                cur.execute("""
                    INSERT IGNORE INTO cartao_arquivo_vendas
                        (operadora, cod_transacao, parcela, estabelecimento, dt_previsao,
                         nfe, dt_operacao, dt_liquidacao, cliente, bruto, desconto,
                         taxa_pct, liquido_est, desconto_lote, forma_pagamento, status, arquivo)
                    VALUES (%s,%s,'',%s,%s,%s,%s,%s,%s,%s,0,0,%s,%s,%s,%s,%s)""",
                    (operadora, 'CUPOM-%s' % num, l['estabelecimento'][:120], l['dt_previsao'],
                     str(num), dh, l['dt_liquidacao'], (cli or '')[:160],
                     round(float(val) + parte, 2), liq_v, parte, 'pelo cupom fiscal',
                     l['status'][:80], arquivo[:200]))
            _log.info('[cartao_arq] %s: pagamento X7 %s de %.2f casado com o(s) cupom(ns) %s',
                      arquivo, dia, l['bruto'], ', '.join(str(c[1]) for c in comb))
    return out


def ler_baratao(conteudo):
    """Os cupons do CSV do Baratao, TODAS as colunas -- frentista, produto,
    litros e rebate nao entram na conferencia, mas ficam para relatorio."""
    if isinstance(conteudo, bytes):
        try:
            texto = conteudo.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto = conteudo.decode('cp1252')
    else:
        texto = conteudo
    leitor = csv.DictReader(io.StringIO(texto), delimiter=';')
    campos = set(leitor.fieldnames or [])
    faltam = {'Cupom', 'Data do Abastecimento', 'Valor Bruto',
              'Taxa Baratao', 'Valor Repasse Total'} - campos
    if faltam:
        raise ValueError('nao parece o CSV do Baratao: faltam as colunas %s'
                         % ', '.join(sorted(faltam)))

    cupons = []
    for row in leitor:
        def n(k):
            v = (row.get(k) or '').strip()
            return 0.0 if v.upper() == 'N/A' else _num(v)
        cupom = (row.get('Cupom') or '').strip()
        if not cupom:
            continue
        cd = (row.get('Cupom Desconto') or '').strip()
        cupons.append({
            'cupom': cupom,
            'dt_abastecimento': datetime.strptime(
                row['Data do Abastecimento'].strip()[:16], '%d/%m/%Y %H:%M'),
            'produto': (row.get('Produto') or '').strip(),
            'regiao': (row.get('Regiao') or '').strip(),
            'posto': (row.get('Posto') or '').strip(),
            'frentista': (row.get('Frentista') or '').strip(),
            'litros': n('Litros'),
            'valor_litro_dia': n('Valor Litro/Dia'),
            'desconto_lt': n('Valor Desconto/Lt'),
            'rebate_lt': n('Valor Rebate/Lt'),
            'valor_lt_total': n('Valor/Lt Total'),
            'valor_rebate': n('Valor Rebate'),
            'cupom_desconto': None if cd.upper() in ('', 'N/A') else cd,
            'dif_atacado': n('Diferenca Valor Atacado'),
            'bruto': n('Valor Bruto'),
            'taxa': n('Taxa Baratao'),
            'desconto': n('Valor Desconto'),
            'repasse': n('Valor Repasse Total'),
        })
    if not cupons:
        raise ValueError('CSV do Baratao sem nenhum cupom')
    return cupons


LEITORES = {'X7': ler_x7, 'BARATAO': ler_baratao}


# ── gravacao ──────────────────────────────────────────────────────────────────

def ensure_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_arquivo_lotes (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            operadora       VARCHAR(20)  NOT NULL,
            chave           CHAR(40)     NOT NULL,
            estabelecimento VARCHAR(120) NOT NULL DEFAULT '',
            dt_previsao     DATE         NOT NULL,
            dt_liquidacao   DATE         NULL,
            qtd             INT          NOT NULL DEFAULT 0,
            bruto           DECIMAL(12,2) NOT NULL DEFAULT 0,
            descontos       DECIMAL(12,2) NOT NULL DEFAULT 0,
            taxas           DECIMAL(12,2) NOT NULL DEFAULT 0,
            liquido         DECIMAL(12,2) NOT NULL DEFAULT 0,
            status          VARCHAR(80)  NULL,
            arquivo         VARCHAR(200) NULL,
            atualizado_em   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_lote (operadora, chave),
            KEY ix_liq (operadora, dt_liquidacao)
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_arquivo_vendas (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            operadora       VARCHAR(20)  NOT NULL,
            cod_transacao   VARCHAR(40)  NOT NULL,
            parcela         VARCHAR(20)  NOT NULL DEFAULT '',
            estabelecimento VARCHAR(120) NOT NULL DEFAULT '',
            dt_previsao     DATE         NULL,
            nfe             VARCHAR(20)  NULL,
            dt_operacao     DATETIME     NOT NULL,
            dt_liquidacao   DATE         NULL,
            cliente         VARCHAR(160) NULL,
            bruto           DECIMAL(12,2) NOT NULL DEFAULT 0,
            desconto        DECIMAL(12,2) NOT NULL DEFAULT 0,
            taxa_pct        DECIMAL(6,3) NOT NULL DEFAULT 0,
            liquido_est     DECIMAL(12,2) NOT NULL DEFAULT 0,
            desconto_lote   DECIMAL(12,2) NOT NULL DEFAULT 0,
            forma_pagamento VARCHAR(60)  NULL,
            status          VARCHAR(80)  NULL,
            arquivo         VARCHAR(200) NULL,
            atualizado_em   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_venda (operadora, cod_transacao, parcela),
            KEY ix_op (operadora, dt_operacao)
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_baratao_cupons (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            cupom            VARCHAR(40)  NOT NULL,
            dt_abastecimento DATETIME     NOT NULL,
            produto          VARCHAR(60)  NULL,
            regiao           VARCHAR(20)  NULL,
            posto            VARCHAR(120) NULL,
            frentista        VARCHAR(120) NULL,
            litros           DECIMAL(12,3) NOT NULL DEFAULT 0,
            valor_litro_dia  DECIMAL(10,4) NOT NULL DEFAULT 0,
            desconto_lt      DECIMAL(10,4) NOT NULL DEFAULT 0,
            rebate_lt        DECIMAL(10,4) NOT NULL DEFAULT 0,
            valor_lt_total   DECIMAL(10,4) NOT NULL DEFAULT 0,
            valor_rebate     DECIMAL(12,2) NOT NULL DEFAULT 0,
            cupom_desconto   VARCHAR(60)  NULL,
            dif_atacado      DECIMAL(12,2) NOT NULL DEFAULT 0,
            bruto            DECIMAL(12,2) NOT NULL DEFAULT 0,
            taxa             DECIMAL(12,2) NOT NULL DEFAULT 0,
            desconto         DECIMAL(12,2) NOT NULL DEFAULT 0,
            repasse          DECIMAL(12,2) NOT NULL DEFAULT 0,
            arquivo          VARCHAR(200) NULL,
            atualizado_em    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_cupom (cupom),
            KEY ix_dt (dt_abastecimento)
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_arquivo_importacoes (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            operadora   VARCHAR(20)  NULL,
            arquivo     VARCHAR(200) NOT NULL,
            tamanho     INT          NULL,
            lotes       INT          NOT NULL DEFAULT 0,
            vendas      INT          NOT NULL DEFAULT 0,
            erro        VARCHAR(400) NULL,
            importado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.commit()
    cur.close()


def gravar(conn, operadora, arquivo, lotes, vendas):
    """Grava por cima: o relatorio da X7 e acumulado (vem desde dez/2025 a
    cada vez), entao o mesmo lote chega de novo com o status atualizado --
    "A Pagar" vira "Pago", a liquidacao aparece. Chave natural, nunca duplica."""
    cur = conn.cursor()
    usados = set()
    for l in lotes:
        if l.get('por_valor'):
            # Lista .xlsx: o lote sem vendas e achado pelos valores. Achou:
            # atualiza o pagamento; nao achou: lote novo, com chave pelos
            # valores e pela previsao em que apareceu primeiro.
            i = _lote_por_valor(cur, operadora, l, usados)
            l['_id'] = i
            if i:
                usados.add(i)
                cur.execute("""
                    UPDATE cartao_arquivo_lotes
                       SET dt_liquidacao=COALESCE(%s, dt_liquidacao),
                           status=%s, arquivo=%s
                     WHERE id=%s""", (l['dt_liquidacao'], l['status'][:80], arquivo[:200], i))
                continue
            base = 'xlsx|%s|%s|%s|%s|%d' % (l['dt_previsao'], l['qtd'], l['bruto'],
                                            l['liquido'], len(usados))
            l['chave'] = hashlib.sha1(base.encode('utf-8')).hexdigest()
        cur.execute("""
            INSERT INTO cartao_arquivo_lotes
                (operadora, chave, estabelecimento, dt_previsao, dt_liquidacao, qtd,
                 bruto, descontos, taxas, liquido, status, arquivo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE dt_previsao=VALUES(dt_previsao),
                dt_liquidacao=VALUES(dt_liquidacao),
                qtd=VALUES(qtd), bruto=VALUES(bruto), descontos=VALUES(descontos),
                taxas=VALUES(taxas), liquido=VALUES(liquido),
                status=VALUES(status), arquivo=VALUES(arquivo)""",
            (operadora, l['chave'], l['estabelecimento'], l['dt_previsao'], l['dt_liquidacao'],
             l['qtd'], l['bruto'], l['descontos'], l['taxas'], l['liquido'],
             l['status'][:80], arquivo[:200]))
        if l.get('por_valor') and cur.lastrowid:
            usados.add(cur.lastrowid)
            l['_id'] = cur.lastrowid
    if any(l.get('por_valor') for l in lotes):
        _x7_depois_da_lista(cur, operadora, arquivo, lotes, usados)
    for v in vendas:
        cur.execute("""
            INSERT INTO cartao_arquivo_vendas
                (operadora, cod_transacao, parcela, estabelecimento, dt_previsao,
                 nfe, dt_operacao, dt_liquidacao, cliente, bruto, desconto,
                 taxa_pct, liquido_est, desconto_lote, forma_pagamento, status, arquivo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE estabelecimento=VALUES(estabelecimento),
                dt_previsao=VALUES(dt_previsao), nfe=VALUES(nfe),
                dt_operacao=VALUES(dt_operacao), dt_liquidacao=VALUES(dt_liquidacao),
                cliente=VALUES(cliente), bruto=VALUES(bruto), desconto=VALUES(desconto),
                taxa_pct=VALUES(taxa_pct), liquido_est=VALUES(liquido_est),
                desconto_lote=VALUES(desconto_lote),
                forma_pagamento=VALUES(forma_pagamento), status=VALUES(status),
                arquivo=VALUES(arquivo)""",
            (operadora, v['cod_transacao'], v['parcela'], v['estabelecimento'],
             v['dt_previsao'], v['nfe'], v['dt_operacao'], v['dt_liquidacao'],
             (v['cliente'] or '')[:160], v['bruto'], v['desconto'], v['taxa_pct'],
             v['liquido_est'], v.get('desconto_lote', 0.0),
             (v['forma_pagamento'] or '')[:60],
             (v['status'] or '')[:80], arquivo[:200]))
    conn.commit()
    cur.close()


_COLS_BARATAO = ('cupom', 'dt_abastecimento', 'produto', 'regiao', 'posto',
                 'frentista', 'litros', 'valor_litro_dia', 'desconto_lt',
                 'rebate_lt', 'valor_lt_total', 'valor_rebate', 'cupom_desconto',
                 'dif_atacado', 'bruto', 'taxa', 'desconto', 'repasse')


def gravar_baratao(conn, arquivo, cupons):
    """Por cima, pelo numero do cupom: o CSV vem acumulado desde jan/2026."""
    cols = _COLS_BARATAO + ('arquivo',)
    sql = ('INSERT INTO cartao_baratao_cupons (%s) VALUES (%s) '
           'ON DUPLICATE KEY UPDATE %s' % (
               ', '.join(cols), ', '.join(['%s'] * len(cols)),
               ', '.join('%s=VALUES(%s)' % (c, c) for c in cols if c != 'cupom')))
    cur = conn.cursor()
    cur.executemany(sql, [tuple(c[k] for k in _COLS_BARATAO) + (arquivo[:200],)
                          for c in cupons])
    conn.commit()
    cur.close()


def _registrar(conn, operadora, arquivo, tamanho, lotes=0, vendas=0, erro=None):
    cur = conn.cursor()
    cur.execute("""INSERT INTO cartao_arquivo_importacoes
                   (operadora, arquivo, tamanho, lotes, vendas, erro)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (operadora, arquivo[:200], tamanho, lotes, vendas,
                 (erro or '')[:400] or None))
    conn.commit()
    cur.close()


def importar(conn, nome, conteudo):
    """Le e grava UM arquivo. Devolve (operadora, n_lotes, n_vendas)."""
    operadora = operadora_do_nome(nome)
    if not operadora:
        raise ValueError('nome nao comeca com uma operadora conhecida: %s' % nome)
    ensure_tables(conn)
    try:
        if operadora == 'BARATAO':
            lotes, vendas = [], LEITORES[operadora](conteudo)
            gravar_baratao(conn, nome, vendas)
        elif operadora == 'SIPAG':
            ensure_tables_sipag(conn)
            tipo, vendas = ler_sipag(conteudo, nome)
            lotes = []
            gravar_sipag(conn, tipo, nome, vendas)
        elif operadora == 'SICREDI':
            ensure_tables_sicredi(conn)
            lotes, vendas = [], ler_sicredi(conteudo)
            gravar_sicredi(conn, nome, vendas)
        elif operadora == 'PIX':
            from utils import pix_extrato
            cab, vendas = pix_extrato.ler_sicoob(conteudo)
            lotes = []
            pix_extrato.gravar(conn, nome, cab, vendas)
        else:
            lotes, vendas = LEITORES[operadora](conteudo)
            gravar(conn, operadora, nome, lotes, vendas)
    except Exception as exc:
        conn.rollback()
        _registrar(conn, operadora, nome, len(conteudo), erro=str(exc))
        raise
    _registrar(conn, operadora, nome, len(conteudo), len(lotes), len(vendas))
    return operadora, len(lotes), len(vendas)


def processar_dropbox():
    """Varre /BANCOS/OFX/NOVO, importa o que for de operadora e move o
    arquivo para a pasta de importados. Devolve a lista do que fez.

    Arquivo que nao le TAMBEM sai da pasta: o erro fica registrado e aparece
    na tela da conferencia. Deixar la faria tentar de 10 em 10 minutos para
    sempre, e o OFX do lado nao tem nada com isso."""
    from integrations.dropbox_ofx import _criar_dbx, _get_config, is_configured
    if not is_configured():
        return []
    _, inbox, processed = _get_config()
    dbx = _criar_dbx()
    res = dbx.files_list_folder(inbox)
    entradas = list(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        entradas.extend(res.entries)

    feitos = []
    for e in entradas:
        if not hasattr(e, 'size') or not operadora_do_nome(e.name):
            continue
        _, resp = dbx.files_download('%s/%s' % (inbox, e.name))
        conteudo = resp.content
        conn = get_db_connection()
        try:
            op, nl, nv = importar(conn, e.name, conteudo)
            feitos.append((e.name, op, nl, nv, None))
        except Exception as exc:
            _log.warning('[cartao_arq] %s nao foi lido: %s', e.name, exc)
            feitos.append((e.name, None, 0, 0, str(exc)))
        finally:
            conn.close()
        try:
            dbx.files_move_v2('%s/%s' % (inbox, e.name),
                              '%s/%s' % (processed, e.name), autorename=True)
        except Exception:
            _log.exception('[cartao_arq] %s importado mas nao saiu da pasta', e.name)
    return feitos


# ── a conferencia ─────────────────────────────────────────────────────────────

def _ate_onde(conn, forma_ids):
    """(ultimo caixa fechado, ultimo extrato importado das formas).

    Venda depois do ultimo caixa fechado e pagamento depois do ultimo extrato
    importado nao sao divergencia: o outro lado ainda nao chegou. Sem este
    corte, todo dia de hoje e de ontem viraria "venda sem lancamento"."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT MAX(lc.data) AS m FROM lancamentos_caixa_comprovacao lcc "
                    "JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id "
                    "WHERE lcc.bandeira_cartao_id IS NOT NULL")
        cx = (cur.fetchone() or {}).get('m')
        ex = None
        if forma_ids:
            ph = ','.join(['%s'] * len(forma_ids))
            cur.execute(f"SELECT MAX(data_transacao) AS m FROM bank_transactions bt "
                        f"WHERE bt.account_id IN (SELECT DISTINCT account_id FROM bank_transactions "
                        f"WHERE forma_recebimento_id IN ({ph}))", list(forma_ids))
            ex = (cur.fetchone() or {}).get('m')
    finally:
        cur.close()
    return cx, ex


def operadora_da_bandeira(conn, bandeira_id):
    """Qual operadora (prefixo) tem arquivo para esta bandeira, ou None."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome, tipo FROM bandeiras_cartao WHERE id=%s", (bandeira_id,))
        b = cur.fetchone()
    finally:
        cur.close()
    if not b:
        return None
    nome = _sem_acento(b['nome']).strip().upper()
    for prefixo, o in OPERADORAS.items():
        if o.get('so_arquivo') or o.get('dentro_de'):
            continue
        if 'bandeiras' in o:
            if nome.startswith(o['bandeiras']):
                return prefixo
        elif nome.startswith(o['bandeira_like'].rstrip('%')) and \
                (b['tipo'] or '').upper() == o['tipo']:
            return prefixo
    return None


def conferencia(conn, operadora, bandeira_id, forma_ids, data_inicio, data_fim,
                taxa_contratada=None):
    """A conferencia pelo arquivo, no periodo [data_inicio, data_fim].

    - por_dia: cada dia de LIQUIDACAO do periodo -- o liquido que a operadora
      diz que pagou x o credito no extrato (formas vinculadas a bandeira).
    - caixa: cada dia de OPERACAO do periodo em que a venda do arquivo (bruto
      menos o desconto do cliente) nao bate com o lancado no caixa.
    """
    try:
        ensure_tables(conn)
    except Exception:
        return None
    if operadora == 'BARATAO':
        return conferencia_baratao(conn, bandeira_id, forma_ids, data_inicio, data_fim)
    if operadora == 'SIPAG':
        return conferencia_sipag(conn, bandeira_id, forma_ids, data_inicio, data_fim)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT dt_liquidacao AS d, COUNT(*) AS n, SUM(qtd) AS qtd,
                   SUM(bruto) AS bruto, SUM(descontos) AS descontos,
                   SUM(taxas) AS taxas, SUM(liquido) AS liquido
              FROM cartao_arquivo_lotes
             WHERE operadora=%s AND dt_liquidacao BETWEEN %s AND %s
             GROUP BY dt_liquidacao""", (operadora, data_inicio, data_fim))
        lotes = {r['d']: r for r in cur.fetchall()}

        extrato = {}
        if forma_ids:
            ph = ','.join(['%s'] * len(forma_ids))
            cur.execute(f"""
                SELECT data_transacao AS d, SUM(valor) AS v, COUNT(*) AS n
                  FROM bank_transactions
                 WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
                   AND data_transacao BETWEEN %s AND %s
                 GROUP BY data_transacao""", list(forma_ids) + [data_inicio, data_fim])
            extrato = {r['d']: r for r in cur.fetchall()}

        cur.execute("""
            SELECT dt_previsao, qtd, bruto, descontos, taxas, liquido, status
              FROM cartao_arquivo_lotes
             WHERE operadora=%s AND dt_liquidacao IS NULL
             ORDER BY dt_previsao""", (operadora,))
        a_receber = cur.fetchall()

        cur.execute("""
            SELECT DATE(dt_operacao) AS d, COUNT(*) AS n,
                   SUM(bruto - desconto_lote) AS bruto
              FROM cartao_arquivo_vendas
             WHERE operadora=%s AND dt_operacao >= %s AND dt_operacao < %s
             GROUP BY DATE(dt_operacao)""",
            (operadora, data_inicio,
             (datetime.strptime(data_fim, '%Y-%m-%d') + timedelta(days=1)).date()))
        arq_dia = {r['d']: r for r in cur.fetchall()}

        cur.execute("""
            SELECT lc.data AS d, COUNT(*) AS n, SUM(lcc.valor) AS v
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
             WHERE lcc.bandeira_cartao_id=%s AND lc.data BETWEEN %s AND %s
             GROUP BY lc.data""", (bandeira_id, data_inicio, data_fim))
        caixa_dia = {r['d']: r for r in cur.fetchall()}

        cur.execute("""
            SELECT arquivo, importado_em, lotes, vendas, erro
              FROM cartao_arquivo_importacoes
             WHERE operadora=%s ORDER BY id DESC LIMIT 1""", (operadora,))
        ultima = cur.fetchone()
        cur.execute("SELECT MAX(dt_operacao) AS m FROM cartao_arquivo_vendas "
                    "WHERE operadora=%s", (operadora,))
        ultima_venda = (cur.fetchone() or {}).get('m')
    finally:
        cur.close()

    if not lotes and not arq_dia and not ultima:
        return None

    ult_caixa, ult_extrato = _ate_onde(conn, forma_ids)
    por_dia = []
    for d in sorted(set(lotes) | set(extrato)):
        if ult_extrato and d > ult_extrato and d not in extrato:
            continue
        l = lotes.get(d)
        e = extrato.get(d)
        liq = float(l['liquido']) if l else 0.0
        ext = float(e['v']) if e else 0.0
        if l and e:
            st = 'ok' if abs(ext - liq) < _TOL else 'diverge'
        elif l:
            st = 'sem_credito'
        else:
            st = 'sem_lote'
        por_dia.append({
            'data': d, 'qtd': int(l['qtd']) if l else 0,
            'bruto': float(l['bruto']) if l else 0.0,
            'descontos': float(l['descontos']) if l else 0.0,
            'taxas': float(l['taxas']) if l else 0.0,
            'liquido': liq, 'extrato': ext, 'dif': round(ext - liq, 2),
            'status': st,
        })

    caixa = []
    for d in sorted(set(arq_dia) | set(caixa_dia)):
        if ult_caixa and d > ult_caixa:
            continue
        a = float(arq_dia[d]['bruto']) if d in arq_dia else 0.0
        c = float(caixa_dia[d]['v']) if d in caixa_dia else 0.0
        caixa.append({
            'data': d, 'arquivo': a, 'n_arquivo': int(arq_dia[d]['n']) if d in arq_dia else 0,
            'caixa': c, 'n_caixa': int(caixa_dia[d]['n']) if d in caixa_dia else 0,
            'dif': round(c - a, 2), 'ok': abs(c - a) < _TOL,
        })

    lot = [x for x in por_dia if x['qtd']]
    bruto = sum(x['bruto'] for x in lot)
    desc = sum(x['descontos'] for x in lot)
    taxas = sum(x['taxas'] for x in lot)
    taxa_esperada = None
    if taxa_contratada:
        taxa_esperada = round((bruto - desc) * float(taxa_contratada) / 100, 2)
    return {
        'operadora': operadora, 'nome': OPERADORAS[operadora]['nome'],
        'rotulo_dia': 'Liquidação', 'txt_dia': 'dia de liquidação',
        'por_dia': por_dia, 'caixa': caixa, 'a_receber': a_receber,
        'bruto': bruto, 'descontos': desc, 'taxas': taxas,
        'liquido': sum(x['liquido'] for x in lot),
        'extrato': sum(x['extrato'] for x in por_dia),
        'taxa_pct': (taxas / (bruto - desc) * 100) if bruto - desc else None,
        'taxa_esperada': taxa_esperada,
        'dias_ok': sum(1 for x in por_dia if x['status'] == 'ok'),
        'dias_problema': [x for x in por_dia if x['status'] != 'ok'],
        'caixa_arquivo': sum(x['arquivo'] for x in caixa),
        'caixa_lancado': sum(x['caixa'] for x in caixa),
        'caixa_problema': [x for x in caixa if not x['ok']],
        'ultima': ultima, 'ultima_venda': ultima_venda,
    }


# ── Baratao ───────────────────────────────────────────────────────────────────

#: Arredondamento: o PIX do dia sai ate uns centavos diferente da soma dos
#: cupons (13/03/2026: 7.023,81 nos cupons, 7.023,71 no PIX). Ate isto e o
#: mesmo pagamento; acima, e outro.
_TOL_CENTAVOS = 0.15
#: Quantos dias depois do abastecimento o PIX ainda pode chegar.
_JANELA_PIX = 10


def _casar_pix(dias, pix):
    """Acha o PIX de cada dia de abastecimento. dias: {data: repasse};
    pix: [{'id','d','v'}] em ordem. Devolve {data: [pix...]}, marcando 'u'.

    Tres passadas, da mais certa para a menos: valor exato, valor com
    centavos de arredondamento, e o dia pago em 2 a 4 PIX."""
    for p in pix:
        p['u'] = False
    casados = {}

    def candidatos(d):
        return [p for p in pix
                if not p['u'] and 0 <= (p['d'] - d).days <= _JANELA_PIX]

    for tol in (_TOL, _TOL_CENTAVOS):
        for d in sorted(dias):
            if d in casados:
                continue
            cs = [p for p in candidatos(d) if abs(p['v'] - dias[d]) < tol]
            if cs:
                p = min(cs, key=lambda x: (x['d'], abs(x['v'] - dias[d])))
                p['u'] = True
                casados[d] = [p]
    for d in sorted(dias):
        if d in casados:
            continue
        cs = candidatos(d)[:12]
        for k in (2, 3, 4):
            achou = next((c for c in combinations(cs, k)
                          if abs(sum(p['v'] for p in c) - dias[d]) < _TOL * k), None)
            if achou:
                for p in achou:
                    p['u'] = True
                casados[d] = list(achou)
                break
    return casados


def conferencia_baratao(conn, bandeira_id, forma_ids, data_inicio, data_fim):
    """A conferencia do Baratao no periodo, pelo DIA DE ABASTECIMENTO.

    Mesmo formato da X7 (o template e um so), mais o relatorio por frentista
    e por produto -- e por isso que o cupom inteiro e guardado."""
    ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
    fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
    # Dias de antes do periodo entram so para casar: um PIX do dia 2 pode
    # ser do abastecimento do dia 30 do mes anterior.
    ini_ext = ini - timedelta(days=_JANELA_PIX)
    fim_ext = fim + timedelta(days=_JANELA_PIX)
    taxa_pct = OPERADORAS['BARATAO']['taxa']

    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT DATE(dt_abastecimento) AS d, COUNT(*) AS n,
                   SUM(bruto) AS bruto, SUM(desconto) AS descontos,
                   SUM(taxa) AS taxas, SUM(repasse) AS liquido
              FROM cartao_baratao_cupons
             WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
             GROUP BY DATE(dt_abastecimento)""",
            (ini_ext, fim + timedelta(days=1)))
        dias = {r['d']: r for r in cur.fetchall()}

        pix, ultimo_pix = [], None
        if forma_ids:
            ph = ','.join(['%s'] * len(forma_ids))
            cur.execute(f"""
                SELECT id, data_transacao AS d, valor AS v
                  FROM bank_transactions
                 WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
                   AND data_transacao BETWEEN %s AND %s
                 ORDER BY data_transacao, id""",
                list(forma_ids) + [ini_ext, fim_ext])
            pix = [{'id': r['id'], 'd': r['d'], 'v': round(float(r['v']), 2)}
                   for r in cur.fetchall()]
            cur.execute(f"""
                SELECT MAX(data_transacao) AS m FROM bank_transactions
                 WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})""",
                list(forma_ids))
            ultimo_pix = (cur.fetchone() or {}).get('m')

        # A taxa so vale a partir do primeiro cupom que a teve (fev/2026).
        cur.execute("SELECT MIN(dt_abastecimento) AS m FROM cartao_baratao_cupons "
                    "WHERE taxa > 0")
        taxa_desde = (cur.fetchone() or {}).get('m')
        cur.execute("""
            SELECT COALESCE(SUM(bruto - desconto), 0) AS base, COUNT(*) AS n,
                   COALESCE(SUM(ROUND((bruto - desconto) * %s / 100, 2)), 0) AS esperada,
                   COALESCE(SUM(ABS(taxa - ROUND((bruto - desconto) * %s / 100, 2)) > 0.01), 0) AS fora
              FROM cartao_baratao_cupons
             WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
               AND dt_abastecimento >= %s""",
            (taxa_pct, taxa_pct, ini, fim + timedelta(days=1),
             taxa_desde or datetime(2100, 1, 1)))
        tx = cur.fetchone()

        cur.execute("""
            SELECT lc.data AS d, COUNT(*) AS n, SUM(lcc.valor) AS v
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
             WHERE lcc.bandeira_cartao_id=%s AND lc.data BETWEEN %s AND %s
             GROUP BY lc.data""", (bandeira_id, data_inicio, data_fim))
        caixa_dia = {r['d']: r for r in cur.fetchall()}

        rel = {}
        for chave, campo in (('frentistas', 'frentista'), ('produtos', 'produto')):
            cur.execute(f"""
                SELECT COALESCE(NULLIF({campo}, ''), '-') AS nome, COUNT(*) AS cupons,
                       SUM(litros) AS litros, SUM(bruto) AS bruto,
                       SUM(valor_rebate) AS rebate, SUM(taxa) AS taxa
                  FROM cartao_baratao_cupons
                 WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
                 GROUP BY nome ORDER BY bruto DESC""",
                (ini, fim + timedelta(days=1)))
            rel[chave] = cur.fetchall()

        cur.execute("""
            SELECT arquivo, importado_em, lotes, vendas, erro
              FROM cartao_arquivo_importacoes
             WHERE operadora='BARATAO' ORDER BY id DESC LIMIT 1""")
        ultima = cur.fetchone()
        cur.execute("SELECT MAX(dt_abastecimento) AS m FROM cartao_baratao_cupons")
        ultima_venda = (cur.fetchone() or {}).get('m')
    finally:
        cur.close()

    if not dias and not ultima:
        return None

    casados = _casar_pix({d: round(float(r['liquido']), 2) for d, r in dias.items()}, pix)

    por_dia, a_receber = [], []
    for d in sorted(x for x in dias if ini <= x <= fim):
        r = dias[d]
        liq = round(float(r['liquido']), 2)
        ps = casados.get(d, [])
        ext = round(sum(p['v'] for p in ps), 2)
        if ps:
            st = 'ok' if abs(ext - liq) < _TOL * len(ps) else 'centavos'
        elif not ultimo_pix or ultimo_pix < d + timedelta(days=4):
            # O extrato ainda nao chegou ate onde esse PIX cairia.
            a_receber.append({'liquido': liq, 'dt_previsao': d + timedelta(days=2)})
            continue
        else:
            st = 'sem_credito'
        por_dia.append({
            'data': d, 'qtd': int(r['n']), 'bruto': float(r['bruto']),
            'descontos': float(r['descontos']), 'taxas': float(r['taxas']),
            'liquido': liq, 'extrato': ext, 'dif': round(ext - liq, 2),
            'status': st, 'pix': [p['d'] for p in ps],
        })
    for p in pix:
        if not p['u'] and ini <= p['d'] <= fim:
            por_dia.append({
                'data': p['d'], 'qtd': 0, 'bruto': 0.0, 'descontos': 0.0,
                'taxas': 0.0, 'liquido': 0.0, 'extrato': p['v'], 'dif': p['v'],
                'status': 'sem_lote', 'pix': [p['d']],
            })
    por_dia.sort(key=lambda x: x['data'])

    lo, hi = OPERADORAS['BARATAO']['cupom_acima']
    ult_caixa, _ = _ate_onde(conn, [])
    caixa = []
    for d in sorted(set(x for x in dias if ini <= x <= fim) | set(caixa_dia)):
        if ult_caixa and d > ult_caixa:
            continue
        a = float(dias[d]['bruto']) - float(dias[d]['descontos']) if d in dias else 0.0
        c = float(caixa_dia[d]['v']) if d in caixa_dia else 0.0
        pct = ((c / a - 1) * 100) if a and c else None
        caixa.append({
            'data': d, 'arquivo': a, 'n_arquivo': int(dias[d]['n']) if d in dias else 0,
            'caixa': c, 'n_caixa': int(caixa_dia[d]['n']) if d in caixa_dia else 0,
            'dif': round(c - a, 2), 'pct': pct,
            'ok': pct is not None and lo <= pct <= hi,
        })

    lot = [x for x in por_dia if x['qtd']]
    no_periodo = [r for d, r in dias.items() if ini <= d <= fim]
    base_taxa = float(tx['base'] or 0)
    centavos = [x for x in por_dia if x['status'] == 'centavos']
    return {
        'operadora': 'BARATAO', 'nome': OPERADORAS['BARATAO']['nome'],
        'rotulo_dia': 'Abastecimento', 'txt_dia': 'dia de abastecimento',
        'por_dia': por_dia, 'caixa': caixa, 'a_receber': a_receber,
        'bruto': sum(float(r['bruto']) for r in no_periodo),
        'descontos': sum(float(r['descontos']) for r in no_periodo),
        'taxas': sum(float(r['taxas']) for r in no_periodo),
        'liquido': sum(x['liquido'] for x in lot),
        'extrato': sum(x['extrato'] for x in por_dia),
        'taxa_pct': (sum(float(r['taxas']) for r in no_periodo) / base_taxa * 100)
                    if base_taxa else None,
        # Cupom a cupom, como o Baratao arredonda -- a conta no total daria
        # R$ 1,64 de "diferenca" que nao existe em jan-out/2026.
        'taxa_esperada': float(tx['esperada']) if base_taxa else None,
        'taxa_contrato': taxa_pct, 'taxa_cupons_fora': int(tx['fora'] or 0),
        'taxa_desde': taxa_desde,
        'dias_ok': sum(1 for x in por_dia if x['status'] in ('ok', 'centavos')),
        'dias_problema': [x for x in por_dia if x['status'] not in ('ok', 'centavos')],
        'centavos_n': len(centavos),
        'centavos_total': round(sum(x['dif'] for x in centavos), 2),
        'caixa_arquivo': sum(x['arquivo'] for x in caixa),
        'caixa_lancado': sum(x['caixa'] for x in caixa),
        'caixa_problema': [x for x in caixa if not x['ok']],
        'frentistas': rel['frentistas'], 'produtos': rel['produtos'],
        'cupom_faixa': (lo, hi),
        'cupom_acima': sum(x['dif'] for x in caixa if x['ok']),
        'cupom_acima_pct': (sum(x['dif'] for x in caixa if x['ok'])
                            / sum(x['arquivo'] for x in caixa if x['ok']) * 100)
                           if any(x['ok'] for x in caixa) else None,
        'ultima': ultima, 'ultima_venda': ultima_venda,
    }


# ── SIPAG ─────────────────────────────────────────────────────────────────────
#
# Dois relatorios, de proposito -- um audita o outro:
#   vendas_realizadas_relatorio_detalhado_<data>.csv   tudo o que foi vendido,
#       com a data PREVISTA de liquidacao e o desconto da venda (so o MDR:
#       ~0,3% no credito);
#   relatorio_vendas_recebidas_detalhadas_<data>.csv   o que a SIPAG PAGOU, com a
#       data do pagamento, a conta e o desconto final (credito a vista ja com a
#       antecipacao: ~2,1%).
# Os dois casam pelo No da transacao. Linhas com No da transacao 0 sao
# abatimentos do pagamento (-6,20, -1,92...): nao sao venda, mas sairam do
# que caiu no banco. Em 17/10/2026, 390 de 408 dias x bandeira x debito/credito
# bateram no centavo com o extrato (o resto: extrato ainda nao importado e o
# comeco do arquivo).

_SIPAG_BANDEIRA = {'VISA': 'Visa', 'MASTERCARD': 'Mastercard', 'ELO': 'Elo',
                   'AMEX': 'Amex', 'CABAL': 'Cabal'}
_SIPAG_TIPO = {'DEBITO': 'Débito', 'CREDITO': 'Crédito'}


def _num_sipag(s):
    """'R$ 1.018,34' -> 1018.34; '-R$ 6,20' -> -6.2."""
    s = (s or '').replace('R$', '').replace('\xa0', '').replace(' ', '')
    neg = s.startswith('-')
    s = s.lstrip('-')
    if not s:
        return 0.0
    v = float(s.replace('.', '').replace(',', '.'))
    return -v if neg else v


def ler_sipag(conteudo, nome):
    """As transacoes de um dos dois relatorios. Devolve (tipo, linhas)."""
    tipo = 'recebidas' if 'RECEBIDAS' in _sem_acento(nome).upper() else 'realizadas'
    if isinstance(conteudo, bytes):
        try:
            texto = conteudo.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto = conteudo.decode('cp1252')
    else:
        texto = conteudo
    linhas = texto.splitlines()
    try:
        i = next(k for k, l in enumerate(linhas) if l.startswith('Nº do estabelecimento'))
    except StopIteration:
        raise ValueError('nao parece um relatorio da SIPAG: sem a linha de cabecalho')
    leitor = csv.DictReader(io.StringIO('\n'.join(linhas[i:])), delimiter=';')
    if tipo == 'recebidas' and 'Data do pagamento' not in (leitor.fieldnames or []):
        raise ValueError('relatorio de vendas recebidas sem a coluna "Data do pagamento"')

    def d(s, fmt='%d/%m/%Y'):
        s = (s or '').strip()
        return None if s in ('', '-') else datetime.strptime(s[:len(fmt) + 2], fmt)

    saida, vistos = [], defaultdict(int)
    for r in leitor:
        nsu = (r.get('Nº da transação') or '').strip()
        if not nsu or (r.get('Nº do estabelecimento') or '').startswith('Total'):
            continue
        dt = d(r.get('Data da transação'), '%d/%m/%Y %H:%M:%S')
        x = {
            'nsu': nsu,
            'estabelecimento': (r.get('Nº do estabelecimento') or '').strip(),
            'dt_transacao': dt,
            'id_venda': (r.get('ID Venda') or '').strip(),
            'bandeira': (r.get('Bandeira') or '').strip(),
            'forma': (r.get('Forma de Pagamento') or '').strip(),
            'plano': (r.get('Plano de venda') or '').strip(),
            'parcela': (r.get('Parcela') or '').strip(),
            'total_parcelas': (r.get('Total de parcela') or '').strip(),
            'autorizacao': (r.get('Número da autorização') or '').strip(),
            'tipo_cartao': (r.get('Tipo cartão') or '').strip(),
            'cartao': (r.get('Número do cartão') or '').strip(),
            'terminal': (r.get('Número do terminal') or '').strip(),
            'captura': (r.get('Tipo captura') or '').strip(),
            'ind_cd': (r.get('Indicador Crédito/Débito') or '').strip(),
            'ind_cancel': (r.get('Indicador de cancelamento da venda') or '').strip(),
            'resumo': (r.get('Nº resumo da venda') or '').strip(),
            'dt_prevista': (d(r.get('Data prevista de liquidação')) or None),
            'seu_numero': (r.get('Seu número') or '').strip(),
            'ordem_pagamento': (r.get('Nº ordem de pagamento') or '').strip(),
            'status': (r.get('Status') or '').strip(),
            'bruto': _num_sipag(r.get('Valor parcela bruto')),
            'desconto': _num_sipag(r.get('Desconto parcela')),
            'liquido': _num_sipag(r.get('Valor parcela liquido')),
            'total_plano': _num_sipag(r.get('Total plano de venda')),
        }
        if x['dt_prevista']:
            x['dt_prevista'] = x['dt_prevista'].date()
        if tipo == 'recebidas':
            pg = d(r.get('Data do pagamento'))
            x.update({'dt_pagamento': pg.date() if pg else None,
                      'banco': (r.get('Nº do banco') or '').strip(),
                      'agencia': (r.get('Nº da agência') or '').strip(),
                      'conta': (r.get('Nº da conta') or '').strip()})
        if nsu == '0':
            # Abatimento: nao tem numero. Linhas iguais no mesmo arquivo sao
            # abatimentos diferentes (02/10/2026: quatro de -6,20), entao a
            # ordem de aparicao entra na chave.
            base = '|'.join(str(x.get(k)) for k in (
                'dt_transacao', 'bandeira', 'forma', 'bruto', 'dt_pagamento'))
            vistos[base] += 1
            x['chave'] = 'AJ-' + hashlib.sha1(
                ('%s|%d' % (base, vistos[base])).encode('utf-8')).hexdigest()[:37]
        else:
            x['chave'] = '%s/%s' % (nsu, x['parcela'])
        saida.append(x)
    if not saida:
        raise ValueError('relatorio da SIPAG sem nenhuma transacao')
    return tipo, saida


_COLS_SIPAG = ('chave', 'nsu', 'estabelecimento', 'dt_transacao', 'id_venda',
               'bandeira', 'forma', 'plano', 'parcela', 'total_parcelas',
               'autorizacao', 'tipo_cartao', 'cartao', 'terminal', 'captura',
               'ind_cd', 'ind_cancel', 'resumo', 'dt_prevista', 'seu_numero',
               'ordem_pagamento', 'status', 'bruto', 'total_plano')


def ensure_tables_sipag(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_sipag_transacoes (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            chave            VARCHAR(60)  NOT NULL,
            nsu              VARCHAR(30)  NOT NULL,
            estabelecimento  VARCHAR(40)  NULL,
            dt_transacao     DATETIME     NULL,
            id_venda         VARCHAR(60)  NULL,
            bandeira         VARCHAR(30)  NULL,
            forma            VARCHAR(20)  NULL,
            plano            VARCHAR(30)  NULL,
            parcela          VARCHAR(10)  NULL,
            total_parcelas   VARCHAR(10)  NULL,
            autorizacao      VARCHAR(20)  NULL,
            tipo_cartao      VARCHAR(60)  NULL,
            cartao           VARCHAR(30)  NULL,
            terminal         VARCHAR(20)  NULL,
            captura          VARCHAR(20)  NULL,
            ind_cd           VARCHAR(5)   NULL,
            ind_cancel       VARCHAR(10)  NULL,
            resumo           VARCHAR(30)  NULL,
            dt_prevista      DATE         NULL,
            seu_numero       VARCHAR(30)  NULL,
            ordem_pagamento  VARCHAR(30)  NULL,
            status           VARCHAR(60)  NULL,
            bruto            DECIMAL(12,2) NOT NULL DEFAULT 0,
            total_plano      DECIMAL(12,2) NOT NULL DEFAULT 0,
            desconto_venda   DECIMAL(12,2) NULL,
            liquido_venda    DECIMAL(12,2) NULL,
            dt_pagamento     DATE         NULL,
            banco            VARCHAR(10)  NULL,
            agencia          VARCHAR(10)  NULL,
            conta            VARCHAR(20)  NULL,
            status_pagamento VARCHAR(60)  NULL,
            desconto_pago    DECIMAL(12,2) NULL,
            liquido_pago     DECIMAL(12,2) NULL,
            arq_realizadas   VARCHAR(200) NULL,
            arq_recebidas    VARCHAR(200) NULL,
            atualizado_em    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_chave (chave),
            KEY ix_tr (dt_transacao),
            KEY ix_pg (dt_pagamento),
            KEY ix_band (bandeira, forma)
        )""")
    conn.commit()
    cur.close()


def gravar_sipag(conn, tipo, arquivo, linhas):
    """Cada relatorio grava a sua parte da mesma linha: o de realizadas, o
    desconto e o liquido da VENDA; o de recebidas, o do PAGAMENTO."""
    if tipo == 'realizadas':
        extra = ('desconto_venda', 'liquido_venda', 'arq_realizadas')
        vals = lambda x: (x['desconto'], x['liquido'], arquivo[:200])
    else:
        extra = ('dt_pagamento', 'banco', 'agencia', 'conta', 'status_pagamento',
                 'desconto_pago', 'liquido_pago', 'arq_recebidas')
        vals = lambda x: (x['dt_pagamento'], x['banco'], x['agencia'], x['conta'],
                          x['status'], x['desconto'], x['liquido'], arquivo[:200])
    cols = _COLS_SIPAG + extra
    # O status do relatorio de recebidas ("Pagamento Realizado") vai so para
    # status_pagamento; o "status" da linha e o da venda.
    atualiza = [c for c in cols if c != 'chave' and not (tipo == 'recebidas' and c == 'status')]
    sql = ('INSERT INTO cartao_sipag_transacoes (%s) VALUES (%s) '
           'ON DUPLICATE KEY UPDATE %s' % (
               ', '.join(cols), ', '.join(['%s'] * len(cols)),
               ', '.join('%s=VALUES(%s)' % (c, c) for c in atualiza)))
    cur = conn.cursor()
    cur.executemany(sql, [tuple(x[k] for k in _COLS_SIPAG) + vals(x) for x in linhas])
    conn.commit()
    cur.close()


def _sipag_da_bandeira(nome, tipo):
    """(bandeira, forma) como a SIPAG escreve, para a bandeira do cadastro."""
    n = _sem_acento(nome).strip().upper()
    for pref, b in _SIPAG_BANDEIRA.items():
        if n.startswith(pref):
            return b, _SIPAG_TIPO.get((tipo or '').upper())
    return None, None


def conferencia_sipag(conn, bandeira_id, forma_ids, data_inicio, data_fim):
    """A conferencia da SIPAG para UMA bandeira (ex.: VISA debito), pelo dia
    de PAGAMENTO -- e assim que o extrato credita: uma linha por dia, por
    bandeira, por debito/credito."""
    ensure_tables_sipag(conn)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome, tipo FROM bandeiras_cartao WHERE id=%s", (bandeira_id,))
        b = cur.fetchone() or {}
        sb, sf = _sipag_da_bandeira(b.get('nome'), b.get('tipo'))
        if not sb or not sf:
            return None
        flt = "bandeira=%s AND forma=%s"
        cur.execute(f"""
            SELECT dt_pagamento AS d, SUM(nsu <> '0') AS qtd,
                   SUM(CASE WHEN nsu <> '0' THEN bruto ELSE 0 END) AS bruto,
                   SUM(COALESCE(desconto_pago, 0)) AS taxas,
                   SUM(CASE WHEN nsu <> '0' THEN COALESCE(desconto_venda, 0) ELSE 0 END) AS mdr,
                   SUM(CASE WHEN nsu = '0' THEN liquido_pago ELSE 0 END) AS abatimentos,
                   SUM(liquido_pago) AS liquido
              FROM cartao_sipag_transacoes
             WHERE {flt} AND dt_pagamento BETWEEN %s AND %s
             GROUP BY dt_pagamento""", (sb, sf, data_inicio, data_fim))
        pagos = {r['d']: r for r in cur.fetchall()}
        cur.execute("SELECT MAX(dt_pagamento) AS z "
                    "FROM cartao_sipag_transacoes WHERE dt_pagamento IS NOT NULL")
        cob = cur.fetchone() or {}
        cur.execute(f"""
            SELECT dt_pagamento AS d, SUM(liquido_pago) AS v
              FROM cartao_sipag_transacoes
             WHERE {flt} AND dt_pagamento IS NOT NULL
             GROUP BY dt_pagamento ORDER BY dt_pagamento""", (sb, sf))
        pagos_todos = [(r['d'], float(r['v'] or 0)) for r in cur.fetchall()]

        extrato, extrato_todo = {}, {}
        if forma_ids and pagos_todos:
            ph = ','.join(['%s'] * len(forma_ids))
            cur.execute(f"""
                SELECT data_transacao AS d, SUM(valor) AS v
                  FROM bank_transactions
                 WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
                   AND data_transacao BETWEEN %s AND %s
                 GROUP BY data_transacao""",
                list(forma_ids) + [pagos_todos[0][0], max(data_fim, pagos_todos[-1][0].isoformat())])
            extrato_todo = {r['d']: float(r['v']) for r in cur.fetchall()}
        # Quando a SIPAG assumiu esta bandeira: o primeiro dia em que ela pagou
        # pelo menos metade do que caiu no banco. Antes disso (jul/2026, ate
        # ~14/07) o arquivo so tem venda de teste de R$ 0,10, e o credito do
        # extrato e da maquininha antiga -- nao e problema da SIPAG.
        sipag_desde = _sipag_desde(cur, sb, sf, forma_ids)
        extrato = {d: v for d, v in extrato_todo.items()
                   if data_inicio <= d.isoformat() <= data_fim}

        # Venda que ja devia ter sido paga e nao aparece no relatorio de
        # recebidas: a previsao passou e o relatorio ja cobre aquele dia.
        cur.execute(f"""
            SELECT dt_prevista, COUNT(*) AS n, SUM(bruto) AS bruto,
                   SUM(liquido_venda) AS liquido
              FROM cartao_sipag_transacoes
             WHERE {flt} AND nsu <> '0' AND dt_pagamento IS NULL
               AND dt_prevista IS NOT NULL
             GROUP BY dt_prevista ORDER BY dt_prevista""", (sb, sf))
        nao_pagas = cur.fetchall()

        cur.execute(f"""
            SELECT DATE(dt_transacao) AS d, COUNT(*) AS n, SUM(bruto) AS bruto
              FROM cartao_sipag_transacoes
             WHERE {flt} AND nsu <> '0' AND arq_realizadas IS NOT NULL
               AND dt_transacao >= %s AND dt_transacao < %s
             GROUP BY DATE(dt_transacao)""",
            (sb, sf, data_inicio,
             (datetime.strptime(data_fim, '%Y-%m-%d') + timedelta(days=1)).date()))
        arq_dia = {r['d']: r for r in cur.fetchall()}
        # O mesmo corte do lado da venda: o primeiro dia em que o arquivo
        # tem ao menos metade do que o caixa lancou para a bandeira. O credito
        # parcelado do comeco de julho tem venda de teste paga em agosto, e
        # contar a partir dela poria a maquininha antiga na conta da SIPAG.
        cur.execute(f"""
            SELECT DATE(dt_transacao) AS d, SUM(bruto) AS v
              FROM cartao_sipag_transacoes
             WHERE {flt} AND nsu <> '0' AND arq_realizadas IS NOT NULL
             GROUP BY DATE(dt_transacao) ORDER BY d""", (sb, sf))
        venda_todo = [(r['d'], float(r['v'] or 0)) for r in cur.fetchall()]
        cur.execute("""
            SELECT lc.data AS d, SUM(lcc.valor) AS v
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
             WHERE lcc.bandeira_cartao_id=%s AND lc.data >= %s
             GROUP BY lc.data""", (bandeira_id, venda_todo[0][0] if venda_todo else date(2100, 1, 1)))
        caixa_todo = {r['d']: float(r['v'] or 0) for r in cur.fetchall()}
        real_desde = next((d for d, v in venda_todo
                           if caixa_todo.get(d) and v >= 0.5 * caixa_todo[d]), None)

        cur.execute("""
            SELECT lc.data AS d, COUNT(*) AS n, SUM(lcc.valor) AS v
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
             WHERE lcc.bandeira_cartao_id=%s AND lc.data BETWEEN %s AND %s
             GROUP BY lc.data""", (bandeira_id, data_inicio, data_fim))
        caixa_dia = {r['d']: r for r in cur.fetchall()}

        cur.execute("""
            SELECT arquivo, importado_em, lotes, vendas, erro
              FROM cartao_arquivo_importacoes
             WHERE operadora='SIPAG' ORDER BY id DESC LIMIT 1""")
        ultima = cur.fetchone()
        cur.execute(f"SELECT MAX(dt_transacao) AS m FROM cartao_sipag_transacoes "
                    f"WHERE {flt} AND nsu <> '0'", (sb, sf))
        ultima_venda = (cur.fetchone() or {}).get('m')
    finally:
        cur.close()

    if not pagos and not arq_dia and not ultima:
        return None

    ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
    fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
    pago_ate = cob.get('z')

    ult_caixa, ult_extrato = _ate_onde(conn, forma_ids)
    por_dia = []
    for d in sorted(set(pagos) | set(extrato)):
        if sipag_desde and d < sipag_desde:
            continue
        if ult_extrato and d > ult_extrato and d not in extrato:
            continue
        p = pagos.get(d)
        liq = float(p['liquido']) if p else 0.0
        ext = extrato.get(d, 0.0)
        if p and d in extrato:
            st = 'ok' if abs(ext - liq) < _TOL else 'diverge'
        elif p:
            st = 'sem_credito'
        else:
            # Credito no extrato num dia que o relatorio de recebidas nao
            # cobre nao e problema: o arquivo e que nao chega la.
            if not sipag_desde or not (sipag_desde < d <= pago_ate):
                continue
            st = 'sem_lote'
        por_dia.append({
            'data': d, 'qtd': int(p['qtd']) if p else 0,
            'bruto': float(p['bruto']) if p else 0.0,
            'descontos': -float(p['abatimentos']) if p else 0.0,
            'taxas': float(p['taxas']) if p else 0.0,
            'liquido': liq, 'extrato': ext, 'dif': round(ext - liq, 2),
            'status': st,
        })

    a_receber, atrasadas = [], []
    for r in nao_pagas:
        if sipag_desde and r['dt_prevista'] < sipag_desde:
            continue
        if pago_ate and r['dt_prevista'] <= pago_ate:
            atrasadas.append(r)
        elif ini <= r['dt_prevista'] or r['dt_prevista'] > (pago_ate or fim):
            a_receber.append({'liquido': float(r['liquido'] or 0),
                              'dt_previsao': r['dt_prevista']})

    caixa = []
    for d in sorted(set(arq_dia) | set(caixa_dia)):
        if not real_desde or d < real_desde:
            continue
        if ult_caixa and d > ult_caixa:
            continue
        a = float(arq_dia[d]['bruto']) if d in arq_dia else 0.0
        c = float(caixa_dia[d]['v']) if d in caixa_dia else 0.0
        caixa.append({
            'data': d, 'arquivo': a, 'n_arquivo': int(arq_dia[d]['n']) if d in arq_dia else 0,
            'caixa': c, 'n_caixa': int(caixa_dia[d]['n']) if d in caixa_dia else 0,
            'dif': round(c - a, 2), 'ok': abs(c - a) < _TOL,
        })

    lot = [x for x in por_dia if x['qtd'] or x['descontos']]
    bruto = sum(x['bruto'] for x in lot)
    taxas = sum(x['taxas'] for x in lot)
    mdr = sum(float(p['mdr'] or 0) for p in pagos.values())
    return {
        'operadora': 'SIPAG', 'nome': 'SIPAG',
        'rotulo_dia': 'Pagamento', 'txt_dia': 'dia de pagamento',
        'rotulo_descontos': 'Abatimentos',
        'por_dia': por_dia, 'caixa': caixa, 'a_receber': a_receber,
        'atrasadas': atrasadas,
        'bruto': bruto, 'descontos': 0.0, 'taxas': taxas,
        'abatimentos': sum(x['descontos'] for x in lot),
        'mdr': mdr, 'antecipacao': round(taxas - mdr, 2),
        'liquido': sum(x['liquido'] for x in lot),
        'extrato': sum(x['extrato'] for x in por_dia),
        'taxa_pct': (taxas / bruto * 100) if bruto else None,
        'taxa_esperada': None,
        'dias_ok': sum(1 for x in por_dia if x['status'] == 'ok'),
        'dias_problema': [x for x in por_dia if x['status'] != 'ok'],
        'caixa_arquivo': sum(x['arquivo'] for x in caixa),
        'caixa_lancado': sum(x['caixa'] for x in caixa),
        'caixa_problema': [x for x in caixa if not x['ok']],
        'ultima': ultima, 'ultima_venda': ultima_venda,
        'bandeira_arquivo': '%s %s' % (sb, sf.lower()),
        'desde': sipag_desde,
    }


# ── a venda da operadora, no formato do motor da Conferencia ──────────────────
#
# A aba "Operadora" e a MESMA tela da aba "Caixa" -- mesmos cards, mesma
# tabela de ciclos --, so que a venda E a data em que ela foi paga saem do
# arquivo da operadora. A primeira versao (c2b6b0c5) mandava so a venda e
# deixava o motor adivinhar o pagamento pelo prazo da bandeira: na X7, que
# paga com 0 a 44 dias, sobrava "ainda nao caiu" e "caiu sem venda" que nao
# existiam. Aqui se entregam os ciclos prontos.

def _operadora_de(nome, tipo):
    nome = _sem_acento(nome).strip().upper()
    for prefixo, o in OPERADORAS.items():
        if o.get('so_arquivo') or o.get('dentro_de'):
            continue
        if 'bandeiras' in o:
            if nome.startswith(o['bandeiras']):
                return prefixo
        elif nome.startswith(o['bandeira_like'].rstrip('%')) and \
                (tipo or '').upper() == o['tipo']:
            return prefixo
    return None


def _sipag_desde(cur, sb, sf, forma_ids):
    """O primeiro dia em que a SIPAG pagou ao menos metade do que caiu no
    banco para a bandeira. Antes disso (jul/2026, ate ~14/07) o arquivo so tem
    venda de teste e o credito do extrato e da maquininha antiga."""
    cur.execute("""
        SELECT dt_pagamento AS d, SUM(liquido_pago) AS v
          FROM cartao_sipag_transacoes
         WHERE bandeira=%s AND forma=%s AND dt_pagamento IS NOT NULL
         GROUP BY dt_pagamento ORDER BY dt_pagamento""", (sb, sf))
    pagos = [(r['d'], float(r['v'] or 0)) for r in cur.fetchall()]
    if not pagos:
        return None
    extrato = {}
    if forma_ids:
        ph = ','.join(['%s'] * len(forma_ids))
        cur.execute(f"""
            SELECT data_transacao AS d, SUM(valor) AS v
              FROM bank_transactions
             WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
               AND data_transacao BETWEEN %s AND %s
             GROUP BY data_transacao""",
            list(forma_ids) + [pagos[0][0], pagos[-1][0]])
        extrato = {r['d']: float(r['v'] or 0) for r in cur.fetchall()}
    return next((d for d, v in pagos if extrato.get(d) and v >= 0.5 * extrato[d]),
                pagos[-1][0])


def ciclos_operadora(conn, bandeiras, vinculos_map, data_inicio, data_fim):
    """(bandeiras, desde, ciclos) para o motor da Conferencia, na aba Operadora.

    O arquivo diz QUANDO cada venda foi paga -- nao ha o que adivinhar pelo
    prazo. Cada ciclo e um dia de pagamento com as vendas que ele pagou:

        ciclos = {bandeira_id: {data_pagamento_iso: {data_venda_iso: valor}}}

    - X7: a Dt. Liquidacao de cada venda;
    - SIPAG: a Data do pagamento do relatorio de recebidas;
    - Baratao: o dia do PIX que pagou aquele dia de abastecimento (_casar_pix).
    Venda ainda nao paga entra no dia PREVISTO, e o motor a conta como "ainda
    nao caiu". Entra o ciclo pago no periodo e a venda do periodo paga depois.

    - bandeiras: so as que tem operadora; copia de cada uma, sem o saldo
      anterior (acerto do CAIXA) e com o contrato da operadora quando a
      bandeira nao tem (Baratao: 2%).
    - desde: {bandeira_id: data}; credito do extrato antes disso nao e desta
      operadora (SIPAG antes de 15/07/2026: maquininha antiga).
    """
    ensure_tables(conn)
    ensure_tables_sipag(conn)
    ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
    fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
    fim1 = fim + timedelta(days=1)
    saida_band, desde, ciclos = [], {}, {}
    cur = conn.cursor(dictionary=True)

    def entra(pago, prev, venda_d):
        """(data do ciclo, entra?) de uma venda."""
        if pago:
            if ini <= pago <= fim:
                return pago, True
            return pago, (ini <= venda_d <= fim and pago > fim)
        return (prev or venda_d), ini <= venda_d <= fim

    try:
        for b in bandeiras:
            op = _operadora_de(b.get('nome'), b.get('tipo'))
            if not op:
                continue
            c = defaultdict(lambda: defaultdict(float))
            d0 = None
            if op == 'X7':
                cur.execute("""
                    SELECT DATE(dt_operacao) AS v, bruto - desconto_lote AS valor,
                           dt_liquidacao AS pago, dt_previsao AS prev
                      FROM cartao_arquivo_vendas
                     WHERE operadora='X7'
                       AND (dt_liquidacao BETWEEN %s AND %s
                            OR (dt_operacao >= %s AND dt_operacao < %s))""",
                    (ini, fim, ini, fim1))
                for r in cur.fetchall():
                    rd, ok = entra(r['pago'], r['prev'], r['v'])
                    if ok:
                        c[rd.isoformat()][r['v'].isoformat()] += float(r['valor'] or 0)
                cur.execute("SELECT MIN(DATE(dt_operacao)) AS d FROM cartao_arquivo_vendas "
                            "WHERE operadora='X7'")
                d0 = (cur.fetchone() or {}).get('d')
            elif op == 'BARATAO':
                janela = timedelta(days=_JANELA_PIX * 2)
                cur.execute("""
                    SELECT DATE(dt_abastecimento) AS d, SUM(bruto - desconto) AS venda,
                           SUM(repasse) AS repasse
                      FROM cartao_baratao_cupons
                     WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
                     GROUP BY DATE(dt_abastecimento)""", (ini - janela, fim1))
                dias = {r['d']: r for r in cur.fetchall()}
                pix = []
                fs = vinculos_map.get(b['id'], [])
                if fs:
                    ph = ','.join(['%s'] * len(fs))
                    cur.execute(f"""
                        SELECT id, data_transacao AS d, valor AS v FROM bank_transactions
                         WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
                           AND data_transacao BETWEEN %s AND %s
                         ORDER BY data_transacao, id""",
                        list(fs) + [ini - janela, fim + timedelta(days=_JANELA_PIX)])
                    pix = [{'id': r['id'], 'd': r['d'], 'v': round(float(r['v']), 2)}
                           for r in cur.fetchall()]
                casados = _casar_pix({d: round(float(r['repasse']), 2)
                                      for d, r in dias.items()}, pix)
                for d, r in dias.items():
                    ps = casados.get(d)
                    pago = max(p['d'] for p in ps) if ps else None
                    rd, ok = entra(pago, d + timedelta(days=2), d)
                    if ok:
                        c[rd.isoformat()][d.isoformat()] += float(r['venda'] or 0)
                cur.execute("SELECT MIN(DATE(dt_abastecimento)) AS d FROM cartao_baratao_cupons")
                d0 = (cur.fetchone() or {}).get('d')
            else:
                sb, sf = _sipag_da_bandeira(b.get('nome'), b.get('tipo'))
                if not sb or not sf:
                    continue
                d0 = _sipag_desde(cur, sb, sf, vinculos_map.get(b['id'], []))
                cur.execute("""
                    SELECT DATE(dt_transacao) AS v, bruto AS valor,
                           dt_pagamento AS pago, dt_prevista AS prev
                      FROM cartao_sipag_transacoes
                     WHERE bandeira=%s AND forma=%s AND nsu <> '0'
                       AND (dt_pagamento BETWEEN %s AND %s
                            OR (dt_transacao >= %s AND dt_transacao < %s))""",
                    (sb, sf, ini, fim, ini, fim1))
                for r in cur.fetchall():
                    rd, ok = entra(r['pago'], r['prev'], r['v'])
                    # antes de a SIPAG assumir, o pagamento e de teste
                    if ok and not (d0 and rd < d0):
                        c[rd.isoformat()][r['v'].isoformat()] += float(r['valor'] or 0)
                # antes da SIPAG a maquininha era do Sicredi: o credito do
                # extrato desse tempo e dele, e o "desde" recua junto
                sic = _sicredi_antes(cur, sb, sf, d0,
                                     'dt_pagamento BETWEEN %s AND %s OR '
                                     '(dt_transacao >= %s AND dt_transacao < %s)',
                                     (ini, fim, ini, fim1))
                for r in sic:
                    v = r['dt_transacao'].date()
                    rd, ok = entra(r['pago'], r['prev'], v)
                    if ok:
                        c[rd.isoformat()][v.isoformat()] += float(r['bruto'] or 0)
                if d0:
                    try:
                        cur.execute("SELECT MIN(DATE(dt_transacao)) AS d FROM cartao_sicredi_transacoes "
                                    "WHERE bandeira=%s AND forma=%s AND status='Aprovada' "
                                    "AND dt_transacao < %s", (sb, sf, d0))
                        d0 = (cur.fetchone() or {}).get('d') or d0
                    except Exception:
                        pass                # tabela ainda nao existe
            if d0 is None and not c:
                continue
            copia = dict(b)
            copia['saldo_anterior'] = 0.0
            copia['saldo_anterior_data'] = None
            if copia.get('taxa_contratada') is None and OPERADORAS[op].get('taxa'):
                copia['taxa_contratada'] = OPERADORAS[op]['taxa']
            saida_band.append(copia)
            if d0:
                desde[b['id']] = d0
            ciclos[b['id']] = {rd: {sd: round(v, 2) for sd, v in vs.items()}
                               for rd, vs in c.items()}
    finally:
        cur.close()
    return saida_band, desde, ciclos


def pagamentos_operadora(conn, bandeiras, vinculos_map, desde, data_inicio, data_fim):
    """A aba Operadora: {bandeira_id: {...}}, pela DATA DA VENDA.

    Na ordem que o usuario confere: 1o a venda do periodo (a mesma do Excel
    filtrado pelo mes), 2o quando a operadora a pagou, 3o o extrato provando
    que caiu. A taxa e a do arquivo (vendido - liquido) e so do que ja foi
    pago; o que nao foi pago nao e taxa, vai para "a receber".

    A primeira versao tomava o periodo pela data do PAGAMENTO: a X7 de
    ago/2026 dava 2.698,05 -- duas vendas de julho pagas em agosto --, contra
    2.465,58 vendidos em agosto no Excel.

        pagamentos: [{data, vendas, n, vendido, taxa, liquido, total_dia,
                      outras, abatimentos, extrato, n_creditos, status, itens}]
            vendido/taxa/liquido sao das vendas DO PERIODO pagas naquele
            dia; total_dia e o que a operadora pagou no dia inteiro (com
            venda de fora do periodo: "outras"), e e ele que se confere com
            o extrato. itens: as vendas, uma a uma.
        a_receber: [{dt, data_venda, previsto, vendido, desc}]  -- uma a uma
        por_venda: {data_venda: {vendido, liquido, pago_em}}
    """
    ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
    fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
    fim1 = fim + timedelta(days=1)
    saida = {}
    cur = conn.cursor(dictionary=True)

    def item(dt, pago, prev, vendido, taxa, liquido, desc, ref=None, cols=None):
        dt = dt if isinstance(dt, datetime) else datetime.combine(dt, datetime.min.time())
        return {'dt': dt, 'venda': dt.date(), 'pago': pago, 'prev': prev,
                'vendido': round(vendido, 2), 'taxa': round(taxa, 2),
                'liquido': round(liquido, 2), 'desc': desc, 'ref': ref, 'cupom': None,
                'cols': cols or []}

    # o que e cada pedaco do "desc", coluna a coluna, na lista das vendas
    cabecalhos = {'X7': ['Cliente', 'NF-e', 'Desconto do lote'],
                  'BARATAO': ['Produto', 'Litros', 'Frentista', 'Cupom Baratão'],
                  'SIPAG': ['Cartão', 'Final', 'Autorização']}

    # o cupom (NFC-e) de cada venda, casado em utils/cartao_cupom; "sem
    # cupom" so a partir de quando ha cupom no sistema
    try:
        from utils import cartao_cupom
        cur.execute("SELECT MIN(dh_emissao) AS m FROM vendas_xml")
        cupom_desde = (cur.fetchone() or {}).get('m')
    except Exception:
        cartao_cupom, cupom_desde = None, None

    try:
        for b in bandeiras:
            op = _operadora_de(b.get('nome'), b.get('tipo'))
            if not op:
                continue
            fs = vinculos_map.get(b['id'], [])
            itens = []
            total_dia = {}       # pago_em -> liquido pago no dia inteiro
            abat_dia = defaultdict(float)
            if op == 'X7':
                cur.execute("""
                    SELECT id, dt_operacao, bruto, desconto_lote, taxa_pct, cliente, nfe,
                           cod_transacao, dt_liquidacao AS pago, dt_previsao AS prev
                      FROM cartao_arquivo_vendas
                     WHERE operadora='X7' AND dt_operacao >= %s AND dt_operacao < %s
                     ORDER BY dt_operacao""", (ini, fim1))
                for r in cur.fetchall():
                    vd = float(r['bruto'] or 0) - float(r['desconto_lote'] or 0)
                    tx = round(vd * float(r['taxa_pct'] or 0) / 100, 2)
                    desc = ' · '.join(x for x in (
                        r['cliente'], ('NF-e %s' % r['nfe']) if r['nfe'] else '',
                        ('desconto %s' % _fmt_br(r['desconto_lote'])) if r['desconto_lote'] else '') if x)
                    itens.append(item(r['dt_operacao'], r['pago'], r['prev'], vd, tx, vd - tx, desc, r['id'],
                                      [r['cliente'] or '', r['nfe'] or '',
                                       _fmt_br(r['desconto_lote']) if r['desconto_lote'] else '']))
                dias = sorted({i['pago'] for i in itens if i['pago']})
                if dias:
                    ph = ','.join(['%s'] * len(dias))
                    cur.execute(f"""
                        SELECT dt_liquidacao AS d, SUM(liquido) AS l, SUM(taxas) AS t,
                               SUM(bruto - descontos) AS b
                          FROM cartao_arquivo_lotes
                         WHERE operadora='X7' AND dt_liquidacao IN ({ph})
                         GROUP BY dt_liquidacao""", dias)
                    lotes = {r['d']: r for r in cur.fetchall()}
                    total_dia = {d: float(r['l'] or 0) for d, r in lotes.items()}
                    # A taxa da X7 e do lote: quando o dia so tem venda do
                    # periodo, vale a do lote (o centavo de arredondamento
                    # vai na ultima venda do dia).
                    por_dia = defaultdict(list)
                    for it in itens:
                        if it['pago']:
                            por_dia[it['pago']].append(it)
                    for d, its in por_dia.items():
                        lt = lotes.get(d)
                        if lt and abs(sum(i['vendido'] for i in its) - float(lt['b'] or 0)) < _TOL:
                            dif = round(float(lt['t'] or 0) - sum(i['taxa'] for i in its), 2)
                            if abs(dif) > 0.0049:
                                its[-1]['taxa'] = round(its[-1]['taxa'] + dif, 2)
                                its[-1]['liquido'] = round(its[-1]['liquido'] - dif, 2)
            elif op == 'BARATAO':
                # o pagamento e por dia (um PIX por dia de abastecimento);
                # a venda, por cupom
                janela = timedelta(days=_JANELA_PIX * 2)
                cur.execute("""
                    SELECT DATE(dt_abastecimento) AS d, SUM(repasse) AS repasse
                      FROM cartao_baratao_cupons
                     WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
                     GROUP BY DATE(dt_abastecimento)""",
                    (ini - janela, fim1 + timedelta(days=_JANELA_PIX)))
                dias = {r['d']: float(r['repasse'] or 0) for r in cur.fetchall()}
                pix = []
                if fs:
                    ph = ','.join(['%s'] * len(fs))
                    cur.execute(f"""
                        SELECT id, data_transacao AS d, valor AS v FROM bank_transactions
                         WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
                           AND data_transacao BETWEEN %s AND %s
                         ORDER BY data_transacao, id""",
                        list(fs) + [ini - janela, fim + janela])
                    pix = [{'id': r['id'], 'd': r['d'], 'v': round(float(r['v']), 2)}
                           for r in cur.fetchall()]
                casados = _casar_pix({d: round(v, 2) for d, v in dias.items()}, pix)
                pago_do_dia = {}
                for d, v in dias.items():
                    ps = casados.get(d)
                    if ps:
                        pago_do_dia[d] = max(p['d'] for p in ps)
                        total_dia[pago_do_dia[d]] = total_dia.get(pago_do_dia[d], 0.0) + v
                cur.execute("""
                    SELECT id, dt_abastecimento, cupom, frentista, produto, litros,
                           bruto - desconto AS venda, taxa, repasse
                      FROM cartao_baratao_cupons
                     WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
                     ORDER BY dt_abastecimento""", (ini, fim1))
                for r in cur.fetchall():
                    d = r['dt_abastecimento'].date()
                    desc = ' · '.join(x for x in (
                        r['produto'], ('%s L' % _fmt_br(r['litros'], 0)) if r['litros'] else '',
                        r['frentista'], 'cupom %s' % r['cupom'][-8:]) if x)
                    itens.append(item(r['dt_abastecimento'], pago_do_dia.get(d),
                                      d + timedelta(days=2), float(r['venda'] or 0),
                                      float(r['taxa'] or 0), float(r['repasse'] or 0), desc, r['id'],
                                      [r['produto'] or '', _fmt_br(r['litros'], 0) if r['litros'] else '',
                                       r['frentista'] or '', r['cupom'][-8:]]))
            else:
                sb, sf = _sipag_da_bandeira(b.get('nome'), b.get('tipo'))
                if not sb or not sf:
                    continue
                cur.execute("""
                    SELECT id, dt_transacao, bruto, desconto_pago, liquido_pago, desconto_venda,
                           liquido_venda, tipo_cartao, cartao, autorizacao,
                           dt_pagamento AS pago, dt_prevista AS prev
                      FROM cartao_sipag_transacoes
                     WHERE bandeira=%s AND forma=%s AND nsu <> '0'
                       AND arq_realizadas IS NOT NULL
                       AND dt_transacao >= %s AND dt_transacao < %s
                     ORDER BY dt_transacao""", (sb, sf, ini, fim1))
                for r in cur.fetchall():
                    pago = r['pago']
                    tx = r['desconto_pago'] if pago else r['desconto_venda']
                    lq = r['liquido_pago'] if pago else r['liquido_venda']
                    desc = ' · '.join(x for x in (
                        (r['tipo_cartao'] or '').strip(),
                        ('final %s' % r['cartao'][-4:]) if r['cartao'] else '',
                        ('aut. %s' % r['autorizacao']) if r['autorizacao'] else '') if x)
                    itens.append(item(r['dt_transacao'], pago, r['prev'], float(r['bruto'] or 0),
                                      float(tx or 0), float(lq or 0), desc, r['id'],
                                      [(r['tipo_cartao'] or '').strip(), r['cartao'][-4:] if r['cartao'] else '',
                                       r['autorizacao'] or '']))
                # o Sicredi, antes de a SIPAG assumir: mesma bandeira, mesmas
                # colunas; a taxa e o MDR da propria venda
                sic_ate = _sipag_desde(cur, sb, sf, fs)
                for r in _sicredi_antes(cur, sb, sf, sic_ate,
                                        'dt_transacao >= %s AND dt_transacao < %s', (ini, fim1)):
                    desc = ' · '.join(x for x in (
                        r['produto'] or '', ('final %s' % r['cartao'][-4:]) if r['cartao'] else '',
                        ('aut. %s' % r['autorizacao']) if r['autorizacao'] else '') if x)
                    it = item(r['dt_transacao'], r['pago'], r['prev'], float(r['bruto'] or 0),
                              float(r['taxa'] or 0), float(r['liquido'] or 0), desc, r['id'],
                              [r['produto'] or '', r['cartao'][-4:] if r['cartao'] else '',
                               r['autorizacao'] or ''])
                    it['op'], it['operadora'] = 'SICREDI', OPERADORAS['SICREDI']['nome']
                    itens.append(it)
                dias = sorted({i['pago'] for i in itens if i['pago']})
                if dias:
                    ph = ','.join(['%s'] * len(dias))
                    cur.execute(f"""
                        SELECT dt_pagamento AS d, SUM(liquido_pago) AS l,
                               SUM(CASE WHEN nsu = '0' THEN liquido_pago ELSE 0 END) AS ab
                          FROM cartao_sipag_transacoes
                         WHERE bandeira=%s AND forma=%s AND dt_pagamento IN ({ph})
                         GROUP BY dt_pagamento""", [sb, sf] + dias)
                    for r in cur.fetchall():
                        total_dia[r['d']] = float(r['l'] or 0)
                        abat_dia[r['d']] = -float(r['ab'] or 0)
                    # o Sicredi do dia inteiro (com venda de fora do periodo)
                    sic_dias = sorted({i['pago'] for i in itens
                                       if i['pago'] and i.get('op') == 'SICREDI'})
                    if sic_dias:
                        pd = ','.join(['%s'] * len(sic_dias))
                        cur.execute(f'''
                            SELECT dt_pagamento AS d, SUM(liquido) AS l
                              FROM cartao_sicredi_transacoes
                             WHERE bandeira=%s AND forma=%s AND status='Aprovada'
                               AND dt_pagamento IN ({pd})
                             GROUP BY dt_pagamento''', [sb, sf] + sic_dias)
                        for r in cur.fetchall():
                            total_dia[r['d']] = total_dia.get(r['d'], 0.0) + float(r['l'] or 0)

            if cartao_cupom and itens:
                cps = {}
                for o_ in {i.get('op', op) for i in itens}:
                    try:
                        cps[o_] = cartao_cupom.cupons_das_vendas(
                            conn, o_, [i['ref'] for i in itens if i['ref'] and i.get('op', op) == o_])
                    except Exception:
                        cps[o_] = {}
                for it in itens:
                    it['cupom'] = cps.get(it.get('op', op), {}).get(it['ref'])
                    it['sem_cupom'] = (not it['cupom'] and cupom_desde is not None
                                       and it['dt'] >= cupom_desde)

            # o extrato de cada dia de pagamento (pode ser depois do periodo)
            dias_pag = sorted({i['pago'] for i in itens if i['pago']})
            extrato, bancos, ult_extrato = {}, {}, None
            if fs:
                ph = ','.join(['%s'] * len(fs))
                if dias_pag:
                    pd = ','.join(['%s'] * len(dias_pag))
                    cur.execute(f"""
                        SELECT bt.data_transacao AS d, SUM(bt.valor) AS v, COUNT(*) AS n,
                               GROUP_CONCAT(DISTINCT COALESCE(NULLIF(ba.apelido,''), ba.banco_nome)
                                            ORDER BY 1 SEPARATOR ' + ') AS bancos
                          FROM bank_transactions bt
                          JOIN bank_accounts ba ON ba.id = bt.account_id
                         WHERE bt.tipo='CREDIT' AND bt.forma_recebimento_id IN ({ph})
                           AND bt.data_transacao IN ({pd})
                         GROUP BY bt.data_transacao""", list(fs) + dias_pag)
                    _rs = cur.fetchall()
                    extrato = {r['d']: (float(r['v'] or 0), int(r['n'])) for r in _rs}
                    bancos = {r['d']: r['bancos'] or '' for r in _rs}
                cur.execute(f"""
                    SELECT MAX(data_transacao) AS m FROM bank_transactions
                     WHERE account_id IN (SELECT DISTINCT account_id FROM bank_transactions
                                           WHERE forma_recebimento_id IN ({ph}))""", list(fs))
                ult_extrato = (cur.fetchone() or {}).get('m')

            pag = defaultdict(list)
            a_receber = []
            por_venda = defaultdict(lambda: {'vendido': 0.0, 'liquido': 0.0, 'pago_em': None})
            for it in itens:
                pv = por_venda[it['venda']]
                pv['vendido'] += it['vendido']
                if it['pago']:
                    pag[it['pago']].append(it)
                    pv['liquido'] += it['liquido']
                    pv['pago_em'] = max(pv['pago_em'] or it['pago'], it['pago'])
                else:
                    a_receber.append(it)

            linhas = []
            for d in sorted(pag):
                its = pag[d]
                liq = round(sum(i['liquido'] for i in its), 2)
                tot = round(total_dia.get(d, liq), 2)
                ext, n = extrato.get(d, (0.0, 0))
                if not n and ult_extrato and d > ult_extrato:
                    st = 'aguardando'
                elif n and abs(ext - tot) < _TOL_CENTAVOS:
                    st = 'ok'
                else:
                    st = 'diverge'
                linhas.append({
                    'data': d, 'vendas': sorted({i['venda'] for i in its}), 'n': len(its),
                    'vendido': round(sum(i['vendido'] for i in its), 2),
                    'taxa': round(sum(i['taxa'] for i in its), 2),
                    'liquido': liq, 'total_dia': tot,
                    'outras': round(tot - liq + abat_dia.get(d, 0.0), 2),
                    'abatimentos': round(abat_dia.get(d, 0.0), 2),
                    'extrato': round(ext, 2), 'n_creditos': n, 'banco': bancos.get(d, ''),
                    'dif': round(ext - tot, 2), 'status': st,
                    'itens': sorted(its, key=lambda i: i['dt']),
                })
            vendido = sum(i['vendido'] for i in itens)
            vendido_pago = sum(x['vendido'] for x in linhas)
            taxa = sum(x['taxa'] for x in linhas)
            nomes = sorted({i.get('operadora') or OPERADORAS[op]['nome'] for i in itens})
            saida[b['id']] = {
                'operadora': ' + '.join(nomes) if nomes else OPERADORAS[op]['nome'],
                'cab': cabecalhos['SIPAG' if op not in cabecalhos else op],
                'pagamentos': linhas,
                'a_receber': sorted(a_receber, key=lambda i: i['dt']),
                'por_venda': dict(por_venda),
                'n_vendas': len(itens),
                'n_com_cupom': sum(1 for i in itens if i.get('cupom')),
                'n_sem_cupom': sum(1 for i in itens if i.get('sem_cupom')),
                'vendido': round(vendido, 2),
                'vendido_pago': round(vendido_pago, 2),
                'taxa': round(taxa, 2),
                'taxa_pct': (taxa / vendido_pago * 100) if vendido_pago else None,
                'abatimentos': round(sum(x['abatimentos'] for x in linhas), 2),
                'liquido': round(sum(x['liquido'] for x in linhas), 2),
                'total_receber': round(sum(i['vendido'] for i in a_receber), 2),
                'n_ok': sum(1 for x in linhas if x['status'] == 'ok'),
                'n_aguardando': sum(1 for x in linhas if x['status'] == 'aguardando'),
                'n_problema': sum(1 for x in linhas if x['status'] == 'diverge'),
                'contrato': (float(b['taxa_contratada']) if b.get('taxa_contratada') is not None
                             else OPERADORAS[op].get('taxa')),
            }
    finally:
        cur.close()
    return saida


def _fmt_br(v, casas=2):
    """1234.5 -> '1.234,50' (so para o texto da venda)."""
    s = ('{:,.%df}' % casas).format(float(v or 0))
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


# ── Sicredi (a maquininha antes da SIPAG) ─────────────────────────────────────
#
# Ate 13/07/2026 as maquininhas eram do Sicredi; a SIPAG assumiu em ~15/07.
# O portal do Sicredi exporta o "Relatorio de vendas detalhado" (.xlsx), uma
# transacao por linha, com a taxa (MDR) e a Data efetiva do pagamento -- o
# mesmo papel dos dois relatorios da SIPAG num arquivo so. As bandeiras do
# cadastro sao as mesmas (VISA, MASTERCARD, ELO...): na aba Operadora a venda
# do Sicredi entra na bandeira, antes do dia em que a SIPAG assumiu.
# Jan-jul/2026: credito 0,85% e debito 0,80%, todas as bandeiras, pago D+1.
#
# O mesmo arquivo traz o PIX da maquininha ("Via QRCODE"); fica gravado, mas
# nao e cartao e nao entra na conferencia.

#: bandeira do Sicredi -> como a SIPAG (e o cadastro) escreve
_SICREDI_BANDEIRA = {'VISA': 'Visa', 'MASTERCARD': 'Mastercard', 'MDS': 'Mastercard',
                     'ELO FULL': 'Elo', 'ELO': 'Elo', 'AMEX FULL': 'Amex',
                     'AMEX': 'Amex', 'CABAL': 'Cabal'}


def ler_sicredi(conteudo):
    """As transacoes do "Relatorio de vendas detalhado" do Sicredi (.xlsx)."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    linhas = list(wb.worksheets[0].iter_rows(values_only=True))
    if not linhas or 'vendas detalhado' not in str(linhas[0][0] or '').lower():
        raise ValueError('nao parece um relatorio do Sicredi: falta o '
                         '"Relatório de vendas detalhado" na 1a linha')
    try:
        i = next(k for k, r in enumerate(linhas) if r and r[0] == 'Data da venda')
    except StopIteration:
        raise ValueError('relatorio do Sicredi sem a linha de cabecalho')
    cab = [str(c or '').strip() for c in linhas[i]]

    def t(r, nome):
        v = r[cab.index(nome)] if nome in cab else None
        v = str(v).strip() if v is not None else ''
        return '' if v == '-' else v

    def n(r, nome):
        v = r[cab.index(nome)] if nome in cab else None
        return float(v) if isinstance(v, (int, float)) else _num(str(v or ''))

    saida, vistos = [], defaultdict(int)
    for r in linhas[i + 1:]:
        if not r or not r[0] or str(r[0]).startswith('Total'):
            continue
        dt = datetime.strptime('%s %s' % (t(r, 'Data da venda'), t(r, 'Hora da venda')),
                               '%d/%m/%Y %H:%M:%S')
        mod = t(r, 'Modalidade')
        band = t(r, 'Bandeira')
        x = {
            'dt_transacao': dt,
            'autorizacao': t(r, 'Código de autorização')[:40],
            'estabelecimento': t(r, 'Código do estabelecimento'),
            'modalidade': mod, 'produto': t(r, 'Produto'),
            'bandeira_sicredi': band,
            'bandeira': _SICREDI_BANDEIRA.get(_sem_acento(band).upper(), band),
            'forma': mod if mod in ('Crédito', 'Débito') else None,
            'canal': t(r, 'Canal'),
            'bruto': n(r, 'Valor bruto transação'),
            'bruto_parcela': n(r, 'Valor bruto da parcela'),
            'taxa': n(r, 'Valor da taxa (MDR)'),
            'liquido': n(r, 'Valor líquido da parcela/transação'),
            'status': t(r, 'Status'),
            'terminal': t(r, 'Número do terminal'),
            'comprovante': t(r, 'Comprovante de venda'),
            'pedido': t(r, 'Código do pedido'),
            'cartao': t(r, 'Número do cartão'),
            'dt_prevista': _data(t(r, 'Data prevista pagamento da venda')),
            'dt_pagamento': _data(t(r, 'Data efetiva do pagamento da venda')),
            'cod_pagamento': t(r, 'Código do pagamento'),
            'tipo_cartao': t(r, 'Tipo de cartão'),
        }
        # Nao ha um numero unico em toda linha (a recusada nao tem pedido);
        # terminal + comprovante + hora + valor separa, e a ordem de aparicao
        # desempata linha repetida.
        base = '|'.join(str(x[k]) for k in ('dt_transacao', 'terminal', 'comprovante',
                                            'autorizacao', 'bruto', 'status'))
        vistos[base] += 1
        x['chave'] = hashlib.sha1(('%s|%d' % (base, vistos[base])).encode('utf-8')).hexdigest()
        saida.append(x)
    if not saida:
        raise ValueError('relatorio do Sicredi sem nenhuma transacao')
    return saida


_COLS_SICREDI = ('chave', 'dt_transacao', 'autorizacao', 'estabelecimento', 'modalidade',
                 'produto', 'bandeira_sicredi', 'bandeira', 'forma', 'canal', 'bruto',
                 'bruto_parcela', 'taxa', 'liquido', 'status', 'terminal', 'comprovante',
                 'pedido', 'cartao', 'dt_prevista', 'dt_pagamento', 'cod_pagamento',
                 'tipo_cartao')


def ensure_tables_sicredi(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cartao_sicredi_transacoes (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            chave            CHAR(40)     NOT NULL,
            dt_transacao     DATETIME     NOT NULL,
            autorizacao      VARCHAR(40)  NULL,
            estabelecimento  VARCHAR(20)  NULL,
            modalidade       VARCHAR(30)  NULL,
            produto          VARCHAR(30)  NULL,
            bandeira_sicredi VARCHAR(30)  NULL,
            bandeira         VARCHAR(30)  NULL,
            forma            VARCHAR(20)  NULL,
            canal            VARCHAR(20)  NULL,
            bruto            DECIMAL(12,2) NOT NULL DEFAULT 0,
            bruto_parcela    DECIMAL(12,2) NOT NULL DEFAULT 0,
            taxa             DECIMAL(12,2) NOT NULL DEFAULT 0,
            liquido          DECIMAL(12,2) NOT NULL DEFAULT 0,
            status           VARCHAR(20)  NULL,
            terminal         VARCHAR(20)  NULL,
            comprovante      VARCHAR(20)  NULL,
            pedido           VARCHAR(30)  NULL,
            cartao           VARCHAR(30)  NULL,
            dt_prevista      DATE         NULL,
            dt_pagamento     DATE         NULL,
            cod_pagamento    VARCHAR(30)  NULL,
            tipo_cartao      VARCHAR(20)  NULL,
            arquivo          VARCHAR(200) NULL,
            atualizado_em    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_chave (chave),
            KEY ix_tr (dt_transacao),
            KEY ix_pg (dt_pagamento),
            KEY ix_band (bandeira, forma)
        )""")
    conn.commit()
    cur.close()


def gravar_sicredi(conn, arquivo, linhas):
    cols = _COLS_SICREDI + ('arquivo',)
    sql = ('INSERT INTO cartao_sicredi_transacoes (%s) VALUES (%s) '
           'ON DUPLICATE KEY UPDATE %s' % (
               ', '.join(cols), ', '.join(['%s'] * len(cols)),
               ', '.join('%s=VALUES(%s)' % (c, c) for c in cols if c != 'chave')))
    cur = conn.cursor()
    cur.executemany(sql, [tuple(x[k] for k in _COLS_SICREDI) + (arquivo[:200],)
                          for x in linhas])
    conn.commit()
    cur.close()


def _sicredi_antes(cur, sb, sf, ate, onde, params):
    """As vendas de cartao aprovadas do Sicredi para a bandeira, antes de
    `ate` (o dia em que a SIPAG assumiu; None = todas) e no recorte `onde`.
    Sem a tabela, nada."""
    try:
        cur.execute(f"""
            SELECT id, dt_transacao, bruto, taxa, liquido, produto, cartao, autorizacao,
                   dt_pagamento AS pago, dt_prevista AS prev
              FROM cartao_sicredi_transacoes
             WHERE bandeira=%s AND forma=%s AND status='Aprovada'
               AND (%s IS NULL OR dt_transacao < %s) AND ({onde})
             ORDER BY dt_transacao""", [sb, sf, ate, ate] + list(params))
    except Exception:
        return []                       # tabela ainda nao existe
    return cur.fetchall()


# ── Conferir um dia de deposito ───────────────────────────────────────────────
#
# A tela pergunta por UM dia de deposito: o que cada planilha (SIPAG, X7,
# Baratao) diz que pagou naquele dia x o que caiu no banco, cartao a cartao.
# Quando nao bate, procura a causa na ordem da mais comum para a mais rara e
# escreve em portugues; so le, nao grava nada.

#: Ate quantos dias para cada lado se procura o dinheiro que "caiu em outro dia".
_VIZINHO_DIAS = 4


def _planilha_dia(cur, op, b, dia):
    """{n, vendido, taxa, abatimentos, liquido, vendas: [...]} do que a planilha
    da operadora diz que pagou em `dia` para a bandeira; None se nada."""
    vendas = []
    if op == 'SIPAG':
        sb, sf = _sipag_da_bandeira(b.get('nome'), b.get('tipo'))
        if not sb or not sf:
            return None
        cur.execute("""
            SELECT dt_transacao, nsu, bruto, desconto_pago, liquido_pago, cartao,
                   autorizacao, tipo_cartao
              FROM cartao_sipag_transacoes
             WHERE bandeira=%s AND forma=%s AND dt_pagamento=%s
             ORDER BY dt_transacao""", (sb, sf, dia))
        for r in cur.fetchall():
            abat = r['nsu'] == '0'
            vendas.append({
                'dt': r['dt_transacao'], 'abat': abat,
                'vendido': 0.0 if abat else float(r['bruto'] or 0),
                'taxa': float(r['desconto_pago'] or 0),
                'liquido': float(r['liquido_pago'] or 0),
                'desc': ('abatimento (aluguel/estorno)' if abat else ' · '.join(x for x in (
                    (r['tipo_cartao'] or '').strip(),
                    ('final %s' % r['cartao'][-4:]) if r['cartao'] else '',
                    ('aut. %s' % r['autorizacao']) if r['autorizacao'] else '') if x))})
        # o Sicredi, antes de a SIPAG assumir a bandeira
        try:
            cur.execute("""
                SELECT dt_transacao, bruto, taxa, liquido, cartao, produto
                  FROM cartao_sicredi_transacoes
                 WHERE bandeira=%s AND forma=%s AND status='Aprovada' AND dt_pagamento=%s
                 ORDER BY dt_transacao""", (sb, sf, dia))
            for r in cur.fetchall():
                vendas.append({
                    'dt': r['dt_transacao'], 'abat': False,
                    'vendido': float(r['bruto'] or 0), 'taxa': float(r['taxa'] or 0),
                    'liquido': float(r['liquido'] or 0),
                    'desc': ' · '.join(x for x in (
                        'Sicredi', r['produto'] or '',
                        ('final %s' % r['cartao'][-4:]) if r['cartao'] else '') if x)})
        except Exception:
            pass                        # tabela do Sicredi ainda nao existe
    elif op == 'X7':
        cur.execute("""
            SELECT dt_operacao, bruto, desconto_lote, taxa_pct, cliente, nfe
              FROM cartao_arquivo_vendas
             WHERE operadora='X7' AND dt_liquidacao=%s ORDER BY dt_operacao""", (dia,))
        for r in cur.fetchall():
            vd = float(r['bruto'] or 0) - float(r['desconto_lote'] or 0)
            tx = round(vd * float(r['taxa_pct'] or 0) / 100, 2)
            vendas.append({'dt': r['dt_operacao'], 'abat': False, 'vendido': vd,
                           'taxa': tx, 'liquido': vd - tx,
                           'desc': ' · '.join(x for x in (
                               r['cliente'], ('NF-e %s' % r['nfe']) if r['nfe'] else '') if x)})
        # o liquido que vale e o do lote (a taxa da X7 e arredondada no lote)
        cur.execute("""
            SELECT SUM(qtd) AS n, SUM(bruto - descontos) AS vd, SUM(taxas) AS tx,
                   SUM(liquido) AS lq, COUNT(*) AS lotes
              FROM cartao_arquivo_lotes WHERE operadora='X7' AND dt_liquidacao=%s""", (dia,))
        lt = cur.fetchone() or {}
        if not lt.get('lotes'):
            return None
        return {'n': int(lt['n'] or 0), 'vendido': round(float(lt['vd'] or 0), 2),
                'taxa': round(float(lt['tx'] or 0), 2), 'abatimentos': 0.0,
                'liquido': round(float(lt['lq'] or 0), 2), 'vendas': vendas}
    if not vendas:
        return None
    return {'n': sum(1 for v in vendas if not v['abat']),
            'vendido': round(sum(v['vendido'] for v in vendas), 2),
            'taxa': round(sum(v['taxa'] for v in vendas if not v['abat']), 2),
            'abatimentos': round(sum(v['liquido'] for v in vendas if v['abat']), 2),
            'liquido': round(sum(v['liquido'] for v in vendas), 2),
            'vendas': vendas}


def _baratao_dia(cur, fs, dia):
    """O que "a planilha pagou" do Baratao em `dia`. Ele paga um PIX por dia de
    abastecimento, entao sao os dias de abastecimento cujo PIX caiu nele -- o
    mesmo _casar_pix da Auditoria."""
    janela = timedelta(days=_JANELA_PIX * 2)
    cur.execute("""
        SELECT DATE(dt_abastecimento) AS d, SUM(repasse) AS v
          FROM cartao_baratao_cupons
         WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
         GROUP BY DATE(dt_abastecimento)""", (dia - janela, dia + timedelta(days=1)))
    dias = {r['d']: round(float(r['v'] or 0), 2) for r in cur.fetchall()}
    pix = []
    if fs:
        ph = ','.join(['%s'] * len(fs))
        cur.execute(f"""
            SELECT id, data_transacao AS d, valor AS v FROM bank_transactions
             WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
               AND data_transacao BETWEEN %s AND %s ORDER BY data_transacao, id""",
            list(fs) + [dia - janela, dia + timedelta(days=_JANELA_PIX)])
        pix = [{'id': r['id'], 'd': r['d'], 'v': round(float(r['v']), 2)} for r in cur.fetchall()]
    casados = _casar_pix(dias, pix)
    pagos = sorted(d for d, ps in casados.items() if any(p['d'] == dia for p in ps))
    if not pagos:
        return None
    cur.execute("""
        SELECT dt_abastecimento, cupom, produto, litros, frentista,
               bruto - desconto AS venda, taxa, repasse
          FROM cartao_baratao_cupons
         WHERE dt_abastecimento >= %s AND dt_abastecimento < %s
         ORDER BY dt_abastecimento""", (min(pagos), max(pagos) + timedelta(days=1)))
    vendas = [{'dt': r['dt_abastecimento'], 'abat': False,
               'vendido': float(r['venda'] or 0), 'taxa': float(r['taxa'] or 0),
               'liquido': float(r['repasse'] or 0),
               'desc': ' · '.join(x for x in (
                   r['produto'], ('%s L' % _fmt_br(r['litros'], 0)) if r['litros'] else '',
                   r['frentista'], 'cupom %s' % (r['cupom'] or '')[-8:]) if x)}
              for r in cur.fetchall() if r['dt_abastecimento'].date() in pagos]
    return {'n': len(vendas), 'vendido': round(sum(v['vendido'] for v in vendas), 2),
            'taxa': round(sum(v['taxa'] for v in vendas), 2), 'abatimentos': 0.0,
            'liquido': round(sum(dias[d] for d in pagos), 2), 'vendas': vendas,
            'dias_abastecimento': pagos}


def _cobertura(cur):
    """Ate que dia cada planilha chegou, e a ultima importacao de cada uma
    (com o erro, e quantas falharam seguidas)."""
    cob = {}
    cur.execute("SELECT MAX(dt_pagamento) AS m FROM cartao_sipag_transacoes")
    cob['SIPAG'] = (cur.fetchone() or {}).get('m')
    cur.execute("SELECT MAX(dt_liquidacao) AS m FROM cartao_arquivo_lotes WHERE operadora='X7'")
    cob['X7'] = (cur.fetchone() or {}).get('m')
    cur.execute("SELECT MAX(dt_abastecimento) AS m FROM cartao_baratao_cupons")
    m = (cur.fetchone() or {}).get('m')
    cob['BARATAO'] = m.date() if isinstance(m, datetime) else m
    imp = {}
    for op in ('SIPAG', 'X7', 'BARATAO'):
        # da SIPAG, quem diz o que foi pago e o relatorio de recebidas
        cur.execute("""
            SELECT arquivo, importado_em, erro FROM cartao_arquivo_importacoes
             WHERE operadora=%s AND (%s <> 'SIPAG' OR arquivo LIKE '%%recebidas%%')
             ORDER BY id DESC LIMIT 10""", (op, op))
        rs = cur.fetchall()
        falhas = 0
        for r in rs:
            if not r['erro']:
                break
            falhas += 1
        imp[op] = {'ultima': rs[0] if rs else None, 'falhas': falhas,
                   'primeira_falha': rs[falhas - 1] if falhas else None}
    return cob, imp


def _quando(dt):
    return dt.strftime('%d/%m %H:%M') if dt else '—'


def conferir_dia(conn, dia, bandeiras):
    """A conferencia de UM dia de deposito, cartao a cartao.

    bandeiras: as do cadastro, com 'vinculos' (routes.conf_cartoes._get_bandeiras).
    Cada linha traz a planilha, o banco, a diferenca, o status e o "porque"
    em texto; 'soltos' sao creditos de cartao do dia sem cartao ligado."""
    ensure_tables(conn)
    ensure_tables_sipag(conn)
    cur = conn.cursor(dictionary=True)
    try:
        cob, imp = _cobertura(cur)
        todas_formas = sorted({v['forma_recebimento_id'] for b in bandeiras
                               for v in b.get('vinculos', [])})
        _, ult_extrato = _ate_onde(conn, todas_formas)
        linhas = []
        for b in bandeiras:
            op = _operadora_de(b.get('nome'), b.get('tipo'))
            if not op:
                continue
            fs = [v['forma_recebimento_id'] for v in b.get('vinculos', [])]
            banco = []
            if fs:
                ph = ','.join(['%s'] * len(fs))
                cur.execute(f"""
                    SELECT bt.id, bt.valor, bt.descricao,
                           COALESCE(NULLIF(ba.apelido,''), ba.banco_nome) AS conta
                      FROM bank_transactions bt JOIN bank_accounts ba ON ba.id = bt.account_id
                     WHERE bt.tipo='CREDIT' AND bt.forma_recebimento_id IN ({ph})
                       AND bt.data_transacao=%s ORDER BY bt.id""", list(fs) + [dia])
                banco = [{'id': r['id'], 'valor': float(r['valor']), 'desc': r['descricao'] or '',
                          'conta': r['conta'] or ''} for r in cur.fetchall()]
            pl = _baratao_dia(cur, fs, dia) if op == 'BARATAO' else _planilha_dia(cur, op, b, dia)
            if not pl and not banco:
                continue
            v_pl = pl['liquido'] if pl else 0.0
            v_banco = round(sum(x['valor'] for x in banco), 2)
            linhas.append({
                'bandeira_id': b['id'], 'nome': b['nome'], 'tipo': (b.get('tipo') or '').upper(),
                'op': op, 'operadora': OPERADORAS[op]['nome'], 'formas': fs,
                'planilha': pl, 'banco': banco, 'v_planilha': round(v_pl, 2),
                'v_banco': v_banco, 'dif': round(v_banco - v_pl, 2), 'porque': ''})

        # 1) o que se explica sozinho: bate, centavos, falta arquivo, falta extrato
        for ln in linhas:
            op, dif = ln['op'], ln['dif']
            cb, im = cob.get(op), imp.get(op) or {}
            if abs(dif) < _TOL:
                ln['status'] = 'ok'
            elif abs(dif) < _TOL_CENTAVOS and ln['planilha'] and ln['banco']:
                ln['status'] = 'centavos'
                ln['porque'] = 'Diferença de %s: arredondamento de centavos.' % _fmt_br(abs(dif))
            elif not ln['planilha'] and (not cb or dia > cb) and im.get('falhas'):
                pf = im['primeira_falha']
                ln['status'] = 'arquivo_erro'
                ln['porque'] = (
                    'A planilha da %s não entrou: %d arquivo(s) seguido(s) deram erro na '
                    'importação, desde "%s" (%s). Erro: %s. A última planilha que entrou '
                    'cobre até %s.' % (ln['operadora'], im['falhas'], pf['arquivo'],
                                       _quando(pf['importado_em']), pf['erro'],
                                       cb.strftime('%d/%m/%Y') if cb else '—'))
            elif not ln['planilha'] and (not cb or dia > cb):
                u = im.get('ultima') or {}
                ln['status'] = 'falta_planilha'
                ln['porque'] = (
                    'A planilha da %s ainda não chegou para esse dia: a última que entrou '
                    '("%s", em %s) cobre até %s. O dinheiro caiu; a conferência fecha quando '
                    'o arquivo novo chegar.' % (ln['operadora'], u.get('arquivo') or '—',
                                                _quando(u.get('importado_em')),
                                                cb.strftime('%d/%m/%Y') if cb else '—'))
            elif ln['planilha'] and not ln['banco'] and ult_extrato and dia > ult_extrato:
                ln['status'] = 'falta_extrato'
                ln['porque'] = ('O extrato do banco ainda não chegou até esse dia (último '
                                'lançamento em %s).' % ult_extrato.strftime('%d/%m/%Y'))
            else:
                ln['status'] = 'diverge'

        # 2) cartao trocado: na mesma operadora, um a mais e outro a menos
        div = [l for l in linhas if l['status'] == 'diverge']
        for a in div:
            for c in div:
                if c is a or c['op'] != a['op'] or a['status'] != 'diverge' \
                        or c['status'] != 'diverge':
                    continue
                if abs(a['dif'] + c['dif']) < _TOL_CENTAVOS:
                    for x, y in ((a, c), (c, a)):
                        x['status'] = 'trocado'
                        x['porque'] = (
                            'Cartão trocado: %s tem %s a %s e %s tem o mesmo valor a %s. O '
                            'dinheiro caiu, mas o lançamento do extrato foi ligado ao cartão '
                            'errado.' % ('%s %s' % (x['nome'], x['tipo'].lower()),
                                         _fmt_br(abs(x['dif'])), 'mais' if x['dif'] > 0 else 'menos',
                                         '%s %s' % (y['nome'], y['tipo'].lower()),
                                         'mais' if y['dif'] > 0 else 'menos'))

        # 3) credito de cartao no extrato do dia que nao esta ligado a cartao nenhum
        cur.execute("""
            SELECT bt.id, bt.valor, bt.descricao, bt.forma_recebimento_id AS f,
                   COALESCE(NULLIF(ba.apelido,''), ba.banco_nome) AS conta
              FROM bank_transactions bt JOIN bank_accounts ba ON ba.id = bt.account_id
             WHERE bt.tipo='CREDIT' AND bt.data_transacao=%s
               AND (bt.descricao LIKE 'SIPAG%%' OR bt.descricao LIKE '%%X7%%'
                    OR bt.descricao LIKE '%%BARAT%%'
                    OR bt.cnpj_cpf LIKE '%%41524064%%' OR bt.cnpj_cpf LIKE '%%45179094%%'
                    OR bt.cnpj_cpf LIKE '%%41.524.064%%' OR bt.cnpj_cpf LIKE '%%45.179.094%%')""",
            (dia,))
        soltos = [{'id': r['id'], 'valor': float(r['valor']), 'desc': r['descricao'] or '',
                   'conta': r['conta'] or '', 'explica': None}
                  for r in cur.fetchall() if r['f'] not in todas_formas]

        # 4) o resto: outro dia, abatimento, credito solto -- ou sem explicacao
        for ln in linhas:
            if ln['status'] != 'diverge':
                continue
            dif, motivos, fs = ln['dif'], [], ln['formas']
            if fs and dif < 0:
                ph = ','.join(['%s'] * len(fs))
                cur.execute(f"""
                    SELECT data_transacao AS d, SUM(valor) AS v FROM bank_transactions
                     WHERE tipo='CREDIT' AND forma_recebimento_id IN ({ph})
                       AND data_transacao BETWEEN %s AND %s AND data_transacao <> %s
                     GROUP BY data_transacao ORDER BY ABS(DATEDIFF(data_transacao, %s))""",
                    list(fs) + [dia - timedelta(days=_VIZINHO_DIAS),
                                dia + timedelta(days=_VIZINHO_DIAS), dia, dia])
                for r in cur.fetchall():
                    if abs(float(r['v']) - abs(dif)) < _TOL_CENTAVOS:
                        motivos.append('caiu em outro dia: %s entrou no banco em %s'
                                       % (_fmt_br(abs(dif)), r['d'].strftime('%d/%m')))
                        break
            pl = ln['planilha'] or {}
            if pl.get('abatimentos') and abs(dif + pl['abatimentos']) < _TOL_CENTAVOS:
                motivos.append('o banco pagou sem o desconto de %s que está na planilha '
                               '(aluguel de maquininha ou estorno)' % _fmt_br(abs(pl['abatimentos'])))
            for s in soltos:
                if dif < 0 and not s['explica'] and abs(s['valor'] - abs(dif)) < _TOL_CENTAVOS:
                    motivos.append('há um crédito de %s no extrato (%s, "%s") que não está '
                                   'ligado a nenhum cartão: é ele que falta aqui'
                                   % (_fmt_br(s['valor']), s['conta'], s['desc'][:60]))
                    s['explica'] = '%s %s' % (ln['nome'], ln['tipo'].lower())
                    break
            if motivos:
                ln['status'] = 'explicado'
                ln['porque'] = 'Diferença de %s: %s.' % (_fmt_br(abs(dif)), '; '.join(motivos))
            else:
                ln['status'] = 'sem_explicacao'
                if not ln['banco']:
                    txt = ('a planilha diz que a %s pagou %s e nada caiu no banco nesse dia '
                           'para esse cartão' % (ln['operadora'], _fmt_br(ln['v_planilha'])))
                elif not ln['planilha']:
                    txt = ('caiu %s no banco e a planilha da %s não tem pagamento desse '
                           'cartão nesse dia' % (_fmt_br(ln['v_banco']), ln['operadora']))
                else:
                    txt = 'o banco tem %s %s do que a planilha' % (
                        _fmt_br(abs(dif)), 'a mais' if dif > 0 else 'a menos')
                ln['porque'] = ('Diferença sem causa conhecida: %s. Abra as vendas da planilha '
                                'e os lançamentos do banco para comparar.' % txt)

        ordem = {'SIPAG': 0, 'X7': 1, 'BARATAO': 2}
        linhas.sort(key=lambda l: (ordem.get(l['op'], 9), l['tipo'] != 'DEBITO', l['nome']))
        for ln in linhas:
            pl = ln['planilha']
            if pl:
                for v in pl['vendas']:
                    v['dt'] = v['dt'].strftime('%d/%m %H:%M') if v.get('dt') else ''
                if pl.get('dias_abastecimento'):
                    pl['dias_abastecimento'] = [d.strftime('%d/%m') for d in pl['dias_abastecimento']]
        cont = defaultdict(int)
        for ln in linhas:
            cont[ln['status']] += 1

        def soma(campo):
            return round(sum((l['planilha'] or {}).get(campo, 0) for l in linhas), 2)
        return {
            'data': dia.isoformat(), 'data_br': dia.strftime('%d/%m/%Y'),
            'linhas': linhas, 'soltos': soltos, 'contagem': dict(cont),
            'totais': {'planilha': round(sum(l['v_planilha'] for l in linhas), 2),
                       'banco': round(sum(l['v_banco'] for l in linhas), 2),
                       'n': int(soma('n')), 'vendido': soma('vendido'),
                       'taxa': soma('taxa'), 'abatimentos': soma('abatimentos')},
            'cobertura': {k: (v.strftime('%d/%m/%Y') if v else None) for k, v in cob.items()},
            'ult_extrato': ult_extrato.strftime('%d/%m/%Y') if ult_extrato else None,
        }
    finally:
        cur.close()
