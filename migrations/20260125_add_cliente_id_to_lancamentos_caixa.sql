-- Migration: Add cliente_id column to lancamentos_caixa table
-- Date: 2026-01-25
-- Description: Adds client reference to cash closure entries for better tracking

-- Add cliente_id column to lancamentos_caixa
ALTER TABLE `lancamentos_caixa` 
ADD COLUMN `cliente_id` INT NULL AFTER `data`,
ADD INDEX `idx_lancamentos_caixa_cliente` (`cliente_id`),
ADD FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE SET NULL;

-- Note: Existing records will have NULL for cliente_id
-- This is acceptable as they were created before this feature was added
