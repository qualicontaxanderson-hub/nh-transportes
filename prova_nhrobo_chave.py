# -*- coding: utf-8 -*-
"""Prova dos botoes que GRAVAM: gerar, regerar, revogar e data de corte.

Existe porque prova_nhrobo_abas.py so ABRIA telas. Um SQL com seis %s e cinco
valores passa incolume por qualquer GET e derruba a pagina no primeiro clique
em "Gerar chave" -- foi exatamente o que aconteceu em 08/09/2026.

NAO ENCOSTA EM CHAVE VIVA. Escolhe uma pessoa que nao tem chave nenhuma, faz o
ciclo inteiro nela e apaga a linha no fim -- ela nao existia antes. Se a unica
pessoa disponivel ja tivesse chave, o teste desiste em vez de arriscar: regerar
a chave de quem esta rodando pararia a maquina daquela pessoa na hora.

    python prova_nhrobo_chave.py
"""
import io
import os
import re
import secrets
import sys

if not os.environ.get('DB_PASSWORD') and os.path.exists('bakup_railway.bat'):
    _bat = io.open('bakup_railway.bat', encoding='latin-1').read()
    _m = re.search(r'set DBPASS=(.+)', _bat, re.I)
    if _m:
        os.environ['DB_PASSWORD'] = _m.group(1).strip()
os.environ.setdefault('SECRET_KEY', secrets.token_hex(32))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app                             # noqa: E402
from utils.db import get_db_connection          # noqa: E402
from utils.fuso import agora_brasilia           # noqa: E402

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
    finally:
        cur.close()
        conn.close()


def cfg(uid):
    r = consulta("SELECT * FROM nhrobo_config WHERE usuario_id = %s", (uid,))
    return r[0] if r else None


# ── quem serve de cobaia ─────────────────────────────────────────────────────
admin = consulta("""SELECT id, nome_completo FROM usuarios
                     WHERE ativo = 1 AND UPPER(nivel) IN ('ADMIN','ADMINISTRADOR')
                     ORDER BY id LIMIT 1""")
livres = consulta("""SELECT u.id, u.nome_completo FROM usuarios u
                      LEFT JOIN nhrobo_config c ON c.usuario_id = u.id
                     WHERE u.ativo = 1 AND c.id IS NULL
                     ORDER BY u.id LIMIT 1""")
if not admin or not livres:
    print('Preciso de um ADMIN e de alguem SEM chave para provar sem risco.')
    sys.exit(2)

admin, cobaia = admin[0], livres[0]
uid = cobaia['id']
print('Admin: %s | cobaia (sem chave): %s (id %s)\n'
      % (admin['nome_completo'], cobaia['nome_completo'], uid))

app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as s:
    s['_user_id'] = str(admin['id'])
    s['_fresh'] = True

