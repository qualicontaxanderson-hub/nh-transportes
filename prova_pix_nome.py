# -*- coding: utf-8 -*-
"""Prova do casamento de nome do comprovante PIX.

Dois PIX ficaram com o envelope vermelho e a causa era so o fim do nome: o
aviso da Cora diz "MARCIO MENDES LTDA" e o cliente PIX esta cadastrado como
"MARCIO MENDES". Valor igual, dia igual, envelope vermelho.

O risco de afrouxar a comparacao e colar um comprovante na solicitacao
ERRADA -- prova de pagamento no registro de outra pessoa. Entao aqui se prova
tanto o que TEM de casar quanto o que NAO PODE casar, e a segunda metade e a
que importa.

Nao escreve nada: so le, e roda a funcao de casamento contra as linhas reais.

    python prova_pix_nome.py
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.db import get_db_connection                 # noqa: E402
from integrations import pix_email as px               # noqa: E402

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


# ── o que TEM de casar ───────────────────────────────────────────────────
IGUAIS = [
    ('MARCIO MENDES LTDA',                'MARCIO MENDES'),
    ('MENESES E MENESES TRANSPORTES LTDA', 'MENESES E MENESES TRANSPORTES'),
    ('POSTO BOM JESUS LTDA ME',           'POSTO BOM JESUS'),
    ('TRANSPORTES SILVA EIRELI',          'TRANSPORTES SILVA'),
    ('COMERCIAL AGUIA EPP',               'COMERCIAL AGUIA'),
    ('Maikon Jorge de Oliveira',          'MAIKON JORGE DE OLIVEIRA'),
    ('JOSÉ GOMES VIEIRA JÚNIOR',          'JOSE GOMES VIEIRA JUNIOR'),
    ('WESLEY  LUIZ   COSTA',              'WESLEY LUIZ COSTA'),
]
erros = [(a, b) for a, b in IGUAIS if not px._mesmo_nome(a, b)]
prova('o mesmo nome com e sem a terminação casa', not erros, '%r' % erros)

# ── o que NAO PODE casar ─────────────────────────────────────────────────
# Esta lista e a que protege o dinheiro. Colar um comprovante na solicitacao
# errada e pior do que deixar o envelope vermelho: o vermelho alguem resolve,
# o errado ninguem percebe.
DIFERENTES = [
    ('MARCIO MENDES LTDA',       'MARCIO MENDONCA'),
    ('MARCIO MENDES LTDA',       'MARCIA MENDES'),
    ('JOSE CARLOS DA SILVA',     'JOSE CARLOS DE SOUZA'),
    ('MARIA SA',                 'MARIA SANTOS'),
    ('MARIA SA',                 'MARIA'),
    ('JOSE',                     'JOSE CARLOS DA SILVA'),
    ('ANA LIMA',                 'ANA LIMA SOBRINHO'),
    ('TRANSPORTES SILVA LTDA',   'TRANSPORTES SILVEIRA'),
    ('',                         'MARCIO MENDES'),
    ('MARCIO MENDES',            ''),
]
erros = [(a, b) for a, b in DIFERENTES if px._mesmo_nome(a, b)]
prova('nomes de pessoas diferentes NÃO casam', not erros,
      'casou indevidamente: %r' % erros)

prova('"MARIA SA" não vira "MARIA" — SA ali é sobrenome',
      px._nucleo('MARIA SA') == 'MARIA SA',
      'virou %r' % px._nucleo('MARIA SA'))
prova('mas "TRANSPORTES REUNIDOS SA" perde o SA',
      px._nucleo('TRANSPORTES REUNIDOS SA') == 'TRANSPORTES REUNIDOS',
      'virou %r' % px._nucleo('TRANSPORTES REUNIDOS SA'))
prova('nome idêntico vale mais que nome parecido',
      px._mesmo_nome('MARCIO MENDES', 'MARCIO MENDES')
      > px._mesmo_nome('MARCIO MENDES LTDA', 'MARCIO MENDES'))

# ── contra as linhas de verdade ──────────────────────────────────────────
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
try:
    cur.execute("""SELECT id, enviado_em, valor, favorecido, troco_pix_id
                     FROM troco_pix_comprovantes
                    WHERE troco_pix_id IS NULL
                    ORDER BY enviado_em DESC LIMIT 20""")
    orfaos = cur.fetchall()
    prova('há comprovante órfão para testar', bool(orfaos),
          'sem órfão, a prova não testaria o caso que motivou a correção')

    achados = []
    for o in orfaos:
        alvo = px.casar(cur, float(o['valor']), o['favorecido'], o['enviado_em'])
        if alvo:
            cur.execute("""SELECT tp.data, tp.troco_pix, tpc.nome_completo
                             FROM troco_pix tp
                             LEFT JOIN troco_pix_clientes tpc
                               ON tpc.id = tp.troco_pix_cliente_id
                            WHERE tp.id = %s""", (alvo,))
            s = cur.fetchone()
            achados.append((o['favorecido'], s['nome_completo'],
                            float(o['valor']), alvo))
    prova('os órfãos de hoje encontram a solicitação deles', bool(achados),
          'nenhum dos %s órfãos casou — a correção não pegou' % len(orfaos))
    for e, d, v, i in achados:
        print('        "%s"  ->  "%s"   R$ %.2f   solicitação %s' % (e, d, v, i))

    # e o valor continua tendo de bater: nome certo com valor errado nao casa
    if orfaos:
        o = orfaos[0]
        errado = px.casar(cur, float(o['valor']) + 13.37, o['favorecido'],
                          o['enviado_em'])
        prova('nome certo com valor diferente não casa', errado is None,
              'casou com a solicitação %s mesmo com o valor errado' % errado)
        antigo = px.casar(cur, float(o['valor']), o['favorecido'],
                          o['enviado_em'], dias=0)
        cur.execute("""SELECT DATE(%s) = (SELECT tp.data FROM troco_pix tp
                                           WHERE tp.id = %s) AS mesmo""",
                    (o['enviado_em'], antigo or 0))
        prova('a janela de dias continua valendo',
              antigo is None or (cur.fetchone() or {}).get('mesmo') == 1,
              'com janela zero casou com solicitação de outro dia')
finally:
    cur.close()
    conn.close()

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
