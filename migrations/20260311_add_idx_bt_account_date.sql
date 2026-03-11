-- Migration: 20260311_add_idx_bt_account_date.sql
-- Adds a composite index on (account_id, data_transacao) to support the
-- content-based deduplication query added in _save_transactions.
-- The query: WHERE account_id = %s AND data_transacao BETWEEN %s AND %s
-- benefits from this index, which covers both filter columns together.

ALTER TABLE bank_transactions
    ADD INDEX IF NOT EXISTS idx_bt_account_date (account_id, data_transacao);
