# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRATION IDEMPOTENTE - classificacao de COMPRAS do servico DFe.
#
#  Cria:
#    - dfe_classificacao_regra  (de-para memorizado: CNPJ+cProd -> categoria/produto)
#  Adiciona (ALTER aditivo) em dfe_itens:
#    - categoria, classificado_produto_id, classificado_em, classificado_modo
#
#  NAO remove nem altera nada existente. Pode rodar quantas vezes quiser:
#    - tabela via CREATE TABLE IF NOT EXISTS
#    - colunas so sao adicionadas se ainda nao existirem (MySQL 8 nao tem
#      ADD COLUMN IF NOT EXISTS; conferimos no information_schema antes).
# ============================================================================
import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV", database="railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)

DDL_REGRA = """
CREATE TABLE IF NOT EXISTS dfe_classificacao_regra (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    emit_cnpj         CHAR(14)      NOT NULL,
    cprod_fornecedor  VARCHAR(60)   NOT NULL,
    categoria         VARCHAR(20)   NOT NULL,   -- combustivel|despesa|ativo|produto
    produto_id        INT           NULL,       -- so quando categoria='combustivel'
    criado_em         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_regra (emit_cnpj, cprod_fornecedor),
    KEY ix_categoria (categoria),
    KEY ix_produto (produto_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# Colunas aditivas em dfe_itens: (nome, definicao)
COLS_ITENS = [
    ("categoria",                "VARCHAR(20)  NULL AFTER produto_id"),
    ("classificado_produto_id",  "INT          NULL AFTER categoria"),
    ("classificado_em",          "TIMESTAMP    NULL AFTER classificado_produto_id"),
    ("classificado_modo",        "VARCHAR(12)  NULL AFTER classificado_em"),  # memorizado|so_desta_vez
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

        # 1) Tabela de regras (de-para).
        cur.execute(DDL_REGRA)
        print("  [1] dfe_classificacao_regra OK (CREATE IF NOT EXISTS)")

        # 2) Colunas aditivas em dfe_itens.
        for nome, definicao in COLS_ITENS:
            if coluna_existe(cur, "dfe_itens", nome):
                print(f"  [2] dfe_itens.{nome}: ja existe (nao altera)")
            else:
                cur.execute(f"ALTER TABLE dfe_itens ADD COLUMN {nome} {definicao}")
                print(f"  [2] dfe_itens.{nome}: ADICIONADA")

        # Indice opcional para acelerar 'pendentes' (categoria IS NULL).
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = 'dfe_itens' "
            "AND index_name = 'ix_categoria'"
        )
        if cur.fetchone()["n"] == 0:
            cur.execute("ALTER TABLE dfe_itens ADD KEY ix_categoria (categoria)")
            print("  [3] indice dfe_itens.ix_categoria: ADICIONADO")
        else:
            print("  [3] indice dfe_itens.ix_categoria: ja existe")

        con.commit()

        # Confirmacao.
        cur.execute("SELECT COUNT(*) AS n FROM dfe_classificacao_regra")
        print(f"  dfe_classificacao_regra: {cur.fetchone()['n']} linhas")
finally:
    con.close()

print("FIM - migration de classificacao aplicada (isolada, aditiva).")
