-- ============================================================
-- Migration: Formas de Recebimento + Regras de Conciliação
-- Data: 2026-02-22
-- ============================================================

-- 1. Tabela principal de formas de recebimento bancário
CREATE TABLE IF NOT EXISTS formas_recebimento (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    nome        VARCHAR(100)                    NOT NULL,
    eh_cartao   TINYINT(1)                      NOT NULL DEFAULT 0,
    tipo_cartao ENUM('DEBITO','CREDITO')         NULL,
    ativo       TINYINT(1)                      NOT NULL DEFAULT 1,
    UNIQUE KEY uq_formas_recebimento_nome (nome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Vincular forma de recebimento às transações bancárias (créditos)
ALTER TABLE bank_transactions
    ADD COLUMN IF NOT EXISTS forma_recebimento_id INT NULL
        REFERENCES formas_recebimento(id) ON DELETE SET NULL;

-- 3. Índice de performance
CREATE INDEX IF NOT EXISTS idx_bt_forma_recebimento
    ON bank_transactions (forma_recebimento_id);

-- 4. Regras automáticas de conciliação por padrão de descrição
CREATE TABLE IF NOT EXISTS bank_conciliacao_regras (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    padrao_descricao      VARCHAR(200)  NOT NULL COMMENT 'Texto a buscar na descrição',
    tipo_match            ENUM('exato','contem') NOT NULL DEFAULT 'contem'
                              COMMENT 'exato=match total; contem=substring',
    tipo_transacao        ENUM('CREDIT','DEBIT','AMBOS') NOT NULL DEFAULT 'AMBOS',
    forma_recebimento_id  INT  NULL REFERENCES formas_recebimento(id) ON DELETE SET NULL,
    fornecedor_id         INT  NULL REFERENCES fornecedores(id) ON DELETE SET NULL,
    ativo                 TINYINT(1) NOT NULL DEFAULT 1,
    total_aplicacoes      INT NOT NULL DEFAULT 0,
    criado_em             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_regras_ativo (ativo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Ampliar bank_supplier_mapping para suportar forma_recebimento_id (créditos)
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS forma_recebimento_id INT NULL
        REFERENCES formas_recebimento(id) ON DELETE SET NULL;

-- 6. Dados iniciais padrão
INSERT IGNORE INTO formas_recebimento (nome) VALUES
  ('Depósito em Cheque'),
  ('Depósito em Dinheiro'),
  ('Recebimento Pix'),
  ('Cartão de Débito - Elo'),
  ('Cartão de Crédito - Elo'),
  ('Cartão de Débito - Master'),
  ('Cartão de Crédito - Master'),
  ('Cartão de Débito - Visa'),
  ('Cartão de Crédito - Visa'),
  ('Cartão X7 Bank'),
  ('Cartão Baratão'),
  ('Cliente à Prazo - Tremea'),
  ('Recebimento de Aluguel - Fenix'),
  ('Recebimento de Aluguel - Restaurante');

-- 7. Regra padrão: tarifas de boleto
INSERT IGNORE INTO bank_conciliacao_regras
    (padrao_descricao, tipo_match, tipo_transacao)
VALUES
  ('TARIFA COM R LIQUIDACAO', 'contem', 'DEBIT');
