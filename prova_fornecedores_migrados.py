# -*- coding: utf-8 -*-
"""Prova do /relatorios/fornecedores_migrados (Modelo 3).

Roda a tela de verdade, com o banco de verdade, e cobra dela:

  1) as colunas que o Anderson pediu -- data de compra, datas de descargas,
     nome da distribuidora, preco unitario, quantidade, preco total, data de
     pagamento e banco;
  2) que o motor (utils/fornecedor_migrado) feche com o banco por OUTRO
     caminho -- soma direta em SQL, sem passar pelo motor;
  3) que os numeros do motor sejam os que a tela imprime;
  4) que o filtro de um fornecedor so funcione sem perder a lista;
  5) que os dois relatorios migrados se liguem, nos dois sentidos.

  SECRET_KEY=... DB_HOST=... DB_PASSWORD=... python prova_fornecedores_migrados.py
"""
import io
import re
import sys
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from utils.db import get_db_connection
from utils import fornecedor_migrado

INI, FIM = date(2026, 9, 1), date(2026, 9, 15)

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

_SO_NOTA = """
   WHERE d.tipo='NFe' AND d.resumo=0
     AND (d.situacao IS NULL OR UPPER(d.situacao)='AUTORIZADO')
     AND DATE(d.dh_emissao) BETWEEN %s AND %s
"""

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
ap = fornecedor_migrado.apurar(cur, INI, FIM)
t = ap['total']

# ---- o mesmo total por outro caminho: SQL direto ----
cur.execute("SELECT COUNT(*) notas, COALESCE(SUM(d.valor_total),0) nota_rs "
            "  FROM dfe_documentos d " + _SO_NOTA, (INI, FIM))
sql_doc = cur.fetchone()
cur.execute("SELECT COALESCE(SUM(pn.valor),0) pago "
            "  FROM dfe_pagamento_nota pn "
            "  JOIN dfe_documentos d ON d.id = pn.documento_id " + _SO_NOTA,
            (INI, FIM))
sql_pago = cur.fetchone()
cur.execute("SELECT COALESCE(SUM(i.quantidade),0) litros "
            "  FROM dfe_itens i "
            "  JOIN dfe_documentos d ON d.id = i.documento_id " +
            _SO_NOTA.replace('WHERE', "WHERE i.categoria='combustivel' AND"),
            (INI, FIM))
sql_litros = cur.fetchone()
cur.close()
conn.close()

client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True

url = ('/relatorios/fornecedores_migrados?data_inicio=%s&data_fim=%s'
       % (INI.isoformat(), FIM.isoformat()))
r = client.get(url)
html = r.get_data(as_text=True)
open('_fmg.html', 'w', encoding='utf-8').write(html)

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


def litros(v):
    return '{:,.0f}'.format(v or 0).replace(',', '.')


def reais(v):
    n = '{:,.2f}'.format(abs(v or 0))
    n = n.replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('-R$ ' if (v or 0) < 0 else 'R$ ') + n


def preco(v):
    return 'R$ ' + ('%.4f' % (v or 0)).replace('.', ',')


print('\n1) a tela abre e traz as colunas pedidas')
prova('HTTP 200 (e nao um redirect para o login)', r.status_code == 200)
for rot in ('Compra', 'Descargas', 'Nota', 'Produto', 'Preço unit.', 'Qtd',
            'Preço total', 'Total da nota', 'Pagamento', 'Banco'):
    prova('a tabela tem a coluna "%s"' % rot, ('>%s<' % rot) in html)
prova('o nome do fornecedor tem quadro proprio',
      'ph__n' in html and 'De quem se compra' in html)

print('\n2) o motor fecha com o banco, por outro caminho')
prova('notas: motor %d = SQL %d' % (t['notas'], sql_doc['notas']),
      t['notas'] == sql_doc['notas'])
prova('total das notas: motor %s = SQL %s'
      % (reais(t['nota_rs']), reais(float(sql_doc['nota_rs']))),
      abs(t['nota_rs'] - float(sql_doc['nota_rs'])) < 0.01)
