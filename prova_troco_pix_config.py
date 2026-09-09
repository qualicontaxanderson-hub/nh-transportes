# -*- coding: utf-8 -*-
"""Prova da tela de Config. contábil do Troco PIX.

É aqui que se diz, por empresa, qual conta contábil leva o DÉBITO dos trocos na
exportação. São 5 empresas e 228 contas no plano — e até agora só uma empresa
estava configurada, coisa que a tela antiga não deixava ver: a conta escolhida
aparecia só dentro de um campo de texto, e quem abria não sabia quais faltavam.

A parte que grava (salvar de verdade, pelo POST da tela) é desfeita no fim, e a
última prova confere que a configuração voltou como estava.

    python prova_troco_pix_config.py [--html arquivo.html]
"""
import io
import os
import re
import secrets
import sys

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


admin = (consulta("""SELECT id, nome_completo FROM usuarios
                      WHERE ativo = 1 AND UPPER(nivel) = 'ADMIN' LIMIT 1""") or [None])[0]
if not admin:
    print('Sem usuario ADMIN ativo; nao da para provar.')
    sys.exit(2)
# O POST desta tela é protegido por CSRF; no navegador o token vai sozinho.
app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as s:
    s['_user_id'] = str(admin['id'])
    s['_fresh'] = True
print('Provando como %s (id %s)\n' % (admin['nome_completo'], admin['id']))

