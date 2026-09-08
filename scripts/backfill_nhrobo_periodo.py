# -*- coding: utf-8 -*-
"""Preenche doc_tipo (e periodo, quando o NOME diz) das linhas antigas.

As linhas gravadas antes de 08/09/2026 nao tem tipo nem periodo: as colunas
nasceram depois delas. Sem isto a aba Historico mostra ".ofx" cru no lugar de
"Extrato bancario" para quem chegou primeiro -- a coluna pareceria quebrada.

SO PELO NOME, de proposito. O periodo bom sai de DENTRO do arquivo, e o arquivo
ja saiu do /BANCOS/OFX/NOVO (o importador de extrato o move). Baixar de volta o
que talvez nem esteja mais la, para adivinhar o mes de duas linhas de teste,
custa mais do que vale -- e um periodo errado seria pior do que um travessao.

    python scripts/backfill_nhrobo_periodo.py          (mostra o que faria)
    python scripts/backfill_nhrobo_periodo.py --gravar (grava)
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get('DB_PASSWORD'):
    _bat = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'bakup_railway.bat')
    if os.path.exists(_bat):
        _m = re.search(r'set DBPASS=(.+)', io.open(_bat, encoding='latin-1').read(), re.I)
        if _m:
            os.environ['DB_PASSWORD'] = _m.group(1).strip()
os.environ.setdefault('SECRET_KEY', 'backfill-nhrobo')

from utils.db import get_db_connection            # noqa: E402
from utils.nhrobo_periodo import identificar, rotulo   # noqa: E402

GRAVAR = '--gravar' in sys.argv

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("""SELECT id, nome_original, nome_final, ext
                 FROM nhrobo_recebidos
                WHERE doc_tipo IS NULL
                ORDER BY id""")
linhas = cur.fetchall()
cur.close()

print('%d linha(s) sem tipo.\n' % len(linhas))
mudou = 0
esc = conn.cursor()
for r in linhas:
    tipo, ini, fim, fonte = identificar(r['nome_original'] or r['nome_final'],
                                        None, r['ext'])
    if not tipo and not ini:
        print('  #%-4s %-45s -> nada a preencher' % (r['id'], r['nome_final'][:45]))
        continue
    print('  #%-4s %-45s -> %-12s %s' % (r['id'], r['nome_final'][:45],
                                         tipo or '-', rotulo(ini, fim) or '—'))
    if GRAVAR:
        esc.execute("""UPDATE nhrobo_recebidos
                          SET doc_tipo = %s, periodo_ini = %s, periodo_fim = %s,
                              periodo_fonte = %s
                        WHERE id = %s AND doc_tipo IS NULL""",
                    (tipo, ini, fim, fonte, r['id']))
        mudou += esc.rowcount

if GRAVAR:
    conn.commit()
    print('\n%d linha(s) gravada(s).' % mudou)
else:
    print('\nEnsaio. Rode com --gravar para valer.')
esc.close()
conn.close()
