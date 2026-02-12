-- Migration script to add Titulos (Main Expense Categories) to expense management system
-- Created: 2026-02-12
-- Description: Creates titulos_despesas table and modifies categorias_despesas to reference it

-- Create titulos_despesas table (Main Expense Titles)
CREATE TABLE IF NOT EXISTS `titulos_despesas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(100) NOT NULL,
    `descricao` TEXT NULL,
    `ativo` BOOLEAN NOT NULL DEFAULT TRUE,
    `ordem` INT NOT NULL DEFAULT 0,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_titulos_ativo` (`ativo`),
    INDEX `idx_titulos_ordem` (`ordem`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add titulo_id to categorias_despesas
ALTER TABLE `categorias_despesas` 
ADD COLUMN `titulo_id` INT NULL AFTER `id`,
ADD COLUMN `ordem` INT NOT NULL DEFAULT 0 AFTER `nome`,
ADD FOREIGN KEY (`titulo_id`) REFERENCES `titulos_despesas`(`id`) ON DELETE RESTRICT,
ADD INDEX `idx_categorias_titulo` (`titulo_id`),
ADD INDEX `idx_categorias_ordem` (`ordem`);

-- Add ordem to subcategorias_despesas for ordering
ALTER TABLE `subcategorias_despesas`
ADD COLUMN `ordem` INT NOT NULL DEFAULT 0 AFTER `nome`,
ADD INDEX `idx_subcategorias_ordem` (`ordem`);

-- Insert initial expense titles based on requirements
INSERT INTO `titulos_despesas` (`nome`, `descricao`, `ativo`, `ordem`) VALUES
('DESPESAS OPERACIONAIS', 'Despesas operacionais da empresa', TRUE, 1),
('IMPOSTOS', 'Impostos e taxas governamentais', TRUE, 2),
('FINANCEIRO', 'Despesas financeiras e bancárias', TRUE, 3),
('DESPESAS POSTO', 'Despesas do posto de combustível', TRUE, 4),
('FUNCIONÁRIOS', 'Despesas com funcionários', TRUE, 5),
('VEICULOS EMPRESA', 'Despesas com veículos da empresa', TRUE, 6),
('CAMINHÕES', 'Despesas detalhadas por caminhão', TRUE, 7),
('INVESTIMENTOS', 'Investimentos e aplicações', TRUE, 8),
('DESPESAS PESSOAIS (MONICA)', 'Despesas pessoais', TRUE, 9);
