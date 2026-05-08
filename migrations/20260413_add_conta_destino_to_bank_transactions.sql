-- Migration: 20260413_add_conta_destino_to_bank_transactions.sql
-- Adiciona coluna conta_destino_id em bank_transactions para registrar para
-- qual conta bancária foi enviado um débito do tipo "Transferência Enviada".
-- Isso permite que a exportação contábil resolva as contas das coligadas
-- no lado débito de transferências entre empresas.

SET @dbname = DATABASE();
SET @colname = 'conta_destino_id';
SET @tablename = 'bank_transactions';

SET @stmt = (
  SELECT IF(
    COUNT(*) = 0,
    CONCAT('ALTER TABLE ', @tablename,
           ' ADD COLUMN ', @colname,
           ' INT NULL COMMENT ''Conta bancária de destino para transferências enviadas (DEBIT)'''),
    'SELECT 1 -- coluna ja existe'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @dbname
    AND TABLE_NAME   = @tablename
    AND COLUMN_NAME  = @colname
);
PREPARE stmt FROM @stmt;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT 'Migration 20260413_add_conta_destino_to_bank_transactions aplicada com sucesso.' AS resultado;
