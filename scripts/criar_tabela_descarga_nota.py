# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRATION IDEMPOTENTE — vinculo descarga <-> NF-e de compra (Camada 2).
#
#  Cria UMA tabela nova e ISOLADA: descarga_nota.
#  NAO altera descargas_pendentes (frete_id continua sendo o controle interno),
#  NAO altera dfe_documentos, dfe_itens nem qualquer coisa existente.
#  Pode rodar quantas vezes quiser (CREATE TABLE IF NOT EXISTS).
#
#  O vinculo e POR ITEM, nao por nota: uma NF-e pode trazer S10 e S500 no mesmo
#  documento e cada um vai pra um tanque/descarga diferente. `litros` guarda
#  QUANTO daquele item foi nesta descarga — e o que permite vinculo PARCIAL
#  (uma nota grande descarregada em varias vezes) sem coluna de flag: total x
#  parcial vira consequencia de somar `litros`, nao um estado gravado.
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/criar_tabela_descarga_nota.py
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

DDL = """
CREATE TABLE IF NOT EXISTS descarga_nota (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    descarga_id   INT           NOT NULL COMMENT 'FK -> descargas_pendentes.id',
    documento_id  INT           NOT NULL COMMENT 'FK -> dfe_documentos.id (a NF-e)',
    item_id       INT           NOT NULL COMMENT 'FK -> dfe_itens.id (qual item da nota)',
    litros        DECIMAL(14,3) NOT NULL COMMENT 'Quanto DESTE item entrou NESTA descarga',
    observacao    VARCHAR(255)  NULL,
    criado_em     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por    INT           NULL COMMENT 'usuarios.id (sem FK: nao trava exclusao de usuario)',
    UNIQUE KEY uq_descarga_item (descarga_id, item_id),
    KEY ix_descarga  (descarga_id),
    KEY ix_documento (documento_id),
    KEY ix_item      (item_id),
    CONSTRAINT ck_dn_litros CHECK (litros > 0),
    CONSTRAINT fk_dn_descarga FOREIGN KEY (descarga_id)
        REFERENCES descargas_pendentes(id) ON DELETE CASCADE,
    CONSTRAINT fk_dn_documento FOREIGN KEY (documento_id)
        REFERENCES dfe_documentos(id) ON DELETE RESTRICT,
    CONSTRAINT fk_dn_item FOREIGN KEY (item_id)
        REFERENCES dfe_itens(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Vinculo por item entre descarga fisica (ELS) e NF-e de compra';
"""


def _existe_tabela(cur, nome):
    cur.execute(
        "SELECT COUNT(*) AS n FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (nome,),
    )
    return cur.fetchone()["n"] > 0


con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db")
        print("Banco:", cur.fetchone()["db"])

        # Pre-checagem: as tabelas que a nova referencia precisam existir, senao
        # o CREATE falha com um erro de FK dificil de ler.
        faltando = [t for t in ("descargas_pendentes", "dfe_documentos", "dfe_itens")
                    if not _existe_tabela(cur, t)]
        if faltando:
            raise SystemExit("ABORTADO: faltam tabelas base: %s" % ", ".join(faltando))

        ja_existia = _existe_tabela(cur, "descarga_nota")
        cur.execute(DDL)
        con.commit()
        print("  descarga_nota:", "ja existia (nao alterada)" if ja_existia else "CRIADA")

        # Confirmacao: estrutura + chaves estrangeiras efetivamente criadas.
        cur.execute("SELECT COUNT(*) AS n FROM descarga_nota")
        print("  linhas:", cur.fetchone()["n"])

        cur.execute(
            "SELECT column_name, column_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'descarga_nota' "
            "ORDER BY ordinal_position"
        )
        print("  colunas:")
        for c in cur.fetchall():
            print("    %-13s %-14s %s" % (c["column_name"], c["column_type"],
                                          "NULL" if c["is_nullable"] == "YES" else "NOT NULL"))

        cur.execute(
            "SELECT constraint_name, referenced_table_name "
            "FROM information_schema.referential_constraints "
            "WHERE constraint_schema = DATABASE() AND table_name = 'descarga_nota'"
        )
        fks = cur.fetchall()
        print("  FKs:", ", ".join("%s -> %s" % (f["constraint_name"], f["referenced_table_name"])
                                  for f in fks) or "(nenhuma)")
finally:
    con.close()

print("FIM — descarga_nota pronta (isolada, aditiva). Nada existente foi tocado.")
