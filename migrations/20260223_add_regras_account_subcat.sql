-- Migration: 20260223_add_regras_account_subcat.sql
-- Adiciona subcategoria_id e account_id em bank_conciliacao_regras.
-- subcategoria_id: nível 3 da hierarquia Título → Categoria → Subcategoria
-- account_id: restringe a regra a uma conta bancária específica (opcional)

ALTER TABLE bank_conciliacao_regras
    ADD COLUMN IF NOT EXISTS subcategoria_id INT NULL
        COMMENT 'Subcategoria da despesa (opcional)' AFTER categoria_id,
    ADD COLUMN IF NOT EXISTS account_id INT NULL
        COMMENT 'Conta bancária específica (NULL = aplica a todas)' AFTER subcategoria_id;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_subcat
        FOREIGN KEY (subcategoria_id) REFERENCES subcategorias_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_account
        FOREIGN KEY (account_id) REFERENCES bank_accounts(id) ON DELETE SET NULL;
