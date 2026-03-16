-- ============================================================
-- Migration: Vincular Fornecedores a Empresas e Conta Contábil por Empresa
-- Data: 2026-03-16
-- ============================================================

-- Tabela junction: fornecedores <-> clientes (empresas)
-- conta_contabil_id é por empresa, referenciando plano_contas_contas
CREATE TABLE IF NOT EXISTS fornecedor_empresas (
    fornecedor_id     INT NOT NULL,
    cliente_id        INT NOT NULL,
    conta_contabil_id INT NULL,
    PRIMARY KEY (fornecedor_id, cliente_id),
    CONSTRAINT fk_fe_fornecedor FOREIGN KEY (fornecedor_id)
        REFERENCES fornecedores(id) ON DELETE CASCADE,
    CONSTRAINT fk_fe_cliente FOREIGN KEY (cliente_id)
        REFERENCES clientes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
