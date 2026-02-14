-- Migration: Add cliente_id to lancamentos_despesas for multi-company support
-- Created: 2026-02-14
-- Description: Adds cliente_id field to support multiple companies in expense postings

-- Add cliente_id column to lancamentos_despesas
ALTER TABLE `lancamentos_despesas` 
ADD COLUMN `cliente_id` INT NULL AFTER `data`,
ADD FOREIGN KEY (`fk_lancamentos_despesas_cliente`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
ADD INDEX `idx_lancamentos_despesas_cliente` (`cliente_id`);

-- Note: Existing records will have cliente_id = NULL
-- They should be updated manually or via admin interface if needed
