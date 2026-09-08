# -*- coding: utf-8 -*-
"""Prova das 3 abas do NH-Robo, com o app de verdade e o banco de verdade.

Sobe o Flask em test_client e ABRE as telas: se um url_for morrer, se o include
das abas quebrar ou se a coluna de periodo sumir do HTML, isto acusa. Renderizar
so o template com Jinja nao acusaria -- foi o que sempre passou batido.

Nao escreve nada no banco: todas as chamadas sao GET.

    set DB_PASSWORD=... && python prova_nhrobo_abas.py
"""
import io
import os
import re
import secrets
import sys

# A senha do banco vive no bakup_railway.bat desta maquina. Em outra maquina,
# ponha DB_PASSWORD no ambiente antes de rodar.
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


def _um_usuario(nivel):
    """(id, nome) de alguem daquele nivel. None quando nao ha."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, nome_completo, nivel FROM usuarios
                        WHERE ativo = 1 AND UPPER(nivel) = %s LIMIT 1""",
                    (nivel,))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def abre(cli, uid, url):
    with cli.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    r = cli.get(url, follow_redirects=False)
    return r.status_code, r.get_data(as_text=True)


admin = _um_usuario('ADMIN')
if not admin:
    print('Sem usuario ADMIN ativo no banco; nao da para provar.')
    sys.exit(2)
print('Provando como %s (id %s)\n' % (admin['nome_completo'], admin['id']))

app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()

# ── as tres abas abrem ───────────────────────────────────────────────────────
telas = [('/nh-robo/', 'chaves'), ('/nh-robo/instalar', 'instalar'),
         ('/nh-robo/historico', 'historico')]
htmls = {}
for url, chave in telas:
    cod, html = abre(cli, admin['id'], url)
    htmls[chave] = html
    prova('%s abre (200)' % url, cod == 200, 'codigo %s' % cod)

# ── a barra e a mesma nas tres, e marca a aba certa ──────────────────────────
for url, chave in telas:
    h = htmls[chave]
    prova('%s traz as 3 abas' % url,
          all(r in h for r in ('>Chaves<', '>Instalar<', '>Histórico<')))
    # A aba da tela e a unica acesa.
    acesas = re.findall(r'class="aba on"[^>]*>([^<]+)<', h)
    esperada = {'chaves': 'Chaves', 'instalar': 'Instalar',
                'historico': 'Histórico'}[chave]
    prova('%s acende so a propria aba' % url,
          acesas == [esperada], 'acesas: %r' % (acesas,))

# ── o topo azul e o mesmo componente das telas de Migracao ───────────────────
for url, chave in telas:
    prova('%s usa o topo azul do padrao (nao um proprio)' % url,
          '-topo{ background:linear-gradient(120deg,#0C4C86,#1D63A5)' in htmls[chave])

# ── a aba Historico: colunas e legenda ───────────────────────────────────────
h = htmls['historico']
for pedaco, oque in [('Arquivos no período', 'o numero de arquivos'),
                     ('Pessoas que mandaram', 'o numero de pessoas'),
                     ('Sem período', 'o contador de nao identificados'),
                     ('Último envio', 'o carimbo do ultimo'),
                     ('Filtrar o histórico', 'a gaveta de filtro'),
                     ('Tipo de documento', 'o filtro por tipo')]:
    prova('Histórico mostra %s' % oque, pedaco in h)

# ── o filtro filtra de verdade ───────────────────────────────────────────────
cod, h_ofx = abre(cli, admin['id'], '/nh-robo/historico?tipo=extrato')
prova('filtro por tipo responde 200', cod == 200, 'codigo %s' % cod)
prova('filtro por tipo aparece na faixa de filtro ativo',
      'Extrato bancário' in h_ofx and 'Limpar' in h_ofx)

cod, h_vazio = abre(cli, admin['id'],
                    '/nh-robo/historico?data_ini=1999-01-01&data_fim=1999-01-02')
prova('recorte sem nada mostra o vazio explicado, nao uma tela quebrada',
      cod == 200 and 'Nada neste recorte' in h_vazio)

cod, h_sem = abre(cli, admin['id'], '/nh-robo/historico?tipo=sem')
prova('"sem período identificado" e uma escolha do filtro',
      cod == 200 and 'sem período identificado' in h_sem)

