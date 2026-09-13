# -*- coding: utf-8 -*-
"""Prova do ponto com foto — contra o banco real.

O que este ponto tem de fazer, e que o papel nao fazia: impedir que o Joao
bata pelo Marcelo. Entao as provas que importam sao as que garantem isso:

  * sem foto nao grava. Nem foto vazia, nem foto que nao e foto.
  * a HORA e a do servidor. Mandar hora pela rede nao muda nada.
  * o TIPO (entrada/saida) tambem e do servidor: alterna sozinho, e mandar
    "ENTRADA" duas vezes seguidas nao cria duas entradas.
  * funcionario desligado nao bate.
  * a foto so sai com login.

Ela GRAVA de verdade e apaga tudo no fim, conferindo que o banco voltou ao
que era — inclusive se algo falhar no meio.

    python prova_ponto.py
"""
import base64
import io
import os
import re
import secrets
import sys
from datetime import datetime, timedelta

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


def uma_foto():
    """Um JPEG de verdade, pequeno mas acima do piso que a rota exige.

    Nao serve um base64 qualquer: a rota recusa dados curtos demais, e e
    justamente isso que se quer provar mais adiante.
    """
    # JPEG minimo valido, repetido ate passar dos 2 KB que a rota exige
    cabeca = base64.b64decode(
        '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof'
        'Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB'
        'AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==')
    return cabeca + b'\x00' * (2500 - len(cabeca))


# ── quem somos, e onde ────────────────────────────────────────────────────
admin = (consulta("""SELECT id, nome_completo FROM usuarios
                      WHERE ativo = 1 AND UPPER(nivel) = 'ADMIN' LIMIT 1""")
         or [None])[0]
if not admin:
    print('Sem usuario ADMIN ativo; nao da para provar.')
    sys.exit(2)
app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as s:
    s['_user_id'] = str(admin['id'])
    s['_fresh'] = True
print('Provando como %s\n' % admin['nome_completo'])

# ── a tabela existe (a migration rodou) ──────────────────────────────────
tab = consulta("""SELECT COLUMN_NAME c, IS_NULLABLE n, DATA_TYPE t
                    FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'ponto_batidas'""")
cols = {r['c']: r for r in tab}
prova('a tabela do ponto existe', bool(cols),
      'rode o app uma vez para a migration passar')
if not cols:
    sys.exit(1)
prova('a foto é NOT NULL no banco, não só na rota',
      cols.get('foto', {}).get('n') == 'NO',
      'se a coluna aceitasse NULL, uma batida sem foto poderia nascer por '
      'outro caminho')
prova('a localização aceita faltar',
      cols.get('lat', {}).get('n') == 'YES' and cols.get('lng', {}).get('n') == 'YES',
      'GPS negado não pode impedir o funcionário de bater')

antes = consulta("SELECT COUNT(*) n FROM ponto_batidas")[0]['n']

