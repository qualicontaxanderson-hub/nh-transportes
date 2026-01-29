-- Migração: Adicionar tabelas do sistema TROCO PIX
-- Data: 2026-01-29
-- Descrição: Cria tabelas para o sistema de gerenciamento de troco PIX

-- Tabela de clientes PIX (pessoas que recebem troco via PIX)
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

-- Tabela principal de transações TROCO PIX
CREATE TABLE IF NOT EXISTS troco_pix (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id INT NOT NULL COMMENT 'ID da tabela clientes (posto de gasolina)',
    data DATE NOT NULL,
    
    -- Detalhes da venda (VENDA)
    venda_abastecimento DECIMAL(10,2) DEFAULT 0.00,
    venda_arla DECIMAL(10,2) DEFAULT 0.00,
    venda_produtos DECIMAL(10,2) DEFAULT 0.00,
    venda_total DECIMAL(10,2) GENERATED ALWAYS AS (venda_abastecimento + venda_arla + venda_produtos) STORED,
    
    -- Detalhes do cheque (CHEQUE)
    cheque_tipo ENUM('A_VISTA', 'A_PRAZO') NOT NULL,
    cheque_data_vencimento DATE NULL COMMENT 'Somente para cheques A_PRAZO',
    cheque_valor DECIMAL(10,2) NOT NULL,
    
    -- Detalhes do troco (TROCO)
    troco_especie DECIMAL(10,2) DEFAULT 0.00,
    troco_pix DECIMAL(10,2) DEFAULT 0.00,
    troco_credito_vda_programada DECIMAL(10,2) DEFAULT 0.00,
    troco_total DECIMAL(10,2) GENERATED ALWAYS AS (troco_especie + troco_pix + troco_credito_vda_programada) STORED,
    
    -- Destinatário do PIX
    troco_pix_cliente_id INT NOT NULL COMMENT 'ID da tabela troco_pix_clientes',
    
    -- Frentista que processou a transação
    funcionario_id INT NOT NULL COMMENT 'ID da tabela funcionarios',
    
    -- Status e rastreamento
    status ENUM('PENDENTE', 'PROCESSADO', 'CANCELADO') DEFAULT 'PENDENTE',
    importado_lancamento_caixa BOOLEAN DEFAULT FALSE COMMENT 'Auto-importado para fechamento de caixa',
    lancamento_caixa_id INT NULL COMMENT 'Referência ao lancamentos_caixa se importado',
    
    -- Campos de auditoria
    criado_por INT NOT NULL COMMENT 'ID do usuário que criou',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    atualizado_por INT NULL COMMENT 'ID do usuário que atualizou',
    
    -- Chaves estrangeiras
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (troco_pix_cliente_id) REFERENCES troco_pix_clientes(id),
    FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id),
    FOREIGN KEY (lancamento_caixa_id) REFERENCES lancamentos_caixa(id) ON DELETE SET NULL,
    
    -- Índices
    INDEX idx_cliente (cliente_id),
    INDEX idx_data (data),
    INDEX idx_status (status),
    INDEX idx_importado (importado_lancamento_caixa),
    INDEX idx_funcionario (funcionario_id),
    INDEX idx_troco_pix_cliente (troco_pix_cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Adicionar comentários às tabelas
ALTER TABLE troco_pix_clientes COMMENT = 'Clientes que recebem troco via PIX';
ALTER TABLE troco_pix COMMENT = 'Transações de troco PIX dos frentistas do posto';
