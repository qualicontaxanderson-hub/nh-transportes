-- Migration script to change tipo column from ENUM to VARCHAR
-- Created: 2026-01-27
-- Description: Allows dynamic receipt types instead of fixed ENUM values
-- This fixes error: "Data truncated for column 'tipo' at row 1"

-- Alter lancamentos_caixa_receitas table to change tipo from ENUM to VARCHAR
ALTER TABLE `lancamentos_caixa_receitas` 
MODIFY COLUMN `tipo` VARCHAR(100) NOT NULL;
