-- Migration to add preco_venda column to lubrificantes_produtos
-- Date: 2026-01-21
-- This allows storing product prices directly in the product table

ALTER TABLE lubrificantes_produtos 
ADD COLUMN preco_venda DECIMAL(10,2) NULL COMMENT 'Preço de venda do produto (opcional)';
