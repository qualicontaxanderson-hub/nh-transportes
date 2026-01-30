-- Migration: Adicionar coluna clienteid à tabela funcionarios se não existir
-- Data: 2026-01-30
-- Descrição: Garante que a coluna clienteid existe na tabela funcionarios para permitir
--            vincular funcionários a clientes/postos específicos
-- Nota: Esta migration é idempotente (pode ser executada múltiplas vezes sem erro)

-- Adicionar coluna clienteid se não existir (usando procedimento seguro)
SET @dbname = DATABASE();
SET @tablename = "funcionarios";
SET @columnname = "clienteid";
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE 
      (table_name = @tablename)
      AND (table_schema = @dbname)
      AND (column_name = @columnname)
  ) > 0,
  "SELECT 1", -- Coluna já existe, não fazer nada
  CONCAT("ALTER TABLE ", @tablename, " ADD COLUMN ", @columnname, " INT NULL AFTER nome")
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- Adicionar índice na coluna clienteid se não existir
SET @indexname = "idx_funcionarios_cliente";
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE 
      (table_name = @tablename)
      AND (table_schema = @dbname)
      AND (index_name = @indexname)
  ) > 0,
  "SELECT 1", -- Índice já existe, não fazer nada
  CONCAT("ALTER TABLE ", @tablename, " ADD INDEX ", @indexname, " (", @columnname, ")")
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;
