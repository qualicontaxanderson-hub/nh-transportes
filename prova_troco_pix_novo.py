# -*- coding: utf-8 -*-
"""Prova da tela de lançamento (e correção) de Troco PIX.

É a tela que grava dinheiro, e a conta dela é uma só:

    TROCO PIX = cheque − abastecimento − arla − produtos
                       − troco em espécie − crédito de venda programada

Prova em três camadas:
  1. o formulário traz todos os campos que as rotas /novo e /editar esperam;
  2. o POST grava de verdade — e cria o lançamento de caixa automático;
  3. o ciclo é desfeito pela própria rota de exclusão, e a última prova confere
     que não sobrou nada nem no troco nem no caixa.

O lançamento de prova é feito numa DATA ANTIGA de propósito: assim ele não
queima um número da sequência de hoje (PIX-DD-MM-AAAA-N…), que a casa lê e
confere. Nada do movimento real é tocado.

    python prova_troco_pix_novo.py [--html arquivo.html]
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

DATA_PROVA = '2020-01-02'          # longe de qualquer movimento real
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

# ── 1. o formulário ───────────────────────────────────────────────────────
r = cli.get('/troco_pix/novo', follow_redirects=True)
h = r.get_data(as_text=True)
prova('a tela abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
prova('não caiu no erro que joga para a listagem',
      'Erro ao carregar formulário' not in h and 'id="tpn"' in h)

# Os nomes que routes/troco_pix.py le do request.form. Se um sumir do HTML, o
# lancamento grava zero calado — por isso a lista esta escrita aqui.
esperados = ['cliente_id', 'data', 'venda_abastecimento', 'venda_arla',
             'venda_produtos', 'cheque_tipo', 'cheque_data_vencimento',
             'cheque_valor', 'troco_especie', 'troco_pix',
             'troco_credito_vda_programada', 'troco_pix_cliente_id',
             'funcionario_id']
faltando = [n for n in esperados if ('name="%s"' % n) not in h]
prova('o formulário traz todos os campos que o servidor lê', not faltando,
      'faltaram: %r' % faltando)

prova('usa o topo azul do padrão',
      'linear-gradient(120deg,#2E6FB0,#1D63A5 55%,#0C4C86)' in h)
prova('o troco por PIX aparece no rodapé, acompanhando a rolagem',
      'class="rodape"' in h and 'id="tpn-rod"' in h)
prova('os campos de dinheiro abrem o teclado numérico',
      h.count('inputmode="decimal"') >= 6,
      '%s campos com teclado numérico' % h.count('inputmode="decimal"'))
# Conta so os radios: o mesmo nome aparece no JS, e contar o arquivo todo
# dava 4 e reprovava uma tela certa.
prova('à vista e a prazo são botões, não uma lista',
      h.count('type="radio" name="cheque_tipo"') == 2
      and 'name="cheque_tipo"' not in h.split('<select')[0].split('<div class="duo">')[0],
      '%s radios de tipo de cheque' % h.count('type="radio" name="cheque_tipo"'))
prova('o cliente PIX é busca, não uma lista de 264',
      'id="tpn-busca"' in h and 'onfocus="tpnAbre()"' in h)
# A rota manda os ATIVOS (e e isso que a tela deve oferecer): cadastro
# desativado nao pode voltar a receber troco por descuido.
clientes_pix = consulta("""SELECT COUNT(*) n FROM troco_pix_clientes
                            WHERE ativo = 1""")[0]['n']
prova('a busca tem todos os clientes PIX ativos',
      h.count('"nome_completo"') == int(clientes_pix),
      '%s no JSON para %s no banco' % (h.count('"nome_completo"'), clientes_pix))
prova('o campo do vencimento começa escondido',
      'id="tpn-venc" hidden' in h)

# ── 2. o POST grava, com a conta certa ────────────────────────────────────
posto = consulta("""SELECT DISTINCT c.id, c.razao_social FROM clientes c
                      JOIN cliente_produtos cp ON c.id = cp.cliente_id
                     WHERE cp.ativo = 1 LIMIT 1""")
cpix = consulta("""SELECT id, nome_completo FROM troco_pix_clientes
                    WHERE ativo = 1 LIMIT 1""")
frent = consulta("SELECT id, nome FROM funcionarios LIMIT 1")
prova('há posto, cliente PIX e frentista para provar o lançamento',
      bool(posto and cpix and frent))

novo_id = None
lanc_id = None
try:
    if posto and cpix and frent:
        # cheque 1.500,00 − venda (900 + 30 + 20) − 50 em espécie − 100 de
        # crédito  =  400,00 de troco por PIX
        dados = {
            'cliente_id': str(posto[0]['id']),
            'data': DATA_PROVA,
            'venda_abastecimento': '900.00',
            'venda_arla': '30.00',
            'venda_produtos': '20.00',
            'cheque_tipo': 'A_VISTA',
            'cheque_valor': '1500.00',
            'troco_especie': '50.00',
            'troco_pix': '400.00',
            'troco_credito_vda_programada': '100.00',
            'troco_pix_cliente_id': str(cpix[0]['id']),
            'funcionario_id': str(frent[0]['id']),
        }
        r = cli.post('/troco_pix/novo', data=dados, follow_redirects=False)
        prova('lançar responde com o redirecionamento para a solicitação',
              r.status_code in (301, 302), 'codigo %s' % r.status_code)
        gravado = consulta("""SELECT * FROM troco_pix
                               WHERE data = %s AND cliente_id = %s
                               ORDER BY id DESC LIMIT 1""",
                           (DATA_PROVA, posto[0]['id']))
        prova('a solicitação foi gravada', bool(gravado))
        if gravado:
            g = gravado[0]
            novo_id = g['id']
            lanc_id = g.get('lancamento_caixa_id')
            prova('o troco por PIX gravado é o da conta (R$ 400,00)',
                  abs(float(g['troco_pix']) - 400.00) < 0.005,
                  'gravou %s' % g['troco_pix'])
            prova('a venda foi gravada parcela por parcela',
                  abs(float(g['venda_abastecimento']) - 900) < 0.005
                  and abs(float(g['venda_arla']) - 30) < 0.005
                  and abs(float(g['venda_produtos']) - 20) < 0.005,
                  'venda: %s / %s / %s' % (g['venda_abastecimento'],
                                           g['venda_arla'], g['venda_produtos']))
            prova('o cheque e os outros trocos também',
                  abs(float(g['cheque_valor']) - 1500) < 0.005
                  and abs(float(g['troco_especie']) - 50) < 0.005
                  and abs(float(g['troco_credito_vda_programada']) - 100) < 0.005)
            prova('ganhou número sequencial da própria data',
                  (g['numero_sequencial'] or '').startswith('PIX-02-01-2020-N'),
                  'número: %r' % g['numero_sequencial'])
            prova('e não tocou na numeração de hoje',
                  '2020' in (g['numero_sequencial'] or ''))
            prova('o lançamento de caixa automático foi criado',
                  bool(lanc_id), 'sem lancamento_caixa_id')

            # ── correção pela tela de editar ──────────────────────────────
            r = cli.get('/troco_pix/editar/%s' % novo_id, follow_redirects=True)
            he = r.get_data(as_text=True)
            prova('a tela de correção abre com os valores de lá',
                  r.status_code == 200 and 'data-raw-value="1500.00"' in he,
                  'codigo %s' % r.status_code)
            prova('e ela já mostra o cliente PIX escolhido',
                  ('value="%s"' % cpix[0]['id']) in he)
            dados2 = dict(dados)
            dados2['cheque_valor'] = '1600.00'
            dados2['troco_pix'] = '500.00'
            r = cli.post('/troco_pix/editar/%s' % novo_id, data=dados2,
                         follow_redirects=False)
            prova('corrigir responde com redirecionamento',
                  r.status_code in (301, 302), 'codigo %s' % r.status_code)
            depois = consulta("SELECT cheque_valor, troco_pix FROM troco_pix WHERE id=%s",
                              (novo_id,))[0]
            prova('a correção gravou o cheque e o troco novos',
                  abs(float(depois['cheque_valor']) - 1600) < 0.005
                  and abs(float(depois['troco_pix']) - 500) < 0.005,
                  'ficou %s / %s' % (depois['cheque_valor'], depois['troco_pix']))
finally:
    if novo_id:
        cli.post('/troco_pix/excluir/%s' % novo_id, follow_redirects=True)

# ── 3. não sobrou nada ────────────────────────────────────────────────────
sobrou = consulta("SELECT id FROM troco_pix WHERE data = %s", (DATA_PROVA,))
prova('a prova não deixou solicitação no banco', not sobrou,
      'sobraram: %r' % [x['id'] for x in sobrou])
if lanc_id:
    lanc = consulta("SELECT id FROM lancamentos_caixa WHERE id = %s", (lanc_id,))
    prova('nem lançamento de caixa', not lanc,
          'o lançamento %s continua lá' % lanc_id)

# ── 4. a tela de conferir e mandar (visualizar) ───────────────────────────
# Ela existe por dois motivos: conferir o que foi gravado e MANDAR no
# WhatsApp para quem faz o PIX.
alvo = consulta("""SELECT tp.id, tp.numero_sequencial, tp.troco_pix,
                          tp.cheque_valor, tp.venda_total, tp.troco_total,
                          tpc.nome_completo, tpc.chave_pix
                     FROM troco_pix tp
                     LEFT JOIN troco_pix_clientes tpc
                            ON tpc.id = tp.troco_pix_cliente_id
                    WHERE COALESCE(tp.troco_pix,0) > 0
                    ORDER BY tp.id DESC LIMIT 1""")
prova('há uma solicitação para conferir', bool(alvo))
if alvo:
    a = alvo[0]
    r = cli.get('/troco_pix/visualizar/%s' % a['id'], follow_redirects=True)
    hv = r.get_data(as_text=True)
    prova('a tela de conferir abre (200)', r.status_code == 200,
          'codigo %s' % r.status_code)
    prova('não caiu no erro que joga para a listagem',
          'Erro ao carregar' not in hv and 'id="tpv"' in hv)
    prova('o número da solicitação está no topo',
          (a['numero_sequencial'] or '') in hv)
    prova('o troco por PIX é o número em destaque',
          'class="resumo__v' in hv
          and ('%.2f' % float(a['troco_pix'])).replace('.', ',') in hv)
    prova('quem recebe e a chave aparecem',
          (a['nome_completo'] or '') in hv and (a['chave_pix'] or '') in hv)
    prova('o botão de WhatsApp é o principal, e continua copiando o mesmo texto',
          'class="zap"' in hv and 'btnCopyWhatsApp' in hv
          and '*TROCO PIX* 💰' in hv and '🔢 *' in hv)
    prova('a conferência do cheque menos a venda continua na tela',
          'confere--ok' in hv or 'confere--nao' in hv)
    prova('acabaram as tabelas de duas colunas',
          '<table' not in hv and 'table-responsive' not in hv)
    prova('o envelope diz se o PIX já saiu',
          'PIX enviado' in hv or 'PIX ainda não enviado' in hv)
    prova('a tela diz quem lançou e quando',
          'Lançado por' in hv)

if len(sys.argv) > 2 and sys.argv[1] == '--html':
    io.open(sys.argv[2], 'w', encoding='utf-8').write(h)
    print('\nHTML salvo em %s' % sys.argv[2])

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
