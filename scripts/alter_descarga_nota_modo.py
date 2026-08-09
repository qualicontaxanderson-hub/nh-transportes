# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRATION IDEMPOTENTE — parcial/integral no vinculo descarga<->nota.
#
#  Acrescenta em descarga_nota:
#    modo          ENUM('parcial','integral')  quem FECHOU a nota
#    perda_sobra_l DECIMAL(14,3) NULL          so na linha do fechamento
#
#  A flag fica no LANCAMENTO, nao na nota: assim fica registrado quando e em
#  qual descarga a nota foi fechada, e desfazer esse vinculo reabre a nota
#  sozinho — sem precisar lembrar de limpar flag em outro lugar.
#
#  perda_sobra_l e gravada SO na linha que fecha, no momento em que fecha.
#  Enquanto a nota esta aberta o numero e calculado na hora (provisorio):
#  valor derivado que fica gravado desincroniza quando entra outro vinculo.
#
#  Aditiva e idempotente: so adiciona coluna que ainda nao existe.
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/alter_descarga_nota_modo.py
# ============================================================================
import os

import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password=os.environ["DB_PASSWORD"],
    database="railway", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)

COLUNAS = [
    ("modo",
     "ENUM('parcial','integral') NOT NULL DEFAULT 'parcial' "
     "COMMENT 'integral = este lancamento FECHOU a nota' AFTER litros"),
    ("perda_sobra_l",
     "DECIMAL(14,3) NULL "
     "COMMENT 'so na linha que fecha: recebido total da nota - quantidade da nota' "
     "AFTER modo"),
]


def coluna_existe(cur, tabela, coluna):
    cur.execute(
        "SELECT COUNT(*) AS n FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (tabela, coluna),
    )
    return cur.fetchone()["n"] > 0


con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db")
        print("Banco:", cur.fetchone()["db"])

        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'descarga_nota'")
        if not cur.fetchone()["n"]:
            raise SystemExit("ABORTADO: tabela descarga_nota nao existe. "
                             "Rode antes scripts/criar_tabela_descarga_nota.py")

        for nome, definicao in COLUNAS:
            if coluna_existe(cur, "descarga_nota", nome):
                print("  descarga_nota.%-14s ja existe (nao altera)" % nome)
            else:
                cur.execute("ALTER TABLE descarga_nota ADD COLUMN %s %s" % (nome, definicao))
                print("  descarga_nota.%-14s ADICIONADA" % nome)

        # Indice para "esta nota ja foi fechada?" (EXISTS por item + modo).
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = 'descarga_nota' "
            "AND index_name = 'ix_item_modo'")
        if cur.fetchone()["n"] == 0:
            cur.execute("ALTER TABLE descarga_nota ADD KEY ix_item_modo (item_id, modo)")
            print("  indice ix_item_modo: ADICIONADO")
        else:
            print("  indice ix_item_modo: ja existe")

        con.commit()

        cur.execute(
            "SELECT column_name, column_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'descarga_nota' "
            "ORDER BY ordinal_position")
        print("\n  descarga_nota agora:")
        for c in cur.fetchall():
            print("    %-14s %-34s %s" % (c["column_name"], c["column_type"],
                                          "NULL" if c["is_nullable"] == "YES" else "NOT NULL"))
finally:
    con.close()

print("\nFIM — migration aditiva aplicada. Nada existente foi alterado.")
