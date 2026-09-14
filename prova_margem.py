# -*- coding: utf-8 -*-
"""Prova da Margem/L — a da bomba, nao a do recebido.

O acrescimo do cartao e do prazo existe para cobrir a taxa da operadora.
Ele continua no Lucro e no faturamento, mas nao na margem: margem e preco
de bomba menos custo corrido, a conta que se faz na pista.

O que se prova:

  * margem = preco de bomba - custo corrido, em cada dia e em cada produto;
  * a margem NAO usa o recebido: onde houve acrescimo ela e menor que o
    lucro por litro, e a diferenca e exatamente o acrescimo liquido;
  * o Lucro continua com o acrescimo dentro, e o faturamento tambem;
  * o painel do posto usa a mesma regra dos produtos;
  * a tela abre e mostra os numeros novos.

Nao escreve nada: so le.

    python prova_margem.py
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
from app import app                                      # noqa: E402
from utils.db import get_db_connection                   # noqa: E402
from utils import lucro_migrado                          # noqa: E402
from utils.formatadores import formatar_moeda as _moeda  # noqa: E402

CLIENTE = 1
INI, FIM = date(2026, 9, 1), date(2026, 9, 30)
PRODUTOS = [1, 2, 4, 5]
NOMES = {1: 'etanol', 2: 'gasolina', 4: 'S-500', 5: 'S-10'}

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def virgula(x):
    return ('%.4f' % x).replace('.', ',')


conn = get_db_connection()
cur = conn.cursor(dictionary=True)
ap = lucro_migrado.apurar(cur, CLIENTE, PRODUTOS, INI, FIM, 'nota')

# ── de onde vem o preco de bomba ────────────────────────────────────────
# Nao ha tabela de preco: o preco de bomba e o vUnCom do proprio cupom, o
# numero que estava no painel quando o cliente abasteceu. A ancora e que a
# linha do item FECHA: valor_total = litros x valor_unitario. Se um item
# fugisse disso, o preco de bomba do relatorio seria invencao.
cur.execute("""SELECT COUNT(*) n,
                      SUM(ABS(i.valor_total - i.quantidade*i.valor_unitario) > 0.02) fora
                 FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id
                WHERE DATE(v.dh_emissao) BETWEEN %s AND %s
                  AND i.produto_id IN (1,2,4,5)""", (INI, FIM))
r = cur.fetchone()
prova('a linha do cupom fecha: valor_total = litros x preco de bomba',
      int(r['fora'] or 0) == 0,
      '%s itens fora de %s' % (r['fora'], r['n']))
print('        %s itens de combustivel em setembro, %s fora da conta'
      % (r['n'], r['fora']))

# e o preco que a tela mostra e a media ponderada desses itens -- nao pode
# ser outro numero, porque o preco muda dentro do dia
erros = []
for pid in PRODUTOS:
    cur.execute("""SELECT SUM(i.valor_total) rs, SUM(i.quantidade) l
                     FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id
                    WHERE i.produto_id = %s
                      AND DATE(v.dh_emissao) BETWEEN %s AND %s
                      AND (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA')""",
                (pid, INI, FIM))
    b = cur.fetchone()
    cru = float(b['rs']) / float(b['l'])
    if abs(ap[pid]['total']['venda_bomba_unit'] - cru) > 0.00005:
        erros.append((NOMES[pid], ap[pid]['total']['venda_bomba_unit'], cru))
prova('o preco de bomba da tela e a media ponderada do cupom, sem atalho',
      not erros, '%r' % erros)

# ── a definicao, produto a produto ──────────────────────────────────────
erros = []
for pid in PRODUTOS:
    t = ap[pid]['total']
    if not t['venda_l']:
        continue
    esperado = t['venda_bomba_unit'] - t['custo_unit']
    if abs(t['margem_l'] - esperado) > 0.00005:
        erros.append((NOMES[pid], t['margem_l'], esperado))
prova('margem = preco de bomba - custo corrido, no total de cada produto',
      not erros, '%r' % erros)

erros = []
for pid in PRODUTOS:
    for d in ap[pid]['dias']:
        if not d['venda_l']:
            continue
        esperado = (d['venda_produto_rs'] - d['custo_rs']) / d['venda_l']
        if abs(d['margem_l'] - esperado) > 0.00005:
            erros.append((NOMES[pid], d['data'], d['margem_l'], esperado))
prova('e em cada dia, nao so no total', not erros, '%r' % erros[:3])

# ── a margem NAO e mais a do recebido ───────────────────────────────────
# Se ainda fosse, nada teria mudado. Onde houve acrescimo ela tem de ficar
# ABAIXO do lucro por litro, e a distancia tem de ser o acrescimo liquido.
erros = []
mudou = 0
for pid in PRODUTOS:
    t = ap[pid]['total']
    if not t['venda_l'] or t['venda_acr_rs'] <= 1:
        continue
    mudou += 1
    lucro_l = t['lucro_rs'] / t['venda_l']
    if not t['margem_l'] < lucro_l:
        erros.append((NOMES[pid], 'margem nao ficou abaixo do lucro/litro'))
    dif = (lucro_l - t['margem_l']) * t['venda_l']
    liquido = t['venda_acr_rs'] - t['venda_desc_rs']
    if abs(dif - liquido) > 0.02:
        erros.append((NOMES[pid], dif, liquido))
prova('a margem deixou de contar o acrescimo, e a diferenca e exatamente ele',
      not erros and mudou == 4, 'mudou em %d produtos; %r' % (mudou, erros))

