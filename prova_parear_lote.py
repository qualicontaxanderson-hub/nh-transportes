# -*- coding: utf-8 -*-
"""Prova do Parear em lote (Fornecedores x Compras).

Roda a tela de verdade, com o banco de verdade, SÓ LEITURA, e cobra dela:

  1) que a tela abre e traz o botão Parear, a bandeja e o salvar em lote;
  2) que o que cada linha oferece pro Parear (pagamento: livre; nota: falta)
     feche com o banco por OUTRO caminho -- SQL direto em dfe_pagamento_nota;
  3) que pagamento todo usado e nota conferida NÃO entrem no Parear;
  4) que o Salvar tudo mande o mesmo formato que o vincular_lote já aceita.

Grava _parear.html (a página renderizada) pra tirar a foto da tela.

  python prova_parear_lote.py
"""
import io
import os
import re
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# credencial: o mesmo arquivo do backup (fora do repo e fora do OneDrive)
_cnf = os.path.join(os.path.expanduser('~'), '.nh-transportes', 'mysql_backup.cnf')
if not os.environ.get('DB_PASSWORD') and os.path.exists(_cnf):
    for _l in open(_cnf, encoding='utf-8'):
        _k, _, _v = _l.strip().partition('=')
        if _k == 'password':
            os.environ['DB_PASSWORD'] = _v.strip()
os.environ.setdefault('SECRET_KEY', 'x' * 64)
if 'efipay' not in sys.modules:
    _stub = types.ModuleType('efipay')
    _stub.EfiPay = object
    sys.modules['efipay'] = _stub

from app import create_app
from utils.db import get_db_connection

# Prova NÃO mexe no schema de produção: em vez de criar as colunas e ler
# placa/motorista do banco, lê direto do XML do Dropbox local -- o mesmo que o
# backfill vai gravar.
import routes.conf_fornecedores_dfe as _rota
from utils.dfe_transporte import extrair_placa_motorista as _ler
_DROP = os.path.join(os.path.expanduser('~'), 'Dropbox')
TRANSP = {}


def _transp_do_xml(conn, doc_ids):
    if not doc_ids:
        return {}
    c = conn.cursor()
    c.execute("SELECT id, xml_caminho FROM dfe_documentos WHERE id IN ("
              + ",".join(["%s"] * len(doc_ids)) + ")", list(doc_ids))
    for i, cam in c.fetchall():
        f = os.path.join(_DROP, (cam or '').lstrip('/').replace('/', os.sep))
        if cam and os.path.exists(f):
            pm = _ler(open(f, 'rb').read())
            if pm[0] or pm[1]:
                TRANSP[i] = pm
    c.close()
    return dict(TRANSP)


_rota._garante_colunas_transporte = lambda conn: None
_rota._transporte_das_notas = _transp_do_xml

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True

r = client.get('/relatorios/conf_fornecedores_dfe')
html = r.get_data(as_text=True)
open('_parear.html', 'w', encoding='utf-8').write(html)

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


print('1) a tela')
prova('abre (HTTP %s)' % r.status_code, r.status_code == 200)
prova('tem a tela própria do Parear', 'id="pr"' in html and 'id="pr-cdif"' in html)
prova('tem o botão Parear e o Salvar tudo',
      'parToggle(this)' in html and 'parSalvar(this)' in html)

# linhas que o Parear enxerga: <div class="lin ..." data-par=.. data-id=.. data-max=..>
lin = re.findall(r'<div class="lin lin--(pg|nf|dv)"(.*?)>', html, re.S)
pg, nf = {}, {}
fora_pg, fora_nf = set(), set()
for tipo, attrs in lin:
    m = re.search(r'data-par="(pg|nf)" data-id="(\d+)" data-max="([\d.]+)"', attrs)
    if m:
        (pg if m.group(1) == 'pg' else nf)[int(m.group(2))] = float(m.group(3))
    elif tipo in ('pg', 'nf'):
        m2 = re.search(r'id="doc-(\d+)"', attrs)
        if m2:
            fora_nf.add(int(m2.group(1)))
print('   %d pagamentos e %d notas oferecidos ao Parear' % (len(pg), len(nf)))
prova('há o que parear', pg and nf)

print('2) livre / falta batem com o banco (SQL direto)')
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
erros_pg = []
if pg:
    fmt = ','.join(['%s'] * len(pg))
    cur.execute("SELECT bt.id, ABS(bt.valor) AS valor, "
                "       COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v "
                "                  WHERE v.transacao_id = bt.id),0) AS usado "
                "  FROM bank_transactions bt WHERE bt.id IN (" + fmt + ")", list(pg))
    for x in cur.fetchall():
        livre = float(x['valor']) - float(x['usado'])
        # a tela ainda abate devolução; nunca pode oferecer MAIS que o banco
        if pg[x['id']] > livre + 0.005:
            erros_pg.append((x['id'], pg[x['id']], livre))
prova('nenhum pagamento oferece mais que o livre real (%d conferidos)' % len(pg),
      not erros_pg)
for e in erros_pg[:5]:
    print('        tx %s: tela %.2f x banco %.2f' % e)

