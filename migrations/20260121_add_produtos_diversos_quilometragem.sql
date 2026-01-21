-- Add valor_produtos_diversos column to quilometragem table
-- This column will store expenses with other products (not just fuel)

ALTER TABLE quilometragem
ADD COLUMN valor_produtos_diversos DECIMAL(10,2) DEFAULT 0.00
COMMENT 'Valor gasto com produtos diversos (não combustível)';
