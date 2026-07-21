# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRACAO IDEMPOTENTE - multi-empresa + e-CPF no servico de captura de DFe.
#
#  ADITIVA / WIDENING apenas (nao perde dado, nao quebra o CNPJ ja cadastrado):
#    1. dfe_certificados.cnpj    CHAR(14) -> VARCHAR(14)  (acomoda CPF de 11 dig)
#    2. dfe_certificados.tipo_doc  ADD VARCHAR(4) NOT NULL DEFAULT 'CNPJ'
#    3. dfe_nsu.cnpj             CHAR(14) -> VARCHAR(14)   (cursor NF-e)
#    4. dfe_nsu_cte.cnpj         CHAR(14) -> VARCHAR(14)   (cursor CT-e)
#
#  Guarda de idempotencia: so altera o que ainda esta em CHAR / falta a coluna.
#  Rodar de novo e no-op. UNIQUE e por cliente_id (nao por cnpj), entao alargar
#  o cnpj nao afeta chave/indices.
# ============================================================================
import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV", database="railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)


def _tipo_coluna(cur, tabela, coluna):
    cur.execute(
        "SELECT DATA_TYPE, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (tabela, coluna),
    )
    row = cur.fetchone()
    return (row["DATA_TYPE"], row["COLUMN_TYPE"]) if row else (None, None)


def _coluna_existe(cur, tabela, coluna):
    cur.execute(
        "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (tabela, coluna),
    )
    return cur.fetchone()["n"] > 0


def _alargar_cnpj(cur, tabela):
    dt, ct = _tipo_coluna(cur, tabela, "cnpj")
    if dt is None:
        print(f"  {tabela}.cnpj: coluna nao existe (tabela ausente?) -- pulado.")
        return
    if dt.lower() == "varchar":
        print(f"  {tabela}.cnpj: ja e {ct} -- pulado.")
        return
    cur.execute(f"ALTER TABLE {tabela} MODIFY cnpj VARCHAR(14) NOT NULL")
    print(f"  {tabela}.cnpj: {ct} -> VARCHAR(14) OK.")


con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db")
        print("Banco:", cur.fetchone()["db"])
        print("\n[1] Alargando cnpj CHAR(14) -> VARCHAR(14):")
        _alargar_cnpj(cur, "dfe_certificados")
        _alargar_cnpj(cur, "dfe_nsu")
        _alargar_cnpj(cur, "dfe_nsu_cte")

        print("\n[2] Coluna tipo_doc em dfe_certificados:")
        if _coluna_existe(cur, "dfe_certificados", "tipo_doc"):
            print("  tipo_doc: ja existe -- pulado.")
        else:
            cur.execute(
                "ALTER TABLE dfe_certificados "
                "ADD COLUMN tipo_doc VARCHAR(4) NOT NULL DEFAULT 'CNPJ' AFTER cnpj"
            )
            print("  tipo_doc: adicionada (VARCHAR(4) NOT NULL DEFAULT 'CNPJ') OK.")
    con.commit()

    print("\n[3] Conferencia final das colunas:")
    with con.cursor() as cur:
        for tab in ("dfe_certificados", "dfe_nsu", "dfe_nsu_cte"):
            cur.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
                "AND COLUMN_NAME IN ('cnpj','tipo_doc') ORDER BY ORDINAL_POSITION",
                (tab,),
            )
            for r in cur.fetchall():
                print("  %-18s %-10s %-14s null=%s default=%s" % (
                    tab, r["COLUMN_NAME"], r["COLUMN_TYPE"], r["IS_NULLABLE"],
                    r["COLUMN_DEFAULT"]))
        cur.execute("SELECT id, cliente_id, cnpj, tipo_doc FROM dfe_certificados")
        print("\n  Registro(s) atual(is):")
        for r in cur.fetchall():
            print("   ", r)
finally:
    con.close()
print("\nFIM - migracao multi-empresa/e-CPF concluida (aditiva, idempotente).")