# ── quem nao e admin nao ve porta que bate na cara dele ──────────────────────
outro = _um_usuario('SUPERVISOR') or _um_usuario('OPERADOR') or _um_usuario('PISTA')
if outro:
    cod, h2 = abre(cli, outro['id'], '/nh-robo/instalar')
    prova('colaborador (%s) abre a aba Instalar' % outro['nivel'], cod == 200,
          'codigo %s' % cod)
    prova('colaborador NAO ve a aba Chaves',
          '>Chaves<' not in h2 and '>Histórico<' not in h2)
    prova('colaborador ve "Meus envios" no lugar', '>Meus envios<' in h2)
    cod, _ = abre(cli, outro['id'], '/nh-robo/historico')
    prova('e o Histórico continua barrado para ele (redireciona)',
          cod in (302, 401, 403), 'codigo %s' % cod)
else:
    print('AVISO  sem usuario nao-admin ativo; pulei 4 provas')

# ── a tela de chaves nao perdeu o que ela ja fazia ───────────────────────────
h = htmls['chaves']
for pedaco, oque in [('Quem pode mandar', 'a lista de pessoas'),
                     ('Gerar chave', 'o botao de gerar'),
                     ('Com chave', 'o numero de quem tem chave'),
                     ('data de corte', 'a explicacao da data de corte')]:
    prova('Chaves mantem %s' % oque, pedaco in h)
prova('Chaves nao repete mais a lista de recebidos (ela virou aba)',
      'O que chegou' not in h)

# O manual e o que se manda JUNTO com a chave. Se so existisse na aba Instalar,
# quem gera a chave teria de trocar de aba para achar o link -- e mandaria so a
# chave.
prova('Chaves traz o link do manual', '/nh-robo/manual' in h)
cod, manual = abre(cli, admin['id'], '/nh-robo/manual')
prova('e o manual abre de verdade (200)', cod == 200, 'codigo %s' % cod)
prova('o manual e o de primeira instalacao, sem "versao anterior"',
      'Manual de Instalação' in manual and 'versão anterior' not in manual)

# ── a hora e a de Brasilia, nao a do container ───────────────────────────────
# O servidor roda em UTC. Enquanto a hora vinha do NOW() do banco, um arquivo
# entregue as 21h18 aparecia como 00:18 do dia seguinte -- hora que ninguem
# trabalha e, pior, DIA errado para quem procurasse pela data.
import datetime as _dt                                  # noqa: E402
from utils.fuso import BRASILIA, agora_brasilia         # noqa: E402

agora = agora_brasilia()
relogio = _dt.datetime.now(BRASILIA).replace(tzinfo=None)
prova('agora_brasilia() bate com o relogio de Brasilia',
      abs((agora - relogio).total_seconds()) < 120,
      '%s vs %s' % (agora, relogio))

conn = get_db_connection()
cur = conn.cursor()
cur.execute("SELECT NOW()")
now_banco = cur.fetchone()[0]
cur.execute("SELECT MAX(recebido_em), MAX(ultimo_contato) FROM nhrobo_recebidos, nhrobo_config")
mais_novo, contato = cur.fetchone()
cur.close()
conn.close()

prova('o relogio do BANCO esta mesmo adiantado (por isso nao usamos NOW())',
      (now_banco - agora).total_seconds() > 3000,
      'banco %s, Brasilia %s' % (now_banco, agora))
# Uma linha gravada em UTC fica ATE 3 HORAS NO FUTURO. E assim que este erro
# se denuncia sem depender de saber a hora certa de cada arquivo.
if mais_novo:
    prova('nenhum arquivo recebido tem hora no futuro',
          mais_novo <= agora + _dt.timedelta(minutes=2),
          'mais novo: %s' % mais_novo)
if contato:
    prova('o ultimo contato do agente nao esta no futuro',
          contato <= agora + _dt.timedelta(minutes=2),
          'ultimo contato: %s' % contato)

# Sem as linhas de comentario: o comentario que EXPLICA por que nao se usa
# NOW() contem "NOW()", e derrubava esta prova por escrito -- nao por codigo.
codigo = [l for l in io.open('utils/nhrobo.py', encoding='utf-8')
          if not l.lstrip().startswith('#')]
sobrou = [l.strip() for l in codigo if 'NOW()' in l]
prova('nenhum NOW() sobrou no SQL do NH-Robo', not sobrou, '\n        '.join(sobrou))

print('\n%d falha(s)' % len(falhas))
sys.exit(1 if falhas else 0)
