-- Migration: 20260224_add_bank_transaction_id_to_despesas.sql
-- Vincula lançamentos de despesas à transação bancária de origem.
-- Permite distinguir orfãos de transferência vs despesas na tela /financeiro/transferencias/.

ALTER TABLE lancamentos_despesas
    ADD COLUMN IF NOT EXISTS bank_transaction_id INT NULL
        COMMENT 'ID da bank_transactions que originou este lançamento (via OFX/conciliação)',
    ADD INDEX IF NOT EXISTS idx_ld_bank_transaction_id (bank_transaction_id);
