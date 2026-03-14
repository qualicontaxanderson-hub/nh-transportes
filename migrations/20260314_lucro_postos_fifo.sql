-- Migration: Relatório Lucro Postos com cálculo FIFO
-- Created: 2026-03-14
-- Scope: fifo_abertura, fifo_competencia, fifo_snapshot_lotes, fifo_resumo_mensal

-- 1. Abertura FIFO: estoque inicial por cliente+produto (base para o 1º mês)
CREATE TABLE IF NOT EXISTS `fifo_abertura` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `cliente_id` INT NOT NULL,
    `produto_id` INT NOT NULL,
    `data_abertura` DATE NOT NULL DEFAULT '2026-01-01',
    `quantidade` DECIMAL(12,3) NOT NULL DEFAULT 0,
    `custo_unitario` DECIMAL(10,4) NOT NULL DEFAULT 0,
    `observacao` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `criado_por` INT NULL,
    `atualizado_em` DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
    `atualizado_por` INT NULL,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uk_fifo_abertura_cliente_produto` (`cliente_id`, `produto_id`),
    INDEX `idx_fifo_abertura_cliente` (`cliente_id`),
    INDEX `idx_fifo_abertura_data` (`data_abertura`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Competência mensal por cliente: controle ABERTO / FECHADO
CREATE TABLE IF NOT EXISTS `fifo_competencia` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `cliente_id` INT NOT NULL,
    `ano_mes` VARCHAR(7) NOT NULL,
    `data_inicio` DATE NOT NULL,
    `data_fim` DATE NOT NULL,
    `status` ENUM('ABERTO', 'FECHADO') NOT NULL DEFAULT 'ABERTO',
    `versao_atual` INT NOT NULL DEFAULT 1,
    `fechado_em` DATETIME NULL,
    `fechado_por` INT NULL,
    `reaberto_em` DATETIME NULL,
    `reaberto_por` INT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
    UNIQUE KEY `uk_fifo_competencia` (`cliente_id`, `ano_mes`),
    INDEX `idx_fifo_competencia_status` (`status`),
    INDEX `idx_fifo_competencia_cliente` (`cliente_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Snapshot FIFO: camadas de estoque no momento do fechamento
CREATE TABLE IF NOT EXISTS `fifo_snapshot_lotes` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `competencia_id` INT NOT NULL,
    `produto_id` INT NOT NULL,
    `versao` INT NOT NULL DEFAULT 1,
    `lote_ordem` INT NOT NULL,
    `quantidade_restante` DECIMAL(12,3) NOT NULL DEFAULT 0,
    `custo_unitario` DECIMAL(10,4) NOT NULL DEFAULT 0,
    `data_origem` DATE NULL,
    `substituido` TINYINT(1) NOT NULL DEFAULT 0,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`competencia_id`) REFERENCES `fifo_competencia`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`) ON DELETE RESTRICT,
    INDEX `idx_snapshot_competencia` (`competencia_id`),
    INDEX `idx_snapshot_produto` (`produto_id`),
    INDEX `idx_snapshot_versao` (`versao`),
    INDEX `idx_snapshot_substituido` (`substituido`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Resumo mensal: totais por produto no fechamento (para exportação rápida)
CREATE TABLE IF NOT EXISTS `fifo_resumo_mensal` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `competencia_id` INT NOT NULL,
    `produto_id` INT NOT NULL,
    `versao` INT NOT NULL DEFAULT 1,
    `qtde_entrada` DECIMAL(12,3) NOT NULL DEFAULT 0,
    `custo_entrada_total` DECIMAL(12,2) NOT NULL DEFAULT 0,
    `qtde_saida` DECIMAL(12,3) NOT NULL DEFAULT 0,
    `receita_saida_total` DECIMAL(12,2) NOT NULL DEFAULT 0,
    `cogs_fifo` DECIMAL(12,2) NOT NULL DEFAULT 0,
    `lucro_bruto` DECIMAL(12,2) NOT NULL DEFAULT 0,
    `estoque_final_qtde` DECIMAL(12,3) NOT NULL DEFAULT 0,
    `estoque_final_valor` DECIMAL(12,2) NOT NULL DEFAULT 0,
    `substituido` TINYINT(1) NOT NULL DEFAULT 0,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`competencia_id`) REFERENCES `fifo_competencia`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`) ON DELETE RESTRICT,
    INDEX `idx_resumo_competencia` (`competencia_id`),
    INDEX `idx_resumo_produto` (`produto_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