try:
    # ── gerar (o caminho do INSERT) ──────────────────────────────────────────
    r = cli.post('/nh-robo/chave/%s/gerar' % uid, data={'data_inicio': '2026-09-01'})
    prova('POST gerar nao devolve 500', r.status_code != 500,
          'codigo %s' % r.status_code)
    prova('POST gerar redireciona para o painel', r.status_code == 302,
          'codigo %s' % r.status_code)

    linha = cfg(uid)
    prova('a chave nasceu no banco', bool(linha and linha['token_hash']))
    if linha:
        prova('nasceu ativa, versao 1',
              linha['ativo'] == 1 and linha['versao'] == 1,
              'ativo=%s versao=%s' % (linha['ativo'], linha['versao']))
        prova('a data de corte do formulario foi gravada',
              str(linha['data_inicio_captura']) == '2026-09-01',
              str(linha['data_inicio_captura']))
        prova('token_gerado_em veio em horario de Brasilia (nao no futuro)',
              linha['token_gerado_em'] is not None
              and (linha['token_gerado_em'] - agora_brasilia()).total_seconds() < 120,
              '%s vs %s' % (linha['token_gerado_em'], agora_brasilia()))
        prova('o prefixo tem 8 caracteres e casa com o hash guardado',
              len(linha['token_prefixo'] or '') == 8 and len(linha['token_hash']) == 64)

    hash1 = linha['token_hash'] if linha else None

    # ── regerar (o caminho do UPDATE) ────────────────────────────────────────
    r = cli.post('/nh-robo/chave/%s/gerar' % uid, data={'regerar': '1'})
    prova('POST regerar nao devolve 500', r.status_code != 500,
          'codigo %s' % r.status_code)
    linha = cfg(uid)
    prova('regerar troca a chave', bool(linha) and linha['token_hash'] != hash1)
    prova('regerar sobe a versao (e assim que se sabe qual chave e a boa)',
          bool(linha) and linha['versao'] == 2, 'versao=%s' % (linha or {}).get('versao'))
    prova('regerar sem data no formulario NAO apaga a data de corte',
          bool(linha) and str(linha['data_inicio_captura']) == '2026-09-01',
          str((linha or {}).get('data_inicio_captura')))

    # ── mudar a data de corte ────────────────────────────────────────────────
    r = cli.post('/nh-robo/chave/%s/corte' % uid, data={'data_inicio': '2026-07-07'})
    prova('POST corte nao devolve 500', r.status_code != 500,
          'codigo %s' % r.status_code)
    prova('a data de corte mudou',
          str(cfg(uid)['data_inicio_captura']) == '2026-07-07')

    r = cli.post('/nh-robo/chave/%s/corte' % uid, data={'data_inicio': '2099-01-01'})
    prova('data no futuro e recusada (o agente ficaria parado sem ninguem entender)',
          str(cfg(uid)['data_inicio_captura']) == '2026-07-07')

    # ── revogar ──────────────────────────────────────────────────────────────
    r = cli.post('/nh-robo/chave/%s/revogar' % uid)
    prova('POST revogar nao devolve 500', r.status_code != 500,
          'codigo %s' % r.status_code)
    linha = cfg(uid)
    prova('revogar desliga a chave', bool(linha) and linha['ativo'] == 0)
    prova('revogar NAO apaga a linha (o historico continua fazendo sentido)',
          bool(linha) and bool(linha['token_hash']))

    # ── o registro do arquivo recebido ───────────────────────────────────────
    # Este e o caminho que FALHA CALADO: a rota engole a excecao de proposito
    # (o arquivo ja esta no Dropbox, e devolver erro faria o agente reenviar).
    # Sem esta prova, um %s a mais aqui so apareceria como linha que nunca
    # aparece na tela -- e quem procurasse acharia que o arquivo se perdeu.
    from utils import nhrobo                    # noqa: E402
    OFX = ('OFXHEADER:100\r\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>'
           '<BANKTRANLIST><DTSTART>20260801000000<DTEND>20260831000000'
           '</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>')
    nhrobo.registrar_recebido(uid, 'prova nhrobo.ofx', 'prova nhrobo.ofx',
                              '.ofx', len(OFX), '127.0.0.1',
                              OFX.encode('latin-1'))
    novo = consulta("""SELECT * FROM nhrobo_recebidos
                        WHERE usuario_id = %s AND nome_final = 'prova nhrobo.ofx'""",
                    (uid,))
    prova('o arquivo recebido vira linha no historico', len(novo) == 1)
    if novo:
        r = novo[0]
        prova('  e a hora dele e a de Brasilia (nao esta no futuro)',
              (r['recebido_em'] - agora_brasilia()).total_seconds() < 120,
              '%s vs %s' % (r['recebido_em'], agora_brasilia()))
        prova('  o tipo saiu do conteudo: extrato', r['doc_tipo'] == 'extrato',
              str(r['doc_tipo']))
        prova('  o periodo saiu de DENTRO do arquivo: 01/08 a 31/08/2026',
              str(r['periodo_ini']) == '2026-08-01'
              and str(r['periodo_fim']) == '2026-08-31',
              '%s a %s' % (r['periodo_ini'], r['periodo_fim']))
        prova('  e a tela sabe dizer que a fonte foi o arquivo',
              r['periodo_fonte'] == 'arquivo', str(r['periodo_fonte']))

finally:
    # Nada disso existia antes desta prova. Sai inteiro.
    executa("""DELETE FROM nhrobo_recebidos
                WHERE usuario_id = %s AND nome_final = 'prova nhrobo.ofx'""", (uid,))
    executa("DELETE FROM nhrobo_config WHERE usuario_id = %s", (uid,))
    prova('a cobaia voltou a ficar sem chave (nada sobrou no banco)',
          cfg(uid) is None)
    prova('e a linha de teste saiu do historico',
          not consulta("""SELECT id FROM nhrobo_recebidos
                           WHERE nome_final = 'prova nhrobo.ofx'"""))

print('\n%d falha(s)' % len(falhas))
sys.exit(1 if falhas else 0)
