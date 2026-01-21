-- Migration script for Lubrificantes feature
-- Created: 2026-01-21
-- Description: Creates tables for Lubrificantes (similar to ARLA)
-- This feature allows tracking of lubricant products inventory, purchases, sales and prices

-- Create lubrificantes_produtos table (cadastro de produtos de lubrificantes)
CREATE TABLE IF NOT EXISTS `lubrificantes_produtos` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(200) NOT NULL,
    `descricao` TEXT NULL,
    `unidade_medida` VARCHAR(20) DEFAULT 'L' COMMENT 'Unidade: L (litros), KG (quilos), UN (unidade)',
    `ativo` BOOLEAN NOT NULL DEFAULT TRUE,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_lubrif_produtos_ativo` (`ativo`),
    INDEX `idx_lubrif_produtos_nome` (`nome`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Cadastro de produtos de lubrificantes';

-- Create lubrificantes_saldo_inicial table (estoque inicial por cliente e produto)
CREATE TABLE IF NOT EXISTS `lubrificantes_saldo_inicial` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data` DATE NOT NULL,
    `produto_id` INT NOT NULL,
    `cliente_id` INT NOT NULL,
    `volume_inicial` DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'Volume/quantidade inicial em estoque',
    `preco_medio_compra` DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'Preço médio de compra para cálculo',
    `encerrante_inicial` DECIMAL(10, 2) NULL COMMENT 'Encerrante inicial (se aplicável)',
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`produto_id`) REFERENCES `lubrificantes_produtos`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    INDEX `idx_lubrif_saldo_data` (`data`),
    INDEX `idx_lubrif_saldo_produto` (`produto_id`),
    INDEX `idx_lubrif_saldo_cliente` (`cliente_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Saldo inicial de estoque de lubrificantes por cliente e produto';

-- Create lubrificantes_compras table (registro de compras)
CREATE TABLE IF NOT EXISTS `lubrificantes_compras` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data` DATE NOT NULL,
    `produto_id` INT NOT NULL,
    `cliente_id` INT NOT NULL,
    `quantidade` DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    `preco_compra` DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'Preço unitário de compra',
    `fornecedor` VARCHAR(200) NULL,
    `nota_fiscal` VARCHAR(50) NULL,
    `observacao` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`produto_id`) REFERENCES `lubrificantes_produtos`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    INDEX `idx_lubrif_compras_data` (`data`),
    INDEX `idx_lubrif_compras_produto` (`produto_id`),
    INDEX `idx_lubrif_compras_cliente` (`cliente_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Registro de compras de lubrificantes';

-- Create lubrificantes_precos_venda table (preços de venda por produto e período)
CREATE TABLE IF NOT EXISTS `lubrificantes_precos_venda` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data_inicio` DATE NOT NULL,
    `produto_id` INT NOT NULL,
    `cliente_id` INT NOT NULL,
    `preco_venda` DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'Preço de venda unitário',
    `data_fim` DATE NULL COMMENT 'Data fim da vigência (NULL = vigente)',
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`produto_id`) REFERENCES `lubrificantes_produtos`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    INDEX `idx_lubrif_precos_data_inicio` (`data_inicio`),
    INDEX `idx_lubrif_precos_produto` (`produto_id`),
    INDEX `idx_lubrif_precos_cliente` (`cliente_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Histórico de preços de venda de lubrificantes';

-- Create lubrificantes_lancamentos table (vendas/lançamentos diários)
CREATE TABLE IF NOT EXISTS `lubrificantes_lancamentos` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `data` DATE NOT NULL,
    `produto_id` INT NOT NULL,
    `cliente_id` INT NOT NULL,
    `quantidade_vendida` DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    `preco_venda_aplicado` DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'Preço de venda no momento da venda',
    `encerrante_final` DECIMAL(10, 2) NULL COMMENT 'Encerrante final (se aplicável)',
    `observacao` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`produto_id`) REFERENCES `lubrificantes_produtos`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    INDEX `idx_lubrif_lanc_data` (`data`),
    INDEX `idx_lubrif_lanc_produto` (`produto_id`),
    INDEX `idx_lubrif_lanc_cliente` (`cliente_id`),
    UNIQUE KEY `unique_lubrif_lanc_data_produto_cliente` (`data`, `produto_id`, `cliente_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Lançamentos diários de vendas de lubrificantes';

-- Criar produto padrão "PRODUTOS" para início
INSERT INTO `lubrificantes_produtos` (`nome`, `descricao`, `unidade_medida`, `ativo`)
VALUES ('PRODUTOS', 'Produto genérico de lubrificantes - preparado para futuro cadastro de produtos específicos', 'L', TRUE)
ON DUPLICATE KEY UPDATE nome = nome;
