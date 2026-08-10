# -*- coding: utf-8 -*-
# ============================================================================
# RETROATIVO pontual: marca como 'cancelada' os CT-e que a transportadora ja
# cancelou, mas cujo evento de cancelamento a captura ANTIGA descartou (antes do
# handler procEventoCTe existir). Daqui pra frente o cancelamento e automatico;
# este script e SO para os 2 casos ja confirmados.
#
# Chaveado pela CHAVE (44 digitos) -- unica por documento, sem ambiguidade de
# numero/serie/emitente.
#
# USO (PowerShell):
#   $env:DB_PASSWORD = "<senha>"
#   python scripts\cancelar_cte_retroativo.py            # PREVIEW (nao altera nada)
#   python scripts\cancelar_cte_retroativo.py --apply    # aplica o UPDATE
# ============================================================================
import os
import sys

import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password=os.environ["DB_PASSWORD"], database="railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)

# CT-e ja cancelados na transportadora (confirmado manualmente). Chave de 44 dig.
CHAVES = [
    "52260831504262000117570010000555811142178138",  # CT-e 55581
    "52260831504262000117570010000555831433927530",  # CT-e 55583
]


def _preview(cur):
    marc = ", ".join(["%s"] * len(CHAVES))
    cur.execute(
        f"""
        SELECT id, chave, numero, serie, emit_nome, dh_emissao, situacao
          FROM dfe_documentos
         WHERE tipo = 'CTe' AND chave IN ({marc})
         ORDER BY numero
        """,
        CHAVES,
    )
    linhas = cur.fetchall()
    print("=" * 78)
    print("PREVIEW — CT-e alvo (tipo='CTe', pelas chaves):")
    print("=" * 78)
    if not linhas:
        print("  (nenhum CT-e encontrado com essas chaves — confira as chaves.)")
        return linhas
    for r in linhas:
        print(f"  id={r['id']}  NF {r['numero']}/{r['serie']}  {r['emit_nome']}")
        print(f"     chave={r['chave']}")
        print(f"     emissao={r['dh_emissao']}  situacao ATUAL={r['situacao']!r}")
    achou = {r["chave"] for r in linhas}
    faltando = [c for c in CHAVES if c not in achou]
    if faltando:
        print("\n  AVISO: chaves sem CT-e no banco:")
        for c in faltando:
            print(f"    - {c}")
    ja = [r for r in linhas if r["situacao"] == "cancelada"]
    if ja:
        print(f"\n  Nota: {len(ja)} ja esta(o) 'cancelada' — o UPDATE ignora (situacao<>'cancelada').")
    return linhas


def _apply(conn, cur):
    marc = ", ".join(["%s"] * len(CHAVES))
    cur.execute(
        f"""
        UPDATE dfe_documentos
           SET situacao = 'cancelada'
         WHERE tipo = 'CTe' AND chave IN ({marc}) AND situacao <> 'cancelada'
        """,
        CHAVES,
    )
    n = cur.rowcount or 0
    conn.commit()
    print("=" * 78)
    print(f"APLICADO: {n} CT-e marcado(s) como 'cancelada'.")
    print("=" * 78)


def main():
    aplicar = "--apply" in sys.argv[1:]
    conn = pymysql.connect(**CONN)
    try:
        with conn.cursor() as cur:
            linhas = _preview(cur)
            if not aplicar:
                print("\n>>> PREVIEW apenas. Nada foi alterado.")
                print(">>> Confira acima e rode com --apply para aplicar o cancelamento.")
                return
            if not linhas:
                print("\n>>> Nada a aplicar (nenhum CT-e encontrado).")
                return
            print("\n>>> --apply informado: aplicando o UPDATE...")
            _apply(conn, cur)
            _preview(cur)  # reconfere a situacao depois
    finally:
        conn.close()


if __name__ == "__main__":
    main()
