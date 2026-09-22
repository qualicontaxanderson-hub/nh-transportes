# -*- coding: utf-8 -*-
"""Duas cargas no mesmo dia, de ponta a ponta -- e depois apaga tudo."""
import io, sys, json, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from app import create_app
from utils.db import get_db_connection

OK = FALHA = 0
def prova(t, c):
    global OK, FALHA
    if c: OK += 1; print('  OK    %s' % t)
    else: FALHA += 1; print('  FALHA %s' % t)

app = create_app(); app.config['LOGIN_DISABLED'] = True
app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
with cli.session_transaction() as ss:
    ss['_user_id'] = '1'; ss['_fresh'] = True

cn = get_db_connection(); cu = cn.cursor(dictionary=True)
DIA = '2027-03-15'   # dia de teste, longe de tudo
cu.execute("""SELECT f.veiculos_id v, f.motoristas_id m, f.clientes_id c,
                     f.origem_id o, f.fornecedores_id fo, f.produto_id p
                FROM fretes f
               WHERE f.origem_id IS NOT NULL AND f.fornecedores_id IS NOT NULL
                 AND f.produto_id IS NOT NULL
               ORDER BY f.id DESC LIMIT 1""")
b = cu.fetchone(); print('base:', b)

def conta():
    cn.commit()
    n = {}
    for t in ('fretes', 'pedidos', 'pedidos_itens', 'carga_fechada'):
        cu.execute("SELECT COUNT(*) n FROM " + t); n[t] = cu.fetchone()['n']
    return n
antes = conta(); print('antes:', antes)

def post(rota, corpo):
    cn.commit()
    r = cli.post('/ped-frete-novo/' + rota, json=corpo)
    j = r.get_json(silent=True)
    if j is None:
        j = ' '.join(r.get_data(as_text=True).split())[:300]
    return r.status_code, j

item = {'fornecedor_id': b['fo'], 'produto_id': b['p'], 'litros': 10000,
        'preco_litro': 0.10, 'preco_mercadoria': 5.0}
base = {'data': DIA, 'veiculo_id': b['v'], 'motorista_id': b['m'],
        'cliente_id': b['c'], 'origem_id': b['o'], 'itens': [item]}

print('\n1) primeira carga')
st, j = post('lancar', dict(base)); print('  ', st, j)
prova('a primeira carga entrou', st == 200 and j and j.get('ok'))
cn.commit()
cu.execute("SELECT id, numero FROM pedidos WHERE data_pedido=%s ORDER BY id", (DIA,))
peds = cu.fetchall(); pA = peds[0]['id'] if peds else 0
prova('e abriu um pedido (%s)' % (peds[0]['numero'] if peds else '-'), len(peds) == 1)

print('\n2) fecha a primeira')
st, j = post('fechar', dict(base, pedido_id=pA)); print('  ', st, j)
prova('fechou', st == 200 and j and j.get('ok'))
st, j = post('lancar', dict(base)); print('  ', st, j)
prova('e agora ela nao aceita mais item (409)', st == 409)

print('\n3) segunda carga no MESMO caminhao, no MESMO dia')
st, j = post('lancar', dict(base, nova_carga=1)); print('  ', st, j)
prova('a segunda carga entrou', st == 200 and j and j.get('ok'))
cn.commit()
cu.execute("SELECT id, numero FROM pedidos WHERE data_pedido=%s ORDER BY id", (DIA,))
peds = cu.fetchall(); print('  pedidos do dia:', peds)
prova('sao duas viagens, com numeros proprios', len(peds) == 2)
pB = peds[-1]['id'] if len(peds) == 2 else 0

print('\n4) a primeira fechada nao tranca a segunda')
cn.commit()
cu.execute("SELECT id FROM fretes WHERE data_frete=%s AND pedido_id=%s", (DIA, pB))
fB = [r['id'] for r in cu.fetchall()]
st, j = post('editar', {'frete_id': fB[0], 'litros': 9000}); print('  ', st, j)
prova('editar o frete da segunda carga passa', st == 200 and j and j.get('ok'))
st, j = post('lancar', dict(base, pedido_id=pB)); print('  ', st, j)
prova('e lancar outro item nela tambem passa', st == 200 and j and j.get('ok'))

print('\n5) a tela mostra as duas')
import re
h = ' '.join(cli.get('/ped-frete-novo/?data=' + DIA).get_data(as_text=True).split())
# A viagem fechada se identifica no botao "reabrir" (o formulario dela e o
# da PROXIMA carga, e por isso nasce sem pedido). A aberta, no formulario.
reabrir = set(re.findall(r'pfnReabrir\(this, [^)]*?(\d+)\)', h))
form = set(re.findall(r'data-pedido="(\d+)"', h)) - {'0'}
prova('a viagem fechada e a %s (reabrir aponta %s)' % (pA, sorted(reabrir)),
      str(pA) in reabrir)
prova('a viagem aberta e a %s (o formulario aponta %s)' % (pB, sorted(form)),
      str(pB) in form)
prova('uma fechada e uma aberta na mesma tela',
      'Nova carga neste caminh' in h and 'Fechar carga' in h)

print('\n6) fecha a segunda e reabre SO ela')
st, j = post('fechar', dict(base, pedido_id=pB)); print('  ', st, j)
prova('fechou a segunda', st == 200 and j and j.get('ok'))
st, j = post('reabrir', dict(base, pedido_id=pB)); print('  ', st, j)
prova('reabriu a segunda', st == 200 and j and j.get('ok'))
cn.commit()
cu.execute("SELECT pedido_id FROM carga_fechada WHERE data_frete=%s", (DIA,))
restam = [r['pedido_id'] for r in cu.fetchall()]
prova('e a primeira continua fechada (%s)' % restam, restam == [pA])

print('\n7) limpeza')
cu2 = cn.cursor()
cn.commit()
cu2.execute("DELETE FROM carga_fechada WHERE data_frete=%s", (DIA,))
cu2.execute("DELETE FROM frete_saldo_bordo WHERE carga_data=%s", (DIA,))
cu2.execute("DELETE FROM pedidos_itens WHERE pedido_id IN "
            "(SELECT id FROM pedidos WHERE data_pedido=%s)", (DIA,))
cu2.execute("DELETE FROM fretes WHERE data_frete=%s", (DIA,))
cu2.execute("DELETE FROM pedidos WHERE data_pedido=%s", (DIA,))
cn.commit()
depois = conta(); print('depois:', depois)
prova('o banco voltou exatamente ao que era', depois == antes)
cu2.close(); cu.close(); cn.close()
print('\n%d OK, %d FALHA' % (OK, FALHA))
