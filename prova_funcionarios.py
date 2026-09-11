# -*- coding: utf-8 -*-
"""Prova do desligamento de funcionário — e de onde ele some (e onde NÃO some).

A regra que se prova aqui, com o caso que você deu: a Brena sai em 07/2026.
A partir daí ela não pode mais aparecer para ESCOLHER — nem no troco PIX de
hoje, nem na folha de 08/2026, nem na descarga. Mas em tudo que já aconteceu
ela continua: a folha de 07/2026 e dos meses anteriores a oferece normalmente,
e os lançamentos dela seguem intactos.

A prova desliga de verdade (pela tela) e desfaz no fim; a última verificação
confere que a data de saída voltou a ser a que era.

    python prova_funcionarios.py [--html arquivo.html]
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

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def liso(html):
    """HTML com os espacos colapsados.

    O Jinja quebra linha dentro das tags, entao procurar '>NOME<' no HTML cru
    NUNCA casa — e um teste escrito assim passa a toa quando pergunta se algo
    NAO esta la. Foi o que aconteceu com "some do troco PIX": ele dava OK sem
    olhar nada.
    """
    return re.sub(r'\s+', ' ', html or '')


def opcoes_de(html, campo):
    """Os nomes que um <select> oferece de verdade."""
    m = re.search(r'<select[^>]*name="%s".*?</select>' % campo, html or '', re.S)
    if not m:
        return None
    return [re.sub(r'\s+', ' ', t).strip()
            for t in re.findall(r'<option[^>]*>(.*?)</option>', m.group(0), re.S)]


def consulta(sql, args=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def executa(sql, args=()):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        conn.commit()
        return cur.rowcount
    finally:
        cur.close()
        conn.close()


admin = (consulta("""SELECT id, nome_completo FROM usuarios
                      WHERE ativo = 1 AND UPPER(nivel) = 'ADMIN' LIMIT 1""") or [None])[0]
if not admin:
    print('Sem usuario ADMIN ativo; nao da para provar.')
    sys.exit(2)
app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as s:
    s['_user_id'] = str(admin['id'])
    s['_fresh'] = True
print('Provando como %s (id %s)\n' % (admin['nome_completo'], admin['id']))

# ── a coluna já existia; a tela é que não a usava ─────────────────────────
col = consulta("""SELECT COLUMN_NAME c FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'funcionarios'
                     AND COLUMN_NAME = 'data_saida'""")
prova('a data de saída é campo do cadastro', bool(col))

# ── 1. a lista, no padrão novo ───────────────────────────────────────────
r = cli.get('/funcionarios/', follow_redirects=True)
h = r.get_data(as_text=True)
prova('a lista abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
prova('usa o topo azul do padrão',
      'linear-gradient(120deg,#2E6FB0,#1D63A5 55%,#0C4C86)' in h and 'id="fun"' in h)
prova('acabou a tabela', '<table' not in h and 'table-responsive' not in h)
prova('tem busca e as pílulas de trabalhando/desligados',
      'id="fun-busca"' in h and 'data-f="off"' in h and 'data-f="on"' in h)

todos = consulta("SELECT id, nome, data_saida FROM funcionarios WHERE ativo = 1")
cards = re.findall(r'data-off="([01])"', h)
prova('há um card por funcionário do cadastro', len(cards) == len(todos),
      '%s cards para %s no banco' % (len(cards), len(todos)))
prova('quem tem data de saída vem marcado',
      cards.count('1') == len([f for f in todos if f['data_saida']]),
      'tela: %s, banco: %s' % (cards.count('1'),
                               len([f for f in todos if f['data_saida']])))

# ── 2. desligar de verdade: o caso da Brena ──────────────────────────────
alvo = (consulta("""SELECT id, nome, data_saida, data_admissao FROM funcionarios
                     WHERE ativo = 1 AND UPPER(nome) LIKE 'BRENA%' LIMIT 1""")
        or consulta("""SELECT id, nome, data_saida, data_admissao FROM funcionarios
                        WHERE ativo = 1 AND data_saida IS NULL LIMIT 1"""))
prova('há alguém para desligar na prova', bool(alvo))
if not alvo:
    sys.exit(1)
alvo = alvo[0]
antes = alvo['data_saida']
print('desligando %s (id %s) em 31/07/2026\n' % (alvo['nome'], alvo['id']))

try:
    r = cli.post('/funcionarios/desligar/%s' % alvo['id'],
                 data={'data_saida': '2026-07-31'}, follow_redirects=True)
    prova('a tela de desligar responde e volta para a lista',
          r.status_code == 200, 'codigo %s' % r.status_code)
    agora = consulta("SELECT data_saida FROM funcionarios WHERE id = %s",
                     (alvo['id'],))[0]['data_saida']
    prova('a data de saída ficou gravada',
          agora is not None and agora.strftime('%Y-%m-%d') == '2026-07-31',
          'gravou %r' % agora)

    # ── onde ele NÃO pode mais aparecer ──────────────────────────────────
    hn = cli.get('/troco_pix/novo').get_data(as_text=True)
    ops = opcoes_de(hn, 'funcionario_id')
    prova('a tela de lançar tem mesmo uma lista de frentistas',
          ops is not None and len(ops) > 1, 'não achei o select de frentista')
    prova('some da lista de frentista do troco PIX de hoje',
          ops is not None and alvo['nome'] not in ops,
          'ainda aparece para escolher num lançamento novo: %r' % (ops,))

    folha8 = cli.get('/lancamentos-funcionarios/get-funcionarios/1?mes=08/2026')
    nomes8 = [f.get('nome') for f in (folha8.get_json() or [])]
    prova('some da folha de 08/2026 (o mês seguinte ao desligamento)',
          alvo['nome'] not in nomes8,
          'apareceu na folha de agosto')

    folha10 = cli.get('/lancamentos-funcionarios/get-funcionarios/1?mes=10/2026')
    nomes10 = [f.get('nome') for f in (folha10.get_json() or [])]
    prova('e de outubro também — era esse o problema',
          alvo['nome'] not in nomes10, 'apareceu em outubro')

    # ── onde ele TEM de continuar aparecendo ─────────────────────────────
    folha7 = cli.get('/lancamentos-funcionarios/get-funcionarios/1?mes=07/2026')
    nomes7 = [f.get('nome') for f in (folha7.get_json() or [])]
    prova('continua na folha de 07/2026, o mês em que trabalhou',
          alvo['nome'] in nomes7, 'sumiu do próprio mês de saída')

    folha6 = cli.get('/lancamentos-funcionarios/get-funcionarios/1?mes=06/2026')
    nomes6 = [f.get('nome') for f in (folha6.get_json() or [])]
    prova('e nos meses anteriores', alvo['nome'] in nomes6,
          'sumiu de junho, quando estava na casa')

    # a correcao de uma solicitacao antiga tem de continuar achando quem
    # atendeu — senao o campo ficaria em branco ao corrigir
    antiga = consulta("""SELECT id FROM troco_pix
                          WHERE funcionario_id = %s AND data < '2026-07-31'
                          ORDER BY data DESC LIMIT 1""", (alvo['id'],))
    if antiga:
        he = cli.get('/troco_pix/editar/%s' % antiga[0]['id'],
                     follow_redirects=True).get_data(as_text=True)
        ope = opcoes_de(he, 'funcionario_id')
        prova('quem atendeu continua na correção de um lançamento do tempo dele',
              ope is not None and alvo['nome'] in ope,
              'o frentista sumiu da tela de corrigir a própria solicitação')

    # e o cadastro continua inteiro
    lista = cli.get('/funcionarios/').get_data(as_text=True)
    prova('ele continua no cadastro, marcado como desligado',
          alvo['nome'] in liso(lista) and 'saiu em 31/07/2026' in liso(lista))
    prova('a ficha dele explica a regra em português',
          'não aparece mais para' in
          liso(cli.get('/funcionarios/editar/%s' % alvo['id']).get_data(as_text=True)))

    # ── readmitir desfaz ─────────────────────────────────────────────────
    r = cli.post('/funcionarios/readmitir/%s' % alvo['id'], follow_redirects=True)
    depois = consulta("SELECT data_saida FROM funcionarios WHERE id = %s",
                      (alvo['id'],))[0]['data_saida']
    prova('readmitir tira a data de saída', depois is None, 'ficou %r' % depois)
    nomes8b = [f.get('nome') for f in
               (cli.get('/lancamentos-funcionarios/get-funcionarios/1?mes=08/2026')
                .get_json() or [])]
    prova('e ele volta para a folha de agosto', alvo['nome'] in nomes8b)
finally:
    executa("UPDATE funcionarios SET data_saida = %s WHERE id = %s",
            (antes, alvo['id']))

final = consulta("SELECT data_saida FROM funcionarios WHERE id = %s",
                 (alvo['id'],))[0]['data_saida']
prova('a prova devolveu o cadastro como estava', final == antes,
      'antes %r, agora %r' % (antes, final))

# ── a data de saída não pode ser antes da admissão ───────────────────────
com_adm = consulta("""SELECT id, nome, data_admissao, data_saida FROM funcionarios
                       WHERE ativo = 1 AND data_admissao IS NOT NULL LIMIT 1""")
if com_adm:
    c = com_adm[0]
    r = cli.post('/funcionarios/desligar/%s' % c['id'],
                 data={'data_saida': '2000-01-01'}, follow_redirects=True)
    ficou = consulta("SELECT data_saida FROM funcionarios WHERE id = %s",
                     (c['id'],))[0]['data_saida']
    prova('sair antes de entrar é recusado', ficou == c['data_saida'],
          'gravou uma saída anterior à admissão')

if len(sys.argv) > 2 and sys.argv[1] == '--html':
    io.open(sys.argv[2], 'w', encoding='utf-8').write(h)
    print('\nHTML salvo em %s' % sys.argv[2])

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
