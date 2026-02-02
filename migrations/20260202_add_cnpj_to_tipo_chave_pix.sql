-- Migração: Adicionar CNPJ ao ENUM tipo_chave_pix
-- Data: 2026-02-02
-- Descrição: Adiciona opção CNPJ ao tipo de chave PIX na tabela troco_pix_clientes

-- Adicionar CNPJ ao ENUM tipo_chave_pix
ALTER TABLE troco_pix_clientes 
MODIFY COLUMN tipo_chave_pix ENUM('CPF', 'CNPJ', 'EMAIL', 'TELEFONE', 'CHAVE_ALEATORIA', 'SEM_PIX') NOT NULL;

-- Comentário explicativo
-- CNPJ: Chave PIX para pessoas jurídicas (14 dígitos)
-- SEM_PIX: Opção especial para transações sem troco PIX (venda em cheque sem troco)
