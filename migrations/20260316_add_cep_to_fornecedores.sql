-- Migration: add cep column to fornecedores
-- Date: 2026-03-16
-- The cep field was added to the application (forms + route) but the DB column was missing.

ALTER TABLE fornecedores
    ADD COLUMN IF NOT EXISTS cep VARCHAR(10) NULL AFTER bairro;
