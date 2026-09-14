# -*- coding: utf-8 -*-
"""Prova da trava que impede dois boletos para o mesmo frete.

O frete #2830 saiu com duas cobrancas e o cliente pagou uma. A conferencia
que existia olhava cobrancas.frete_id -- nula em toda emissao do caminho de
varios fretes, que e o usado na tela. O cinto nao prendia nada.

O que se prova, contra o banco REAL e sem emitir boleto nenhum:

  * o frete #2830 e reconhecido como JA COBRADO (era o que falhava);
  * um frete cobrado pela ponte, com frete_id nulo, tambem e reconhecido --
    se a prova so usasse frete_id, passaria sem testar o bug;
  * frete sem cobranca continua liberado (a trava nao pode travar tudo);
  * cobranca cancelada nao barra: senao ninguem reemite depois de cancelar;
  * a trava por frete (GET_LOCK) so deixa um passar por vez;
  * os dois nomes de tabela ponte sao olhados.

Nao escreve nada em cobrancas nem fala com a Efi: so le e usa GET_LOCK.

    python prova_boleto_trava.py
"""
import io
import os
import re
import sys
import types

if not os.environ.get('DB_PASSWORD') and os.path.exists('bakup_railway.bat'):
    _m = re.search(r'set DBPASS=(.+)',
                   io.open('bakup_railway.bat', encoding='latin-1').read(), re.I)
    if _m:
        os.environ['DB_PASSWORD'] = _m.group(1).strip()
os.environ.setdefault('SECRET_KEY', 'x' * 64)

# a maquina daqui nao tem o SDK da Efi; a trava nao usa o SDK, entao um
# boneco basta para o modulo importar
if 'efipay' not in sys.modules:
    _stub = types.ModuleType('efipay')
    _stub.EfiPay = object
    sys.modules['efipay'] = _stub

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.db import get_db_connection                  # noqa: E402
from utils import boletos                               # noqa: E402

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


conn = get_db_connection()
cur = conn.cursor(dictionary=True)

# ── o caso que doeu ──────────────────────────────────────────────────────
r = boletos._cobranca_ativa_do_frete(cur, 2830)
prova('o frete #2830 e reconhecido como ja cobrado', bool(r),
      'a trava deixaria nascer um terceiro boleto')
if r:
    print('        barrado por: cobranca %s, charge %s, status %s'
          % (r.get('id'), r.get('charge_id'), r.get('status')))

# ── e o caso GERAL: cobranca ligada so pela ponte, com frete_id nulo ─────
# Se a prova usasse um frete de frete_id preenchido, ela passaria mesmo com
# o codigo velho -- e nao teria testado nada.
cur.execute("""SELECT cf.frete_id, c.id cob, c.charge_id, c.status
                 FROM cobrancas_freites cf JOIN cobrancas c ON c.id = cf.cobranca_id
                WHERE c.frete_id IS NULL
                  AND (c.status IS NULL OR c.status <> 'cancelado')
                ORDER BY c.id DESC LIMIT 5""")
pela_ponte = cur.fetchall()
prova('ha caso de cobranca ligada so pela ponte para testar', bool(pela_ponte),
      'sem isso a prova nao exercita o bug')
erros = []
for x in pela_ponte:
    if not boletos._cobranca_ativa_do_frete(cur, x['frete_id']):
        erros.append((x['frete_id'], x['cob']))
prova('cobranca ligada so pela ponte tambem barra (o bug de verdade)',
      not erros, 'passaram batido: %r' % erros)
if pela_ponte:
    print('        conferidos %d fretes com cobrancas.frete_id NULL'
          % len(pela_ponte))

# ── a trava nao pode travar tudo ────────────────────────────────────────
cur.execute("""SELECT f.id FROM fretes f
                WHERE f.id NOT IN (SELECT COALESCE(frete_id,0) FROM cobrancas)
                  AND f.id NOT IN (SELECT frete_id FROM cobrancas_freites)
                  AND f.id NOT IN (SELECT frete_id FROM cobrancas_fretes)
                ORDER BY f.id DESC LIMIT 3""")
livres = [x['id'] for x in cur.fetchall()]
erros = [i for i in livres if boletos._cobranca_ativa_do_frete(cur, i)]
prova('frete sem cobranca nenhuma continua liberado', bool(livres) and not erros,
      'travou indevidamente: %r' % erros)
if livres:
    print('        fretes livres conferidos: %r' % livres)

# ── cancelada nao barra, senao nao se reemite ───────────────────────────
cur.execute("""SELECT cf.frete_id FROM cobrancas_freites cf
                 JOIN cobrancas c ON c.id = cf.cobranca_id
                WHERE c.status = 'cancelado'
                  AND cf.frete_id NOT IN (
                      SELECT cf2.frete_id FROM cobrancas_freites cf2
                        JOIN cobrancas c2 ON c2.id = cf2.cobranca_id
                       WHERE c2.status IS NULL OR c2.status <> 'cancelado')
                  AND cf.frete_id NOT IN (
                      SELECT COALESCE(frete_id,0) FROM cobrancas
                       WHERE status IS NULL OR status <> 'cancelado')
                LIMIT 3""")
canc = [x['frete_id'] for x in cur.fetchall()]
if canc:
    erros = [i for i in canc if boletos._cobranca_ativa_do_frete(cur, i)]
    prova('cobranca cancelada nao barra a reemissao', not erros,
          'barrou indevidamente: %r' % erros)
    print('        fretes so com cobranca cancelada: %r' % canc)
else:
    print('AVISO  nao ha frete so com cobranca cancelada para testar')

# ── o GET_LOCK deixa passar um de cada vez ──────────────────────────────
nome = boletos._trava_nome([999999])
c2 = get_db_connection()
cur2 = c2.cursor(dictionary=True)
primeiro = boletos._travar(cur, nome)
segundo = boletos._travar(cur2, nome)     # outra conexao: tem de falhar
prova('a trava por frete deixa so um passar de cada vez',
      primeiro and not segundo,
      'primeiro=%s segundo=%s' % (primeiro, segundo))
boletos._destravar(cur, nome)
depois = boletos._travar(cur2, nome)
prova('e libera quando o primeiro termina', depois,
      'a trava ficou presa e nenhuma emissao passaria')
boletos._destravar(cur2, nome)
cur2.close()
c2.close()

# ── as duas pontes sao olhadas ─────────────────────────────────────────
fonte = io.open('utils/boletos.py', encoding='utf-8').read()
for t in ('cobrancas_freites', 'cobrancas_fretes'):
    prova('a trava olha a tabela %s' % t,
          fonte.count('"%s"' % t) + fonte.count("'%s'" % t) >= 2,
          'so aparece %d vez(es) como nome de tabela'
          % (fonte.count('"%s"' % t) + fonte.count("'%s'" % t)))

cur.close()
conn.close()

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
