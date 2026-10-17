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

Hoje so a X7 BANK. SIPAG e Baratao entram quando houver um arquivo de cada.

O "xls" da X7 e HTML com cara de planilha: um bloco por dia de previsao
(o lote: bruto, descontos, taxas, liquido) e as vendas do lote logo abaixo,
cada uma com a Dt. Liquidacao -- o dia em que o lote caiu no banco. Em
17/10/2026, 36 de 37 dias de liquidacao bateram no centavo com o extrato.
"""
import hashlib
import html as _html
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

from utils.db import get_db_connection

_log = logging.getLogger(__name__)

#: Prefixo do nome do arquivo -> operadora. O nome e a unica coisa que o
#: Miguel controla, entao e por ele que se decide quem le o arquivo.
OPERADORAS = {
    'X7': {'nome': 'X7 BANK', 'bandeira_like': 'X7%', 'tipo': 'CREDITO'},
}

EXTENSOES = ('.xls', '.xlsx', '.html', '.htm')

_TOL = 0.02


# ── leitura ───────────────────────────────────────────────────────────────────

def operadora_do_nome(nome):
    n = (nome or '').strip().upper()
    if not n.lower().endswith(EXTENSOES):
        return None
    for prefixo in OPERADORAS:
        if n.startswith(prefixo):
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


LEITORES = {'X7': ler_x7}


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
    for l in lotes:
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
    nome = (b['nome'] or '').strip().upper()
    for prefixo, o in OPERADORAS.items():
        if nome.startswith(o['bandeira_like'].rstrip('%')) and \
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

    por_dia = []
    for d in sorted(set(lotes) | set(extrato)):
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
