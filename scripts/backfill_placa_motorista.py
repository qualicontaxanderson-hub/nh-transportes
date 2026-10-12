# -*- coding: utf-8 -*-
"""Preenche dfe_documentos.transp_placa / transp_motorista das NF-e que já
estavam no banco antes da captura passar a gravar (utils/dfe_transporte).

Lê o XML da pasta LOCAL do Dropbox (o mesmo arquivo que a captura subiu) e só
preenche o que está vazio -- não sobrescreve nada.

  python scripts/backfill_placa_motorista.py            # só mostra o que faria
  python scripts/backfill_placa_motorista.py --aplicar  # grava
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

_cnf = os.path.join(os.path.expanduser('~'), '.nh-transportes', 'mysql_backup.cnf')
if not os.environ.get('DB_PASSWORD') and os.path.exists(_cnf):
    for _l in open(_cnf, encoding='utf-8'):
        _k, _, _v = _l.strip().partition('=')
        if _k == 'password':
            os.environ['DB_PASSWORD'] = _v.strip()
os.environ.setdefault('SECRET_KEY', 'x')

from utils.db import get_db_connection
from utils.dfe_transporte import extrair_placa_motorista

DROPBOX = os.path.join(os.path.expanduser('~'), 'Dropbox')
APLICAR = '--aplicar' in sys.argv

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("""SELECT COUNT(*) n FROM information_schema.columns
                WHERE table_schema = DATABASE() AND table_name = 'dfe_documentos'
                  AND column_name IN ('transp_placa', 'transp_motorista')""")
if cur.fetchone()['n'] < 2:
    print('As colunas transp_placa/transp_motorista ainda não existem: abra a tela '
          'de Fornecedores uma vez depois do deploy (ela cria) e rode de novo.')
    sys.exit(1)

cur.execute("""SELECT id, numero, emit_nome, xml_caminho
                 FROM dfe_documentos
                WHERE tipo = 'NFe' AND resumo = 0 AND xml_caminho IS NOT NULL
                  AND (transp_placa IS NULL OR transp_motorista IS NULL)""")
docs = cur.fetchall()

sem_xml = achou = 0
mudar = []
for d in docs:
    cam = os.path.join(DROPBOX, d['xml_caminho'].lstrip('/').replace('/', os.sep))
    if not os.path.exists(cam):
        sem_xml += 1
        continue
    placa, mot = extrair_placa_motorista(open(cam, 'rb').read())
    if placa or mot:
        achou += 1
        mudar.append((placa, mot, d['id']))

print('Notas com placa/motorista vazios: %d | sem XML local: %d | com dado no XML: %d'
      % (len(docs), sem_xml, achou))
for placa, mot, i in mudar[:10]:
    print('   doc %s: %s / %s' % (i, placa or '—', mot or '—'))

if not APLICAR:
    print('\n(só mostrando -- rode com --aplicar pra gravar)')
    sys.exit(0)

w = conn.cursor()
for placa, mot, i in mudar:
    # COALESCE: só preenche o que está vazio
    w.execute("UPDATE dfe_documentos "
              "   SET transp_placa = COALESCE(transp_placa, %s), "
              "       transp_motorista = COALESCE(transp_motorista, %s) "
              " WHERE id = %s", (placa, mot, i))
conn.commit()
w.close()
cur.execute("""SELECT COUNT(*) n, SUM(transp_placa IS NOT NULL) placa,
                      SUM(transp_motorista IS NOT NULL) mot
                 FROM dfe_documentos WHERE tipo = 'NFe' AND resumo = 0""")
r = cur.fetchone()
print('\nGravado. NF-e completas: %d | com placa: %d | com motorista: %d'
      % (r['n'], r['placa'] or 0, r['mot'] or 0))
cur.close()
conn.close()
