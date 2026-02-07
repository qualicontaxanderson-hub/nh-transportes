-- Migration: Add SUPERVISOR permissions and company access
-- Date: 2026-02-04
-- Description: Allows SUPERVISOR users to access multiple companies and specific sections

-- Create table for user-company relationships (many-to-many)
CREATE TABLE IF NOT EXISTS usuario_empresas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    cliente_id INT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_company (usuario_id, cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add index for performance
CREATE INDEX idx_usuario_empresas_usuario ON usuario_empresas(usuario_id);
CREATE INDEX idx_usuario_empresas_cliente ON usuario_empresas(cliente_id);

-- Create table for SUPERVISOR permissions (optional, for future granular control)
CREATE TABLE IF NOT EXISTS usuario_permissoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    secao VARCHAR(100) NOT NULL,
    pode_criar BOOLEAN DEFAULT TRUE,
    pode_editar BOOLEAN DEFAULT TRUE,
    pode_excluir BOOLEAN DEFAULT FALSE,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_section (usuario_id, secao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Default permissions for SUPERVISOR users
-- These sections will have full access by default for SUPERVISOR level:
-- CADASTRO: caixa, tipos_receita_caixa, cartoes
-- LANÇAMENTOS: quilometragem, arla, posto, fechamento_caixa, troco_pix, troco_pix_pista

-- Comment explaining the usage:
-- For SUPERVISOR users, we'll check:
-- 1. If usuario_empresas has entries, filter data by those companies
-- 2. If no entries, show all companies (for backward compatibility)
-- 3. usuario_permissoes can be used for fine-grained control (future enhancement)