# ── a tela de bater ──────────────────────────────────────────────────────
r = cli.get('/ponto/', follow_redirects=True)
h = r.get_data(as_text=True)
prova('a tela de bater abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
prova('ela lista os funcionários ativos', 'data-id="' in h)

ativos = consulta("""SELECT id, nome FROM funcionarios
                      WHERE ativo = 1 AND (data_saida IS NULL OR data_saida >= CURDATE())
                      ORDER BY nome""")
na_tela = re.findall(r'data-id="(\d+)"', h)
prova('um cartão por funcionário que pode bater hoje',
      len(na_tela) == len(ativos),
      '%s na tela, %s no cadastro' % (len(na_tela), len(ativos)))
prova('a tela diz que a hora é a do sistema',
      'hora é a do sistema' in h and 'foto é obrigatória' in h)

if not ativos:
    print('Sem funcionario ativo; nada a bater.')
    sys.exit(1)
alvo = ativos[0]
foto = base64.b64encode(uma_foto()).decode()
criadas = []

try:
    # ── sem foto nao grava ───────────────────────────────────────────────
    r = cli.post('/ponto/bater', json={'funcionario_id': alvo['id']})
    prova('sem foto a batida é recusada', r.status_code == 400,
          'codigo %s' % r.status_code)
    prova('e o motivo sai em português',
          'obrigat' in (r.get_json() or {}).get('erro', '').lower())

    r = cli.post('/ponto/bater',
                 json={'funcionario_id': alvo['id'], 'foto': 'AAAA'})
    prova('foto vazia ou minúscula também é recusada', r.status_code == 400)

    r = cli.post('/ponto/bater',
                 json={'funcionario_id': alvo['id'], 'foto': 'nao é base64!!'})
    prova('lixo no lugar da foto não derruba a rota', r.status_code == 400,
          'codigo %s' % r.status_code)

    r = cli.post('/ponto/bater', json={'foto': foto})
    prova('batida sem dizer quem é também é recusada', r.status_code == 400)

    # ── a batida de verdade ──────────────────────────────────────────────
    # manda hora e tipo de proposito: os dois tem de ser ignorados
    r = cli.post('/ponto/bater', json={
        'funcionario_id': alvo['id'], 'foto': foto,
        'lat': -18.0128, 'lng': -49.3547, 'precisao': 12,
        'tipo': 'SAIDA', 'momento': '1999-01-01 03:00:00',
        'hora': '23:59'})
    prova('a batida com foto é aceita', r.status_code == 200,
          'codigo %s: %s' % (r.status_code, r.get_data(as_text=True)[:200]))
    resp = r.get_json() or {}
    prova('e responde o que foi registrado',
          resp.get('ok') and resp.get('nome') == alvo['nome'],
          '%r' % resp)

    nova = consulta("""SELECT * FROM ponto_batidas WHERE funcionario_id = %s
                        ORDER BY id DESC LIMIT 1""", (alvo['id'],))[0]
    criadas.append(nova['id'])

    prova('o TIPO é do servidor: mandei SAIDA e ele gravou o que era a vez',
          nova['tipo'] == resp.get('tipo'),
          'a rota disse %r e o banco tem %r' % (resp.get('tipo'), nova['tipo']))
    agora = datetime.utcnow()
    prova('a HORA é a do servidor, não a que mandei',
          abs((agora - nova['momento']).total_seconds()) < 300,
          'gravou %s, o servidor está em %s (UTC)' % (nova['momento'], agora))
    prova('a foto chegou inteira no banco',
          nova['foto'] and len(nova['foto']) == len(uma_foto()),
          'gravou %s bytes' % (len(nova['foto']) if nova['foto'] else 0))
    prova('a localização foi junto',
          nova['lat'] is not None and nova['lng'] is not None
          and not nova['geo_negada'])
    prova('e ficou registrado de que aparelho veio',
          bool(nova['dispositivo']) and nova['usuario_id'] == admin['id'])

    # ── a segunda batida alterna sozinha ─────────────────────────────────
    r = cli.post('/ponto/bater', json={'funcionario_id': alvo['id'],
                                       'foto': foto, 'tipo': 'ENTRADA'})
    prova('a segunda batida é aceita', r.status_code == 200)
    seg = consulta("""SELECT * FROM ponto_batidas WHERE funcionario_id = %s
                       ORDER BY id DESC LIMIT 1""", (alvo['id'],))[0]
    criadas.append(seg['id'])
    prova('e ela alterna sozinha: depois de entrar, sai',
          seg['tipo'] != nova['tipo'],
          'duas seguidas como %r — mandar o tipo pela rede funcionou' % seg['tipo'])

    # ── sem localizacao a batida acontece do mesmo jeito ─────────────────
    r = cli.post('/ponto/bater', json={'funcionario_id': alvo['id'],
                                       'foto': foto})
    prova('sem localização a batida acontece mesmo assim', r.status_code == 200,
          'o trabalho não pode parar na porta por causa de uma permissão')
    ter = consulta("""SELECT * FROM ponto_batidas WHERE funcionario_id = %s
                       ORDER BY id DESC LIMIT 1""", (alvo['id'],))[0]
    criadas.append(ter['id'])
    prova('mas fica marcada como sem localização', ter['geo_negada'] == 1)

    # ── a foto so sai com login ──────────────────────────────────────────
    r = cli.get('/ponto/foto/%s' % nova['id'])
    prova('a foto abre para quem está logado',
          r.status_code == 200 and r.data == uma_foto(),
          'codigo %s, %s bytes' % (r.status_code, len(r.data)))
    anon = app.test_client()
    r = anon.get('/ponto/foto/%s' % nova['id'])
    prova('e não abre para quem não está', r.status_code in (301, 302, 401, 403),
          'a foto de um funcionário saiu sem login (codigo %s)' % r.status_code)

    # ── o espelho mostra o que aconteceu ─────────────────────────────────
    r = cli.get('/ponto/espelho', follow_redirects=True)
    he = r.get_data(as_text=True)
    prova('o espelho abre (200)', r.status_code == 200)
    prova('e traz as fotos das batidas de hoje',
          he.count('/ponto/foto/') >= len(criadas),
          'achei %s foto(s) para %s batida(s)'
          % (he.count('/ponto/foto/'), len(criadas)))
    prova('com o nome de quem bateu', alvo['nome'] in ' '.join(he.split()))
    prova('e avisando qual batida ficou sem localização', 'sem local' in he)

    # ── desligado nao bate ───────────────────────────────────────────────
    saida_antes = consulta("SELECT data_saida FROM funcionarios WHERE id = %s",
                           (alvo['id'],))[0]['data_saida']
    ontem = (datetime.now() - timedelta(days=1)).date()
    executa("UPDATE funcionarios SET data_saida = %s WHERE id = %s",
            (ontem, alvo['id']))
    try:
        r = cli.post('/ponto/bater', json={'funcionario_id': alvo['id'],
                                           'foto': foto})
        prova('funcionário desligado não consegue bater', r.status_code == 400,
              'codigo %s' % r.status_code)
        h2 = cli.get('/ponto/', follow_redirects=True).get_data(as_text=True)
        prova('e some da tela de bater',
              ('data-id="%s"' % alvo['id']) not in h2)
    finally:
        executa("UPDATE funcionarios SET data_saida = %s WHERE id = %s",
                (saida_antes, alvo['id']))
    volta = consulta("SELECT data_saida FROM funcionarios WHERE id = %s",
                     (alvo['id'],))[0]['data_saida']
    prova('a prova devolveu a data de saída como estava', volta == saida_antes,
          'antes %r, agora %r' % (saida_antes, volta))

finally:
    for bid in criadas:
        executa("DELETE FROM ponto_batidas WHERE id = %s", (bid,))

depois = consulta("SELECT COUNT(*) n FROM ponto_batidas")[0]['n']
prova('a prova não deixou batida nenhuma para trás', depois == antes,
      'tinha %s batida(s), ficou com %s' % (antes, depois))

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
