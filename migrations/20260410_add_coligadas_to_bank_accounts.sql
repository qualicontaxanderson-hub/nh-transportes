-- Migration: 20260410_add_coligadas_to_bank_accounts.sql
-- Adiciona colunas de conta contábil para operações entre coligadas em bank_accounts.
-- Cada conta corrente do grupo pode ter uma conta contábil configurada para quando
-- recebe (crédito) ou envia (débito) valores para outras empresas do grupo.

ALTER TABLE bank_accounts
    ADD COLUMN IF NOT EXISTS conta_coligada_debito_id INT NULL
        COMMENT 'FK plano_contas_contas – conta contábil usada como DÉBITO em transferências entre coligadas',
    ADD COLUMN IF NOT EXISTS conta_coligada_credito_id INT NULL
        COMMENT 'FK plano_contas_contas – conta contábil usada como CRÉDITO em transferências entre coligadas';

ALTER TABLE bank_accounts
    ADD CONSTRAINT IF NOT EXISTS fk_ba_coligada_deb
        FOREIGN KEY (conta_coligada_debito_id) REFERENCES plano_contas_contas(id) ON DELETE SET NULL,
    ADD CONSTRAINT IF NOT EXISTS fk_ba_coligada_cred
        FOREIGN KEY (conta_coligada_credito_id) REFERENCES plano_contas_contas(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ba_coligada_deb ON bank_accounts(conta_coligada_debito_id);
CREATE INDEX IF NOT EXISTS idx_ba_coligada_cred ON bank_accounts(conta_coligada_credito_id);

SELECT 'Migration 20260410_add_coligadas_to_bank_accounts aplicada com sucesso.' AS resultado;
