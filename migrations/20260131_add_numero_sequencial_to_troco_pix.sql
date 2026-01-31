-- Migration: Adicionar numero_sequencial ao TROCO PIX
-- Data: 31/01/2026
-- Descrição: Adiciona campo para numeração sequencial estilo PIX-DD-MM-YYYY-N1

-- 1. Adicionar coluna numero_sequencial
ALTER TABLE troco_pix 
ADD COLUMN numero_sequencial VARCHAR(50) NULL 
COMMENT 'Número sequencial do troco PIX (ex: PIX-31-01-2026-N1)';

-- 2. Criar índice para melhor performance
CREATE INDEX idx_troco_pix_numero ON troco_pix(numero_sequencial);

-- 3. Adicionar índice para buscar último número por data
CREATE INDEX idx_troco_pix_data ON troco_pix(data);

-- Verificação
-- SHOW COLUMNS FROM troco_pix LIKE 'numero_sequencial';

-- Rollback (se necessário)
-- ALTER TABLE troco_pix DROP COLUMN numero_sequencial;
-- DROP INDEX idx_troco_pix_numero ON troco_pix;
-- DROP INDEX idx_troco_pix_data ON troco_pix;
