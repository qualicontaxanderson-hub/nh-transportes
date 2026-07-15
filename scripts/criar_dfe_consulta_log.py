# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRATION IDEMPOTENTE - observabilidade da captura de DFe.
#
#  1) CRIA dfe_consulta_log: UMA LINHA POR RODADA/CONSULTA, inclusive as que
#     tomam 656 e as que sao PULADAS pela trava de cota (que hoje nao deixam
#     rastro nenhum no banco).
#  2) ALARGA dfe_nsu.ult_status de VARCHAR(60) -> VARCHAR(255): a mensagem da
#     SEFAZ vinha cortada exatamente na parte que diz qual ultNSU usar.
#
#  Nao apaga nada. Nao mexe em dado existente (o ALTER so alarga a coluna).
#  Rodar de novo e inofensivo.
# ============================================================================
import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV", database="railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)

# Fonte unica do DDL (o mesmo usado em runtime por integrations/dfe_log.py).
import os
import sys
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
from integrations.dfe_log import DDL_CONSULTA_LOG

con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db, NOW() AS agora")
        r = cur.fetchone()
        print("Banco:", r["db"], "| NOW() =", r["agora"], "(UTC)")
        print("=" * 74)

        # ---- 1) tabela de log -------------------------------------------
        print("[1] CREATE TABLE IF NOT EXISTS dfe_consulta_log ...")
        cur.execute(DDL_CONSULTA_LOG)
        con.commit()
        cur.execute("SHOW COLUMNS FROM dfe_consulta_log")
        print("    OK. Colunas:")
        for c in cur.fetchall():
            print("      %-14s %s" % (c["Field"], c["Type"]))

        # ---- 2) alargar ult_status --------------------------------------
        print()
        print("[2] dfe_nsu.ult_status VARCHAR(60) -> VARCHAR(255) ...")
        cur.execute("""
            SELECT CHARACTER_MAXIMUM_LENGTH AS len
              FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'dfe_nsu' AND COLUMN_NAME = 'ult_status'
        """)
        antes = (cur.fetchone() or {}).get("len")
        print("    antes: VARCHAR(%s)" % antes)
        if antes and int(antes) >= 255:
            print("    ja esta >= 255; nada a fazer.")
        else:
            cur.execute("ALTER TABLE dfe_nsu MODIFY COLUMN ult_status VARCHAR(255) NULL")
            con.commit()
            cur.execute("""
                SELECT CHARACTER_MAXIMUM_LENGTH AS len
                  FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME = 'dfe_nsu' AND COLUMN_NAME = 'ult_status'
            """)
            print("    depois: VARCHAR(%s)" % (cur.fetchone() or {}).get("len"))

        # ---- 3) confere que o dado atual continua la ---------------------
        print()
        print("[3] dfe_nsu apos a migration (dado preservado):")
        cur.execute("SELECT cliente_id, ult_nsu, max_nsu, ult_consulta, "
                    "proximo_permitido, ult_status FROM dfe_nsu")
        for r in cur.fetchall():
            print("    cliente_id=%s ult_nsu=%s max_nsu=%s" % (r["cliente_id"], r["ult_nsu"], r["max_nsu"]))
            print("      ult_consulta=%s proximo_permitido=%s" % (r["ult_consulta"], r["proximo_permitido"]))
            print("      ult_status=%r" % r["ult_status"])

        cur.execute("SELECT COUNT(*) AS n FROM dfe_consulta_log")
        print()
        print("    dfe_consulta_log: %s linhas (enche a partir da proxima rodada)."
              % cur.fetchone()["n"])
finally:
    con.close()
print("=" * 74)
print("FIM - migration idempotente aplicada. Nenhum dado foi apagado.")
