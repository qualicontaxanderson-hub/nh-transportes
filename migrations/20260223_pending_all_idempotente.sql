-- ============================================================
-- MIGRATION CONSOLIDADA IDEMPOTENTE — todas as pendentes
-- Execute UMA VEZ no Railway. Seguro re-executar.
-- Data: 2026-02-23
-- ============================================================

-- 1. bank_supplier_mapping: fornecedor_id nullable (para créditos)
ALTER TABLE bank_supplier_mapping
    MODIFY COLUMN fornecedor_id INT NULL;

ALTER TABLE bank_supplier_mapping
    DROP FOREIGN KEY IF EXISTS fk_bsm_fornecedor;

ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT IF NOT EXISTS fk_bsm_fornecedor
        FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id)
        ON DELETE SET NULL;

-- 2. bank_supplier_mapping: colunas de despesa (título/categoria/subcategoria)
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS titulo_id        INT NULL COMMENT 'Mapeamento de despesa: título',
    ADD COLUMN IF NOT EXISTS categoria_id     INT NULL COMMENT 'Mapeamento de despesa: categoria',
    ADD COLUMN IF NOT EXISTS subcategoria_id  INT NULL COMMENT 'Mapeamento de despesa: subcategoria';

ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT IF NOT EXISTS fk_bsm_titulo
        FOREIGN KEY (titulo_id) REFERENCES titulos_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT IF NOT EXISTS fk_bsm_categoria
        FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT IF NOT EXISTS fk_bsm_subcat
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias_despesas(id) ON DELETE SET NULL;

-- 3. bank_supplier_mapping: transferências entre contas
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS conta_destino_id INT NULL    COMMENT 'Para transferências: conta bancária de destino',
    ADD COLUMN IF NOT EXISTS tipo_debito      VARCHAR(20) NULL COMMENT 'fornecedor | despesa | transferencia';

ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT IF NOT EXISTS fk_bsm_conta_destino
        FOREIGN KEY (conta_destino_id) REFERENCES bank_accounts(id)
        ON DELETE SET NULL;

-- 4. bank_conciliacao_regras: campos compostos (já executado na sessão anterior,
--    ADD COLUMN IF NOT EXISTS é seguro re-executar)
ALTER TABLE bank_conciliacao_regras
    ADD COLUMN IF NOT EXISTS padrao_secundario VARCHAR(200) NULL
        COMMENT 'Segundo padrão: a descrição também deve conter este texto'
        AFTER padrao_descricao,
    ADD COLUMN IF NOT EXISTS cliente_id    INT NULL AFTER fornecedor_id,
    ADD COLUMN IF NOT EXISTS titulo_id     INT NULL AFTER cliente_id,
    ADD COLUMN IF NOT EXISTS categoria_id  INT NULL AFTER titulo_id,
    ADD COLUMN IF NOT EXISTS subcategoria_id INT NULL AFTER categoria_id,
    ADD COLUMN IF NOT EXISTS account_id    INT NULL AFTER subcategoria_id;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_cliente
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_titulo
        FOREIGN KEY (titulo_id) REFERENCES titulos_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_categoria
        FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_subcat
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_account
        FOREIGN KEY (account_id) REFERENCES bank_accounts(id) ON DELETE SET NULL;

-- 5. bank_accounts: vincular empresa (cliente_id)
ALTER TABLE bank_accounts
    ADD COLUMN IF NOT EXISTS cliente_id INT NULL AFTER apelido;

ALTER TABLE bank_accounts
    ADD CONSTRAINT IF NOT EXISTS fk_ba_cliente
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ba_cliente ON bank_accounts(cliente_id);
