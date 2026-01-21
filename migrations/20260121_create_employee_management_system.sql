-- Migration script for Employee Management System
-- Created: 2026-01-21
-- Description: Creates comprehensive employee management system with categories, rubricas, and payroll entries

-- ============================================
-- 1. Table: categorias_funcionarios
-- ============================================
CREATE TABLE IF NOT EXISTS `categorias_funcionarios` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `cliente_id` INT NULL,
    `nome` VARCHAR(100) NOT NULL,
    `descricao` VARCHAR(255) NULL,
    `ativo` TINYINT NOT NULL DEFAULT 1,
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_categorias_funcionarios_cliente` (`cliente_id`),
    INDEX `idx_categorias_funcionarios_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default categories
INSERT INTO `categorias_funcionarios` (`nome`, `descricao`, `ativo`) VALUES
('MOTORISTA', 'Motorista de caminhão', 1),
('FRENTISTA', 'Atendente de posto', 1),
('ADMINISTRATIVO', 'Pessoal administrativo', 1),
('MECANICO', 'Mecânico de veículos', 1)
ON DUPLICATE KEY UPDATE nome=nome;

-- ============================================
-- 2. Table: rubricas
-- ============================================
CREATE TABLE IF NOT EXISTS `rubricas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(100) NOT NULL,
    `descricao` VARCHAR(255) NULL,
    `tipo` ENUM('SALARIO','BENEFICIO','DESCONTO','IMPOSTO','ADIANTAMENTO','OUTRO') NOT NULL,
    `percentual_ou_valor_fixo` ENUM('PERCENTUAL','VALOR_FIXO') DEFAULT 'VALOR_FIXO',
    `ativo` TINYINT NOT NULL DEFAULT 1,
    `ordem` INT DEFAULT 1,
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_rubricas_tipo` (`tipo`),
    INDEX `idx_rubricas_ativo` (`ativo`),
    INDEX `idx_rubricas_ordem` (`ordem`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default rubricas
INSERT INTO `rubricas` (`nome`, `descricao`, `tipo`, `percentual_ou_valor_fixo`, `ordem`) VALUES
('SALÁRIO BASE', 'Salário base mensal', 'SALARIO', 'VALOR_FIXO', 1),
('VALE ALIMENTAÇÃO', 'Vale alimentação', 'BENEFICIO', 'VALOR_FIXO', 2),
('FGTS', 'Fundo de Garantia do Tempo de Serviço', 'IMPOSTO', 'PERCENTUAL', 3),
('BENEFÍCIO SOCIAL', 'Benefício social', 'BENEFICIO', 'VALOR_FIXO', 4),
('ODONTO BENEFÍCIO', 'Plano odontológico', 'BENEFICIO', 'VALOR_FIXO', 5),
('FÉRIAS', 'Férias', 'BENEFICIO', 'VALOR_FIXO', 6),
('13º SALÁRIO', '13º salário', 'BENEFICIO', 'VALOR_FIXO', 7),
('RESCISÃO', 'Rescisão contratual', 'OUTRO', 'VALOR_FIXO', 8),
('EMPRÉSTIMOS', 'Empréstimos e adiantamentos', 'DESCONTO', 'VALOR_FIXO', 9)
ON DUPLICATE KEY UPDATE nome=nome;

-- ============================================
-- 3. Table: funcionariocategoria_rubricas
-- ============================================
CREATE TABLE IF NOT EXISTS `funcionariocategoria_rubricas` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `categoria_id` INT NOT NULL,
    `rubrica_id` INT NOT NULL,
    `valor_ou_percentual` DECIMAL(12,2) NULL,
    `descricao` VARCHAR(255) NULL,
    `ativo` TINYINT NOT NULL DEFAULT 1,
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`categoria_id`) REFERENCES `categorias_funcionarios`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`rubrica_id`) REFERENCES `rubricas`(`id`) ON DELETE CASCADE,
    INDEX `idx_funcionariocategoria_rubricas_categoria` (`categoria_id`),
    INDEX `idx_funcionariocategoria_rubricas_rubrica` (`rubrica_id`),
    INDEX `idx_funcionariocategoria_rubricas_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 4. Table: funcionarios
-- ============================================
CREATE TABLE IF NOT EXISTS `funcionarios` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(150) NOT NULL,
    `cliente_id` INT NULL,
    `categoria_id` INT NULL,
    `cpf` VARCHAR(14) NULL,
    `telefone` VARCHAR(20) NULL,
    `email` VARCHAR(100) NULL,
    `cargo` VARCHAR(100) NULL,
    `data_admissao` DATE NULL,
    `data_saida` DATE NULL,
    `salario_base` DECIMAL(12,2) NULL,
    `ativo` TINYINT NOT NULL DEFAULT 1,
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`categoria_id`) REFERENCES `categorias_funcionarios`(`id`) ON DELETE SET NULL,
    INDEX `idx_funcionarios_cliente` (`cliente_id`),
    INDEX `idx_funcionarios_categoria` (`categoria_id`),
    INDEX `idx_funcionarios_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 5. Table: funcionariomotoristaveiculos
