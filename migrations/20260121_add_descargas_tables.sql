-- Migration script for Descargas (Discharges) feature
-- Created: 2026-01-21
-- Description: Creates tables for Descargas (controle de descargas) and Descarga Etapas (two-stage discharges)

-- Create descargas table
CREATE TABLE IF NOT EXISTS `descargas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `frete_id` INT NOT NULL,
    `data_carregamento` DATE NOT NULL,
    `data_descarga` DATE NOT NULL,
    `volume_total` DECIMAL(10, 2) NOT NULL,
    
    -- Measurements before discharge
    `estoque_sistema_antes` DECIMAL(10, 2) NULL,
    `estoque_regua_antes` DECIMAL(10, 2) NULL,
    
    -- Measurements after discharge
    `estoque_sistema_depois` DECIMAL(10, 2) NULL,
    `estoque_regua_depois` DECIMAL(10, 2) NULL,
    
    -- Refueling during discharge
    `abastecimento_durante_descarga` DECIMAL(10, 2) NULL DEFAULT 0,
    
    -- Additional measurements
    `temperatura` DECIMAL(5, 2) NULL,
    `densidade` DECIMAL(5, 4) NULL,
    
    -- Calculated differences (auto-calculated)
    `diferenca_sistema` DECIMAL(10, 2) NULL,
    `diferenca_regua` DECIMAL(10, 2) NULL,
    
    -- Status for multi-stage discharges
    `status` VARCHAR(20) NOT NULL DEFAULT 'pendente', -- pendente, parcial, concluido
    `volume_descarregado` DECIMAL(10, 2) NOT NULL DEFAULT 0,
    
    `observacoes` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `atualizado_em` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (`frete_id`) REFERENCES `fretes`(`id`) ON DELETE RESTRICT,
    INDEX `idx_descargas_frete` (`frete_id`),
    INDEX `idx_descargas_data_descarga` (`data_descarga`),
    INDEX `idx_descargas_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create descarga_etapas table (for multi-stage discharges)
CREATE TABLE IF NOT EXISTS `descarga_etapas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `descarga_id` INT NOT NULL,
    `data_etapa` DATE NOT NULL,
    `volume_etapa` DECIMAL(10, 2) NOT NULL,
    
    -- Measurements for this stage
    `estoque_sistema_antes` DECIMAL(10, 2) NULL,
    `estoque_regua_antes` DECIMAL(10, 2) NULL,
    `estoque_sistema_depois` DECIMAL(10, 2) NULL,
    `estoque_regua_depois` DECIMAL(10, 2) NULL,
    
    -- Refueling during this stage
    `abastecimento_durante_etapa` DECIMAL(10, 2) NULL DEFAULT 0,
    
    -- Calculated differences for this stage
    `diferenca_sistema` DECIMAL(10, 2) NULL,
    `diferenca_regua` DECIMAL(10, 2) NULL,
    
    `observacoes` TEXT NULL,
    `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (`descarga_id`) REFERENCES `descargas`(`id`) ON DELETE CASCADE,
    INDEX `idx_descarga_etapas_descarga` (`descarga_id`),
    INDEX `idx_descarga_etapas_data` (`data_etapa`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
