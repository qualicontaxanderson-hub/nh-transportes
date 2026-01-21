-- Migration script for Fechamento de Caixa (Cash Closure) feature
-- Created: 2026-01-21
-- Description: Creates tables for payment methods, expense categories, and cash closure entries

-- Create formas_pagamento_caixa table (Payment Methods for Cash Closure)
CREATE TABLE IF NOT EXISTS `formas_pagamento_caixa` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(100) NOT NULL,
    `tipo` ENUM('DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO', 'PIX', 'PRAZO', 'CARTAO', 'RETIRADA_PAGAMENTO') NOT NULL,
    `ativo` BOOLEAN NOT NULL DEFAULT TRUE,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_formas_pagamento_tipo` (`tipo`),
    INDEX `idx_formas_pagamento_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create categorias_despesas table (Expense Categories)
CREATE TABLE IF NOT EXISTS `categorias_despesas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(100) NOT NULL,
    `ativo` BOOLEAN NOT NULL DEFAULT TRUE,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_categorias_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create subcategorias_despesas table (Expense Subcategories)
CREATE TABLE IF NOT EXISTS `subcategorias_despesas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `categoria_id` INT NOT NULL,
    `nome` VARCHAR(100) NOT NULL,
    `ativo` BOOLEAN NOT NULL DEFAULT TRUE,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`categoria_id`) REFERENCES `categorias_despesas`(`id`) ON DELETE RESTRICT,
    INDEX `idx_subcategorias_categoria` (`categoria_id`),
    INDEX `idx_subcategorias_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create lancamentos_caixa table (Cash Closure Entries)
CREATE TABLE IF NOT EXISTS `lancamentos_caixa` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data` DATE NOT NULL,
    `data_lancamento` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `usuario_id` INT NULL,
    `observacao` TEXT NULL,
    `total_receitas` DECIMAL(10, 2) NOT NULL DEFAULT 0,
    `total_comprovacao` DECIMAL(10, 2) NOT NULL DEFAULT 0,
    `diferenca` DECIMAL(10, 2) NOT NULL DEFAULT 0,
    `status` ENUM('ABERTO', 'FECHADO') NOT NULL DEFAULT 'ABERTO',
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `atualizado_em` DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`usuario_id`) REFERENCES `usuarios`(`id`) ON DELETE SET NULL,
    INDEX `idx_lancamentos_caixa_data` (`data`),
    INDEX `idx_lancamentos_caixa_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create lancamentos_caixa_receitas table (Left side - Revenues and Entries)
CREATE TABLE IF NOT EXISTS `lancamentos_caixa_receitas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `lancamento_caixa_id` INT NOT NULL,
    `tipo` ENUM('VENDAS_POSTO', 'LUBRIFICANTES', 'ARLA', 'TROCO_PIX', 'EMPRESTIMOS', 'OUTROS') NOT NULL,
    `descricao` VARCHAR(200) NULL,
    `valor` DECIMAL(10, 2) NOT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`lancamento_caixa_id`) REFERENCES `lancamentos_caixa`(`id`) ON DELETE CASCADE,
    INDEX `idx_lancamentos_caixa_receitas_lancamento` (`lancamento_caixa_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create lancamentos_caixa_comprovacao table (Right side - Payment Methods Proof)
CREATE TABLE IF NOT EXISTS `lancamentos_caixa_comprovacao` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `lancamento_caixa_id` INT NOT NULL,
    `forma_pagamento_id` INT NULL,
    `bandeira_cartao_id` INT NULL,
    `descricao` VARCHAR(200) NULL,
    `valor` DECIMAL(10, 2) NOT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`lancamento_caixa_id`) REFERENCES `lancamentos_caixa`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`forma_pagamento_id`) REFERENCES `formas_pagamento_caixa`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`bandeira_cartao_id`) REFERENCES `bandeiras_cartao`(`id`) ON DELETE SET NULL,
    INDEX `idx_lancamentos_caixa_comprovacao_lancamento` (`lancamento_caixa_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default payment methods
INSERT INTO `formas_pagamento_caixa` (`nome`, `tipo`, `ativo`) VALUES
('Depósito em Espécie', 'DEPOSITO_ESPECIE', TRUE),
('Depósito em Cheque à Vista', 'DEPOSITO_CHEQUE_VISTA', TRUE),
('Depósito em Cheque à Prazo', 'DEPOSITO_CHEQUE_PRAZO', TRUE),
('Recebimento via PIX', 'PIX', TRUE),
('Prazo', 'PRAZO', TRUE),
('Cartões', 'CARTAO', TRUE),
('Retiradas para Pagamento', 'RETIRADA_PAGAMENTO', TRUE);
