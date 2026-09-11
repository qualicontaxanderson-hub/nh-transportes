# -*- coding: utf-8 -*-
"""Prova da tela Troco PIX - Pista, entrando como o frentista de verdade.

Esta tela é usada em pé, no celular, com o cheque na mão e alguém esperando.
O que ela precisa fazer bem: abrir uma solicitação nova em um toque, mostrar o
que já foi lançado, e dizer quanto tempo ainda resta para corrigir um erro.

Prova como PISTA (não como ADMIN): é o único jeito de conferir o que o
frentista realmente vê — inclusive que ele vê apenas o próprio posto.

Não escreve nada: todas as chamadas são GET.

    python prova_troco_pix_pista.py [--html arquivo.html]
"""
import io
import os
import re
import secrets
import sys
from datetime import date, timedelta

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
# A MESMA funcao que a tela usa. CURDATE() aqui seria o dia do servidor, que
# roda em UTC: depois das 21h de Brasilia os dois discordam, e a prova mediria
# um dia que a tela nao mostra — foi exatamente o que aconteceu as 21h de
# 09/09, com a prova acusando "2 na tela, 0 no banco".
from routes.troco_pix import _hoje_br                  # noqa: E402

HOJE = _hoje_br()
INI7 = HOJE - timedelta(days=6)

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def consulta(sql, args=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


frentista = (consulta("""SELECT u.id, u.nome_completo, u.cliente_id,
                                c.razao_social AS posto
                           FROM usuarios u
                           LEFT JOIN clientes c ON c.id = u.cliente_id
                          WHERE u.ativo = 1 AND UPPER(u.nivel) = 'PISTA'
                          LIMIT 1""") or [None])[0]
prova('existe um usuário de pista para provar', bool(frentista),
      'sem usuário PISTA ativo não dá para ver o que o frentista vê')
if not frentista:
    sys.exit(1)
print('Provando como %s (pista do %s)\n'
      % (frentista['nome_completo'], frentista['posto']))

app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as s:
    s['_user_id'] = str(frentista['id'])
    s['_fresh'] = True

r = cli.get('/troco_pix/pista', follow_redirects=True)
h = r.get_data(as_text=True)
prova('a tela abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
prova('não caiu no erro que joga para outra tela',
      'Erro ao carregar transações' not in h and 'id="tpp"' in h)

# ── o que o frentista precisa em um toque ─────────────────────────────────
prova('o botão de nova solicitação está lá, grande',
      'class="novo"' in h and 'Nova solicitação de troco' in h)
prova('e leva para o lançamento marcado como vindo da pista',
      "origem=pista" in h or 'origem%3Dpista' in h)
prova('usa o topo azul do padrão',
      'linear-gradient(120deg,#2E6FB0,#1D63A5 55%,#0C4C86)' in h)
prova('acabou a tabela com rolagem lateral',
      '<table' not in h and 'table-responsive' not in h)

# ── o posto certo, e SÓ o posto dele ──────────────────────────────────────
prova('o subtítulo diz o posto dele, não "Todos os postos"',
      (frentista['posto'] or '') in h and 'Todos os postos' not in h,
      'a tela ainda diz "Todos os postos"')

outros = consulta("""SELECT tp.id, c.razao_social
                       FROM troco_pix tp
                       JOIN clientes c ON c.id = tp.cliente_id
                      WHERE tp.cliente_id <> %s
                        AND tp.data >= %s
                      LIMIT 5""", (frentista['cliente_id'], INI7))
prova('não aparece solicitação de outro posto',
      not any(('/visualizar/%d' % o['id']) in h for o in outros),
      'apareceu solicitação de outro posto na tela do frentista')

# ── os últimos 7 dias, não só hoje ────────────────────────────────────────
hoje = HOJE
sete = consulta("""SELECT tp.id, tp.data FROM troco_pix tp
                    WHERE tp.cliente_id = %s
                      AND tp.data BETWEEN %s AND %s""",
                (frentista['cliente_id'], INI7, HOJE))
de_hoje = [t for t in sete if t['data'] == hoje]
antes = [t for t in sete if t['data'] != hoje]
cards = re.findall(r'/visualizar/(\d+)', h)
prova('a tela mostra os últimos 7 dias, e não só hoje',
      {int(x) for x in cards} == {t['id'] for t in sete},
      '%s na tela, %s no banco (7 dias)' % (len(set(cards)), len(sete)))
if antes:
    prova('os dias anteriores vêm separados por dia',
          h.count('class="dia"') >= 2,
          'só um cabeçalho de dia — os anteriores não foram agrupados')
    dias_distintos = {t['data'] for t in antes}
    prova('cada dia anterior tem o seu cabeçalho',
          h.count('class="dia"') == len(dias_distintos) + 1,
          '%s cabeçalhos para %s dias + hoje'
          % (h.count('class="dia"'), len(dias_distintos)))

# ── o relógio dos 15 minutos ──────────────────────────────────────────────
prova('cada solicitação de hoje carrega a hora-limite de correção',
      h.count('data-ate="') == len(de_hoje),
      '%s relógios para %s solicitações de hoje'
      % (h.count('data-ate="'), len(de_hoje)))
prova('a hora-limite vai em UTC, para o celular fazer a conta',
      not de_hoje or re.search(r'data-ate="\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"', h)
      is not None, 'a hora-limite não está em UTC com Z')

# a conta do limite: criado_em + 15 min
if de_hoje:
    um = consulta("""SELECT id, criado_em FROM troco_pix
                      WHERE id = %s""", (de_hoje[0]['id'],))[0]
    esperado = (um['criado_em'] + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
    prova('o limite é a criação mais 15 minutos',
          ('data-ate="%s"' % esperado) in h,
          'esperava %s' % esperado)

prova('o aviso dos 15 minutos continua na tela, em português de gente',
      '15</b> minutos' in h or '<b>15 minutos</b>' in h)
prova('o relógio se atualiza sozinho', 'setInterval(tppPrazos' in h)

# ── os números do dia ─────────────────────────────────────────────────────
def num(rotulo):
    m = re.search(r'<div class="r">' + rotulo + r'</div>\s*<div class="v">([^<]+)<', h)
    return m.group(1).strip() if m else None


prova('o topo diz quantas foram hoje', num('Hoje') == str(len(de_hoje)),
      'tela: %r, banco: %s' % (num('Hoje'), len(de_hoje)))
troco_hoje = consulta("""SELECT COALESCE(SUM(troco_pix),0) t FROM troco_pix
                          WHERE cliente_id = %s AND data = %s""",
                      (frentista['cliente_id'], HOJE))[0]['t']
prova('o topo soma o troco PIX de hoje',
      (num('Troco PIX hoje') or '').replace('\xa0', ' ')
      == ('R$ %s' % ('{:,.2f}'.format(float(troco_hoje))
                     .replace(',', 'X').replace('.', ',').replace('X', '.'))),
      'tela: %r, banco: %s' % (num('Troco PIX hoje'), troco_hoje))

# ── quando não há nada, a tela ensina o caminho ───────────────────────────
if not de_hoje:
    prova('sem lançamento hoje, a tela diz o que fazer',
          'Nenhum troco lançado hoje ainda' in h)

# ── o envelope: o PIX do meu cliente já saiu? ─────────────────────────────
# Mesma linguagem da tela do administrativo: azul o banco já avisou, vermelho
# ainda não. Aqui vale mais ainda, porque quem lançou não faz o PIX — ele
# depende do administrativo e não tinha como saber.
enviados = consulta("""SELECT tp.id FROM troco_pix tp
                         JOIN troco_pix_comprovantes cp ON cp.troco_pix_id = tp.id
                        WHERE tp.cliente_id = %s
                          AND tp.data BETWEEN %s AND %s
                          AND COALESCE(tp.troco_pix,0) > 0""",
                    (frentista['cliente_id'], INI7, HOJE))
faltando = consulta("""SELECT tp.id FROM troco_pix tp
                        LEFT JOIN troco_pix_comprovantes cp ON cp.troco_pix_id = tp.id
                       WHERE tp.cliente_id = %s
                         AND tp.data BETWEEN %s AND %s
                         AND COALESCE(tp.troco_pix,0) > 0
                         AND cp.id IS NULL
                         AND tp.bank_transaction_id IS NULL""",
                    (frentista['cliente_id'], INI7, HOJE))
prova('o troco já enviado leva envelope AZUL',
      h.count('env env--ok') == len(enviados),
      '%s azuis para %s comprovantes no banco'
      % (h.count('env env--ok'), len(enviados)))
prova('o troco que ainda não saiu leva envelope VERMELHO',
      h.count('env env--nao') == len(faltando),
      '%s vermelhos para %s sem comprovante'
      % (h.count('env env--nao'), len(faltando)))
prova('o envelope azul guarda a hora do PIX',
      not enviados or re.search(r'title="PIX enviado em \d{2}/\d{2}/\d{4} às \d{2}:\d{2}"', h)
      is not None, 'não achei a hora no envelope')
prova('o vermelho explica que falta o administrativo mandar',
      not faltando or 'ainda não mandou este PIX' in h)
prova('solicitação sem troco não ganha envelope nenhum',
      h.count('class="env') == len(enviados) + len(faltando),
      'apareceu envelope onde não há troco a mandar')

if len(sys.argv) > 2 and sys.argv[1] == '--html':
    io.open(sys.argv[2], 'w', encoding='utf-8').write(h)
    print('\nHTML salvo em %s' % sys.argv[2])

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
