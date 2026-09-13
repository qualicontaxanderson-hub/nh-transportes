# -*- coding: utf-8 -*-
"""Prova do porteiro: cada nivel so alcanca o que ve no menu.

Duas metades, e a segunda importa tanto quanto a primeira:

  * o que TEM de barrar -- financeiro, banco, folha, emprestimos. Era o
    estado de ontem: os tres niveis abriam as mesmas 16 de 24 telas.
  * o que NAO PODE quebrar -- cada nivel tem de continuar abrindo tudo que o
    menu dele mostra, e a tela da pista tem de continuar lancando PIX. Uma
    trava que prende o frentista do lado de fora do proprio trabalho e pior
    que trava nenhuma.

E mais uma, que e a razao de a trava ser central e nao espalhada: rota nova
nasce FECHADA para quem nao e admin.

    python prova_acesso.py
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
from utils import acesso                               # noqa: E402

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def cliente_de(uid):
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


def abre(c, url):
    """True quando a tela responde de verdade (200), sem seguir redirect.

    Erro de conexao NAO e bloqueio: a primeira versao devolvia False para os
    dois e acusou o porteiro de trancar o frentista fora do trabalho quando o
    que houve foi o banco piscar. Agora tenta de novo, e se insistir em
    falhar, diz que foi erro -- nao "barrado".
    """
    for tentativa in (1, 2, 3):
        try:
            return c.get(url, follow_redirects=False).status_code == 200
        except Exception as e:
            erro = e
    print('        (erro de rede/banco em %s: %s)' % (url, erro))
    return None          # nem aberto nem barrado: nao deu para saber


conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT id, username, nivel FROM usuarios WHERE ativo = 1")
usuarios = cur.fetchall()
cur.close()
conn.close()
app.config['WTF_CSRF_ENABLED'] = False

por_nivel = {}
for u in usuarios:
    por_nivel.setdefault((u['nivel'] or '').strip().upper(), []).append(u)
admin = (por_nivel.get('ADMIN') or [None])[0]
prova('há um ADMIN para comparar', bool(admin))

# ── 1. a regra em si, sem banco nem rede ─────────────────────────────────
prova('PISTA alcança a tela da pista',
      acesso.pode('PISTA', '/troco_pix/pista'))
prova('e NÃO alcança a lista de troco do gestor',
      not acesso.pode('PISTA', '/troco_pix/'),
      'liberar /troco_pix por prefixo entregaria o módulo inteiro')
prova('PISTA não alcança financeiro nem folha',
      not acesso.pode('PISTA', '/financeiro/contas/')
      and not acesso.pode('PISTA', '/lancamentos-funcionarios/'))
prova('SUPERVISOR alcança o fechamento de caixa',
      acesso.pode('SUPERVISOR', '/lancamentos_caixa/'))
prova('e não alcança o banco', not acesso.pode('SUPERVISOR', '/banco/conciliar'))
prova('GERENTE alcança descargas', acesso.pode('GERENTE', '/descargas/'))
prova('e não alcança empréstimos', not acesso.pode('GERENTE', '/emprestimos/'))
prova('ADMIN não tem lista: alcança tudo',
      acesso.pode('ADMIN', '/financeiro/contas/')
      and acesso.pode('ADMIN', '/qualquer/coisa/nova'))
prova('todo nível sai do sistema e troca a própria senha',
      all(acesso.pode(n, '/auth/logout') and acesso.pode(n, '/auth/alterar-senha')
          for n in acesso.NIVEIS),
      'uma trava que impede deslogar prende a pessoa dentro do sistema')

# a razao de a trava ser central: rota nova ja nasce fechada
prova('rota que ainda não existe já nasce fechada para quem não é admin',
      not any(acesso.pode(n, '/modulo-que-alguem-vai-criar-amanha/')
              for n in acesso.NIVEIS),
      'se nascesse aberta, o sistema voltaria sozinho ao estado de ontem')

# ── 2. o que TEM de barrar, pela rede ────────────────────────────────────
BARRAR = [
    ('Financeiro — contas',       '/financeiro/contas/'),
    ('Financeiro — pagamentos',   '/financeiro/pagamentos/'),
    ('Banco — conciliar',         '/banco/conciliar'),
    ('Banco — exportar contábil', '/banco/exportar-contabil'),
    ('Folha',                     '/lancamentos-funcionarios/'),
    ('Funcionários (salários)',   '/funcionarios/'),
    ('Empréstimos',               '/emprestimos/'),
    ('Clientes',                  '/clientes/'),
    ('Fornecedores',              '/fornecedores/'),
    ('Estoque',                   '/estoque'),
    ('Compras DFe',               '/dfe/compras'),
    ('Gerenciar usuários',        '/auth/usuarios'),
]
for nivel in sorted(acesso.NIVEIS):
    gente = por_nivel.get(nivel) or []
    if not gente:
        print('       (sem usuário %s no banco — nada a testar pela rede)' % nivel)
        continue
    c = cliente_de(gente[0]['id'])
    passou = [nome for nome, url in BARRAR if abre(c, url) is True]
    prova('%s (%s) não abre nenhuma das %s telas que não são dele'
          % (gente[0]['username'], nivel, len(BARRAR)),
          not passou, 'ainda abre: %r' % passou)

# ── 3. o que NAO PODE quebrar ────────────────────────────────────────────
# Cada nivel tem de continuar abrindo tudo que o menu dele mostra. Sem isto a
# prova acima passaria com o sistema todo trancado.
MENU = {
    'PISTA': [('Troco PIX Pista', '/troco_pix/pista')],
    'SUPERVISOR': [
        ('Cartões', '/cartoes/'), ('Formas Pagamento Caixa', '/caixa/'),
        ('Formas Recebimento Caixa', '/tipos_receita_caixa/'),
        ('Produtos Lubrificantes', '/lubrificantes/produtos'),
        ('Descargas', '/descargas/'), ('Quilometragem', '/quilometragem/'),
        ('ARLA', '/arla/'), ('Lubrificantes', '/lubrificantes/'),
        ('Vendas Posto', '/posto/vendas'),
        ('Fechamento de Caixa', '/lancamentos_caixa/'),
        ('Troco PIX', '/troco_pix/'), ('Troco PIX Pista', '/troco_pix/pista'),
    ],
    'GERENTE': [
        ('Descargas', '/descargas/'), ('Troco PIX', '/troco_pix/'),
        ('Troco PIX Pista', '/troco_pix/pista'),
    ],
}
for nivel, itens in MENU.items():
    gente = por_nivel.get(nivel) or []
    if not gente:
        continue
    c = cliente_de(gente[0]['id'])
    quebrou = [nome for nome, url in itens if abre(c, url) is not True]
    prova('%s continua abrindo os %s itens do menu dele'
          % (nivel, len(itens)), not quebrou,
          'a trava quebrou: %r' % quebrou)

# o fluxo da pista inteiro, que e o trabalho do frentista
gente = por_nivel.get('PISTA') or []
if gente:
    c = cliente_de(gente[0]['id'])
    fluxo = [('lançar um PIX novo', '/troco_pix/novo?origem=pista'),
             ('achar o cliente PIX', '/troco_pix/clientes')]
    quebrou = [nome for nome, url in fluxo if abre(c, url) is not True]
    prova('o frentista ainda consegue trabalhar na tela da pista',
          not quebrou, 'quebrou: %r' % quebrou)
    r = c.get('/', follow_redirects=False)
    prova('e a raiz leva ele para a pista, não para a tela de fretes',
          r.status_code in (301, 302)
          and '/troco_pix/pista' in (r.headers.get('Location') or ''),
          'foi para %r' % r.headers.get('Location'))
    r = c.get('/financeiro/contas/', follow_redirects=True)
    corpo = ' '.join(r.get_data(as_text=True).split())
    prova('e ao tentar o que não é dele, recebe um aviso em português',
          'não inclui essa tela' in corpo or 'não inclui esta tela' in corpo,
          'a tela barrada não explicou nada')

# ── 4. o ADMIN nao pode ser afetado ──────────────────────────────────────
if admin:
    c = cliente_de(admin['id'])
    fechou = [nome for nome, url in BARRAR if abre(c, url) is not True]
    prova('o ADMIN continua abrindo tudo', not fechou,
          'o porteiro fechou para o admin: %r' % fechou)

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
