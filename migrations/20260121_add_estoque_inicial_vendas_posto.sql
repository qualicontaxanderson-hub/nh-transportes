-- Migration script to add estoque_inicial column to vendas_posto
-- Created: 2026-01-21
-- Description: Adds estoque_inicial (initial stock) column to vendas_posto table

-- Add estoque_inicial column to vendas_posto table (whole numbers only, no decimals)
ALTER TABLE `vendas_posto` 
ADD COLUMN `estoque_inicial` INT NULL DEFAULT NULL 
COMMENT 'Estoque inicial do produto no dia (litros inteiros)' 
AFTER `quantidade_litros`;

-- Add index for better query performance
CREATE INDEX `idx_vendas_posto_estoque` ON `vendas_posto`(`estoque_inicial`);
