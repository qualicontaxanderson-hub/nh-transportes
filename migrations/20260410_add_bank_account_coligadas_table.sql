-- Migration: 20260410_add_bank_account_coligadas_table.sql
-- Tabela de vínculos contábeis por empresa coligada para cada conta bancária.
-- Cada linha representa: para a conta bancária X, quando operar com a empresa Y,
-- use conta_debito_id ao enviar valores e conta_credito_id ao receber valores.
-- Isso substitui os campos genéricos conta_coligada_debito_id/credito_id que eram
-- globais (não distinguiam com qual empresa coligada se estava operando).

CREATE TABLE IF NOT EXISTS bank_account_coligadas (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    bank_account_id      INT NOT NULL
        COMMENT 'Conta bancária sendo configurada',
    coligada_cliente_id  INT NOT NULL
        COMMENT 'Empresa coligada (outra empresa do grupo)',
    conta_debito_id      INT NULL
        COMMENT 'Conta contábil usada como DÉBITO ao enviar valores para a coligada',
    conta_credito_id     INT NULL
        COMMENT 'Conta contábil usada como CRÉDITO ao receber valores da coligada',
    criado_em            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bac_conta_coligada (bank_account_id, coligada_cliente_id),
    CONSTRAINT fk_bac_account    FOREIGN KEY (bank_account_id)
        REFERENCES bank_accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_bac_coligada   FOREIGN KEY (coligada_cliente_id)
        REFERENCES clientes(id) ON DELETE CASCADE,
    CONSTRAINT fk_bac_debito     FOREIGN KEY (conta_debito_id)
        REFERENCES plano_contas_contas(id) ON DELETE SET NULL,
    CONSTRAINT fk_bac_credito    FOREIGN KEY (conta_credito_id)
        REFERENCES plano_contas_contas(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Configuração contábil por empresa coligada para cada conta bancária';

CREATE INDEX IF NOT EXISTS idx_bac_account   ON bank_account_coligadas(bank_account_id);
CREATE INDEX IF NOT EXISTS idx_bac_coligada  ON bank_account_coligadas(coligada_cliente_id);

SELECT 'Migration 20260410_add_bank_account_coligadas_table aplicada com sucesso.' AS resultado;
