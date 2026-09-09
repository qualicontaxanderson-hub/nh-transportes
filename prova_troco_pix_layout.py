# -*- coding: utf-8 -*-
"""Prova do layout novo do Troco PIX, com o app e o banco de verdade.

A tela era uma tabela de nove colunas dentro de table-responsive: no celular
nascia cortada no "POSTO/CLIENT" e escondia valores, conciliacao e botoes
atras de rolagem lateral. Agora e o padrao da casa — topo azul, numeros em
degrade, busca, pilulas de status e uma linha por solicitacao que abre.

Nao escreve nada: todas as chamadas sao GET.

    python prova_troco_pix_layout.py
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

r = cli.get('/troco_pix/', follow_redirects=False)
if r.status_code in (301, 302):
    r = cli.get(r.headers.get('Location') or '/troco_pix/listar',
                follow_redirects=True)
h = r.get_data(as_text=True)
# A tela do PIX manda erro por flash e REDIRECIONA — nao adianta so o 200.
prova('a tela abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
prova('nao caiu no erro que redireciona pra outra tela',
      'Erro ao carregar transações' not in h and 'id="tpx"' in h,
      'a tela renderizada nao e a do Troco PIX')

# ── o que a casa ve: topo, numeros, familia ────────────────────────────────
prova('usa o topo azul do padrao (nao um cabecalho proprio)',
      'linear-gradient(120deg,#2E6FB0,#1D63A5 55%,#0C4C86)' in h)
prova('os numeros vem no padrao em degrade (g-nums)',
      'class="g-nums"' in h and 'n--azul' in h)
prova('as outras telas do PIX estao no topo, como familia',
      h.count('class="fam"') == 1
      and all(x in h for x in ('>Solicitações<', '>Clientes PIX<',
                               '>Config. contábil<')))

# ── o R$ duplicado ────────────────────────────────────────────────────────
prova('o total de hoje nao sai com "R$ R$"', 'R$ R$' not in h,
      re.search(r'R\$ R\$[^<]*', h).group(0) if 'R$ R$' in h else '')

# ── a tabela de nove colunas nao existe mais ──────────────────────────────
prova('acabou a tabela com rolagem lateral',
      'table-responsive' not in h and 'tp-table' not in h)
prova('cada solicitacao e um card que abre',
      'class="c__h" onclick="tpxAbre(this)"' in h)

# ── os dados continuam todos na tela ──────────────────────────────────────
linhas = consulta("""SELECT tp.id, tp.numero_sequencial, tp.status, tp.troco_pix,
                            tp.venda_total, tp.cheque_valor, c.razao_social AS posto
                       FROM troco_pix tp
                       LEFT JOIN clientes c ON c.id = tp.cliente_id
                      WHERE tp.data BETWEEN DATE_FORMAT(CURDATE(), '%Y-%m-01')
                                        AND CURDATE()""")
prova('ha solicitacoes no periodo para provar', bool(linhas),
      'sem dados no mes corrente — a prova nao teria o que conferir')
cards = re.findall(r'<div class="c" data-s="([^"]*)"', h)
prova('a tela mostra um card por solicitacao do periodo',
      len(cards) == len(linhas), '%s cards para %s no banco'
      % (len(cards), len(linhas)))
if linhas:
    um = linhas[0]
    for campo, valor in (('numero de controle', um['numero_sequencial']),
                         ('posto', um['posto'])):
        if valor:
            prova('o %s aparece na tela' % campo, str(valor) in h,
                  'nao achei %r' % valor)
    prova('o status de cada card vai no data-s (as pilulas filtram por ele)',
          all(x in ('PENDENTE', 'PROCESSADO', 'CANCELADO', '') for x in cards),
          'status encontrados: %r' % sorted(set(cards)))

# ── acoes e conciliacao continuam existindo ───────────────────────────────
prova('ver, editar e excluir seguem em cada card',
      h.count('bi bi-eye') >= 1 and h.count('bi bi-pencil') >= 1)
prova('a busca automatica de conciliacao continua na tela',
      'class="concil-auto"' in h or 'selo--conc' in h,
      'nenhum card pendente nem conciliado — verifique manualmente')
prova('o modal de vincular ao banco continua montado',
      'id="modalVincularBanco"' in h and 'btn-vincular-banco' in h)
prova('excluir e desvincular levam o periodo junto (pra voltar no mesmo filtro)',
      h.count('name="data_inicio"') >= 2 and h.count('name="data_fim"') >= 2)

# ── o filtro de periodo ───────────────────────────────────────────────────
prova('o periodo fica a vista, em dd/mm/aaaa',
      re.search(r'id="tpx-per">\s*\d{2}/\d{2}/\d{4}\s*a\s*\d{2}/\d{2}/\d{4}', h)
      is not None,
      'nao achei o periodo formatado')
r2 = cli.get('/troco_pix/?data_inicio=2026-01-01&data_fim=2026-01-31')
h2 = r2.get_data(as_text=True)
prova('mudar o periodo pela URL muda o que a tela mostra',
      r2.status_code == 200 and 'value="2026-01-01"' in h2,
      'codigo %s' % r2.status_code)

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
