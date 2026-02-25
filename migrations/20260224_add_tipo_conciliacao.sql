-- Migration: 20260224_add_tipo_conciliacao.sql
-- Adiciona coluna tipo_conciliacao em bank_transactions para
-- distinguir transferências entre contas de despesas/fornecedores.
-- Valores: 'transferencia', 'fornecedor', 'forma_recebimento',
--          'despesa', 'regra', 'regra_despesa'
-- Executar no Railway (idempotente - usa IF NOT EXISTS).

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'bank_transactions'
      AND COLUMN_NAME  = 'tipo_conciliacao'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE bank_transactions ADD COLUMN tipo_conciliacao VARCHAR(20) NULL COMMENT ''Tipo de conciliação: transferencia, fornecedor, forma_recebimento, despesa, regra, regra_despesa''',
    'SELECT ''coluna tipo_conciliacao já existe''');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Índice para filtrar por tipo rapidamente
SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'bank_transactions'
      AND INDEX_NAME   = 'idx_bt_tipo_conciliacao'
);

SET @sql2 = IF(@idx_exists = 0,
    'ALTER TABLE bank_transactions ADD INDEX idx_bt_tipo_conciliacao (tipo_conciliacao)',
    'SELECT ''índice idx_bt_tipo_conciliacao já existe''');

PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

SELECT 'Migration 20260224_add_tipo_conciliacao aplicada com sucesso.' AS resultado;
