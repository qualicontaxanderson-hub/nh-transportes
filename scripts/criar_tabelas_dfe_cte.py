# -*- coding: utf-8 -*-
# ============================================================
# Cria as tabelas do CT-e capturado do DFe (ISOLADAS, aditivas).
# dfe_cte (1:1 com dfe_documentos) + dfe_cte_nfe (N NF-e vinculadas).
# Idempotente (CREATE TABLE IF NOT EXISTS). NAO toca em nada existente.
# ============================================================
import pymysql

CONN = dict(host="centerbeam.proxy.rlwy.net", port=56026, user="root",
            password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV", database="railway",
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
            read_timeout=30, connect_timeout=15)

DDL = [
"""
CREATE TABLE IF NOT EXISTS dfe_cte (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    documento_id  INT NOT NULL,                       -- FK -> dfe_documentos.id (tipo='CTe')
    cfop          VARCHAR(6)   NULL,
    nat_op        VARCHAR(120) NULL,
    tp_cte        VARCHAR(2)   NULL,                  -- 0=Normal 1=Compl 2=Anulacao 3=Substituto
    rem_cnpj      VARCHAR(14)  NULL, rem_nome  VARCHAR(160) NULL,
    dest_cnpj     VARCHAR(14)  NULL, dest_nome VARCHAR(160) NULL,
    toma_codigo   VARCHAR(2)   NULL,                  -- 0..3 (toma3) ou 4 (toma4)
    toma_cnpj     VARCHAR(14)  NULL, toma_nome VARCHAR(160) NULL,
    mun_ini       VARCHAR(60)  NULL, uf_ini    VARCHAR(2)  NULL,
    mun_fim       VARCHAR(60)  NULL, uf_fim    VARCHAR(2)  NULL,
    vprest        DECIMAL(14,2) NULL,                 -- vTPrest (valor do frete)
    vcarga        DECIMAL(14,2) NULL,                 -- vCarga
    prod_predom   VARCHAR(120) NULL,                  -- proPred
    peso          DECIMAL(14,3) NULL,                 -- infQ PESO DECLARADO
    qtd_unid      DECIMAL(14,3) NULL,                 -- infQ UNIDADE
    rntrc         VARCHAR(20)  NULL,
    motorista_nome VARCHAR(120) NULL,
    motorista_cpf  VARCHAR(14)  NULL,
    placa          VARCHAR(10)  NULL,
    criado_em     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_doc (documento_id),
    KEY ix_toma (toma_cnpj),
    CONSTRAINT fk_cte_doc FOREIGN KEY (documento_id)
        REFERENCES dfe_documentos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""",
"""
CREATE TABLE IF NOT EXISTS dfe_cte_nfe (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    documento_id  INT NOT NULL,
    chave_nfe     CHAR(44) NOT NULL,
    UNIQUE KEY uq_doc_nfe (documento_id, chave_nfe),
    KEY ix_chave (chave_nfe),
    CONSTRAINT fk_ctenfe_doc FOREIGN KEY (documento_id)
        REFERENCES dfe_documentos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""",
]

con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() db"); print("Banco:", cur.fetchone()["db"])
        for i, ddl in enumerate(DDL, 1):
            cur.execute(ddl); print(f"  [{i}/{len(DDL)}] OK")
        con.commit()
        for t in ("dfe_cte", "dfe_cte_nfe"):
            cur.execute(f"SELECT COUNT(*) n FROM `{t}`")
            print(f"  {t}: {cur.fetchone()['n']} linhas")
finally:
    con.close()
print("FIM - tabelas de CT-e criadas (isoladas). Nenhuma tabela existente foi tocada.")
