# -*- coding: utf-8 -*-
# ============================================================================
#  RECALCULA descarga_nota.perda_sobra_l das notas ja fechadas.
#
#  A formula mudou algumas vezes ate assentar. A definitiva e:
#
#      perda_sobra = quanto ENTROU NO TANQUE - quantidade da nota
#
#  onde "entrou no tanque" = SUM(descargas_pendentes.total_descarga) das
#  descargas ligadas aquele item. NAO e a soma de descarga_nota.litros: o
#  vinculo para no saldo da nota, entao quando o tanque recebeu mais do que a
#  nota cobre (S10: 3.156 recebidos, nota de 3.000) a sobra sumiria.
#
#  So mexe em linha com modo='integral' (as unicas que tem valor apurado).
#  Nao altera litros, modo, nem status de descarga.
#
#  SOMENTE LEITURA por padrao. So grava com --aplicar.
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/recalcular_perda_sobra.py             # so mostra
#     python scripts/recalcular_perda_sobra.py --aplicar   # grava
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

SQL = """
SELECT dn.id, dn.descarga_id, dn.item_id, dn.litros, dn.perda_sobra_l AS atual,
       doc.numero AS nota, i.quantidade AS nota_litros,
       dp.produto_nome,
       DATE(COALESCE(dp.data_final, dp.data_inicial, dp.data_descarga)) AS data,
       COALESCE((SELECT SUM(dp2.total_descarga)
                   FROM descarga_nota a
                   JOIN descargas_pendentes dp2 ON dp2.id = a.descarga_id
                  WHERE a.item_id = dn.item_id), 0) AS recebido_fisico,
       (SELECT COUNT(*) FROM descarga_nota a WHERE a.item_id = dn.item_id) AS n_descargas
FROM descarga_nota dn
JOIN dfe_documentos doc      ON doc.id = dn.documento_id
JOIN dfe_itens i             ON i.id  = dn.item_id
JOIN descargas_pendentes dp  ON dp.id = dn.descarga_id
WHERE dn.modo = 'integral'
ORDER BY dn.id
"""

con = pymysql.connect(**CONN)
try:
    cur = con.cursor()
    cur.execute("SELECT DATABASE() AS db")
    print("Banco:", cur.fetchone()["db"])
    print("Modo :", "APLICAR (vai gravar)" if APLICAR else "SOMENTE LEITURA (nada muda)")

    cur.execute(SQL)
    linhas = cur.fetchall()
    if not linhas:
        print("\n  Nenhuma nota fechada (modo='integral'). Nada a recalcular.")
    else:
        print("\n  nota    | data       | produto              | recebido | nota     "
              "| atual    | correto  | muda")
        print("  --------+------------+----------------------+----------+----------"
              "+----------+----------+-----")
        mudam = 0
        for r in linhas:
            recebido = float(r["recebido_fisico"] or 0)
            nota = float(r["nota_litros"] or 0)
            correto = round(recebido - nota, 3)
            atual = None if r["atual"] is None else float(r["atual"])
            muda = atual is None or abs(atual - correto) > 0.001
            if muda:
                mudam += 1
            print("  %-7s | %-10s | %-20s | %8.0f | %8.0f | %8s | %+8.0f | %s"
                  % (r["nota"], r["data"], (r["produto_nome"] or "")[:20], recebido, nota,
                     ("%.0f" % atual) if atual is not None else "-", correto,
                     "SIM" if muda else "nao"))
            if r["n_descargas"] > 1:
                print("            ^ esta nota foi baixada em %d descargas; o recebido "
                      "acima ja soma todas." % r["n_descargas"])
            if APLICAR and muda:
                cur.execute("UPDATE descarga_nota SET perda_sobra_l = %s WHERE id = %s",
                            (correto, r["id"]))
        print("\n  %d linha(s) fechada(s), %d com valor diferente do gravado."
              % (len(linhas), mudam))

        if APLICAR and mudam:
            con.commit()
            print("  APLICADO: %d linha(s) atualizada(s)." % mudam)
        elif not APLICAR:
            print("\n  Nada foi alterado. Para gravar:")
            print("     python scripts/recalcular_perda_sobra.py --aplicar")
    cur.close()
finally:
    con.close()

print("\nFIM")
