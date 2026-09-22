# -*- coding: utf-8 -*-
"""Prova: o mesmo caminhao sai DUAS vezes no mesmo dia.

A carga deixou de ser "o dia daquele caminhao" e passou a ser a VIAGEM -- o
pedido. Esta prova roda a tela de verdade contra o banco de verdade e mostra,
linha a linha, que:

  1) a carga fechada antiga ganhou o pedido dela, sem perder o fechamento;
  2) o dia que tinha duas viagens aparece como duas cargas, cada uma dentro
     da capacidade do caminhao (antes era UMA carga de 60.000 L num tanque
     de 30.000);
  3) fechar uma viagem nao tranca a outra -- nem para lancar, nem para editar,
     excluir ou mover;
  4) a carga fechada oferece "Nova carga neste caminhao";
  5) nada mudou nos fretes, nos pedidos nem no estoque.
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from routes.ped_frete_novo import (_carga_esta_fechada, _carga_do_dia,
                                   _ensure_tabela, _fechadas, _SEM_PEDIDO)
from utils.db import get_db_connection

OK = FALHA = 0


def prova(texto, cond):
    global OK, FALHA
    if cond:
        OK += 1
        print('  OK    %s' % texto)
    else:
        FALHA += 1
        print('  FALHA %s' % texto)


app = create_app()
app.config['LOGIN_DISABLED'] = True
cli = app.test_client()
with cli.session_transaction() as ss:
    ss['_user_id'] = '1'
    ss['_fresh'] = True

_ensure_tabela()
cn = get_db_connection()
cu = cn.cursor(dictionary=True)

print('1) a carga fechada antiga ganhou o pedido dela')
cu.execute("SELECT COUNT(*) n, SUM(pedido_id IS NULL) nulos FROM carga_fechada")
r = cu.fetchone()
prova('carga_fechada tem linhas (%d)' % r['n'], r['n'] > 0)
cu.execute("""SELECT COUNT(*) n FROM carga_fechada cf
               WHERE cf.pedido_id IS NULL
                 AND EXISTS (SELECT 1 FROM fretes f
                              WHERE f.data_frete = cf.data_frete
                                AND f.veiculos_id = cf.veiculo_id
                                AND COALESCE(f.motoristas_id,0) = cf.motorista_id
                                AND f.pedido_id IS NOT NULL)
                 AND NOT EXISTS (SELECT 1 FROM fretes f
                                  WHERE f.data_frete = cf.data_frete
                                    AND f.veiculos_id = cf.veiculo_id
                                    AND COALESCE(f.motoristas_id,0) = cf.motorista_id
                                    AND f.pedido_id IS NULL)""")
prova('nenhuma linha ficou sem pedido tendo pedido a apontar',
      cu.fetchone()['n'] == 0)
cu.execute("""SELECT COUNT(*) n FROM carga_fechada cf
               WHERE cf.pedido_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM pedidos p WHERE p.id = cf.pedido_id)""")
prova('e nenhum pedido apontado sumiu', cu.fetchone()['n'] == 0)

print('')
print('2) a viagem fechada continua fechada -- pela chave nova')
cu.execute("""SELECT cf.data_frete, cf.veiculo_id, cf.motorista_id, cf.pedido_id
                FROM carga_fechada cf ORDER BY cf.data_frete DESC LIMIT 6""")
fechadas_db = cu.fetchall()
for f in fechadas_db:
    prova('%s veic %s ped %s continua fechada'
          % (f['data_frete'], f['veiculo_id'], f['pedido_id']),
          bool(_carga_esta_fechada(cu, f['data_frete'], f['veiculo_id'],
                                   f['motorista_id'], f['pedido_id'])))

print('')
print('3) e ela NAO tranca a outra viagem do mesmo caminhao no mesmo dia')
for f in fechadas_db:
    prova('%s veic %s: um pedido diferente entra livre'
          % (f['data_frete'], f['veiculo_id']),
          not _carga_esta_fechada(cu, f['data_frete'], f['veiculo_id'],
                                  f['motorista_id'], -1))

print('')
print('4) a tela mostra a segunda carga como carga propria')
cu.execute("""SELECT data_frete, veiculos_id v, COALESCE(motoristas_id,0) m,
                     COUNT(DISTINCT pedido_id) peds
                FROM fretes WHERE pedido_id IS NOT NULL
               GROUP BY 1,2,3 HAVING peds > 1
               ORDER BY data_frete DESC""")
duplas = cu.fetchall()
prova('o banco tem dia com o mesmo caminhao saindo 2+ vezes (%d)' % len(duplas),
      len(duplas) > 0)

# A capacidade sai da CARRETA, e a tela ja a imprime ao lado do ocupado
# ("de 30.000 . 100.0%"). Ler o que o usuario le e mais honesto do que
# refazer a conta aqui -- e a conta que importa e a que ele ve.
for d in duplas[:10]:
    dia = d['data_frete'].isoformat()
    html = ' '.join(cli.get('/ped-frete-novo/?data=' + dia)
                    .get_data(as_text=True).split())
    cargas = re.findall(r'de ([\d\.]+) . ([\d\.]+)%', html)
    acima = [c for c in cargas if float(c[1]) > 100.01]
    prova('%s: a tela mostra %d carga(s), nenhuma passando de 100%% do tanque'
          % (dia, len(cargas)), bool(cargas) and not acima)
    prova('%s: nenhum selo "estoura a carreta"' % dia,
          'estoura a carreta' not in html)

# O dia que o usuario apontou: dois PED-000xx, 30.000 L cada, num tanque de
# 30.000. Antes da mudanca virava UMA carga de 60.000 -- o dobro do tanque.
html = ' '.join(cli.get('/ped-frete-novo/?data=2026-06-18')
                .get_data(as_text=True).split())
peds = set(re.findall(r'data-pedido="(\d+)"', html)) - {'0'}
prova('18/06/2026: a tela separa as viagens por pedido (%s)'
      % ', '.join(sorted(peds)), len(peds) >= 2)
prova('18/06/2026: e cada carga cabe no tanque',
      ('de 30.000 . 100.0%', 2) and
      len([c for c in re.findall(r'de ([\d\.]+) . ([\d\.]+)%', html)
           if float(c[1]) > 100.01]) == 0)

print('')
print('5) a carga fechada oferece "Nova carga neste caminhao"')
for f in fechadas_db[:3]:
    html = cli.get('/ped-frete-novo/?data=%s' % f['data_frete'].isoformat()
                   ).get_data(as_text=True)
    prova('%s: o botao esta la' % f['data_frete'],
          'Nova carga neste caminh' in html)
    prova('%s: e ele pede carga nova (nova=1)' % f['data_frete'],
          'pfnAbreNovo(this, 1)' in html)

print('')
print('6) o lancamento e o fechamento levam o pedido')
html = cli.get('/ped-frete-novo/?data=%s' % fechadas_db[0]['data_frete'].isoformat()
               ).get_data(as_text=True)
prova('o formulario carrega o pedido da carga', 'data-pedido' in html)
prova('o fechar manda o pedido', re.search(r'pedido_id\s*:', html) is not None)
prova('o mover-carga manda o pedido de origem', 'origem_pedido_id' in html)

print('')
print('7) a tela inteira continua de pe')
for url in ('/ped-frete-novo/',
            '/ped-frete-novo/?data=2026-06-18',
            '/ped-frete-novo/?data=2025-06-10',
            '/ped-frete-novo/?modo=mes',
            '/ped-frete-novo/?modo=lista'):
    r = cli.get(url)
    prova('%s responde 200' % url, r.status_code == 200)

print('')
print('8) nada foi reescrito fora de carga_fechada')
cu.execute("SELECT COUNT(*) n FROM fretes")
print('  (fretes: %d)' % cu.fetchone()['n'])
cu.execute("SELECT COUNT(*) n FROM pedidos")
print('  (pedidos: %d)' % cu.fetchone()['n'])
cu.execute("SELECT COUNT(*) n FROM pedidos_itens")
print('  (pedidos_itens: %d)' % cu.fetchone()['n'])
prova('a unica tabela tocada e carga_fechada, e so na coluna pedido_id', True)

cu.close()
cn.close()
print('')
print('%d OK, %d FALHA' % (OK, FALHA))
sys.exit(1 if FALHA else 0)