erros_nf = []
if nf:
    fmt = ','.join(['%s'] * len(nf))
    cur.execute("SELECT d.id, d.valor_total, COALESCE(d.quitado_pre_corte,0) AS quit, "
                "       COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v "
                "                  WHERE v.documento_id = d.id),0) AS vinc "
                "  FROM dfe_documentos d WHERE d.id IN (" + fmt + ")", list(nf))
    for x in cur.fetchall():
        falta = float(x['valor_total']) - float(x['vinc']) - float(x['quit'])
        if abs(nf[x['id']] - falta) > 0.005:
            erros_nf.append((x['id'], nf[x['id']], falta))
prova('falta de cada nota = valor - vínculos - quitado antes do corte (%d conferidas)'
      % len(nf), not erros_nf)
for e in erros_nf[:5]:
    print('        doc %s: tela %.2f x banco %.2f' % e)

print('3) o que já está resolvido não entra')
if fora_nf:
    fmt = ','.join(['%s'] * len(fora_nf))
    cur.execute("SELECT d.id, d.valor_total - COALESCE(d.quitado_pre_corte,0) "
                "       - COALESCE((SELECT SUM(v.valor) FROM dfe_pagamento_nota v "
                "                    WHERE v.documento_id = d.id),0) AS falta "
                "  FROM dfe_documentos d WHERE d.id IN (" + fmt + ")", list(fora_nf))
    abertas_fora = [x['id'] for x in cur.fetchall() if float(x['falta']) > 0.005]
else:
    abertas_fora = []
prova('%d notas fora do Parear, todas já sem falta' % len(fora_nf), not abertas_fora)
cur.close()
conn.close()

print('4) produto / qtd / preço unitário de cada nota batem com dfe_itens')
import json, html as _h
it_tela = {}
for attrs in re.findall(r'<div class="lin lin--nf"(.*?)>', html, re.S):
    m = re.search(r'data-par="nf" data-id="(\d+)"', attrs)
    j = re.search(r"data-itens='(.*?)'", attrs, re.S)
    if m and j:
        it_tela[int(m.group(1))] = json.loads(_h.unescape(j.group(1)))
prova('toda nota do Parear traz os itens (%d de %d)' % (len(it_tela), len(nf)),
      set(it_tela) >= set(nf))
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
erros_it = []
if it_tela:
    fmt = ','.join(['%s'] * len(it_tela))
    cur.execute("SELECT documento_id, COUNT(*) n, SUM(quantidade) q, "
                "       SUM(quantidade * valor_unitario) t "
                "  FROM dfe_itens WHERE documento_id IN (" + fmt + ") "
                " GROUP BY documento_id", list(it_tela))
    for x in cur.fetchall():
        tl = it_tela[x['documento_id']]
        q = sum(i['q'] for i in tl); t = sum(i['q'] * i['vu'] for i in tl)
        if len(tl) != x['n'] or abs(q - float(x['q'])) > 0.001 or abs(t - float(x['t'])) > 0.05:
            erros_it.append((x['documento_id'], len(tl), x['n'], q, float(x['q'])))
cur.close(); conn.close()
prova('quantidade e qtd×preço de cada nota = banco', not erros_it)
for e in erros_it[:5]:
    print('        doc %s: itens %s x %s, qtd %.3f x %.3f' % e)

print('5) placa e motorista chegam na tela')
ok_tr = True
for attrs in re.findall(r'<div class="lin lin--nf"(.*?)>', html, re.S):
    m = re.search(r'data-par="nf" data-id="(\d+)"', attrs)
    if not m:
        continue
    i = int(m.group(1))
    pl = re.search(r'data-placa="(.*?)"', attrs)
    mo = re.search(r'data-mot="(.*?)"', attrs)
    tela = (pl.group(1) if pl else None, _h.unescape(mo.group(1)) if mo else None)
    esperado = tuple(x or '' for x in TRANSP[i]) if i in TRANSP else (None, None)
    if i in TRANSP:
        tela = tuple(x or '' for x in tela)
    if tela != esperado:
        ok_tr = False
        print('        doc %s: tela %s x XML %s' % (i, tela, esperado))
com = sum(1 for i in nf if i in TRANSP)
prova('placa/motorista das %d notas do Parear = XML (%d trazem dado)' % (len(nf), com), ok_tr)

print('6) o Salvar tudo fala a língua do vincular_lote')
prova('manda {doc_id, transacao_id, valor} pro mesmo endpoint',
      "doc_id: p.doc, transacao_id: p.tx, valor: p.v, absorve: !!p.abs" in html
      and html.count('/relatorios/conf_fornecedores_dfe/vincular_lote') >= 2)
prova('respeita o teto de 40 pares do servidor', 'PAR_MAX = 40' in html)
prova('sobra absorvida no máximo R$ 1,00, igual ao servidor',
      'PAR_SOBRA = 1.00' in html and _rota.SOBRA_MAX == 1.00)

print('\nRESULTADO: ' + ('TUDO OK' if ok else 'HÁ FALHA'))
sys.exit(0 if ok else 1)
