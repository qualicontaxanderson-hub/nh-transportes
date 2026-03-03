-- ============================================================
-- Migration: Vincular Formas de Recebimento a Empresas e Conta Contábil por Empresa
-- Data: 2026-03-03 (revisado 2026-03-03)
-- ============================================================

-- Tabela junction: formas_recebimento <-> clientes (empresas)
-- conta_contabil_id é por empresa, não por forma de recebimento
CREATE TABLE IF NOT EXISTS formas_recebimento_empresas (
    forma_recebimento_id INT NOT NULL,
    cliente_id           INT NOT NULL,
    conta_contabil_id    INT NULL,
    PRIMARY KEY (forma_recebimento_id, cliente_id),
    CONSTRAINT fk_fre_forma FOREIGN KEY (forma_recebimento_id)
        REFERENCES formas_recebimento(id) ON DELETE CASCADE,
    CONSTRAINT fk_fre_cliente FOREIGN KEY (cliente_id)
        REFERENCES clientes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Adicionar conta_contabil_id caso a tabela já exista sem a coluna
ALTER TABLE formas_recebimento_empresas
    ADD COLUMN IF NOT EXISTS conta_contabil_id INT NULL;