-- ============================================
CREATE TABLE IF NOT EXISTS `funcionariomotoristaveiculos` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `funcionario_id` INT NOT NULL,
    `veiculo_id` INT NOT NULL,
    `data_inicio` DATE NOT NULL,
    `data_fim` DATE NULL,
    `principal` TINYINT DEFAULT 1,
    `ativo` TINYINT NOT NULL DEFAULT 1,
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`funcionario_id`) REFERENCES `funcionarios`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`veiculo_id`) REFERENCES `veiculos`(`id`) ON DELETE CASCADE,
    INDEX `idx_funcionariomotoristaveiculos_funcionario` (`funcionario_id`),
    INDEX `idx_funcionariomotoristaveiculos_veiculo` (`veiculo_id`),
    INDEX `idx_funcionariomotoristaveiculos_ativo` (`ativo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 6. Table: lancamentos_funcionarios_v2
-- ============================================
CREATE TABLE IF NOT EXISTS `lancamentos_funcionarios_v2` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `cliente_id` INT NOT NULL,
    `funcionario_id` INT NOT NULL,
    `mes` CHAR(7) NOT NULL COMMENT 'Formato: MMM/YYYY ex: JAN/2026',
    `rubrica_id` INT NOT NULL,
    `valor` DECIMAL(12,2) NOT NULL,
    `percentual` DECIMAL(5,2) NULL,
    `referencia` VARCHAR(100) NULL,
    `observacao` VARCHAR(255) NULL,
    `caminhao_id` INT NULL,
    `status_lancamento` ENUM('PENDENTE','PROCESSADO','PAGO','CANCELADO') DEFAULT 'PENDENTE',
    `data_vencimento` DATE NULL,
    `data_pagamento` DATE NULL,
    `criado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `atualizado_em` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`funcionario_id`) REFERENCES `funcionarios`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`rubrica_id`) REFERENCES `rubricas`(`id`) ON DELETE RESTRICT,
    FOREIGN KEY (`caminhao_id`) REFERENCES `veiculos`(`id`) ON DELETE SET NULL,
    INDEX `idx_lancamentos_funcionarios_v2_cliente` (`cliente_id`),
    INDEX `idx_lancamentos_funcionarios_v2_funcionario` (`funcionario_id`),
    INDEX `idx_lancamentos_funcionarios_v2_mes` (`mes`),
    INDEX `idx_lancamentos_funcionarios_v2_rubrica` (`rubrica_id`),
    INDEX `idx_lancamentos_funcionarios_v2_caminhao` (`caminhao_id`),
    INDEX `idx_lancamentos_funcionarios_v2_status` (`status_lancamento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 7. Add missing fields to motoristas table
-- ============================================
ALTER TABLE `motoristas` 
ADD COLUMN IF NOT EXISTS `email` VARCHAR(100) NULL AFTER `telefone`,
ADD COLUMN IF NOT EXISTS `cargo` VARCHAR(100) NULL AFTER `email`,
ADD COLUMN IF NOT EXISTS `data_admissao` DATE NULL AFTER `cargo`,
ADD COLUMN IF NOT EXISTS `data_saida` DATE NULL AFTER `data_admissao`,
ADD COLUMN IF NOT EXISTS `data_cadastro` TIMESTAMP DEFAULT CURRENT_TIMESTAMP AFTER `observacoes`;
