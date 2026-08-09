# -*- coding: utf-8 -*-
# ============================================================================
#  ZERA os vinculos descarga<->nota para refazer do zero com a logica nova.
#
#  Apaga TODAS as linhas de descarga_nota e devolve para 'pendente' as
#  descargas que estavam 'vinculada'.
#
#  NAO toca em:
#    - descarga com status 'ignorada' (decisao do usuario)
#    - descarga que ja era 'pendente'
#    - as colunas frete_id / descarga_id (dado historico)
#    - dfe_documentos, dfe_itens, e qualquer outra tabela
#
#  SOMENTE LEITURA por padrao. So grava com --aplicar.
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/limpar_vinculos_descarga.py             # so mostra
#     python scripts/limpar_vinculos_descarga.py --aplicar   # apaga
# ============================================================================
import os
import sys

import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password=os.environ.get("DB_PASSWORD") or "",
    database="railway", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=60, connect_timeout=15,
)
if not CONN["password"]:
    sys.exit('DB_PASSWORD nao definido. Rode: $env:DB_PASSWORD = "<senha>"')

APLICAR = "--aplicar" in sys.argv

con = pymysql.connect(**CONN)
try:
    cur = con.cursor()
    cur.execute("SELECT DATABASE() AS db")
    print("Banco:", cur.fetchone()["db"])
    print("Modo :", "APLICAR (vai gravar)" if APLICAR else "SOMENTE LEITURA (nada muda)")

    # ---------- o que existe hoje ----------
    cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(litros),0) AS litros, "
                "COUNT(DISTINCT descarga_id) AS descargas, "
                "COUNT(DISTINCT documento_id) AS notas FROM descarga_nota")
    v = cur.fetchone()
    print("\n  descarga_nota: %d vinculo(s), %.3f L, em %d descarga(s), %d nota(s)"
          % (v["n"], float(v["litros"] or 0), v["descargas"], v["notas"]))

    cur.execute("SELECT status, COUNT(*) AS n FROM descargas_pendentes "
                "GROUP BY status ORDER BY status")
    print("\n  descargas_pendentes por status:")
    for r in cur.fetchall():
        print("    %-12s %d" % (r["status"], r["n"]))

    cur.execute("SELECT COUNT(*) AS n FROM descargas_pendentes WHERE status = 'vinculada'")
    resetar = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM descargas_pendentes WHERE status = 'ignorada'")
    ignoradas = cur.fetchone()["n"]

    print("\n  A APAGAR   : %d linha(s) de descarga_nota" % v["n"])
    print("  A RESETAR  : %d descarga(s) 'vinculada' -> 'pendente'" % resetar)
    print("  PRESERVADAS: %d 'ignorada' (nao serao tocadas)" % ignoradas)

    if v["n"]:
        cur.execute("""
            SELECT dn.id, dn.descarga_id, dn.litros, doc.numero AS nota,
                   dp.produto_nome,
                   DATE(COALESCE(dp.data_final, dp.data_inicial, dp.data_descarga)) AS data
            FROM descarga_nota dn
            JOIN dfe_documentos doc ON doc.id = dn.documento_id
            JOIN descargas_pendentes dp ON dp.id = dn.descarga_id
            ORDER BY dn.id
            LIMIT 30
        """)
        print("\n  Vinculos que serao apagados (ate 30):")
        print("    id  | descarga | data       | produto              | nota    | litros")
        print("    ----+----------+------------+----------------------+---------+---------")
        for r in cur.fetchall():
            print("    %-3s | %8s | %-10s | %-20s | %-7s | %s"
                  % (r["id"], r["descarga_id"], r["data"],
                     (r["produto_nome"] or "")[:20], r["nota"], r["litros"]))

    # ---------- aplicar ----------
    if not APLICAR:
        print("\n  Nada foi alterado. Para zerar de verdade:")
        print("     python scripts/limpar_vinculos_descarga.py --aplicar")
    elif not v["n"] and not resetar:
        print("\n  Nada a fazer: ja esta zerado.")
    else:
        cur.execute("DELETE FROM descarga_nota")
        apagados = cur.rowcount or 0
        cur.execute("UPDATE descargas_pendentes SET status = 'pendente' "
                    "WHERE status = 'vinculada'")
        resetados = cur.rowcount or 0
        con.commit()
        print("\n  APLICADO: %d vinculo(s) apagado(s), %d descarga(s) de volta para 'pendente'."
              % (apagados, resetados))

        cur.execute("SELECT COUNT(*) AS n FROM descarga_nota")
        cur.execute("SELECT COUNT(*) AS n FROM descarga_nota")
        print("  Conferencia: descarga_nota agora tem %d linha(s) (esperado 0)."
              % cur.fetchone()["n"])
        cur.execute("SELECT status, COUNT(*) AS n FROM descargas_pendentes "
                    "GROUP BY status ORDER BY status")
        print("  Status agora:", ", ".join("%s=%d" % (r["status"], r["n"])
                                           for r in cur.fetchall()))
    cur.close()
finally:
    con.close()

print("\nFIM")
