-- Migration: 20260220_add_bank_import_tables.sql
-- Sistema de Importação e Conciliação de Extrato Bancário (OFX)

-- Tabela de contas bancárias
CREATE TABLE IF NOT EXISTS bank_accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    banco_nome VARCHAR(100) NOT NULL,
    agencia VARCHAR(20) NULL,
    conta VARCHAR(30) NULL,
    apelido VARCHAR(100) NULL,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela de transações importadas
CREATE TABLE IF NOT EXISTS bank_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    hash_dedup VARCHAR(64) NOT NULL UNIQUE,
    data_transacao DATE NOT NULL,
    tipo ENUM('DEBIT','CREDIT') NOT NULL,
    valor DECIMAL(15,2) NOT NULL,
    descricao VARCHAR(500) NULL,
    cnpj_cpf VARCHAR(18) NULL,
    memo VARCHAR(500) NULL,
    fitid VARCHAR(100) NULL,
    status ENUM('pendente','conciliado','ignorado') NOT NULL DEFAULT 'pendente',
    fornecedor_id INT NULL,
    conciliado_em DATETIME NULL,
    conciliado_por VARCHAR(100) NULL,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_bt_account FOREIGN KEY (account_id) REFERENCES bank_accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_bt_fornecedor FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id) ON DELETE SET NULL,
    INDEX idx_bt_account (account_id),
    INDEX idx_bt_data (data_transacao),
    INDEX idx_bt_status (status),
    INDEX idx_bt_cnpj (cnpj_cpf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela de mapeamento fornecedor/CNPJ (aprendizado automático)
CREATE TABLE IF NOT EXISTS bank_supplier_mapping (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fornecedor_id INT NOT NULL,
    cnpj_cpf VARCHAR(18) NOT NULL,
    tipo_chave ENUM('cnpj','cpf','texto') NOT NULL DEFAULT 'cnpj',
    total_conciliacoes INT NOT NULL DEFAULT 0,
    criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bsm_chave (cnpj_cpf),
    CONSTRAINT fk_bsm_fornecedor FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id) ON DELETE CASCADE,
    INDEX idx_bsm_cnpj (cnpj_cpf),
    INDEX idx_bsm_fornecedor (fornecedor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- View: resumo por fornecedor
CREATE OR REPLACE VIEW vw_bank_summary_by_supplier AS
SELECT
    f.id AS fornecedor_id,
    f.razao_social AS fornecedor_nome,
    COUNT(bt.id) AS total_transacoes,
    SUM(CASE WHEN bt.tipo = 'DEBIT' THEN bt.valor ELSE 0 END) AS total_debitos,
    SUM(CASE WHEN bt.tipo = 'CREDIT' THEN bt.valor ELSE 0 END) AS total_creditos,
    SUM(CASE WHEN bt.status = 'conciliado' THEN 1 ELSE 0 END) AS total_conciliados,
    SUM(CASE WHEN bt.status = 'pendente' THEN 1 ELSE 0 END) AS total_pendentes
FROM bank_transactions bt
INNER JOIN fornecedores f ON bt.fornecedor_id = f.id
GROUP BY f.id, f.razao_social;

-- View: transações pendentes de conciliação
CREATE OR REPLACE VIEW vw_bank_pending_reconciliation AS
SELECT
    bt.id,
    bt.account_id,
    ba.apelido AS conta_apelido,
    ba.banco_nome,
    bt.data_transacao,
    bt.tipo,
    bt.valor,
    bt.descricao,
    bt.cnpj_cpf,
    bt.memo,
    bt.criado_em
FROM bank_transactions bt
INNER JOIN bank_accounts ba ON bt.account_id = ba.id
WHERE bt.status = 'pendente'
ORDER BY bt.data_transacao DESC;

-- Stored Procedure: auto-conciliação por mapeamento de CNPJ
DELIMITER $$

CREATE PROCEDURE IF NOT EXISTS sp_auto_reconcile_transactions()
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE v_id INT;
    DECLARE v_cnpj VARCHAR(18);
    DECLARE v_fornecedor_id INT;

    DECLARE cur CURSOR FOR
        SELECT bt.id, bt.cnpj_cpf, bsm.fornecedor_id
        FROM bank_transactions bt
        INNER JOIN bank_supplier_mapping bsm ON bt.cnpj_cpf = bsm.cnpj_cpf
        WHERE bt.status = 'pendente' AND bt.cnpj_cpf IS NOT NULL AND bt.cnpj_cpf != '';

    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

    OPEN cur;

    read_loop: LOOP
        FETCH cur INTO v_id, v_cnpj, v_fornecedor_id;
        IF done THEN
            LEAVE read_loop;
        END IF;

        UPDATE bank_transactions
        SET status = 'conciliado',
            fornecedor_id = v_fornecedor_id,
            conciliado_em = NOW(),
            conciliado_por = 'auto'
        WHERE id = v_id;
    END LOOP;

    CLOSE cur;
END$$

DELIMITER ;

-- Trigger: aprendizado automático ao conciliar manualmente
DELIMITER $$

CREATE TRIGGER IF NOT EXISTS tr_learn_supplier_mapping
AFTER UPDATE ON bank_transactions
FOR EACH ROW
BEGIN
    IF NEW.status = 'conciliado'
        AND OLD.status != 'conciliado'
        AND NEW.fornecedor_id IS NOT NULL
        AND NEW.cnpj_cpf IS NOT NULL
        AND NEW.cnpj_cpf != ''
    THEN
        INSERT INTO bank_supplier_mapping (fornecedor_id, cnpj_cpf, tipo_chave, total_conciliacoes)
        VALUES (NEW.fornecedor_id, NEW.cnpj_cpf, 'cnpj', 1)
        ON DUPLICATE KEY UPDATE
            fornecedor_id = NEW.fornecedor_id,
            total_conciliacoes = total_conciliacoes + 1,
            atualizado_em = NOW();
    END IF;
END$$

DELIMITER ;
