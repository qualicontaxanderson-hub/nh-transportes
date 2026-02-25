-- Migration: 20260221_bank_accounts_add_cliente.sql
-- Adiciona coluna cliente_id à tabela bank_accounts para vincular cada conta bancária
-- à empresa (cliente com produtos) correspondente.

ALTER TABLE bank_accounts
    ADD COLUMN IF NOT EXISTS cliente_id INT NULL AFTER apelido,
    ADD CONSTRAINT IF NOT EXISTS fk_ba_cliente
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ba_cliente ON bank_accounts(cliente_id);
