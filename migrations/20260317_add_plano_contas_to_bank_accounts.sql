-- Migration: 20260317_add_plano_contas_to_bank_accounts.sql
-- Vincula cada conta bancária a uma conta do plano de contas contábil

ALTER TABLE bank_accounts
    ADD COLUMN IF NOT EXISTS plano_contas_conta_id INT NULL
        COMMENT 'FK para plano_contas_contas – conta contábil da conta corrente'
        AFTER cliente_id,
    ADD CONSTRAINT IF NOT EXISTS fk_ba_plano_contas
        FOREIGN KEY (plano_contas_conta_id) REFERENCES plano_contas_contas(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ba_plano_contas ON bank_accounts(plano_contas_conta_id);
