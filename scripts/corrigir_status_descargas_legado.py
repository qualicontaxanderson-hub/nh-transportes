# -*- coding: utf-8 -*-
# ============================================================================
#  CORRIGE o status 'vinculada' herdado do casamento automatico antigo.
#
#  Ate 07/08/2026 o els_email casava a descarga com a tabela `fretes` e ja
#  marcava status='vinculada'. Esse casamento estava errado (frete e controle
#  interno de cobranca, nao a nota de compra). O vinculo de verdade agora vive
#  em `descarga_nota`.
#
#  Entao: toda descarga com status='vinculada' e NENHUMA linha em descarga_nota
#  esta mentindo — volta para 'pendente'.
#
#  NAO toca em:
#    - descargas que TEM vinculo real em descarga_nota
#    - descargas 'pendente' ou 'ignorada'
#    - a coluna frete_id / descarga_id (ficam como estao, dado historico)
#    - a tabela `descargas` (as linhas que o casamento criou ficam para uma
#      limpeza separada — mexer nelas envolve tres tabelas)
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/corrigir_status_descargas_legado.py             # SO MOSTRA
#     python scripts/corrigir_status_descargas_legado.py --aplicar   # corrige
# ============================================================================
import os
import sys

import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password=os.environ["DB_PASSWORD"],
    database="railway", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=60, connect_timeout=15,
)

# A condicao, escrita uma vez so: 'vinculada' sem nenhum vinculo real.
COND = """
    dp.status = 'vinculada'
    AND NOT EXISTS (SELECT 1 FROM descarga_nota dn WHERE dn.descarga_id = dp.id)
"""

APLICAR = "--aplicar" in sys.argv

con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db")
        print("Banco:", cur.fetchone()["db"])
        print("Modo :", "APLICAR (vai gravar)" if APLICAR else "SOMENTE LEITURA (nada muda)")

        # ---------- panorama ----------
        cur.execute("""
            SELECT dp.status,
                   COUNT(*) AS n,
                   SUM(EXISTS (SELECT 1 FROM descarga_nota dn
                                WHERE dn.descarga_id = dp.id)) AS com_vinculo_real,
                   SUM(dp.frete_id IS NOT NULL) AS com_frete_id_antigo
            FROM descargas_pendentes dp
            GROUP BY dp.status
            ORDER BY dp.status
        """)
        print("\n  status      | total | c/ vinculo real | c/ frete_id antigo")
        print("  ------------+-------+-----------------+-------------------")
        for r in cur.fetchall():
            print("  %-11s | %5d | %15d | %d"
                  % (r["status"], r["n"], r["com_vinculo_real"] or 0,
                     r["com_frete_id_antigo"] or 0))

        # ---------- quantas serao corrigidas ----------
        cur.execute("SELECT COUNT(*) AS n FROM descargas_pendentes dp WHERE " + COND)
        alvo = cur.fetchone()["n"]
        print("\n  A CORRIGIR (vinculada SEM vinculo real): %d" % alvo)

        cur.execute("""
            SELECT COUNT(*) AS n FROM descargas_pendentes dp
            WHERE dp.status = 'vinculada'
              AND EXISTS (SELECT 1 FROM descarga_nota dn WHERE dn.descarga_id = dp.id)
        """)
        print("  A PRESERVAR (vinculada COM vinculo real): %d" % cur.fetchone()["n"])

        if alvo:
            cur.execute("""
                SELECT dp.id, dp.produto_nome, dp.tanque, dp.total_descarga,
                       DATE(COALESCE(dp.data_final, dp.data_inicial, dp.data_descarga)) AS data,
                       dp.frete_id, dp.descarga_id
                FROM descargas_pendentes dp
                WHERE """ + COND + """
                ORDER BY COALESCE(dp.data_final, dp.data_inicial, dp.data_descarga) DESC
                LIMIT 20
            """)
            print("\n  Amostra (ate 20):")
            print("    id    | data       | produto              | tanque |    litros | frete_id | descarga_id")
            print("    ------+------------+----------------------+--------+-----------+----------+------------")
            for r in cur.fetchall():
                print("    %-5s | %-10s | %-20s | %6s | %9s | %8s | %s"
                      % (r["id"], r["data"], (r["produto_nome"] or "")[:20],
                         r["tanque"], r["total_descarga"], r["frete_id"], r["descarga_id"]))

        # ---------- aplicar ----------
        if not APLICAR:
            print("\n  Nada foi alterado. Para corrigir de verdade, rode de novo com:")
            print("     python scripts/corrigir_status_descargas_legado.py --aplicar")
        elif not alvo:
            print("\n  Nada a corrigir.")
        else:
            cur.execute("""
                UPDATE descargas_pendentes dp
                   SET dp.status = 'pendente'
                 WHERE """ + COND)
            print("\n  UPDATE aplicado: %d descarga(s) voltaram para 'pendente'." % cur.rowcount)
            con.commit()

            cur.execute("SELECT COUNT(*) AS n FROM descargas_pendentes dp WHERE " + COND)
            resto = cur.fetchone()["n"]
            print("  Conferencia: sobraram %d nesta condicao (esperado 0)." % resto)
finally:
    con.close()

print("\nFIM")
