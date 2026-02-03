-- ================================================
-- Migration: Add TROCO PIX AUTO type
-- Date: 2026-02-03
-- Description: Adds AUTO type for TROCO PIX to distinguish automatic entries
--              from manual entries in cash closure (Fechamento de Caixa)
-- ================================================

-- First, check if TROCO PIX already exists and update it to be MANUAL
UPDATE tipos_receita_caixa 
SET tipo = 'MANUAL', nome = 'TROCO PIX (MANUAL)'
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = 'MANUAL');

-- Insert AUTO version of TROCO PIX
INSERT INTO tipos_receita_caixa (nome, tipo, ativo) 
SELECT 'TROCO PIX (AUTO)', 'AUTO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM tipos_receita_caixa 
    WHERE nome = 'TROCO PIX (AUTO)' AND tipo = 'AUTO'
);

-- ================================================
-- End of Migration
-- ================================================
