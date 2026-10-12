# -*- coding: utf-8 -*-
"""Medição (só leitura): quantas NF-e de compra desde o corte trazem placa e
motorista no XML, por fornecedor. Usa o MESMO leitor que vai gravar
(utils/dfe_transporte), lendo o XML da pasta local do Dropbox.

  python diag_placa_motorista.py
"""
import io
import os
import sys
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
_cnf = os.path.join(os.path.expanduser('~'), '.nh-transportes', 'mysql_backup.cnf')
for _l in open(_cnf, encoding='utf-8'):
    _k, _, _v = _l.strip().partition('=')
    if _k == 'password':
        os.environ.setdefault('DB_PASSWORD', _v.strip())
os.environ.setdefault('SECRET_KEY', 'x')

from utils.db import get_db_connection
from utils.dfe_transporte import extrair_placa_motorista

DROPBOX = os.path.join(os.path.expanduser('~'), 'Dropbox')

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("""SELECT d.id, d.numero, d.emit_nome, d.xml_caminho
                 FROM dfe_documentos d
                WHERE d.tipo = 'NFe' AND d.resumo = 0
                  AND d.dh_emissao >= '2026-07-07'
                  AND EXISTS (SELECT 1 FROM dfe_itens i WHERE i.documento_id = d.id)
                ORDER BY d.dh_emissao""")
docs = cur.fetchall()
cur.close()
conn.close()

por = defaultdict(lambda: [0, 0, 0, 0, None])   # notas, sem xml, placa, motorista, exemplo
for d in docs:
    st = por[(d['emit_nome'] or '?')[:34]]
    st[0] += 1
    cam = os.path.join(DROPBOX, (d['xml_caminho'] or '').lstrip('/').replace('/', os.sep))
    if not d['xml_caminho'] or not os.path.exists(cam):
        st[1] += 1
        continue
    placa, mot = extrair_placa_motorista(open(cam, 'rb').read())
    st[2] += bool(placa)
    st[3] += bool(mot)
    if (placa or mot) and not st[4]:
        st[4] = '%s / %s' % (placa or '—', mot or '—')

tot = [sum(v[i] for v in por.values()) for i in range(4)]
print('NF-e de compra desde 07/07/2026: %d | sem XML local: %d | com placa: %d | com motorista: %d\n'
      % tuple(tot))
print('%-34s %5s %6s %6s %6s  exemplo' % ('fornecedor', 'notas', 's/xml', 'placa', 'motor.'))
for k, v in sorted(por.items(), key=lambda x: -x[1][0]):
    print('%-34s %5d %6d %6d %6d  %s' % (k, v[0], v[1], v[2], v[3], v[4] or ''))