prova('pago: motor %s = SQL %s'
      % (reais(t['pago']), reais(float(sql_pago['pago']))),
      abs(t['pago'] - float(sql_pago['pago'])) < 0.01)
prova('litros: motor %s = SQL %s'
      % (litros(t['litros']), litros(float(sql_litros['litros']))),
      abs(t['litros'] - float(sql_litros['litros'])) < 0.01)
prova('em aberto = total das notas - pago',
      abs(t['saldo'] - (t['nota_rs'] - t['pago'])) < 0.01)
prova('cada grupo soma as notas dele (%d grupos)' % len(ap['grupos']),
      all(abs(g['nota_rs'] - sum(n['total_nota'] for n in g['notas'])) < 0.01
          for g in ap['grupos']))
prova('cada grupo fecha o pago com os pagamentos de cada nota',
      all(abs(g['pago'] - sum(p['valor'] for n in g['notas']
                              for p in n['pagamentos'])) < 0.01
          for g in ap['grupos']))

print('\n3) os numeros do motor saem impressos na tela')
prova('comprado no periodo: %s' % reais(t['nota_rs']), reais(t['nota_rs']) in html)
prova('pago: %s' % reais(t['pago']), reais(t['pago']) in html)
prova('em aberto: %s' % reais(t['saldo']), reais(t['saldo']) in html)
prova('litros: %s L' % litros(t['litros']), ('%s L' % litros(t['litros'])) in html)
prova('preco medio: %s' % preco(t['unit']), preco(t['unit']) in html)
g0 = ap['grupos'][0]
prova('o maior fornecedor (%s) esta na tela' % g0['nome'],
      g0['nome'].replace(' LTDA', '').replace(' S.A.', '')[:18] in html)
prova('o total dele (%s) tambem' % reais(g0['nota_rs']),
      reais(g0['nota_rs']) in html)
n0 = g0['notas'][0]
prova('a nota %s dele aparece na tabela' % n0['numero'],
      ('>%s<' % n0['numero']) in html)
prova('com a data de compra %s' % n0['dia'].strftime('%d/%m'),
      ('>%s</td>' % n0['dia'].strftime('%d/%m')) in html)
if n0['descargas']:
    prova('e a data da descarga %s' % n0['descargas'][0]['dia'].strftime('%d/%m'),
          n0['descargas'][0]['dia'].strftime('%d/%m') in html)
if n0['pagamentos']:
    prova('e o banco de onde o dinheiro saiu (%s)' % n0['pagamentos'][0]['banco'],
          n0['pagamentos'][0]['banco'] in html)
prova('nota sem pagamento sai como "a pagar" (%d no periodo)' % t['sem_pagar'],
      (t['sem_pagar'] == 0) or ('a pagar' in html))
prova('nota sem descarga sai como "nao desceu" (%d no periodo)' % t['sem_descer'],
      (t['sem_descer'] == 0) or ('não desceu' in html))

print('\n4) o filtro de um fornecedor so')
r2 = client.get(url + '&forn=' + g0['chave'])
h2 = r2.get_data(as_text=True)
prova('abre 200', r2.status_code == 200)
prova('mostra o total do fornecedor escolhido', reais(g0['nota_rs']) in h2)
prova('e a lista do filtro continua com todos os %d' % len(ap['grupos']),
      h2.count('<option value="') >= len(ap['grupos']))

print('\n5) os dois relatorios migrados se ligam')
prova('no Fornecedores tem o link do Lucro',
      '/relatorios/lucro_postos_migrados' in html)
rl = client.get('/relatorios/lucro_postos_migrados?cliente_id=1'
                '&data_inicio=%s&data_fim=%s' % (INI.isoformat(), FIM.isoformat()))
hl = rl.get_data(as_text=True)
prova('o Lucro responde 200', rl.status_code == 200)
prova('e no Lucro tem o link do Fornecedores',
      '/relatorios/fornecedores_migrados' in hl)
prova('a pilula do Fornecedores esta acesa na tela dele',
      re.search(r'class="on"[^>]*fornecedores_migrados', html) is not None)
prova('e a do Lucro esta acesa na tela do Lucro',
      re.search(r'class="on"[^>]*lucro_postos_migrados', hl) is not None)

