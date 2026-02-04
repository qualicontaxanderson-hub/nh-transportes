-- ================================================
-- Migration: Adicionar Sobras, Perdas e Vales de Caixa por Funcionário
-- Data: 2026-02-03
-- Descrição: Adiciona tabelas para registrar sobras, perdas e vales
--            de caixa vinculados a funcionários no fechamento de caixa
-- ================================================

-- Tabela para Sobras de Caixa (Receitas)
CREATE TABLE IF NOT EXISTS lancamentos_caixa_sobras_funcionarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lancamento_caixa_id INT NOT NULL,
    funcionario_id INT NOT NULL,
    valor DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    observacao VARCHAR(500) NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (lancamento_caixa_id) REFERENCES lancamentos_caixa(id) ON DELETE CASCADE,
    FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id),
    
    INDEX idx_lancamento (lancamento_caixa_id),
    INDEX idx_funcionario (funcionario_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Sobras de caixa por funcionário (Receitas)';

-- Tabela para Perdas de Caixa (Comprovações)
CREATE TABLE IF NOT EXISTS lancamentos_caixa_perdas_funcionarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lancamento_caixa_id INT NOT NULL,
    funcionario_id INT NOT NULL,
    valor DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    observacao VARCHAR(500) NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (lancamento_caixa_id) REFERENCES lancamentos_caixa(id) ON DELETE CASCADE,
    FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id),
    
    INDEX idx_lancamento (lancamento_caixa_id),
    INDEX idx_funcionario (funcionario_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Perdas de caixa por funcionário (Comprovações)';

-- Tabela para Vales de Quebras de Caixa (Comprovações)
CREATE TABLE IF NOT EXISTS lancamentos_caixa_vales_funcionarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lancamento_caixa_id INT NOT NULL,
    funcionario_id INT NOT NULL,
    valor DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    observacao VARCHAR(500) NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (lancamento_caixa_id) REFERENCES lancamentos_caixa(id) ON DELETE CASCADE,
    FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id),
    
    INDEX idx_lancamento (lancamento_caixa_id),
    INDEX idx_funcionario (funcionario_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Vales de quebras de caixa por funcionário (Comprovações)';

-- ================================================
-- Fim da Migration
-- ================================================
