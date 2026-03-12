-- Migration: adiciona coluna pedido_id na tabela fretes
-- Vincula cada frete ao pedido de origem (opcional, NULL por padrão).
-- Idempotente: o bloco IF só executa o ALTER quando a coluna ainda não existe.

SET @col_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'fretes'
      AND COLUMN_NAME  = 'pedido_id'
);

SET @sql = IF(
    @col_exists = 0,
    'ALTER TABLE fretes ADD COLUMN pedido_id INT NULL DEFAULT NULL',
    'SELECT ''coluna pedido_id já existe'' AS info'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