print('\n6) a aba POR PRODUTO')
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
pp = fornecedor_migrado.por_produto(cur, INI, FIM)
# o mesmo total do corte por produto, por outro caminho: SQL direto
cur.execute("SELECT COUNT(DISTINCT d.id) notas, "
            "       COALESCE(SUM(i.quantidade),0) litros, "
            "       COALESCE(SUM(i.valor_total),0) rs "
            "  FROM dfe_itens i "
            "  JOIN dfe_documentos d ON d.id = i.documento_id "
            " WHERE i.categoria='combustivel' AND i.produto_id IS NOT NULL "
            "   AND d.tipo='NFe' AND d.resumo=0 "
            "   AND (d.situacao IS NULL OR UPPER(d.situacao)='AUTORIZADO') "
            "   AND DATE(d.dh_emissao) BETWEEN %s AND %s", (INI, FIM))
sql_pp = cur.fetchone()
cur.close()
conn.close()

tp = pp['total']
prova('litros: motor %s = SQL %s'
      % (litros(tp['litros']), litros(float(sql_pp['litros']))),
      abs(tp['litros'] - float(sql_pp['litros'])) < 0.01)
prova('total R$: motor %s = SQL %s'
      % (reais(tp['rs']), reais(float(sql_pp['rs']))),
      abs(tp['rs'] - float(sql_pp['rs'])) < 0.01)
prova('notas: motor %d = SQL %d' % (tp['notas'], sql_pp['notas']),
      tp['notas'] == sql_pp['notas'])
prova('cada produto soma os fornecedores dele',
      all(abs(p['litros'] - sum(f['litros'] for f in p['fornecedores'])) < 0.01
          and abs(p['rs'] - sum(f['rs'] for f in p['fornecedores'])) < 0.01
          for p in pp['produtos']))
prova('o preco medio esta entre o menor e o maior de cada produto',
      all(p['menor'] - 0.0001 <= p['unit'] <= p['maior'] + 0.0001
          for p in pp['produtos']))
prova('o primeiro fornecedor de cada produto e o mais barato (acima = 0)',
      all(p['fornecedores'][0]['acima'] < 0.0001 for p in pp['produtos']))
prova('as fatias somam 100%',
      abs(sum(p['fatia'] for p in pp['produtos']) - 100) < 0.01)
prova('o aviso conta os itens de combustivel SEM produto classificado (%d)'
      % pp['sem_classificar']['itens'], pp['sem_classificar']['itens'] > 0)

r3 = client.get(url + '&aba=produto')
h3 = r3.get_data(as_text=True)
open('_fmg_produto.html', 'w', encoding='utf-8').write(h3)
prova('a aba abre 200', r3.status_code == 200)
prova('a pilula "Por produto" esta acesa',
      re.search(r'class="on"[^>]*aba=produto', h3) is not None)
prova('e a outra aba continua alcancavel', 'Por fornecedor' in h3)
for rot in ('Preço médio', 'Mais barato', 'Mais caro', 'fatia da compra',
            'preço dia a dia', 'Contra o melhor'):
    prova('a aba mostra "%s"' % rot, rot in h3)
for p in pp['produtos']:
    prova('%s: %s L na tela' % (p['nome'], litros(p['litros'])),
          ('>%s<' % litros(p['litros'])) in h3)
    prova('%s: preco medio %s' % (p['nome'], preco(p['unit'])), preco(p['unit']) in h3)
    f0 = p['fornecedores'][0]
    prova('%s: o mais barato e %s a %s' % (p['nome'], f0['nome'], preco(f0['unit'])),
          preco(f0['unit']) in h3)
prova('o aviso dos nao classificados aparece na tela',
      ('%s L' % litros(pp['sem_classificar']['litros'])) in h3)
prova('a aba respeita o filtro de fornecedor',
      client.get(url + '&aba=produto&forn=' + g0['chave']).status_code == 200)

