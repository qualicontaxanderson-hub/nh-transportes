# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRATION IDEMPOTENTE — lancamento MANUAL de descarga.
#
#  Acrescenta em descargas_pendentes:
#    origem     VARCHAR(30) NOT NULL DEFAULT 'els_email'   els_email | manual
#    descricao  VARCHAR(255) NULL                          motivo do manual
#    criado_por INT NULL                                   usuarios.id
#
#  origem copia nome, tipo e default de leitura_tanque_diaria.origem, que ja
#  existe. Assim as linhas atuais viram 'els_email' sozinhas — que e a verdade,
#  todas vieram do e-mail.
#
#  criado_por sem FK (mesma escolha de descarga_nota): apagar um usuario nao
#  pode travar por causa de um lancamento antigo.
#
#  Aditiva e idempotente: so adiciona coluna que ainda nao existe.
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/alter_descargas_pendentes_manual.py
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
    ("origem",
     "VARCHAR(30) NOT NULL DEFAULT 'els_email' "
     "COMMENT 'els_email | manual' AFTER status"),
    ("descricao",
     "VARCHAR(255) NULL COMMENT 'motivo do lancamento manual' AFTER origem"),
    ("criado_por",
     "INT NULL COMMENT 'usuarios.id de quem lancou (NULL quando veio do ELS)' "
     "AFTER descricao"),
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
            "WHERE table_schema = DATABASE() AND table_name = 'descargas_pendentes'")
        if not cur.fetchone()["n"]:
            raise SystemExit("ABORTADO: tabela descargas_pendentes nao existe.")

        for nome, definicao in COLUNAS:
            if coluna_existe(cur, "descargas_pendentes", nome):
                print("  descargas_pendentes.%-11s ja existe (nao altera)" % nome)
            else:
                cur.execute("ALTER TABLE descargas_pendentes ADD COLUMN %s %s"
                            % (nome, definicao))
                print("  descargas_pendentes.%-11s ADICIONADA" % nome)

        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = 'descargas_pendentes' "
            "AND index_name = 'ix_origem'")
        if cur.fetchone()["n"] == 0:
            cur.execute("ALTER TABLE descargas_pendentes ADD KEY ix_origem (origem)")
            print("  indice ix_origem: ADICIONADO")
        else:
            print("  indice ix_origem: ja existe")

        con.commit()

        cur.execute("SELECT origem, COUNT(*) AS n FROM descargas_pendentes "
                    "GROUP BY origem ORDER BY origem")
        print("\n  descargas por origem:")
        for r in cur.fetchall():
            print("    %-12s %d" % (r["origem"], r["n"]))
finally:
    con.close()

print("\nFIM — migration aditiva aplicada. Nenhuma descarga existente foi alterada.")