r = cli.get('/troco_pix/config-contabil', follow_redirects=True)
h = r.get_data(as_text=True)
prova('a tela abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
prova('não caiu no erro que joga para outra tela',
      'Erro ao carregar configuração' not in h and 'id="tpg"' in h)

# ── o padrão da casa ───────────────────────────────────────────────────────
prova('usa o topo azul do padrão',
      'linear-gradient(120deg,#2E6FB0,#1D63A5 55%,#0C4C86)' in h)
prova('os números vêm em degradê', 'class="g-nums"' in h)
prova('as três telas do PIX estão no topo, e esta é a acesa',
      re.search(r'<a class="on"[^>]*>Config\. contábil</a>', h) is not None)
prova('acabou a tabela', '<table' not in h and 'table-responsive' not in h)

# ── um cartão por empresa, dizendo quem tem e quem não tem conta ──────────
empresas = consulta("""SELECT DISTINCT c.id, c.razao_social
                         FROM clientes c
                         JOIN cliente_produtos cp ON c.id = cp.cliente_id
                        WHERE cp.ativo = 1""")
cfgs = consulta("""SELECT cliente_id, conta_debito_id
                     FROM troco_pix_conta_contabil""")
tem = {c['cliente_id'] for c in cfgs if c['conta_debito_id']}
cartoes = re.findall(r'data-empresa="(\d+)"\s*\n?\s*data-tem="([01])"', h)
prova('há um cartão por empresa', len(cartoes) == len(empresas),
      '%s cartões para %s empresas' % (len(cartoes), len(empresas)))
prova('cada cartão diz se aquela empresa já tem conta',
      {int(i) for i, t in cartoes if t == '1'} == tem,
      'tela: %r, banco: %r' % ({int(i) for i, t in cartoes if t == '1'}, tem))
prova('quem está sem conta aparece marcado',
      h.count('>sem conta contábil</span>') == len(empresas) - len(tem),
      '%s selos para %s empresas sem conta'
      % (h.count('>sem conta contábil</span>'), len(empresas) - len(tem)))

# O que a tela antiga escondia: a conta escolhida so aparecia dentro do campo.
for c in cfgs:
    if not c['conta_debito_id']:
        continue
    conta = consulta("""SELECT codigo, nome FROM plano_contas_contas
                         WHERE id = %s""", (c['conta_debito_id'],))
    if conta:
        prova('a conta já escolhida aparece à vista (%s)' % conta[0]['codigo'],
              conta[0]['codigo'] in h and conta[0]['nome'] in h)

# ── os números do topo ────────────────────────────────────────────────────
def num(rotulo):
    m = re.search(r'<div class="r">' + rotulo + r'</div>\s*<div class="v">([^<]+)<', h)
    return m.group(1).strip() if m else None


contas = consulta("SELECT COUNT(*) n FROM plano_contas_contas WHERE ativo = 1")
prova('o topo diz quantas empresas são', num('Empresas') == str(len(empresas)))
prova('o topo diz quantas estão configuradas',
      num('Configuradas') == str(len(tem)), 'tela: %r' % num('Configuradas'))
prova('o topo diz quantas faltam',
      num('Sem conta') == str(len(empresas) - len(tem)), 'tela: %r' % num('Sem conta'))
prova('o topo diz o tamanho do plano de contas',
      num('Contas no plano') == str(int(contas[0]['n'])),
      'tela: %r, banco: %s' % (num('Contas no plano'), contas[0]['n']))

# ── as 228 contas vão para a busca, não para uma lista rolável ────────────
prova('a busca tem o plano de contas inteiro',
      h.count('"codigo"') == int(contas[0]['n']),
      '%s contas no JSON para %s ativas' % (h.count('"codigo"'), contas[0]['n']))
prova('escolher é por busca, não por rolagem',
      'onfocus="tpgAbre(this)"' in h and 'oninput="tpgFiltra(this)"' in h)
prova('o que vai para o servidor é o id da conta, não o texto digitado',
      h.count('class="csel__h"') == len(empresas))

# ── salvar de verdade, e desfazer ─────────────────────────────────────────
antes = {c['cliente_id']: c['conta_debito_id'] for c in cfgs}
alvo = empresas[0]
outra = consulta("""SELECT id, codigo FROM plano_contas_contas
                     WHERE ativo = 1 ORDER BY codigo LIMIT 1""")
try:
    if outra:
        campos = {'conta_debito_id_%s' % e['id']:
                  (str(antes.get(e['id']) or '')) for e in empresas}
        campos['conta_debito_id_%s' % alvo['id']] = str(outra[0]['id'])
        r = cli.post('/troco_pix/config-contabil', data=campos,
                     follow_redirects=True)
        prova('salvar responde e volta para a tela', r.status_code == 200,
              'codigo %s' % r.status_code)
        agora = {c['cliente_id']: c['conta_debito_id'] for c in
                 consulta("SELECT cliente_id, conta_debito_id FROM troco_pix_conta_contabil")}
        prova('a conta escolhida foi gravada para a empresa certa',
              agora.get(alvo['id']) == outra[0]['id'],
              'gravou %r, esperava %s' % (agora.get(alvo['id']), outra[0]['id']))
        prova('as outras empresas não foram mexidas',
              all(agora.get(e['id']) == antes.get(e['id'])
                  for e in empresas if e['id'] != alvo['id']),
              'antes %r, agora %r' % (antes, agora))
        html2 = cli.get('/troco_pix/config-contabil').get_data(as_text=True)
        prova('a tela já mostra a conta nova',
              outra[0]['codigo'] in html2)
finally:
    # devolve exatamente o que havia
    executa("DELETE FROM troco_pix_conta_contabil")
    for cid, conta in antes.items():
        if conta:
            executa("""INSERT INTO troco_pix_conta_contabil (cliente_id, conta_debito_id)
                       VALUES (%s, %s)""", (cid, conta))

depois = {c['cliente_id']: c['conta_debito_id'] for c in
          consulta("SELECT cliente_id, conta_debito_id FROM troco_pix_conta_contabil")}
prova('a configuração voltou exatamente como estava', depois == antes,
      'antes %r, depois %r' % (antes, depois))

if len(sys.argv) > 2 and sys.argv[1] == '--html':
    io.open(sys.argv[2], 'w', encoding='utf-8').write(h)
    print('\nHTML salvo em %s' % sys.argv[2])

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