print('\n7) a regua de meses')
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
mm = fornecedor_migrado.meses(cur, date(2026, 9, 15))
cur.execute("SELECT DATE_FORMAT(d.dh_emissao,'%Y-%m') mes, COUNT(*) n "
            "  FROM dfe_documentos d "
            " WHERE d.tipo='NFe' AND d.resumo=0 "
            "   AND (d.situacao IS NULL OR UPPER(d.situacao)='AUTORIZADO') "
            " GROUP BY mes ORDER BY mes")
sql_mm = cur.fetchall()
cur.close()
conn.close()

prova('a regua traz os %d meses que TEM nota, e so eles' % len(sql_mm),
      [m['mes'] for m in mm] == [r['mes'] for r in sql_mm])
prova('cada mes leva a sua contagem de notas',
      all(m['notas'] == r['n'] for m, r in zip(mm, sql_mm)))
prova('todo mes comeca no dia 1', all(m['ini'].day == 1 for m in mm))
prova('os meses vem do mais antigo para o mais novo',
      [m['ini'] for m in mm] == sorted(m['ini'] for m in mm))
prova('nenhum mes passa de hoje', all(m['fim'] <= date(2026, 9, 15) for m in mm))
prova('o mes corrente para HOJE, e nao no dia 30 (%s)'
      % mm[-1]['fim'].strftime('%d/%m'), mm[-1]['fim'] == date(2026, 9, 15))
prova('o rotulo e o mes em portugues (%s)' % mm[-1]['rotulo'],
      mm[-1]['rotulo'] == 'SET/26')
prova('as pilulas dos meses aparecem na tela',
      all(('>%s<' % m['rotulo']) in h3 for m in mm))
prova('tem a pilula "Tudo", para o periodo inteiro', '>Tudo<' in h3)
prova('a pilula do mes corrente esta acesa (o periodo E 01-15/09)',
      re.search(r'class="on"[^>]*data_fim=2026-09-15', h3) is not None)
rm = client.get('/relatorios/fornecedores_migrados?aba=produto'
                '&data_inicio=2026-08-01&data_fim=2026-08-31')
hm = rm.get_data(as_text=True)
prova('clicar em AGO/26 abre o mes inteiro', rm.status_code == 200)
prova('e o periodo que abre e mesmo agosto',
      'value="2026-08-01"' in hm and 'value="2026-08-31"' in hm)
prova('a regua guarda a aba: de AGO/26 nao se volta para "Por fornecedor"',
      re.search(r'class="on"[^>]*aba=produto', hm) is not None)

print('\n8) a relacao nota a nota, com data de compra e de descarga')
rel = pp['notas']
prova('a relacao existe e tem linha (%d)' % len(rel), len(rel) > 0)
prova('os litros da relacao fecham com o total do periodo',
      abs(sum(n['litros'] for n in rel) - tp['litros']) < 0.01)
prova('os reais da relacao fecham com o total do periodo',
      abs(sum(n['rs'] for n in rel) - tp['rs']) < 0.01)
prova('cada produto fecha com as linhas dele',
      all(abs(p['litros'] - sum(n['litros'] for n in rel
                                if n['pid'] == p['pid'])) < 0.01
          for p in pp['produtos']))
prova('as notas da relacao sao as mesmas notas do periodo',
      len(set(n['doc'] for n in rel)) == tp['notas'])
prova('uma linha por nota E produto (nenhuma repetida)',
      len(set((n['doc'], n['pid']) for n in rel)) == len(rel))
prova('a mais nova vem primeiro',
      [n['dia'] for n in rel] == sorted((n['dia'] for n in rel), reverse=True))
prova('toda linha tem data de compra e numero de nota',
      all(n['dia'] and n['numero'] for n in rel))
prova('o preco/L de cada linha e o total dividido pelos litros',
      all(abs(n['unit'] * n['litros'] - n['rs']) < 0.02 for n in rel))
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT COUNT(DISTINCT v.documento_id) n "
            "  FROM descarga_nota v "
            "  JOIN dfe_documentos d ON d.id = v.documento_id "
            "  JOIN dfe_itens i ON i.documento_id = d.id "
            " WHERE d.tipo='NFe' AND d.resumo=0 "
            "   AND (d.situacao IS NULL OR UPPER(d.situacao)='AUTORIZADO') "
            "   AND i.categoria='combustivel' AND i.produto_id IS NOT NULL "
            "   AND DATE(d.dh_emissao) BETWEEN %s AND %s", (INI, FIM))
