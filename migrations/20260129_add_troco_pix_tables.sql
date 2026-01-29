-- Migration: Add TROCO PIX system tables
-- Date: 2026-01-29
-- Description: Creates tables for PIX change management system

-- Table for PIX customers (people who receive PIX change)
CREATE TABLE IF NOT EXISTS troco_pix_clientes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome_completo VARCHAR(200) NOT NULL,
    tipo_chave_pix ENUM('CPF', 'EMAIL', 'TELEFONE', 'CHAVE_ALEATORIA') NOT NULL,
    chave_pix VARCHAR(200) NOT NULL,
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_nome (nome_completo),
    INDEX idx_ativo (ativo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Main TROCO PIX transactions table
CREATE TABLE IF NOT EXISTS troco_pix (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT NOT NULL COMMENT 'ID from clientes table (gas station)',
    data DATE NOT NULL,
    
    -- Sale details (VENDA)
    venda_abastecimento DECIMAL(10,2) DEFAULT 0.00,
    venda_arla DECIMAL(10,2) DEFAULT 0.00,
    venda_produtos DECIMAL(10,2) DEFAULT 0.00,
    venda_total DECIMAL(10,2) GENERATED ALWAYS AS (venda_abastecimento + venda_arla + venda_produtos) STORED,
    
    -- Check details (CHEQUE)
    cheque_tipo ENUM('A_VISTA', 'A_PRAZO') NOT NULL,
    cheque_data_vencimento DATE NULL COMMENT 'Only for A_PRAZO checks',
    cheque_valor DECIMAL(10,2) NOT NULL,
    
    -- Change details (TROCO)
    troco_especie DECIMAL(10,2) DEFAULT 0.00,
    troco_pix DECIMAL(10,2) DEFAULT 0.00,
    troco_credito_vda_programada DECIMAL(10,2) DEFAULT 0.00,
    troco_total DECIMAL(10,2) GENERATED ALWAYS AS (troco_especie + troco_pix + troco_credito_vda_programada) STORED,
    
    -- PIX recipient
    troco_pix_cliente_id INT NOT NULL COMMENT 'ID from troco_pix_clientes table',
    
    -- Attendant who processed the transaction
    funcionario_id INT NOT NULL COMMENT 'ID from funcionarios table',
    
    -- Status and tracking
    status ENUM('PENDENTE', 'PROCESSADO', 'CANCELADO') DEFAULT 'PENDENTE',
    importado_lancamento_caixa BOOLEAN DEFAULT FALSE COMMENT 'Auto-imported to cash closure',
    lancamento_caixa_id INT NULL COMMENT 'Reference to lancamentos_caixa if imported',
    
    -- Audit fields
    criado_por INT NOT NULL COMMENT 'User ID who created',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    atualizado_por INT NULL COMMENT 'User ID who last updated',
    
    -- Foreign keys
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (troco_pix_cliente_id) REFERENCES troco_pix_clientes(id),
    FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id),
    FOREIGN KEY (lancamento_caixa_id) REFERENCES lancamentos_caixa(id) ON DELETE SET NULL,
    
    -- Indexes
    INDEX idx_cliente (cliente_id),
    INDEX idx_data (data),
    INDEX idx_status (status),
    INDEX idx_importado (importado_lancamento_caixa),
    INDEX idx_funcionario (funcionario_id),
    INDEX idx_troco_pix_cliente (troco_pix_cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add comment to tables
ALTER TABLE troco_pix_clientes COMMENT = 'Customers who receive PIX change';
ALTER TABLE troco_pix COMMENT = 'PIX change transactions from gas station attendants';
