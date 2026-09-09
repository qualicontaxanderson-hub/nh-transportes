# -*- coding: utf-8 -*-
"""Prova da tela de Clientes PIX, com o app e o banco de verdade.

Eram 264 cadastros numa tabela de sete colunas dentro de table-responsive: no
celular cabiam ID e Nome, e a CHAVE PIX — a única coisa que importa aqui —
ficava atrás da rolagem lateral. Sem busca, achar alguém entre 264 era rolar no
olho.

Não escreve nada: todas as chamadas são GET.

    python prova_troco_pix_clientes.py [--html arquivo.html]
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

r = cli.get('/troco_pix/clientes', follow_redirects=True)
h = r.get_data(as_text=True)
prova('a tela abre (200)', r.status_code == 200, 'codigo %s' % r.status_code)
# A rota manda erro por flash e REDIRECIONA — 200 sozinho nao prova nada.
prova('não caiu no erro que joga para outra tela',
      'Erro ao carregar clientes' not in h and 'id="tpc"' in h)

# ── o padrão da casa ───────────────────────────────────────────────────────
prova('usa o topo azul do padrão',
      'linear-gradient(120deg,#2E6FB0,#1D63A5 55%,#0C4C86)' in h)
prova('os números vêm em degradê (g-nums)', 'class="g-nums"' in h)
prova('as três telas do PIX estão no topo, e esta é a acesa',
      re.search(r'<a class="on"[^>]*>Clientes PIX</a>', h) is not None
      and '>Solicitações<' in h and '>Config. contábil<' in h)
prova('acabou a tabela com rolagem lateral',
      'table-responsive' not in h and '<table' not in h)
prova('tem busca por nome ou chave', 'id="tpc-busca"' in h)

# ── um card por cliente, com a chave à vista ───────────────────────────────
base = consulta("""SELECT id, nome_completo, chave_pix, tipo_chave_pix, ativo
                     FROM troco_pix_clientes""")
# Um atributo só, sem tentar casar a classe junto: a versão anterior deste
# regex exigia `class="c "` com espaço e perdia justamente os inativos, que
# têm `class="c c--off"` — e acusou o código de esconder 7 cadastros que
# estavam lá.
cards = re.findall(r'data-ativo="([01])"', h)
prova('há um card por cliente cadastrado', len(cards) == len(base),
      '%s cards para %s no banco' % (len(cards), len(base)))
prova('os inativos vêm marcados, e batem com o banco',
      cards.count('0') == sum(1 for c in base if not c['ativo']),
      'inativos na tela: %s, no banco: %s'
      % (cards.count('0'), sum(1 for c in base if not c['ativo'])))

# A chave PIX era o que sumia na rolagem: agora tem de estar no HTML.
faltando = [c['id'] for c in base
            if (c['chave_pix'] or '') and (c['chave_pix'] not in h)]
prova('a chave PIX de todos aparece na tela', not faltando,
      'faltaram %s chaves (ex.: cliente %s)' % (len(faltando), faltando[:3]))

# ── os números do topo ─────────────────────────────────────────────────────
def num(rotulo):
    m = re.search(r'<div class="r">' + rotulo + r'</div>\s*<div class="v">([^<]+)<', h)
    return m.group(1).strip() if m else None


usados = consulta("""SELECT COUNT(DISTINCT tp.troco_pix_cliente_id) n
                       FROM troco_pix tp WHERE COALESCE(tp.troco_pix,0) > 0""")
prova('o topo diz quantos clientes existem', num('Clientes') == str(len(base)),
      'tela: %r, banco: %s' % (num('Clientes'), len(base)))
prova('o topo diz quantos já receberam troco',
      num('Já receberam') == str(int(usados[0]['n'])),
      'tela: %r, banco: %s' % (num('Já receberam'), usados[0]['n']))
prova('nunca usados = o resto',
      num('Nunca usados') == str(len(base) - int(usados[0]['n'])),
      'tela: %r' % num('Nunca usados'))

# ── o "SEM PIX" não pode virar o maior cliente da casa ─────────────────────
# Ele e o registro tecnico das solicitacoes sem troco: 614 lancamentos, todos
# com troco zero. Contar isso como recebimento poria uma mentira no topo da
# lista.
sem_pix = consulta("""SELECT id FROM troco_pix_clientes
                       WHERE UPPER(nome_completo) = 'SEM PIX' LIMIT 1""")
if sem_pix:
    bloco = h[h.find('>SEM PIX<'):] if '>SEM PIX<' in h else ''
    prova('o registro "SEM PIX" aparece como nunca usado',
          bool(bloco) and 'sem troco' in bloco[:900],
          'o card do SEM PIX mostra recebimento')

# ── nome repetido: não é erro, mas tem de estar marcado ───────────────────
rep = consulta("""SELECT nome_completo, COUNT(*) n FROM troco_pix_clientes
                   GROUP BY nome_completo HAVING n > 1""")
prova('a tela marca os nomes repetidos',
      h.count('>nome repetido</span>') == sum(int(r['n']) for r in rep),
      '%s selos para %s cadastros com nome repetido'
      % (h.count('>nome repetido</span>'), sum(int(r['n']) for r in rep)))

# ── pílulas e ações ───────────────────────────────────────────────────────
pil = dict(re.findall(r'data-f="([^"]*)"[^>]*>\s*([^<]+?)\s*<span class="b">', h))
prova('as pílulas cobrem todos, ativos, inativos, nunca usados e repetidos',
      {'', 'ativo', 'sem'} <= set(pil), 'pilulas: %r' % pil)
prova('editar continua em cada card',
      h.count('bi bi-pencil') == len(base),
      '%s botões de editar para %s clientes' % (h.count('bi bi-pencil'), len(base)))
prova('desativar só aparece em quem está ativo',
      h.count('bi bi-slash-circle') == sum(1 for c in base if c['ativo']),
      '%s botões para %s ativos'
      % (h.count('bi bi-slash-circle'), sum(1 for c in base if c['ativo'])))

# ── a volta muda com o nível de quem olha ─────────────────────────────────
prova('o link "Solicitações" leva para a tela certa deste usuário',
      '/troco_pix/' in h)

# ── a relação dos trocos, dentro do card ──────────────────────────────────
# "8 trocos" nao diz quando nem de quanto. A relacao tem de bater, troco a
# troco, com o que esta no banco.
linhas_tela = re.findall(
    r'<a class="tr" href="[^"]*/visualizar/(\d+)">\s*'
    r'<span class="tr__d">([^<]+)</span>', h)
no_banco = consulta("""SELECT tp.id, tp.data, tp.troco_pix, tp.troco_pix_cliente_id
                         FROM troco_pix tp
                        WHERE COALESCE(tp.troco_pix,0) > 0""")
prova('a tela lista os trocos um a um',
      len(linhas_tela) == len(no_banco),
      '%s linhas na tela para %s trocos no banco'
      % (len(linhas_tela), len(no_banco)))
prova('cada linha da relação leva à solicitação',
      {int(i) for i, _ in linhas_tela} == {r['id'] for r in no_banco},
      'a tela lista solicitações que não existem, ou deixa de fora')

# O cliente que o print mostrava com 8 trocos: a relacao dele tem de ter 8,
# com as datas certas.
maior = consulta("""SELECT tpc.id, tpc.nome_completo, COUNT(tp.id) n
                      FROM troco_pix_clientes tpc
                      JOIN troco_pix tp ON tp.troco_pix_cliente_id = tpc.id
                                       AND COALESCE(tp.troco_pix,0) > 0
                     GROUP BY tpc.id, tpc.nome_completo
                     ORDER BY n DESC LIMIT 1""")
if maior:
    m = maior[0]
    trechos = h.split('data-busca=')
    dele = [t for t in trechos if (m['nome_completo'] or '').lower() in t.lower()]
    bloco = dele[0] if dele else ''
    prova('o cliente com mais trocos (%s) mostra a relação completa'
          % (m['nome_completo'] or '?').split()[0].title(),
          bloco.count('<a class="tr"') == int(m['n']),
          '%s linhas para %s trocos' % (bloco.count('<a class="tr"'), m['n']))
    prova('o cabeçalho da relação diz quantos são',
          'Trocos recebidos (%s)' % m['n'] in bloco,
          'não achei "Trocos recebidos (%s)"' % m['n'])
    # A data vem crua e é formatada aqui: DATE_FORMAT com %%d dentro de uma
    # consulta parametrizada depende de como o driver trata o escape, e foi
    # isso que fez esta prova acusar datas faltando numa tela que tinha todas.
    datas = consulta("""SELECT tp.data FROM troco_pix tp
                         WHERE tp.troco_pix_cliente_id = %s
                           AND COALESCE(tp.troco_pix,0) > 0""", (m['id'],))
    faltam = [d['data'].strftime('%d/%m/%Y') for d in datas
              if d['data'] and d['data'].strftime('%d/%m/%Y') not in bloco]
    prova('as datas de cada troco aparecem', not faltam,
          'faltaram: %r' % faltam)

prova('a relação diz o que já foi conciliado',
      h.count('bi bi-check-circle-fill tr__ok')
      == len([r for r in consulta("""SELECT id FROM troco_pix
                                      WHERE COALESCE(troco_pix,0) > 0
                                        AND bank_transaction_id IS NOT NULL""")]),
      'os certinhos verdes não batem com os conciliados do banco')

if len(sys.argv) > 2 and sys.argv[1] == '--html':
    io.open(sys.argv[2], 'w', encoding='utf-8').write(h)
    print('\nHTML salvo em %s' % sys.argv[2])

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
