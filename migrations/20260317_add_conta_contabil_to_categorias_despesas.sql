-- Migration: 20260317_add_conta_contabil_to_categorias_despesas.sql
-- Vincula cada categoria de despesa a uma conta do Plano de Contas Contábil.
-- Idempotente (usa IF NOT EXISTS / verifica coluna antes de adicionar).

ALTER TABLE categorias_despesas
    ADD COLUMN IF NOT EXISTS conta_contabil_id INT NULL
        COMMENT 'Conta do Plano de Contas Contábil vinculada a esta categoria',
    ADD CONSTRAINT IF NOT EXISTS fk_catdesp_conta
        FOREIGN KEY (conta_contabil_id)
        REFERENCES plano_contas_contas(id)
        ON DELETE SET NULL;

SELECT 'Migration 20260317_add_conta_contabil_to_categorias_despesas aplicada com sucesso.' AS resultado;
