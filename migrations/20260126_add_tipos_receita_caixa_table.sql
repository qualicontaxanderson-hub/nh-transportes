-- ================================================
-- Migration: Add tipos_receita_caixa Table
-- Date: 2026-01-26
-- Description: Creates table for managing cash receipt types
-- ================================================

-- Create tipos_receita_caixa table
CREATE TABLE IF NOT EXISTS tipos_receita_caixa (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    tipo VARCHAR(30) NULL COMMENT 'AUTO para auto-preenchidos, MANUAL para manuais',
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tipos_receita_ativo (ativo),
    INDEX idx_tipos_receita_tipo (tipo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tipos de receitas para fechamento de caixa';

-- Insert initial data (all in UPPERCASE as requested)
INSERT INTO tipos_receita_caixa (nome, tipo, ativo) VALUES
('VENDAS POSTO', 'AUTO', 1),
('ARLA', 'AUTO', 1),
('LUBRIFICANTES', 'AUTO', 1),
('TROCO PIX', 'MANUAL', 1),
('EMPRESTIMOS', 'MANUAL', 1),
('OUTROS', 'MANUAL', 1);

-- ================================================
-- End of Migration
-- ================================================
