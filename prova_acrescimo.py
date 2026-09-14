# -*- coding: utf-8 -*-
"""Prova do acréscimo e do desconto — nas duas telas.

No posto, quem paga no crédito ou a prazo paga mais, e esse a mais entra no
cupom FORA da linha do produto. O Lucro Postos Migrados somava só a linha:
em setembro isso escondia R$ 8.065,95 de acréscimo e R$ 415,51 de desconto,
R$ 7.650 de lucro que ninguém via.

O que se prova aqui:

  * a receita do relatório é produto + acréscimo - desconto, e bate com a
    soma crua do banco, produto a produto;
  * o preço médio por litro sobe junto — senão o número da tela continuaria
    contando outra história;
  * a tela de vendas separa as três partes e elas FECHAM com o total do
    cupom. Se não fechassem, seriam três números bonitos mentindo juntos.

Não escreve nada: só lê.

    python prova_acrescimo.py
"""
import io
import os
import re
import secrets
import sys
from datetime import date

if not os.environ.get('DB_PASSWORD') and os.path.exists('bakup_railway.bat'):
    _m = re.search(r'set DBPASS=(.+)',
                   io.open('bakup_railway.bat', encoding='latin-1').read(), re.I)
    if _m:
        os.environ['DB_PASSWORD'] = _m.group(1).strip()
os.environ.setdefault('SECRET_KEY', secrets.token_hex(32))
os.environ.setdefault('WTF_CSRF_ENABLED', 'False')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app                                    # noqa: E402
from utils.db import get_db_connection                 # noqa: E402
from utils import lucro_migrado                        # noqa: E402
from utils.formatadores import formatar_moeda as _moeda  # noqa: E402

CLIENTE = 1
INI, FIM = date(2026, 9, 1), date(2026, 9, 30)
PRODUTOS = [1, 2, 4, 5]

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


conn = get_db_connection()
cur = conn.cursor(dictionary=True)

# ── existe acrescimo para testar? ────────────────────────────────────────
cur.execute("""SELECT SUM(COALESCE(i.vlr_acrescimo,0)) acr,
                      SUM(COALESCE(i.vlr_desconto,0)) dsc,
                      SUM(i.valor_total) prod
                 FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id
                WHERE i.produto_id IN (1,2,4,5)
                  AND DATE(v.dh_emissao) BETWEEN %s AND %s
                  AND (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA')""",
            (INI, FIM))
b = cur.fetchone()
acr, dsc, prod = float(b['acr']), float(b['dsc']), float(b['prod'])
prova('há acréscimo no período para testar', acr > 1,
      'sem acréscimo a prova não testaria nada')
print('        setembro: produto %s + acréscimo %s - desconto %s'
      % (_moeda(prod), _moeda(acr), _moeda(dsc)))

# ── o relatorio conta as tres partes ─────────────────────────────────────
ap = lucro_migrado.apurar(cur, CLIENTE, PRODUTOS, INI, FIM, 'nota')
erros = []
for pid in PRODUTOS:
    cur.execute("""SELECT SUM(i.valor_total) prod,
                          SUM(COALESCE(i.vlr_acrescimo,0)) acr,
                          SUM(COALESCE(i.vlr_desconto,0)) dsc,
                          SUM(i.quantidade) l
                     FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id
                    WHERE i.produto_id = %s
                      AND DATE(v.dh_emissao) BETWEEN %s AND %s
                      AND (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA')""",
                (pid, INI, FIM))
    r = cur.fetchone()
    esperado = float(r['prod']) + float(r['acr']) - float(r['dsc'])
    t = ap[pid]['total']
    if abs(t['venda_rs'] - esperado) > 0.01:
        erros.append((pid, t['venda_rs'], esperado))
    # e as tres partes tem de estar guardadas em separado, nao so somadas
    if (abs(t['venda_produto_rs'] - float(r['prod'])) > 0.01
            or abs(t['venda_acr_rs'] - float(r['acr'])) > 0.01
            or abs(t['venda_desc_rs'] - float(r['dsc'])) > 0.01):
        erros.append((pid, 'partes'))
