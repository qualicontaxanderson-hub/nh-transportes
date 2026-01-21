-- Migration script for Receitas feature
-- Created: 2026-01-21
-- Description: Creates tables for Receitas (cadastro) and Lancamentos de Receitas

-- Create receitas table
CREATE TABLE IF NOT EXISTS `receitas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(200) NOT NULL,
    `cliente_id` INT NOT NULL,
    `ativo` BOOLEAN NOT NULL DEFAULT TRUE,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    INDEX `idx_receitas_cliente` (`cliente_id`),
    INDEX `idx_receitas_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create lancamentos_receitas table
CREATE TABLE IF NOT EXISTS `lancamentos_receitas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data` DATE NOT NULL,
    `receita_id` INT NOT NULL,
    `valor` DECIMAL(10, 2) NOT NULL,
    `observacao` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`receita_id`) REFERENCES `receitas`(`id`) ON DELETE RESTRICT,
    INDEX `idx_lancamentos_data` (`data`),
    INDEX `idx_lancamentos_receita` (`receita_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
