-- Migration: 20260302_plano_contas_contas.sql
-- Cria tabela de contas dentro de cada grupo do Plano de Contas Contábil.
-- Idempotente (usa IF NOT EXISTS).

-- 1. Tabela plano_contas_contas
CREATE TABLE IF NOT EXISTS plano_contas_contas (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    grupo_id    INT          NOT NULL COMMENT 'Grupo (plano) ao qual esta conta pertence',
    codigo      VARCHAR(30)  NOT NULL COMMENT 'Código contábil dentro do grupo, ex.: 1121',
    nome        VARCHAR(120) NOT NULL COMMENT 'Nome da conta, ex.: Banco Bradesco',
    descricao   TEXT         NULL,
    ativo       TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pcc_grupo_codigo (grupo_id, codigo),
    CONSTRAINT fk_pcc_grupo FOREIGN KEY (grupo_id)
        REFERENCES plano_contas_grupos(id) ON DELETE CASCADE
) COMMENT='Contas do Plano de Contas Contábil dentro de cada Grupo';

SELECT 'Migration 20260302_plano_contas_contas aplicada com sucesso.' AS resultado;
