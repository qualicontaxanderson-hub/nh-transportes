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

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
