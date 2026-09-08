# -*- coding: utf-8 -*-
"""Prova do identificador de tipo e periodo (utils/nhrobo_periodo.py).

Roda sem banco e sem app: e so texto entrando e data saindo. O caso do OFX usa
o ARQUIVO DE VERDADE que ja subiu pelo robo, quando ele esta na maquina --
prova sintetica de OFX eu mesmo escreveria no formato que o meu regex espera.

    python prova_nhrobo_periodo.py
"""
import datetime as _dt
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.nhrobo_periodo import identificar, rotulo   # noqa: E402

D = _dt.date
falhas = []


def prova(titulo, obtido, esperado):
    ok = obtido == esperado
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        print('        esperado: %r' % (esperado,))
        print('        obtido:   %r' % (obtido,))
        falhas.append(titulo)


# ── OFX: o arquivo real, se estiver aqui ─────────────────────────────────────
REAL = os.path.join(os.path.expanduser('~'), 'Dropbox', 'Aplicativos',
                    'NH-ROBO MEU', 'extrato teste.ofx')
if os.path.exists(REAL):
    with io.open(REAL, 'rb') as fh:
        bruto = fh.read()
    prova('OFX de verdade: tipo e periodo saem de dentro do arquivo',
          identificar('extrato teste.ofx', bruto),
          ('extrato', D(2026, 9, 4), D(2026, 9, 7), 'arquivo'))
    prova('OFX de verdade: o rotulo que a tela mostra',
          rotulo(D(2026, 9, 4), D(2026, 9, 7)), '04/09 a 07/09/2026')
else:
    print('AVISO  o OFX de verdade nao esta nesta maquina; pulei 2 provas')

# ── OFX sem cabecalho de periodo ─────────────────────────────────────────────
SEM_CABECALHO = ('<OFX><BANKTRANLIST>'
                 '<STMTTRN><DTPOSTED>20260812120000<TRNAMT>-10.00</STMTTRN>'
                 '<STMTTRN><DTPOSTED>20260803120000<TRNAMT>-20.00</STMTTRN>'
                 '</BANKTRANLIST></OFX>')
prova('OFX sem DTSTART: o periodo vem dos proprios lancamentos',
      identificar('extrato.ofx', SEM_CABECALHO.encode('latin-1')),
      ('extrato', D(2026, 8, 3), D(2026, 8, 12), 'arquivo'))

# ── SPED ─────────────────────────────────────────────────────────────────────
SPED = ('|0000|017|0|01082026|31082026|POSTO NOVO HORIZONTE LTDA|12345678000199|GO|\r\n'
        '|0001|0|\r\n|0150|1|FORNECEDOR X|\r\n')
prova('SPED: DT_INI e DT_FIN do registro 0000, em DDMMAAAA',
      identificar('SPED FISCAL 08-2026.txt', SPED.encode('latin-1')),
      ('sped', D(2026, 8, 1), D(2026, 8, 31), 'arquivo'))
prova('SPED: mes fechado vira "08/2026", nao "01/08 a 31/08/2026"',
      rotulo(D(2026, 8, 1), D(2026, 8, 31)), '08/2026')

# .txt que nao e SPED continua sendo .txt, e sem periodo
prova('texto solto nao vira SPED so por ser .txt',
      identificar('anotacoes.txt', b'qualquer coisa\nsem registro 0000\n'),
      ('texto', None, None, None))

# ── XML ──────────────────────────────────────────────────────────────────────
NFE = ('<nfeProc><NFe><infNFe Id="NFe3526..."><ide><mod>55</mod>'
       '<dhEmi>2026-08-14T10:31:00-03:00</dhEmi></ide></infNFe></NFe></nfeProc>')
prova('NF-e: tipo pelo conteudo e a data de emissao como periodo de um dia',
      identificar('35260812345678000199550010000123451000123456-nfe.xml',
                  NFE.encode('utf-8')),
      ('nfe', D(2026, 8, 14), D(2026, 8, 14), 'arquivo'))

NFCE = NFE.replace('<mod>55</mod>', '<mod>65</mod>')
prova('NFC-e nao e confundida com NF-e (muda so o modelo, dentro do XML)',
      identificar('venda.xml', NFCE.encode('utf-8'))[0], 'nfce')

CTE = ('<cteProc><CTe><infCte Id="CTe352608..."><ide>'
       '<dhEmi>2026-08-03T08:00:00-03:00</dhEmi></ide></infCte></CTe></cteProc>')
prova('CT-e tem extensao de XML e nao e nota',
      identificar('cte.xml', CTE.encode('utf-8')),
      ('cte', D(2026, 8, 3), D(2026, 8, 3), 'arquivo'))

# ── o nome, quando o conteudo nao diz ────────────────────────────────────────
for nome, esperado in [
        ('Fechamento 07-2026.xlsx',       (D(2026, 7, 1), D(2026, 7, 31))),
        ('relatorio 2026-02 caixa.xlsx',  (D(2026, 2, 1), D(2026, 2, 28))),
        ('conferencia 122026.xlsx',       (D(2026, 12, 1), D(2026, 12, 31))),
        ('planilha do posto.xlsx',        (None, None))]:
    tipo, ini, fim, fonte = identificar(nome, b'PK\x03\x04binario')
    prova('nome "%s"' % nome, (ini, fim), esperado)
    prova('  -> fonte declarada como %s' % ('nome' if esperado[0] else 'nenhuma'),
          fonte, 'nome' if esperado[0] else None)

# O caso que estraga tudo se o regex for frouxo: a chave de 44 digitos tem
# "072026" no meio dela em algum lugar quase sempre.
CHAVE = '35260812345678000199550010000123451000123456'
prova('chave de 44 digitos no nome NAO vira periodo',
      identificar(CHAVE + '.xml', b'<xml/>')[1:], (None, None, None))

# ── nada pode estourar ───────────────────────────────────────────────────────
for titulo, args in [('conteudo vazio', ('x.ofx', b'')),
                     ('conteudo None', ('x.ofx', None)),
                     ('nome vazio', ('', b'oi')),
                     ('nome None', (None, b'oi')),
                     ('binario cru', ('x.pdf', bytes(range(256)) * 40)),
                     ('extensao desconhecida', ('x.qqq', b'oi'))]:
    r = identificar(*args)
    prova('nao estoura com %s' % titulo, isinstance(r, tuple) and len(r) == 4, True)

prova('rotulo de periodo inexistente e vazio', rotulo(None, None), '')

print('\n%d falha(s)' % len(falhas))
sys.exit(1 if falhas else 0)
