# -*- coding: utf-8 -*-
"""Prova das tres mudancas no /relatorios/lucro_postos_migrados.

  1) os dois textos explicativos (as legendas) sairam da tela;
  2) a coluna "Dif. do dia" pinta pelo sinal: negativo vermelho, positivo
     verde -- e o que aparece como "0" nao fica pintado;
  3) cada card traz a perda (ou a sobra) acumulada do periodo, em litros e em
     R$, e o litro e o MESMO numero da coluna "Acumulada" no fim da tabela.

Roda a tela de verdade, com o banco de verdade.

  SECRET_KEY=... DB_HOST=... DB_PASSWORD=... python prova_lucro_perda_sobra.py
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from utils.db import get_db_connection
from utils.fuso import hoje_brasilia
from utils import lucro_migrado

hoje = hoje_brasilia()
ini_mes = hoje.replace(day=1)

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
apurado = lucro_migrado.apurar(cur, 1, [1, 2, 4, 5], ini_mes, hoje, 'nota')
cur.close()
conn.close()

client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True

r = client.get('/relatorios/lucro_postos_migrados?cliente_id=1'
               '&data_inicio=%s&data_fim=%s&base=nota'
               % (ini_mes.isoformat(), hoje.isoformat()))
html = r.get_data(as_text=True)
open('_lucro_migrado.html', 'w', encoding='utf-8').write(html)

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


def litros(v):
    return '{:,.0f}'.format(v or 0).replace(',', '.')


def reais(v):
    n = '{:,.2f}'.format(abs(v or 0)).replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('-R$ ' if (v or 0) < 0 else 'R$ ') + n


prova('a tela responde 200', r.status_code == 200)

# ---- 1) as legendas sairam ----
print('\n1) os textos explicativos')
for pedaco in ('é a nota que você escolheu ao lançar a descarga',
               'De onde sai o dinheiro',
               'A mesma carga, medida por três instrumentos',
               'média móvel ponderada do que está no tanque',
               'o combustível encolhe no caminho'):
    prova('saiu da tela: "%s..."' % pedaco[:42], pedaco not in html)
prova('nenhum bloco class="leg" sobrou', 'class="leg"' not in html)
# e o que NAO era para sair continua na tela
prova('a tabela continua inteira (o cabecalho Custo corrido esta la)',
      '<th>Custo corrido</th>' in html)
prova('o comparativo das tres fontes continua la',
      'A mesma carga contada de três jeitos' in html)

# ---- 2) Dif. do dia pinta pelo sinal ----
print('\n2) a cor da coluna Dif. do dia')
celulas = re.findall(r'<td data-r="Dif\. do dia"[^>]*?class="sec (neg|pos|est)">\s*([^<]+)</td>',
                     html, re.S)
prova('achei as celulas da coluna (%d)' % len(celulas), len(celulas) > 0)
erradas = []
for classe, txt in celulas:
    txt = txt.strip()
    if txt == '—':
        esperado = 'est'
    else:
        n = float(txt.replace('.', ''))
        esperado = 'neg' if n < -0.5 else 'pos' if n > 0.5 else 'est'
    if classe != esperado:
        erradas.append((txt, classe, esperado))
prova('toda celula negativa esta em vermelho e toda positiva em verde',
      not erradas)
if erradas:
    print('      erradas:', erradas[:6])
neg = sum(1 for c, _ in celulas if c == 'neg')
pos = sum(1 for c, _ in celulas if c == 'pos')
print('      %d em vermelho, %d em verde, %d neutras' % (neg, pos, len(celulas) - neg - pos))
prova('tem pelo menos uma de cada cor (senao a prova nao provaria nada)',
      neg > 0 and pos > 0)

# ---- 3) o card de perda/sobra ----
print('\n3) o card da perda ou sobra')
for pid, dados in apurado.items():
    t = dados['total']
    rot = ('Perda no período' if t['variacao_l'] < -0.5
           else 'Sobra no período' if t['variacao_l'] > 0.5 else 'Perda ou sobra')
    prova('produto %s: o card diz "%s"' % (pid, rot), rot in html)
    prova('produto %s: %s L no card' % (pid, litros(t['variacao_l'])),
          ('>\n          %s L</div>' % litros(t['variacao_l'])) in html
          or ('%s L</div>' % litros(t['variacao_l'])) in html)
    prova('produto %s: %s no card' % (pid, reais(t['variacao_rs'])),
          reais(t['variacao_rs']) in html)
    # o litro do card e o MESMO da ultima linha "Acumulada" da tabela
    ultimo = dados['dias'][-1]['var_acum']
    prova('produto %s: o card (%s L) e o acumulado do ultimo dia (%s L)'
          % (pid, litros(t['variacao_l']), litros(ultimo)),
          abs(t['variacao_l'] - ultimo) < 0.01)
    # e o dinheiro e a soma dia a dia, cada um ao custo corrido do seu dia
    mao = sum(d['variacao'] * d['custo_unit']
              for d in dados['dias'] if d['variacao'] is not None)
    prova('produto %s: %s = soma de (dif. do dia x custo corrido do dia)'
          % (pid, reais(t['variacao_rs'])), abs(t['variacao_rs'] - mao) < 0.01)

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
