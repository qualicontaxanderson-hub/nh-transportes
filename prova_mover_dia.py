# -*- coding: utf-8 -*-
"""Prova de que a carga muda de DIA -- o frete sozinho e a carga inteira.

"Essa carga vem amanha": ate agora o painel de mover so trocava o caminhao,
dentro do mesmo dia. Aqui prova-se que a data entra junto, que a lista de
caminhoes passa a ser a do dia escolhido (cada dia tem as suas cargas), e que
a carga inteira anda de uma vez.

Esta prova ESCREVE no banco de verdade e desfaz tudo no fim -- ela guarda o
estado antes, move, confere, e devolve cada frete para a data, o caminhao, o
motorista e o pedido em que estava. O resumo final acusa se algo ficou fora do
lugar. Nao existe jeito honesto de provar um movimento sem move-lo.

    python prova_mover_dia.py
"""
import io
import os
import re
import secrets
import sys
from datetime import timedelta

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
app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as s:
    s['_user_id'] = str(admin['id'])
    s['_fresh'] = True
print('Provando como %s (id %s)\n' % (admin['nome_completo'], admin['id']))

# ── a carga usada na prova: a mais recente que nao esta fechada ─────────────
carga = consulta("""SELECT f.data_frete AS d, f.veiculos_id AS v,
                           COALESCE(f.motoristas_id,0) AS m, COUNT(*) AS n
                      FROM fretes f
                     WHERE NOT EXISTS (SELECT 1 FROM carga_fechada cf
                                        WHERE cf.data_frete = f.data_frete
                                          AND cf.veiculo_id = f.veiculos_id
                                          AND cf.motorista_id = COALESCE(f.motoristas_id,0))
                     GROUP BY f.data_frete, f.veiculos_id, COALESCE(f.motoristas_id,0)
                     HAVING n >= 2
                     ORDER BY f.data_frete DESC LIMIT 1""")
prova('existe uma carga aberta com mais de um frete', bool(carga))
if not carga:
    sys.exit(1)
carga = carga[0]
dia, vid, mid = carga['d'], carga['v'], carga['m']
amanha = dia + timedelta(days=1)
print('carga de prova: %s, veiculo %s, motorista %s, %s fretes\n'
      % (dia, vid, mid, carga['n']))

# estado ANTES, para devolver tudo no fim
antes = consulta("""SELECT id, data_frete, veiculos_id, motoristas_id, pedido_id
                      FROM fretes
                     WHERE data_frete=%s AND veiculos_id=%s
                       AND COALESCE(motoristas_id,0)=%s""", (dia, vid, mid))
itens_antes = consulta("""SELECT id, pedido_id, frete_id FROM pedidos_itens
                           WHERE frete_id IN (%s)"""
                       % ','.join(str(r['id']) for r in antes))
pedidos_antes = {r['id'] for r in consulta("SELECT id FROM pedidos")}


def devolve():
    """Poe cada frete de volta exatamente onde estava."""
    for r in antes:
        executa("""UPDATE fretes SET data_frete=%s, veiculos_id=%s, motoristas_id=%s,
                          pedido_id=%s WHERE id=%s""",
                (r['data_frete'], r['veiculos_id'], r['motoristas_id'],
                 r['pedido_id'], r['id']))
    for r in itens_antes:
        executa("UPDATE pedidos_itens SET pedido_id=%s WHERE id=%s",
                (r['pedido_id'], r['id']))
    # pedidos criados pela prova, e que ficaram sem nenhum frete
    novos = [r['id'] for r in consulta("SELECT id FROM pedidos")
             if r['id'] not in pedidos_antes]
    for pid in novos:
        vazio = consulta("SELECT COUNT(*) AS n FROM fretes WHERE pedido_id=%s", (pid,))
        if int(vazio[0]['n']) == 0:
            executa("DELETE FROM pedidos_itens WHERE pedido_id=%s", (pid,))
            executa("DELETE FROM pedidos WHERE id=%s", (pid,))


