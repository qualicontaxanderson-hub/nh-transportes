-- Migration: 20260223_add_despesa_to_mapping.sql
-- Adiciona colunas de mapeamento de despesa em bank_supplier_mapping.
-- Permite que um CNPJ seja mapeado para um título/categoria de despesa
-- (para auto-conciliação e sugestão inteligente em débitos).
-- Execute no Railway antes do próximo deploy.

ALTER TABLE bank_supplier_mapping
    ADD COLUMN titulo_id    INT NULL,
    ADD COLUMN categoria_id INT NULL,
    ADD COLUMN subcategoria_id INT NULL;
