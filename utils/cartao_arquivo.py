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
    'X7': {'nome': 'X7 BANK', 'bandeira_like': 'X7%', 'tipo': 'CREDITO',
           'extensoes': ('.xls', '.xlsx', '.html', '.htm')},
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
        if n.startswith(o.get('prefixos', (prefixo,))) and \
                n.lower().endswith(o['extensoes']):
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
# A aba "Operadora" e a MESMA tela da aba "Caixa" -- mesmos cards, mesmos
# ciclos, mesma conferencia por valor --, so que a venda sai do arquivo da
# operadora. Por isso aqui so se entrega a venda no formato que o motor
# (routes/conf_cartoes._build_report) ja le; o resto e dele.

def _operadora_de(nome, tipo):
    nome = _sem_acento(nome).strip().upper()
    for prefixo, o in OPERADORAS.items():
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


def vendas_operadora(conn, bandeiras, vinculos_map, data_inicio, data_fim):
    """(bandeiras, desde, linhas_por_dia, vendas_uma_a_uma) para o motor.

    - bandeiras: so as que tem operadora com arquivo; copia de cada uma, sem
      o saldo anterior (ele e acerto do CAIXA) e com a taxa do contrato da
      operadora quando a bandeira nao tem (Baratao: 2%).
    - desde: {bandeira_id: data} a partir de quando o arquivo cobre a
      bandeira; o credito do extrato de antes nao e desta operadora.
    - linhas_por_dia: [{data_venda, bandeira_id, bandeira_nome, tipo_cartao,
      total_venda}], como o _fetch_vendas.
    - vendas_uma_a_uma: {bandeira_id: [{data, valor}]}, para a conferencia
      casada por valor.
    """
    ensure_tables(conn)
    ensure_tables_sipag(conn)
    fim = (datetime.strptime(data_fim, '%Y-%m-%d') + timedelta(days=1)).date()
    saida_band, desde, linhas = [], {}, []
    uma_a_uma = defaultdict(list)
    cur = conn.cursor(dictionary=True)
    try:
        for b in bandeiras:
            op = _operadora_de(b.get('nome'), b.get('tipo'))
            if not op:
                continue
            if op == 'X7':
                cur.execute("""
                    SELECT dt_operacao AS t, bruto - desconto_lote AS v
                      FROM cartao_arquivo_vendas
                     WHERE operadora='X7' AND dt_operacao >= %s AND dt_operacao < %s""",
                    (data_inicio, fim))
                vendas = cur.fetchall()
                cur.execute("SELECT MIN(DATE(dt_operacao)) AS d FROM cartao_arquivo_vendas "
                            "WHERE operadora='X7'")
                d0 = (cur.fetchone() or {}).get('d')
            elif op == 'BARATAO':
                cur.execute("""
                    SELECT dt_abastecimento AS t, bruto - desconto AS v
                      FROM cartao_baratao_cupons
                     WHERE dt_abastecimento >= %s AND dt_abastecimento < %s""",
                    (data_inicio, fim))
                vendas = cur.fetchall()
                cur.execute("SELECT MIN(DATE(dt_abastecimento)) AS d FROM cartao_baratao_cupons")
                d0 = (cur.fetchone() or {}).get('d')
            else:
                sb, sf = _sipag_da_bandeira(b.get('nome'), b.get('tipo'))
                if not sb or not sf:
                    continue
                cur.execute("""
                    SELECT dt_transacao AS t, bruto AS v
                      FROM cartao_sipag_transacoes
                     WHERE bandeira=%s AND forma=%s AND nsu <> '0'
                       AND arq_realizadas IS NOT NULL
                       AND dt_transacao >= %s AND dt_transacao < %s""",
                    (sb, sf, data_inicio, fim))
                vendas = cur.fetchall()
                d0 = _sipag_desde(cur, sb, sf, vinculos_map.get(b['id'], []))
            if d0 is None and not vendas:
                continue
            copia = dict(b)
            copia['saldo_anterior'] = 0.0
            copia['saldo_anterior_data'] = None
            if copia.get('taxa_contratada') is None and OPERADORAS[op].get('taxa'):
                copia['taxa_contratada'] = OPERADORAS[op]['taxa']
            saida_band.append(copia)
            if d0:
                desde[b['id']] = d0
            por_dia = defaultdict(float)
            for v in vendas:
                d = v['t'].date() if hasattr(v['t'], 'date') else v['t']
                valor = float(v['v'] or 0)
                por_dia[d] += valor
                uma_a_uma[b['id']].append({'data': d, 'valor': valor})
            for d, total in sorted(por_dia.items()):
                linhas.append({'data_venda': d, 'bandeira_id': b['id'],
                               'bandeira_nome': b.get('nome'),
                               'tipo_cartao': b.get('tipo'),
                               'total_venda': round(total, 2)})
    finally:
        cur.close()
    return saida_band, desde, linhas, uma_a_uma