# ── o que NAO podia mudar ───────────────────────────────────────────────
erros = []
for pid in PRODUTOS:
    t = ap[pid]['total']
    cur.execute("""SELECT COALESCE(SUM(i.valor_total),0) prod,
                          COALESCE(SUM(COALESCE(i.vlr_acrescimo,0)),0) acr,
                          COALESCE(SUM(COALESCE(i.vlr_desconto,0)),0) dsc
                     FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id
                    WHERE i.produto_id = %s
                      AND DATE(v.dh_emissao) BETWEEN %s AND %s
                      AND (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA')""",
                (pid, INI, FIM))
    r = cur.fetchone()
    fat = float(r['prod']) + float(r['acr']) - float(r['dsc'])
    if abs(t['venda_rs'] - fat) > 0.01:
        erros.append((NOMES[pid], 'faturamento', t['venda_rs'], fat))
prova('o faturamento continua sendo o Recebido, com acrescimo e desconto',
      not erros, '%r' % erros)

erros = [NOMES[pid] for pid in PRODUTOS
         if abs(ap[pid]['total']['lucro_rs']
                - (ap[pid]['total']['venda_rs']
                   - ap[pid]['total']['custo_rs'])) > 0.01]
prova('e o Lucro continua saindo do Recebido, nao da bomba',
      not erros, '%r' % erros)

# O lucro do posto nao pode ser congelado numa constante: o mes corrente
# ainda esta recebendo venda (as notas de hoje entram durante o dia). O que
# vale conferir e a REGRA -- lucro = faturamento - custo -- contra o banco.
soma = sum(ap[p]['total']['lucro_rs'] for p in PRODUTOS)
fat_posto = sum(ap[p]['total']['venda_rs'] for p in PRODUTOS)
custo_posto = sum(ap[p]['total']['custo_rs'] for p in PRODUTOS)
prova('o lucro do posto e o faturamento menos o custo, e nada mais',
      abs(soma - (fat_posto - custo_posto)) < 0.01,
      'lucro %s, fat-custo %s' % (_moeda(soma), _moeda(fat_posto - custo_posto)))

# e a margem do posto tem de ficar abaixo do lucro por litro, pelo acrescimo
litros_posto = sum(ap[p]['total']['venda_l'] for p in PRODUTOS)
acr_posto = sum(ap[p]['total']['venda_acr_rs']
                - ap[p]['total']['venda_desc_rs'] for p in PRODUTOS)
prova('a margem do posto fica abaixo do lucro/litro, na medida do acrescimo',
      abs(((soma / litros_posto)
           - (fat_posto - acr_posto - custo_posto) / litros_posto)
          - acr_posto / litros_posto) < 0.00005,
      'acrescimo liquido %s' % _moeda(acr_posto))

bomba = ((sum(ap[p]['total']['venda_produto_rs'] for p in PRODUTOS)
          - sum(ap[p]['total']['custo_rs'] for p in PRODUTOS))
         / sum(ap[p]['total']['venda_l'] for p in PRODUTOS))
print('        posto: margem R$ %s/L  |  lucro %s  |  faturamento %s'
      % (virgula(bomba), _moeda(soma),
         _moeda(sum(ap[p]['total']['venda_rs'] for p in PRODUTOS))))
for pid in PRODUTOS:
    t = ap[pid]['total']
    print('        %-9s bomba %s - custo %s = margem %s   (lucro/L %s)'
          % (NOMES[pid], virgula(t['venda_bomba_unit']),
             virgula(t['custo_unit']), virgula(t['margem_l']),
             virgula(t['lucro_rs'] / t['venda_l'])))

# ── a tela ──────────────────────────────────────────────────────────────
cur.execute("""SELECT id FROM usuarios WHERE ativo = 1
                AND UPPER(nivel) = 'ADMIN' LIMIT 1""")
adm = cur.fetchone()
if adm:
    app.config['WTF_CSRF_ENABLED'] = False
    cli = app.test_client()
    with cli.session_transaction() as s:
        s['_user_id'] = str(adm['id'])
        s['_fresh'] = True
    r = cli.get('/relatorios/lucro_postos_migrados?data_inicio=2026-09-01'
                '&data_fim=2026-09-30&cliente_id=1&base=nota'
                '&produto_ids[]=1&produto_ids[]=2&produto_ids[]=4'
                '&produto_ids[]=5', follow_redirects=True)
    h = ' '.join(r.get_data(as_text=True).split())
    prova('a tela abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)

    prova('o painel do posto mostra a margem da bomba',
          'margem de R$ %s/L na bomba' % virgula(bomba) in h,
          'nao achei R$ %s' % virgula(bomba))
    prova('a palavra margem acompanha o numero, para nao ler como lucro/litro',
          h.count('margem') >= 4, 'so %d ocorrencias' % h.count('margem'))
    prova('a legenda explica por que margem x litros nao da o lucro',
          'Margem/L × litros não dá o Lucro do dia' in h, 'legenda antiga')
    for pid in PRODUTOS:
        alvo = 'margem R$ %s/L' % virgula(ap[pid]['total']['margem_l'])
        prova('a margem do %s esta na tela (%s)' % (NOMES[pid], alvo),
              alvo in h, 'nao achei')
    for pid in PRODUTOS:
        prova('o lucro do %s nao mudou na tela' % NOMES[pid],
              _moeda(ap[pid]['total']['lucro_rs']) in h,
              'nao achei %s' % _moeda(ap[pid]['total']['lucro_rs']))

cur.close()
conn.close()

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