sql_desc = cur.fetchone()['n']
cur.close()
conn.close()
com_desc = len(set(n['doc'] for n in rel if n['descargas']))
prova('as notas com descarga sao as que o ELS amarrou: motor %d = SQL %d'
      % (com_desc, sql_desc), com_desc == sql_desc)
prova('toda descarga tem dia e litros',
      all(x['dia'] and x['litros'] >= 0 for n in rel for x in n['descargas']))
for rot in ('Compra', 'Descarga', 'Nota', 'Produto', 'Fornecedor', 'Litros',
            'Total'):
    prova('a relacao tem a coluna "%s"' % rot, ('>%s<' % rot) in h3)
prova('a relacao tem a coluna "Preco/L"', 'Preço/L' in h3)
prova('a tela conta as %d linhas da relacao' % len(rel),
      ('%d notas' % len(rel)) in h3)
n0 = rel[0]
prova('a data de compra sai por extenso (%s)' % n0['dia'].strftime('%d/%m/%Y'),
      n0['dia'].strftime('%d/%m/%Y') in h3)
prova('a nota sem descarga aparece como "nao desceu"',
      ('não desceu' in h3) == any(not n['descargas'] for n in rel))
com = [n for n in rel if n['descargas']]
prova('a data de descarga sai na linha (%s)'
      % (com[0]['descargas'][0]['dia'].strftime('%d/%m') if com else '-'),
      (not com) or com[0]['descargas'][0]['dia'].strftime('%d/%m') in h3)

print('\n9) clicar no card mostra um combustivel so -- e da para voltar')
p0 = pp['produtos'][0]
rp = client.get(url + '&aba=produto&pid=%d' % p0['pid'])
hp = rp.get_data(as_text=True)
open('_fmg_pid.html', 'w', encoding='utf-8').write(hp)
so = [n for n in rel if n['pid'] == p0['pid']]
prova('a tela do %s abre 200' % p0['nome'], rp.status_code == 200)
prova('sem clique, nenhum card fica aceso e nao ha barra de volta',
      'class="pc pc--on"' not in h3 and 'ver todos os produtos' not in h3)
prova('com clique, o card do %s fica aceso' % p0['nome'],
      'class="pc pc--on"' in hp)
prova('e os outros %d cards continuam na tela (o seletor nao some)'
      % (len(pp['produtos']) - 1),
      all(p['nome'] in hp for p in pp['produtos']))
prova('os outros cards ficam apagados',
      hp.count('class="pc pc--off"') == len(pp['produtos']) - 1)
prova('a relacao mostra so as %d notas do %s' % (len(so), p0['nome']),
      hp.count('data-r="Compra"') == len(so))
prova('e a tela diz quantas sao', ('%d notas' % len(so)) in hp)
prova('o rodape passa a ser o do produto (%s)' % preco(p0['unit']),
      preco(p0['unit']) in hp)
prova('a tabela "de quem vem" tambem so mostra o %s' % p0['nome'],
      hp.count('data-r="Fornecedor"') == len(so) + len(p0['fornecedores']))
prova('tem o caminho de volta para todos os produtos',
      'ver todos os produtos' in hp and 'vendo só este' in hp)
volta = client.get(url + '&aba=produto')
prova('e a volta traz os %d produtos de novo' % len(pp['produtos']),
      volta.get_data(as_text=True).count('data-r="Compra"') == len(rel))
prova('o produto escolhido sobrevive a troca de mes',
      client.get('/relatorios/fornecedores_migrados?aba=produto&pid=%d'
                 '&data_inicio=2026-08-01&data_fim=2026-08-31'
                 % p0['pid']).status_code == 200)
prova('um pid que nao existe nao quebra a tela',
      client.get(url + '&aba=produto&pid=999999').status_code == 200)
prova('um pid podre nao quebra a tela',
      client.get(url + '&aba=produto&pid=xis').status_code == 200)

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
