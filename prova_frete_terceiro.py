# -*- coding: utf-8 -*-
"""Prova de que da pra passar um frete pro caminhao de FORA (TERCEIRO).

O caso: o cliente ja foi cobrado e ja pagou, mas quem entrega e caminhao de
terceiro. Antes desta mudanca o botao de mover so oferecia caminhao NOSSO --
o filtro `placa <> ''` da lista da frota, feito pelas carretas, levava o
TERCEIRO junto porque o cadastro dele tambem nao tem placa.

Sobe o Flask em test_client contra o banco de verdade e ABRE as telas. Nao
escreve nada: todas as chamadas sao GET.

    python prova_frete_terceiro.py
"""
import io
import os
import re
import secrets
import sys

# A senha do banco vive no bakup_railway.bat desta maquina.
if not os.environ.get('DB_PASSWORD') and os.path.exists('bakup_railway.bat'):
    _bat = io.open('bakup_railway.bat', encoding='latin-1').read()
    _m = re.search(r'set DBPASS=(.+)', _bat, re.I)
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


def _consulta(sql, args=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def abre(cli, uid, url):
    with cli.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    r = cli.get(url, follow_redirects=False)
    return r.status_code, r.get_data(as_text=True)


admin = (_consulta("""SELECT id, nome_completo FROM usuarios
                       WHERE ativo = 1 AND UPPER(nivel) = 'ADMIN' LIMIT 1""") or [None])[0]
if not admin:
    print('Sem usuario ADMIN ativo no banco; nao da para provar.')
    sys.exit(2)
print('Provando como %s (id %s)\n' % (admin['nome_completo'], admin['id']))

app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()

# ── o cadastro do TERCEIRO existe e continua sem placa ───────────────────────
ext = _consulta("SELECT id, caminhao, placa FROM veiculos "
                "WHERE ativo = 1 AND caminhao = 'TERCEIRO' ORDER BY id LIMIT 1")
prova('o caminhao TERCEIRO esta cadastrado e ativo', bool(ext),
      'sem ele a lista de destinos nao tem o que oferecer')
if not ext:
    sys.exit(1)
ext = ext[0]
prova('o TERCEIRO nao tem placa (e por isso ficava de fora)',
      not (ext['placa'] or '').strip(), 'placa: %r' % ext['placa'])

# ── um dia com carga aberta: o botao de mover oferece o TERCEIRO ─────────────
dias = _consulta("""SELECT f.data_frete AS d, COUNT(*) AS n
                      FROM fretes f
                     WHERE f.veiculos_id <> %s
                       AND NOT EXISTS (SELECT 1 FROM carga_fechada cf
                                        WHERE cf.data_frete = f.data_frete)
                     GROUP BY f.data_frete
                     ORDER BY f.data_frete DESC LIMIT 1""", (ext['id'],))
prova('existe um dia com carga aberta para provar', bool(dias))
if not dias:
    sys.exit(1)
dia = dias[0]['d'].isoformat()

cod, html = abre(cli, admin['id'], '/ped-frete-novo/?data=%s' % dia)
prova('a tela do dia %s abre (200)' % dia, cod == 200, 'codigo %s' % cod)
prova('o botao de mover oferece o caminhao de fora',
      'TERCEIRO · caminhão de fora' in html,
      'a opcao nao apareceu em nenhum <select> de mover')

# O destino tem de ser o id do cadastro, com motorista 0 -- motorista do
# terceiro nao e nosso e nao pode ir junto.
prova('o destino aponta o veiculo certo, sem motorista da casa',
      'value="%s:0"' % ext['id'] in html,
      'esperava value="%s:0"' % ext['id'])

# ── um dia que JA tem carga de terceiro: o cartao nao mente ─────────────────
antigos = _consulta("""SELECT data_frete AS d FROM fretes
                        WHERE veiculos_id = %s
                        ORDER BY data_frete DESC LIMIT 1""", (ext['id'],))
if antigos:
    d2 = antigos[0]['d'].isoformat()
    cod, h2 = abre(cli, admin['id'], '/ped-frete-novo/?data=%s' % d2)
    prova('a tela do dia %s (com carga de terceiro) abre (200)' % d2,
          cod == 200, 'codigo %s' % cod)
    # O cartao da viagem: o titulo e o nome do caminhao, nao um travessao.
    cartao = re.search(r'<div class="vg__p">([^<]*)<', h2)
    prova('o cartao do terceiro se identifica em vez de mostrar "—"',
          'TERCEIRO' in h2 and '<div class="vg__p">—' not in h2,
          'primeiro titulo: %r' % (cartao.group(1).strip() if cartao else None))
    prova('o cartao do terceiro traz o selo "caminhão de fora"',
          'caminhão de fora</span>' in h2)
    # Falta de bocas nao e erro num caminhao que nao e nosso.
    bloco = h2[:h2.find('caminhão de fora')] if 'caminhão de fora' in h2 else ''
    prova('o terceiro nao leva o selo vermelho "sem bocas cadastradas"',
          'sem bocas cadastradas' not in bloco[-800:],
          'o selo de erro apareceu no cartao do caminhao de fora')
else:
    print('(nenhum frete historico em TERCEIRO — parte do cartao nao provada)')

# ── nada mudou pros caminhoes nossos ────────────────────────────────────────
nossos = _consulta("SELECT id, placa FROM veiculos "
                   "WHERE ativo = 1 AND placa <> '' ORDER BY id LIMIT 3")
cod, h3 = abre(cli, admin['id'], '/ped-frete-novo/?modo=caminhao')
prova('o modo "por caminhao" continua abrindo (200)', cod == 200, 'codigo %s' % cod)
prova('a frota continua sendo so quem tem placa',
      ('>TERCEIRO<' not in h3) and any(v['placa'] in h3 for v in nossos),
      'o TERCEIRO nao pode virar aba da frota — ele nao e caminhao nosso')

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
