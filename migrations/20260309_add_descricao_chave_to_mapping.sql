-- ============================================================
-- Migration: 20260309_add_descricao_chave_to_mapping.sql
-- Altera a chave de memorização de (cnpj_cpf) para
-- (cnpj_cpf, descricao_chave) para que o mesmo CNPJ possa
-- ter memorizações distintas para tipos de transação diferentes.
--
-- CONTEXTO
-- --------
-- A tabela bank_supplier_mapping armazenava UMA memorização por
-- CNPJ/CPF. Isso causava problemas quando o mesmo fornecedor
-- aparecia em transações de categorias diferentes (ex: uma mesma
-- empresa pagando por tipos diferentes de veículos/serviços).
-- A nova chave usa os primeiros 100 caracteres da descrição
-- (em maiúsculas) junto ao CNPJ, permitindo memorizar o vínculo
-- correto para cada tipo de transação.
-- ============================================================

-- 1. Adiciona coluna descricao_chave (primeiros 100 chars da descrição, maiúsculas)
ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS descricao_chave VARCHAR(100) NOT NULL DEFAULT ''
        COMMENT 'Prefixo normalizado da descrição (LEFT(UPPER(TRIM(descricao)),100)) para diferenciar entradas com mesmo CNPJ';

-- 2. Remove a constraint única antiga (somente cnpj_cpf)
ALTER TABLE bank_supplier_mapping
    DROP INDEX IF EXISTS uq_bsm_chave;

-- 3. Adiciona nova constraint única composta (cnpj_cpf + descricao_chave)
ALTER TABLE bank_supplier_mapping
    ADD UNIQUE KEY IF NOT EXISTS uq_bsm_chave (cnpj_cpf, descricao_chave);

-- 4. Remove o trigger redundante (o código Python já gerencia os mapeamentos
--    explicitamente e agora inclui descricao_chave; manter o trigger
--    causaria inserções com descricao_chave='' que nunca seriam consultadas)
DROP TRIGGER IF EXISTS tr_learn_supplier_mapping;

SELECT 'Migration 20260309_add_descricao_chave_to_mapping aplicada com sucesso.' AS resultado;
