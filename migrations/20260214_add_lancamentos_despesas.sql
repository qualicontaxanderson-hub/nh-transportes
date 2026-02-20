-- Migration script for Lançamentos de Despesas (Expense Postings)
-- Created: 2026-02-14
-- Description: Creates table for expense postings/entries

-- Create lancamentos_despesas table (Expense Postings)
CREATE TABLE IF NOT EXISTS `lancamentos_despesas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data` DATE NOT NULL,
    `titulo_id` INT NOT NULL,
    `categoria_id` INT NOT NULL,
    `subcategoria_id` INT NULL,
    `valor` DECIMAL(10, 2) NOT NULL,
    `fornecedor` VARCHAR(255) NULL,
    `observacao` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `atualizado_em` DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`titulo_id`) REFERENCES `titulos_despesas`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`categoria_id`) REFERENCES `categorias_despesas`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`subcategoria_id`) REFERENCES `subcategorias_despesas`(`id`) ON DELETE SET NULL,
    INDEX `idx_lancamentos_despesas_data` (`data`),
    INDEX `idx_lancamentos_despesas_titulo` (`titulo_id`),
    INDEX `idx_lancamentos_despesas_categoria` (`categoria_id`),
    INDEX `idx_lancamentos_despesas_subcategoria` (`subcategoria_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
