-- Migration CONSOLIDADA (idempotente): bank_conciliacao_regras
-- Substitui as migrations anteriores:
--   20260223_add_regras_composite.sql
--   20260223_add_regras_account_subcat.sql
-- Seguro re-executar (ADD COLUMN IF NOT EXISTS).
-- Execute no Railway antes do próximo deploy.

ALTER TABLE bank_conciliacao_regras
    ADD COLUMN IF NOT EXISTS padrao_secundario VARCHAR(200) NULL
        COMMENT 'Segundo padrão: descrição também deve conter este texto' AFTER padrao_descricao,
    ADD COLUMN IF NOT EXISTS cliente_id INT NULL
        COMMENT 'Para créditos de cobrança: vincula ao cliente específico' AFTER fornecedor_id,
    ADD COLUMN IF NOT EXISTS titulo_id INT NULL
        COMMENT 'Para débitos → despesa: título da despesa' AFTER cliente_id,
    ADD COLUMN IF NOT EXISTS categoria_id INT NULL
        COMMENT 'Para débitos → despesa: categoria da despesa' AFTER titulo_id,
    ADD COLUMN IF NOT EXISTS subcategoria_id INT NULL
        COMMENT 'Subcategoria da despesa (opcional)' AFTER categoria_id,
    ADD COLUMN IF NOT EXISTS account_id INT NULL
        COMMENT 'Conta bancária específica (NULL = aplica a todas)' AFTER subcategoria_id;

-- FKs (ignorar erro se já existirem)
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
