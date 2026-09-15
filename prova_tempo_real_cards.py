# -*- coding: utf-8 -*-
"""Prova da /estoque/tempo-real em CARDS.

Roda a tela de verdade (test_client, banco de verdade) e cobra dela as quatro
coisas que o usuario pediu em cada card: quantidade atual, quanto abriu, custo
corrido por litro e o custo do estoque em R$. Cobra tambem que a faixa branca
do filtro saiu do meio da tela.

O custo nao e recalculado aqui. A prova faz duas cobrancas, e a segunda e a
que importa:

  1) o custo da tela e o que utils/lucro_migrado responde na base NOTA
     (media movel ponderada; nota = a das Compras Migradas);
  2) esse MESMO texto sai na linha de hoje de
     /relatorios/lucro_postos_migrados, na coluna "Custo corrido" -- as duas
     telas buscadas no mesmo teste, e comparadas pelo que aparece na tela.

No dia em que as duas divergirem, esta prova cai.

  SECRET_KEY=... DB_HOST=... DB_PASSWORD=... python prova_tempo_real_cards.py
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from utils.db import get_db_connection
from utils.fuso import hoje_brasilia
from utils import lucro_migrado

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

# ---- o que o banco diz, por outro caminho: o motor do relatorio migrado,
#      na base NOTA, do dia 1 do mes ate hoje (como o relatorio abre) ----
hoje = hoje_brasilia()
ini_mes = hoje.replace(day=1)
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
apurado = lucro_migrado.apurar(cur, 1, [1, 2, 4, 5], ini_mes, hoje, 'nota')
esperado = {pid: d['total']['ef_unit'] for pid, d in apurado.items()}
cur.close()
conn.close()

client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True

r = client.get('/estoque/tempo-real')
print('HTTP', r.status_code)
html = r.get_data(as_text=True)
# o HTML da tela fica em disco para conferir o visual a olho
open('_treal.html', 'w', encoding='utf-8').write(html)

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


def br(v, dec):
    return ('{:,.%df}' % dec).format(v).replace(',', 'X').replace('.', ',').replace('X', '.')


prova('a tela responde 200', r.status_code == 200)
prova('a faixa branca do filtro sumiu (nada de <form class="filtro">)',
      'class="filtro"' not in html)
prova('o aviso e o filtro viraram pills do topo azul',
      'class="aprox"' not in html)
prova('os cards estao numa grade', 'class="grade"' in html)
n = len(re.findall(r'class="card-p"', html))
prova('um card por combustivel com movimento hoje (achei %d)' % n, n >= 1)
for rot in ('quantidade atual', 'abriu', 'recebeu', 'vendeu',
            'Custo corrido', 'Estoque em R$'):
    prova('o card mostra "%s"' % rot, rot in html)

# custo corrido: o numero da tela e o MESMO do relatorio de lucro
for pid, u in esperado.items():
    if u > 0:
        prova('produto %s: custo corrido R$ %s /L na tela' % (pid, br(u, 4)),
              ('R$ ' + br(u, 4)) in html)

# estoque em R$ = quantidade atual do card x custo corrido
cards = re.findall(r'<b>([\d\.]+)</b><span>L</span>.*?Estoque em R\$.*?R\$ ([\d\.,]+)',
                   html, re.S)
print('  pares (saldo, estoque R$) lidos da tela:', cards)
prova('cada card traz quantidade atual E estoque em R$', len(cards) == n)
for saldo_s, rs_s in cards:
    saldo = float(saldo_s.replace('.', ''))
    rs = float(rs_s.replace('.', '').replace(',', '.'))
    u = rs / saldo if saldo else 0
    prova('%s L x R$ %.4f = R$ %s (o custo e o de um dos produtos)'
          % (saldo_s, u, rs_s),
          any(abs(u - e) < 0.01 for e in esperado.values()))

# ---------------------------------------------------------------------------
# A cobranca que importa: o MESMO texto na linha de hoje do relatorio migrado.
# O relatorio escreve o custo com 4 casas ("R$ 5,2756") na coluna marcada
# data-r="Custo corrido" -- e e esse pedaco de HTML que a prova procura.
# ---------------------------------------------------------------------------
rel = client.get('/relatorios/lucro_postos_migrados?cliente_id=1'
                 '&data_inicio=%s&data_fim=%s&base=nota'
                 % (ini_mes.isoformat(), hoje.isoformat()))
html_rel = rel.get_data(as_text=True)
open('_lucro_migrado_prova.html', 'w', encoding='utf-8').write(html_rel)
prova('o relatorio migrado responde 200', rel.status_code == 200)

for pid, u in esperado.items():
    if u <= 0:
        continue
    txt = 'R$ ' + br(u, 4)
    prova('produto %s: "%s" sai na coluna Custo corrido do relatorio' % (pid, txt),
          ('data-r="Custo corrido">%s<' % txt) in html_rel)
    prova('produto %s: o MESMO "%s /L" sai no card do Tempo Real' % (pid, txt),
          (txt + ' <span') in html)

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