try:
    # ── a rota dos destinos responde pelo DIA pedido ───────────────────────
    r = cli.get('/ped-frete-novo/destinos?data=%s' % amanha.isoformat())
    d = r.get_json() or {}
    prova('a rota de destinos responde 200', r.status_code == 200, 'codigo %s' % r.status_code)
    prova('ela devolve os caminhoes do dia pedido',
          d.get('ok') and d.get('data') == amanha.isoformat() and d.get('destinos'),
          'resposta: %r' % d)
    prova('os nomes vem curtos, como na tela',
          all(re.match(r'^(R\d{3}|Truck|Terceiro)( · \w+)?$', x['label'])
              for x in d.get('destinos', [])),
          'destinos: %r' % d.get('destinos'))
    # o dia de amanha nao tem a carga de hoje: o caminhao dela aparece como
    # parado, com o motorista do cadastro -- e nao com o par de hoje.
    r2 = cli.get('/ped-frete-novo/destinos?data=%s' % dia.isoformat())
    d2 = r2.get_json() or {}
    prova('dias diferentes devolvem listas diferentes',
          d.get('destinos') != d2.get('destinos'),
          'os dois dias devolveram a mesma lista — a data nao esta sendo usada')
    r3 = cli.get('/ped-frete-novo/destinos?data=31-02-2026')
    prova('data invalida e recusada com 400', r3.status_code == 400,
          'codigo %s' % r3.status_code)

    # ── um frete sozinho muda de dia ──────────────────────────────────────
    um = antes[0]
    r = cli.post('/ped-frete-novo/mover',
                 json={'frete_id': um['id'], 'veiculo_id': vid,
                       'motorista_id': mid or um['motoristas_id'],
                       'data': amanha.isoformat()})
    corpo = r.get_json() or {}
    prova('mover um frete para amanha responde ok',
          r.status_code == 200 and corpo.get('ok'), 'resposta: %r' % corpo)
    prova('a resposta avisa que o dia mudou', corpo.get('mudou_dia') is True,
          'resposta: %r' % corpo)
    agora = consulta("""SELECT data_frete, pedido_id FROM fretes WHERE id=%s""",
                     (um['id'],))[0]
    prova('o frete esta em amanha no banco', agora['data_frete'] == amanha,
          'data no banco: %s' % agora['data_frete'])
    prova('e mudou de carga junto (pedido novo)',
          agora['pedido_id'] != um['pedido_id'],
          'pedido continua %s' % agora['pedido_id'])
    ped = consulta("SELECT data_pedido, veiculo_id FROM pedidos WHERE id=%s",
                   (agora['pedido_id'],))[0]
    prova('a carga de destino e do dia certo', ped['data_pedido'] == amanha,
          'pedido do dia %s' % ped['data_pedido'])
    it = consulta("SELECT pedido_id FROM pedidos_itens WHERE frete_id=%s", (um['id'],))
    prova('o item do pedido foi junto',
          all(x['pedido_id'] == agora['pedido_id'] for x in it) if it else True,
          'itens: %r' % it)
    # o resto da carga NAO se mexeu
    resto = consulta("""SELECT COUNT(*) AS n FROM fretes
                         WHERE data_frete=%s AND veiculos_id=%s
                           AND COALESCE(motoristas_id,0)=%s""", (dia, vid, mid))
    prova('os outros fretes ficaram onde estavam',
          int(resto[0]['n']) == len(antes) - 1,
          '%s de %s continuam no dia %s' % (resto[0]['n'], len(antes) - 1, dia))

    devolve()
    volta = consulta("SELECT data_frete FROM fretes WHERE id=%s", (um['id'],))[0]
    prova('desfazer devolveu o frete para o dia de origem',
          volta['data_frete'] == dia, 'data: %s' % volta['data_frete'])

    # ── a carga inteira muda de dia ───────────────────────────────────────
    r = cli.post('/ped-frete-novo/mover-carga',
                 json={'origem_data': dia.isoformat(), 'origem_veiculo_id': vid,
                       'origem_motorista_id': mid, 'data': amanha.isoformat(),
                       'veiculo_id': vid, 'motorista_id': mid})
    corpo = r.get_json() or {}
    prova('mover a carga inteira responde ok',
          r.status_code == 200 and corpo.get('ok'), 'resposta: %r' % corpo)
    prova('moveu todos os fretes da carga, de uma vez',
          corpo.get('fretes_movidos') == len(antes),
          'moveu %s de %s' % (corpo.get('fretes_movidos'), len(antes)))
    ficou = consulta("""SELECT COUNT(*) AS n FROM fretes
                         WHERE data_frete=%s AND veiculos_id=%s
                           AND COALESCE(motoristas_id,0)=%s""", (dia, vid, mid))
    prova('o dia de origem ficou sem a carga', int(ficou[0]['n']) == 0,
          'sobraram %s fretes' % ficou[0]['n'])
    chegou = consulta("""SELECT COUNT(*) AS n, COUNT(DISTINCT pedido_id) AS cargas
                           FROM fretes
                          WHERE data_frete=%s AND veiculos_id=%s
                            AND COALESCE(motoristas_id,0)=%s""", (amanha, vid, mid))
    prova('chegaram todos em amanha, numa carga so',
          int(chegou[0]['n']) == len(antes) and int(chegou[0]['cargas']) == 1,
          '%s fretes em %s cargas' % (chegou[0]['n'], chegou[0]['cargas']))

    # mover para o mesmo lugar e recusado, sem tocar em nada
    r = cli.post('/ped-frete-novo/mover-carga',
                 json={'origem_data': amanha.isoformat(), 'origem_veiculo_id': vid,
                       'origem_motorista_id': mid, 'data': amanha.isoformat(),
                       'veiculo_id': vid, 'motorista_id': mid})
    prova('mover a carga pro lugar onde ela ja esta e recusado',
          r.status_code == 400, 'codigo %s' % r.status_code)
    # sem dizer quem leva, tambem nao vai
    r = cli.post('/ped-frete-novo/mover-carga',
                 json={'origem_data': amanha.isoformat(), 'origem_veiculo_id': vid,
                       'origem_motorista_id': mid, 'data': dia.isoformat(),
                       'veiculo_id': vid, 'motorista_id': 0})
    corpo = r.get_json() or {}
    prova('carga sem quem leva e recusada em portugues',
          r.status_code == 400 and 'quem leva' in (corpo.get('erro') or ''),
          'resposta: %r' % corpo)
finally:
    devolve()

# ── nada ficou fora do lugar ───────────────────────────────────────────────
depois = consulta("""SELECT id, data_frete, veiculos_id, motoristas_id, pedido_id
                       FROM fretes WHERE id IN (%s)"""
                  % ','.join(str(r['id']) for r in antes))
igual = ({(r['id'], r['data_frete'], r['veiculos_id'], r['motoristas_id'],
           r['pedido_id']) for r in antes} ==
         {(r['id'], r['data_frete'], r['veiculos_id'], r['motoristas_id'],
           r['pedido_id']) for r in depois})
prova('a carga voltou exatamente como estava', igual,
      'antes: %r\n        depois: %r' % (antes, depois))
sobrou = [r['id'] for r in consulta("SELECT id FROM pedidos") if r['id'] not in pedidos_antes]
prova('nenhum pedido novo ficou sobrando', not sobrou, 'pedidos: %r' % sobrou)

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
