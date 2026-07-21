# -*- coding: utf-8 -*-
# ============================================================================
#  MIGRATION IDEMPOTENTE - tabelas do servico de captura de DFe (SEFAZ)
#  Cria 4 tabelas NOVAS e ISOLADAS. Empresa = clientes.id. XML fica no Dropbox.
# ============================================================================
import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV",
    database="railway", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)

DDL = [
"""
CREATE TABLE IF NOT EXISTS dfe_certificados (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id        INT           NOT NULL,
    cnpj              VARCHAR(14)   NOT NULL,
    tipo_doc          VARCHAR(4)    NOT NULL DEFAULT 'CNPJ',
    nome_arquivo      VARCHAR(160)  NULL,
    pfx_conteudo      LONGBLOB      NULL,
    senha_cifrada     VARBINARY(512) NULL,
    validade_ate      DATE          NULL,
    modo_automatico   TINYINT(1)    NOT NULL DEFAULT 1,
    ativo             TINYINT(1)    NOT NULL DEFAULT 1,
    criado_em         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cliente (cliente_id),
    KEY ix_cnpj (cnpj),
    KEY ix_validade (validade_ate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""",
"""
CREATE TABLE IF NOT EXISTS dfe_nsu (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id        INT           NOT NULL,
    cnpj              VARCHAR(14)   NOT NULL,
    ult_nsu           BIGINT        NOT NULL DEFAULT 0,
    max_nsu           BIGINT        NOT NULL DEFAULT 0,
    ult_consulta      DATETIME      NULL,
    proximo_permitido DATETIME      NULL,
    ult_status        VARCHAR(255)  NULL,
    atualizado_em     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cliente (cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""",
"""
CREATE TABLE IF NOT EXISTS dfe_documentos (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id        INT           NOT NULL,
    chave             CHAR(44)      NOT NULL,
    tipo              VARCHAR(6)     NOT NULL,
    nsu               BIGINT         NULL,
    schema_dfe        VARCHAR(40)    NULL,
    resumo            TINYINT(1)     NOT NULL DEFAULT 0,
    numero            VARCHAR(20)    NULL,
    serie             VARCHAR(6)     NULL,
    modelo            VARCHAR(4)     NULL,
    dh_emissao        DATETIME       NULL,
    emit_cnpj         VARCHAR(14)    NULL,
    emit_nome         VARCHAR(160)   NULL,
    dest_cnpj         VARCHAR(14)    NULL,
    valor_total       DECIMAL(14,2)  NULL,
    situacao          VARCHAR(20)    NOT NULL DEFAULT 'autorizado',
    manifesto         VARCHAR(20)    NULL,
    xml_caminho       VARCHAR(300)   NULL,
    xml_expira_em     DATE           NULL,
    pedido_id         INT            NULL,
    frete_id          INT            NULL,
    conferido         TINYINT(1)     NOT NULL DEFAULT 0,
    criado_em         TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em     TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_chave (chave),
    KEY ix_cliente (cliente_id),
    KEY ix_tipo (tipo),
    KEY ix_emit (emit_cnpj),
    KEY ix_dh (dh_emissao),
    KEY ix_situacao (situacao),
    KEY ix_expira (xml_expira_em)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""",
"""
CREATE TABLE IF NOT EXISTS dfe_itens (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    documento_id      INT            NOT NULL,
    n_item            INT            NOT NULL,
    produto_xml       VARCHAR(160)   NULL,
    cod_anp           VARCHAR(12)    NULL,
    produto_id        INT            NULL,
    ncm               VARCHAR(10)    NULL,
    unidade           VARCHAR(6)     NULL,
    quantidade        DECIMAL(15,4)  NULL,
    valor_unitario    DECIMAL(15,6)  NULL,
    valor_total       DECIMAL(14,2)  NULL,
    UNIQUE KEY uq_item (documento_id, n_item),
    KEY ix_anp (cod_anp),
    KEY ix_produto (produto_id),
    CONSTRAINT fk_dfeitem_doc FOREIGN KEY (documento_id)
        REFERENCES dfe_documentos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""",
]

con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db"); print("Banco:", cur.fetchone()["db"])
        for i, ddl in enumerate(DDL, 1):
            cur.execute(ddl); print(f"  [{i}/{len(DDL)}] OK")
        con.commit()
        for t in ("dfe_certificados", "dfe_nsu", "dfe_documentos", "dfe_itens"):
            cur.execute(f"SELECT COUNT(*) AS n FROM `{t}`")
            print(f"  {t}: {cur.fetchone()['n']} linhas")
finally:
    con.close()
print("FIM - 4 tabelas DFe criadas, isoladas.")