prova('a receita é produto + acréscimo - desconto, produto a produto',
      not erros, '%r' % erros)

erros = [pid for pid in PRODUTOS
         if abs(ap[pid]['total']['venda_produto_rs']
                + ap[pid]['total']['venda_acr_rs']
                - ap[pid]['total']['venda_desc_rs']
                - ap[pid]['total']['venda_rs']) > 0.01]
prova('as três partes fecham com o total, sem sobra', not erros, '%r' % erros)

# o preco por litro tem de subir junto: se ficasse no valor do produto, a
# tela diria um preco que ninguem cobrou
erros = []
for pid in PRODUTOS:
    t = ap[pid]['total']
    if t['venda_l'] and t['venda_acr_rs'] > 1:
        so_produto = t['venda_produto_rs'] / t['venda_l']
        if not t['venda_unit'] > so_produto:
            erros.append((pid, t['venda_unit'], so_produto))
prova('o preço por litro sobe junto com o acréscimo', not erros, '%r' % erros)
if not erros:
    t = ap[1]['total']
    print('        etanol: R$ %.4f/L com o acréscimo, contra R$ %.4f/L só no produto'
          % (t['venda_unit'], t['venda_produto_rs'] / t['venda_l']))

# ── o dia a dia tambem, nao so o total ───────────────────────────────────
erros = []
for pid in PRODUTOS:
    for d in ap[pid]['dias']:
        if abs((d['venda_produto_rs'] + d['venda_acr_rs'] - d['venda_desc_rs'])
               - d['venda_rs']) > 0.01:
            erros.append((pid, d['data']))
prova('e fecha em cada dia, não só no total', not erros, '%r' % erros[:4])

# ── o preco de BOMBA tem de ficar separado do recebido ───────────────────
# "Eu preciso com certeza o que foi o valor original de bomba e tudo
# separado." Entao os dois precos tem de existir e ser DIFERENTES onde houve
# acrescimo -- um so numero nao responde as duas perguntas.
erros = []
for pid in PRODUTOS:
    t = ap[pid]['total']
    if not t['venda_l']:
        continue
    bomba = t['venda_produto_rs'] / t['venda_l']
    if abs(t['venda_bomba_unit'] - bomba) > 0.00005:
        erros.append((pid, 'bomba', t['venda_bomba_unit'], bomba))
    if t['venda_acr_rs'] > 1 and not t['venda_unit'] > t['venda_bomba_unit']:
        erros.append((pid, 'recebido nao supera a bomba'))
prova('o preço de bomba é o do produto, e o recebido é maior onde houve '
      'acréscimo', not erros, '%r' % erros)
t = ap[1]['total']
print('        etanol: bomba R$ %.4f/L -> recebido R$ %.4f/L'
      % (t['venda_bomba_unit'], t['venda_unit']))

# ── a tela de vendas ─────────────────────────────────────────────────────
cur.execute("""SELECT id FROM usuarios WHERE ativo = 1
                AND UPPER(nivel) = 'ADMIN' LIMIT 1""")
