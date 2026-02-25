-- ================================================================
-- MIGRATION FINAL CONSOLIDADA — Execute no Railway
-- Seguro re-executar (ADD COLUMN IF NOT EXISTS / ADD INDEX IF NOT EXISTS)
-- Data: 2026-02-24
-- ================================================================

-- 1. bank_transactions: tipo de conciliação (transferencia/despesa/fornecedor...)
--    Sem isso, a página /financeiro/transferencias/ fica vazia.
ALTER TABLE bank_transactions
    ADD COLUMN IF NOT EXISTS tipo_conciliacao VARCHAR(20) NULL
        COMMENT 'Tipo: transferencia, fornecedor, forma_recebimento, despesa, regra, regra_despesa';

ALTER TABLE bank_transactions
    ADD INDEX IF NOT EXISTS idx_bt_tipo_conciliacao (tipo_conciliacao);

-- 2. lancamentos_despesas: vínculo com a transação bancária de origem
ALTER TABLE lancamentos_despesas
    ADD COLUMN IF NOT EXISTS bank_transaction_id INT NULL
        COMMENT 'ID da bank_transactions que originou este lançamento',
    ADD INDEX IF NOT EXISTS idx_ld_bank_transaction_id (bank_transaction_id);

-- 3. bank_supplier_mapping: permitir fornecedor_id = NULL (para créditos/formas recebimento)
ALTER TABLE bank_supplier_mapping
    MODIFY COLUMN fornecedor_id INT NULL;

-- 4. bank_supplier_mapping: colunas de mapeamento de despesas
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS titulo_id        INT NULL,
    ADD COLUMN IF NOT EXISTS categoria_id     INT NULL,
    ADD COLUMN IF NOT EXISTS subcategoria_id  INT NULL,
    ADD COLUMN IF NOT EXISTS conta_destino_id INT NULL,
    ADD COLUMN IF NOT EXISTS tipo_debito      VARCHAR(20) NULL;

-- 5. bank_conciliacao_regras: campos adicionais de regras compostas
ALTER TABLE bank_conciliacao_regras
    ADD COLUMN IF NOT EXISTS padrao_secundario VARCHAR(200) NULL AFTER padrao_descricao,
    ADD COLUMN IF NOT EXISTS cliente_id        INT NULL,
    ADD COLUMN IF NOT EXISTS titulo_id         INT NULL,
    ADD COLUMN IF NOT EXISTS categoria_id      INT NULL,
    ADD COLUMN IF NOT EXISTS subcategoria_id   INT NULL,
    ADD COLUMN IF NOT EXISTS account_id        INT NULL;

-- 6. bank_accounts: vincular conta a uma empresa (cliente_id)
ALTER TABLE bank_accounts
    ADD COLUMN IF NOT EXISTS cliente_id INT NULL;

SELECT 'Migration FINAL aplicada com sucesso!' AS resultado;
