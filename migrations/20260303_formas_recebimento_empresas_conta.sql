-- ============================================================
-- Migration: Vincular Formas de Recebimento a Empresas e Conta Contábil
-- Data: 2026-03-03
-- ============================================================

-- 1. Adicionar coluna conta_contabil_id em formas_recebimento
ALTER TABLE formas_recebimento
    ADD COLUMN IF NOT EXISTS conta_contabil_id INT NULL;

ALTER TABLE formas_recebimento
    ADD CONSTRAINT IF NOT EXISTS fk_fr_conta_contabil
        FOREIGN KEY (conta_contabil_id)
        REFERENCES plano_contas_contas(id) ON DELETE SET NULL;

-- 2. Tabela junction: formas_recebimento <-> clientes (empresas)
CREATE TABLE IF NOT EXISTS formas_recebimento_empresas (
    forma_recebimento_id INT NOT NULL,
    cliente_id           INT NOT NULL,
    PRIMARY KEY (forma_recebimento_id, cliente_id),
    CONSTRAINT fk_fre_forma FOREIGN KEY (forma_recebimento_id)
        REFERENCES formas_recebimento(id) ON DELETE CASCADE,
    CONSTRAINT fk_fre_cliente FOREIGN KEY (cliente_id)
        REFERENCES clientes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
