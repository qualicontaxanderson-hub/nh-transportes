# -*- coding: utf-8 -*-
"""Busca na EFI o codigo de barras e o Pix dos boletos que ficaram sem eles.

As colunas cobrancas.barcode e cobrancas.pix_qrcode so passaram a existir em
26/08/2026 (a migration de 06/06 tinha erro de sintaxe e foi gravada como
sucesso). Ate ali o app buscava os dois na emissao e os descartava. Este script
vai na EFI e preenche o que da pra recuperar.

Roda ONDE EXISTIREM AS CREDENCIAIS DA EFI — no Railway, nao na maquina local:

    python scripts/preencher_barcode_pix.py            # so mostra o que faria
    python scripts/preencher_barcode_pix.py --gravar   # grava

Por padrao mexe so nos boletos EM ABERTO (nem pagos nem cancelados), que sao os
unicos que alguem ainda precisa reenviar. Para varrer todos, use --todos.

Precisa no ambiente: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
EFI_CLIENT_ID, EFI_CLIENT_SECRET e (se houver) EFI_CERT_PATH.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import get_db_connection          # noqa: E402
from utils.boletos import (                     # noqa: E402
    fetch_charge,
    _safe_get_charge_fields,
    _ensure_credentials_from_env,
)


def _credenciais():
    c = _ensure_credentials_from_env({
        "client_id": os.getenv("EFI_CLIENT_ID"),
        "client_secret": os.getenv("EFI_CLIENT_SECRET"),
        "certificate": os.getenv("EFI_CERT_PATH"),
        "sandbox": str(os.getenv("EFI_SANDBOX", "false")).lower() in ("1", "true", "sim"),
    })
    if not c.get("client_id") or not c.get("client_secret"):
        sys.exit("EFI_CLIENT_ID / EFI_CLIENT_SECRET nao estao no ambiente. "
                 "Rode isto onde as credenciais existem (Railway).")
    return c


def _pendentes(cur, todos):
    filtro = "" if todos else \
        " AND LOWER(COALESCE(cb.status,'')) NOT IN ('pago','cancelado')"
    cur.execute("""
        SELECT cb.id, cb.charge_id, cb.valor, cb.status, cb.data_vencimento,
               COALESCE(cl.nome_fantasia, cl.razao_social, '?') AS cliente
          FROM cobrancas cb
          LEFT JOIN clientes cl ON cl.id = cb.id_cliente
         WHERE cb.charge_id IS NOT NULL
           AND (cb.barcode IS NULL OR cb.pix_qrcode IS NULL)
        """ + filtro + """
         ORDER BY cb.data_vencimento DESC
    """)
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gravar', action='store_true',
                    help='grava de verdade; sem isso so mostra o que faria')
    ap.add_argument('--todos', action='store_true',
                    help='inclui pagos e cancelados (por padrao so os em aberto)')
    args = ap.parse_args()

    cred = _credenciais()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    alvos = _pendentes(cur, args.todos)

    print('%d boleto(s) sem codigo de barras ou sem Pix%s'
          % (len(alvos), '' if args.todos else ' (so os em aberto)'))
    if not args.gravar:
        print('MODO DE TESTE — nada sera gravado. Use --gravar.\n')

    achou = falhou = gravou = 0
    for r in alvos:
        rotulo = ('  cob %-6s charge %-11s %-30s R$ %9.2f  venc %s'
                  % (r['id'], r['charge_id'], str(r['cliente'])[:30],
                     float(r['valor'] or 0), r['data_vencimento']))
        try:
            resp = fetch_charge(cred, r['charge_id'])
            _, _, barcode, pix = _safe_get_charge_fields(resp)
        except Exception as e:
            print(rotulo + '  ERRO: %s' % str(e)[:70])
            falhou += 1
            continue

        if not (barcode or pix):
            print(rotulo + '  a EFI nao devolveu nem barras nem Pix')
            falhou += 1
            continue

        achou += 1
        print(rotulo + '  barras=%s pix=%s'
              % ('sim' if barcode else 'nao', 'sim' if pix else 'nao'))
        if args.gravar:
            # COALESCE: nunca sobrescreve o que ja estiver gravado.
            cur.execute("""UPDATE cobrancas
                              SET barcode    = COALESCE(barcode, %s),
                                  pix_qrcode = COALESCE(pix_qrcode, %s)
                            WHERE id = %s""", (barcode, pix, r['id']))
            conn.commit()
            gravou += 1

    print('\nresumo: %d com dado na EFI, %d sem, %d gravado(s)'
          % (achou, falhou, gravou))
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
