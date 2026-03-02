-- Migration: 20260302_plano_contas_grupos.sql
-- Cria tabela de grupos do Plano de Contas Contábil e vincula clientes aos grupos.
-- Idempotente (usa IF NOT EXISTS / SET @).

-- 1. Tabela plano_contas_grupos
CREATE TABLE IF NOT EXISTS plano_contas_grupos (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    codigo      VARCHAR(30)  NOT NULL COMMENT 'Código contábil, ex.: 11211',
    nome        VARCHAR(120) NOT NULL COMMENT 'Descrição, ex.: Conta Sicoob',
    descricao   TEXT         NULL,
    ativo       TINYINT(1)   NOT NULL DEFAULT 1,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pcg_codigo (codigo)
) COMMENT='Grupos do Plano de Contas Contábil';

-- 2. Coluna grupo_contabil_id em clientes (idempotente)
SET @col_existe = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'clientes'
      AND COLUMN_NAME  = 'grupo_contabil_id'
);

SET @sql = IF(@col_existe = 0,
    'ALTER TABLE clientes ADD COLUMN grupo_contabil_id INT NULL AFTER destino_id',
    'SELECT ''coluna grupo_contabil_id já existe''');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. FK clientes.grupo_contabil_id → plano_contas_grupos.id (idempotente)
SET @fk_existe = (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA  = DATABASE()
      AND TABLE_NAME    = 'clientes'
      AND CONSTRAINT_NAME = 'fk_clientes_grupo_contabil'
);

SET @sql2 = IF(@fk_existe = 0,
    'ALTER TABLE clientes ADD CONSTRAINT fk_clientes_grupo_contabil FOREIGN KEY (grupo_contabil_id) REFERENCES plano_contas_grupos(id) ON DELETE SET NULL',
    'SELECT ''FK fk_clientes_grupo_contabil já existe''');

PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

SELECT 'Migration 20260302_plano_contas_grupos aplicada com sucesso.' AS resultado;
