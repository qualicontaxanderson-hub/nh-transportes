-- Migration script for Empréstimos (Loans) Management System
-- Created: 2026-01-23
-- Description: Creates table for managing employee loans with installment tracking

-- ============================================
-- Table: emprestimos
-- ============================================
CREATE TABLE IF NOT EXISTS `emprestimos` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `funcionario_id` INT NOT NULL,
    `cliente_id` INT NOT NULL,
    `data_emprestimo` DATE NOT NULL,
    `mes_inicio_desconto` CHAR(7) NOT NULL COMMENT 'Formato: MM/YYYY ex: 01/2026',
    `descricao` VARCHAR(255) NULL,
    `valor_total` DECIMAL(12,2) NOT NULL,
    `quantidade_parcelas` INT NOT NULL,
    `valor_parcela` DECIMAL(12,2) NOT NULL COMMENT 'Calculated: valor_total / quantidade_parcelas',
    `status` ENUM('ATIVO','QUITADO','CANCELADO') DEFAULT 'ATIVO',
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `atualizado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`funcionario_id`) REFERENCES `funcionarios`(`id`) ON DELETE CASCADE,
    INDEX `idx_emprestimos_funcionario` (`funcionario_id`),
    INDEX `idx_emprestimos_cliente` (`cliente_id`),
    INDEX `idx_emprestimos_status` (`status`),
    INDEX `idx_emprestimos_mes_inicio` (`mes_inicio_desconto`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- Table: emprestimos_parcelas (Optional: for detailed tracking)
-- ============================================
CREATE TABLE IF NOT EXISTS `emprestimos_parcelas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `emprestimo_id` INT NOT NULL,
    `numero_parcela` INT NOT NULL COMMENT 'Current installment number (1, 2, 3...)',
    `mes_referencia` CHAR(7) NOT NULL COMMENT 'MM/YYYY - month this installment applies to',
    `valor` DECIMAL(12,2) NOT NULL,
    `pago` TINYINT DEFAULT 0 COMMENT '0 = not paid, 1 = paid',
    `data_pagamento` DATE NULL,
    `lancamento_id` INT NULL COMMENT 'Reference to lancamentosfuncionarios_v2.id if linked',
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`emprestimo_id`) REFERENCES `emprestimos`(`id`) ON DELETE CASCADE,
    INDEX `idx_emprestimos_parcelas_emprestimo` (`emprestimo_id`),
    INDEX `idx_emprestimos_parcelas_mes` (`mes_referencia`),
    INDEX `idx_emprestimos_parcelas_pago` (`pago`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
