-- Migration: 20260223_fix_bank_supplier_mapping_nullable.sql
-- Permite fornecedor_id NULL em bank_supplier_mapping para suportar
-- mapeamentos de crédito (CNPJ → forma_recebimento, sem fornecedor).

-- 1. Remover FK existente (ON DELETE CASCADE exige NOT NULL)
ALTER TABLE bank_supplier_mapping
    DROP FOREIGN KEY IF EXISTS fk_bsm_fornecedor;

-- 2. Tornar fornecedor_id nullable
ALTER TABLE bank_supplier_mapping
    MODIFY COLUMN fornecedor_id INT NULL;

-- 3. Recriar FK com ON DELETE SET NULL (compatível com nullable)
ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT fk_bsm_fornecedor
        FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id)
        ON DELETE SET NULL;