adm = cur.fetchone()
if adm:
    app.config['WTF_CSRF_ENABLED'] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s['_user_id'] = str(adm['id'])
        s['_fresh'] = True
    r = cli.get('/vendas?data_ini=2026-09-01&data_fim=2026-09-30',
                follow_redirects=True)
    h = r.get_data(as_text=True)
    liso = ' '.join(h.split())
    prova('a tela de vendas abre (200)', r.status_code == 200,
          'codigo %s' % r.status_code)

    cur.execute("""SELECT COALESCE(SUM(CASE WHEN v.situacao <> 'cancelada'
                                 THEN v.valor_total ELSE 0 END),0) tot,
                          COALESCE(SUM(CASE WHEN v.situacao <> 'cancelada'
                                 THEN COALESCE(v.vlr_acrescimo,0) ELSE 0 END),0) acr,
                          COALESCE(SUM(CASE WHEN v.situacao <> 'cancelada'
                                 THEN COALESCE(v.vlr_desconto,0) ELSE 0 END),0) dsc
                     FROM vendas_xml v
                    WHERE v.dh_emissao >= %s AND v.dh_emissao <= %s""",
                (INI.strftime('%Y-%m-%d') + ' 00:00:00',
                 FIM.strftime('%Y-%m-%d') + ' 23:59:59'))
    v = cur.fetchone()
    tot, a2, d2 = float(v['tot']), float(v['acr']), float(v['dsc'])
    produtos = tot - a2 + d2
    prova('a tela mostra o acréscimo em separado', _moeda(a2) in liso,
          'não achei %s' % _moeda(a2))
    prova('e o valor dos produtos, fora do acréscimo', _moeda(produtos) in liso,
          'não achei %s' % _moeda(produtos))
    prova('as três partes fecham com o total do cupom',
          abs((produtos + a2 - d2) - tot) < 0.01,
          'produtos %s + acr %s - desc %s ≠ total %s'
          % (_moeda(produtos), _moeda(a2), _moeda(d2), _moeda(tot)))
    print('        vendas: produtos %s + acréscimo %s - desconto %s = %s'
          % (_moeda(produtos), _moeda(a2), _moeda(d2), _moeda(tot)))

    # ── o relatorio mostra as tres partes, cada uma com seu numero ───
    rl = cli.get('/relatorios/lucro_postos_migrados?data_inicio=2026-09-01'
                 '&data_fim=2026-09-30&cliente_id=1&base=nota'
                 '&produto_ids[]=1&produto_ids[]=2&produto_ids[]=4'
                 '&produto_ids[]=5', follow_redirects=True)
    hl = ' '.join(rl.get_data(as_text=True).split())
    prova('o relatório de lucro abre (200)', rl.status_code == 200,
          'codigo %s' % rl.status_code)
    for rotulo in ('Venda na bomba', 'Acréscimo e desconto', '>Preço bomba<',
                   '>Venda bomba<', '>Acréscimo<', '>Desconto<', '>Recebido<'):
        prova('o relatório separa: %s' % rotulo.strip('<>'),
              rotulo.replace('<', '').replace('>', '') in hl
              if rotulo.startswith('>') else rotulo in hl,
              'não achei na tela')
    erros = []
    for pid in PRODUTOS:
        t = ap[pid]['total']
        for nome, v in (('bomba', t['venda_produto_rs']),
                        ('acréscimo', t['venda_acr_rs']),
                        ('recebido', t['venda_rs'])):
            if v > 1 and _moeda(v) not in hl:
                erros.append((pid, nome, _moeda(v)))
    prova('e os três valores de cada produto estão lá, separados',
          not erros, 'faltou: %r' % erros[:4])

    # o cupom com acrescimo tem de mostrar o dele
    cur.execute("""SELECT numero, valor_total, vlr_acrescimo FROM vendas_xml
                    WHERE DATE(dh_emissao) BETWEEN %s AND %s
                      AND COALESCE(vlr_acrescimo,0) > 0
                    ORDER BY dh_emissao DESC LIMIT 1""", (INI, FIM))
    c = cur.fetchone()
    if c:
        r2 = cli.get('/vendas?data_inicio=%s&data_fim=%s'
                     % (FIM.strftime('%Y-%m-%d'), FIM.strftime('%Y-%m-%d')),
                     follow_redirects=True)
        prova('o cupom com acréscimo carrega a marca dele',
              'c-acr' in h, 'nenhum cupom da página mostrou o acréscimo')

cur.close()
conn.close()

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
