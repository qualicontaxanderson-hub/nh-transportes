-- Migration: 20260304_add_conta_origem_to_bank_transactions.sql
-- Adiciona coluna conta_origem_id em bank_transactions para registrar de qual
-- conta bancária veio um crédito do tipo "Transferência Recebida".
-- Isso permite ligar as duas pontas de uma transferência entre contas.

SET @dbname = DATABASE();
SET @colname = 'conta_origem_id';
SET @tablename = 'bank_transactions';

SET @stmt = (
  SELECT IF(
    COUNT(*) = 0,
    CONCAT('ALTER TABLE ', @tablename,
           ' ADD COLUMN ', @colname,
           ' INT NULL COMMENT ''Conta bancária de origem para transferências recebidas (CREDIT)''',
           ', ADD CONSTRAINT fk_bt_conta_origem FOREIGN KEY (conta_origem_id)'
           ' REFERENCES bank_accounts(id) ON DELETE SET NULL'),
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
