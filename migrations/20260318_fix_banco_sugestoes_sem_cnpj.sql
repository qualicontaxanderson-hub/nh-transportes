-- ============================================================
-- Migration: 20260318_fix_banco_sugestoes_sem_cnpj.sql
-- Corrige o schema de bank_supplier_mapping para que transações
-- bancárias SEM CNPJ/CPF (ex: resgates de aplicação financeira)
-- recebam sugestão de forma de recebimento após a primeira
-- conciliação manual.
--
-- PROBLEMA
-- --------
-- Transações de crédito sem CNPJ (ex: RESG.APLIC.FIN.AVISO
-- PREV-CAPTACAO) não recebem sugestão automática porque o
-- INSERT de memorização em bank_supplier_mapping falhava
-- silenciosamente por:
--   1. fornecedor_id NOT NULL sem default (impede INSERT sem fornecedor)
--   2. descricao_chave ausente (impede lookup por descrição)
--   3. Unique key antiga (cnpj_cpf only) sem suporte a chave composta
--
-- QUANDO EXECUTAR
-- ---------------
-- Execute este script UMA VEZ diretamente no banco Railway se as
-- sugestões de formas de recebimento para transações sem CNPJ não
-- estiverem aparecendo após a conciliação manual.
-- O sistema aplica estas mudanças automaticamente na inicialização,
-- mas pode ser necessário executar manualmente se o banco estava
-- indisponível durante o primeiro deployment.
--
-- IDEMPOTENTE: pode ser reexecutado com segurança.
-- ============================================================

-- 1. Permite fornecedor_id = NULL (necessário para mapeamentos de crédito
--    que usam forma_recebimento em vez de fornecedor)
ALTER TABLE bank_supplier_mapping
    MODIFY COLUMN fornecedor_id INT NULL;

-- 2. Adiciona colunas de mapeamento de despesas e transferências (idempotente)
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS forma_recebimento_id INT NULL,
    ADD COLUMN IF NOT EXISTS titulo_id            INT NULL,
    ADD COLUMN IF NOT EXISTS categoria_id         INT NULL,
    ADD COLUMN IF NOT EXISTS subcategoria_id      INT NULL,
    ADD COLUMN IF NOT EXISTS conta_destino_id     INT NULL,
    ADD COLUMN IF NOT EXISTS tipo_debito          VARCHAR(20) NULL;

-- 3. Adiciona coluna descricao_chave para diferenciar mapeamentos por
--    descrição da transação (permite memorização mesmo sem CNPJ)
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS descricao_chave VARCHAR(100) NOT NULL DEFAULT ''
        COMMENT 'Primeiros 100 chars da descrição em MAIÚSCULAS, para mapeamentos sem CNPJ';

-- 4. Remove a constraint única antiga (somente cnpj_cpf) se ainda existir
ALTER TABLE bank_supplier_mapping
    DROP INDEX IF EXISTS uq_bsm_chave;

-- 5. Adiciona nova constraint única composta (cnpj_cpf + descricao_chave)
--    Permite múltiplas memorização por CNPJ com descrições distintas
ALTER TABLE bank_supplier_mapping
    ADD UNIQUE KEY IF NOT EXISTS uq_bsm_chave (cnpj_cpf, descricao_chave);

-- 6. Expande ENUM tipo_chave para incluir 'descricao' (transações sem CNPJ)
ALTER TABLE bank_supplier_mapping
    MODIFY COLUMN tipo_chave ENUM('cnpj','cpf','texto','descricao') NOT NULL DEFAULT 'cnpj';

-- 7. Remove trigger redundante (o código Python gerencia os mapeamentos
--    explicitamente, o trigger causava inserções com descricao_chave='' incorretas)
DROP TRIGGER IF EXISTS tr_learn_supplier_mapping;

SELECT CONCAT(
    'Migration aplicada com sucesso. '
    'Colunas atuais de bank_supplier_mapping: ',
    GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR ', ')
) AS resultado
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'bank_supplier_mapping';
