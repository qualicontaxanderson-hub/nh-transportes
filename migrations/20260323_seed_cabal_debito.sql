-- Migration: Inserir bandeira de cartão CABAL / OUTROS (DÉBITO)
-- Data: 2026-03-23
-- Descrição: Adiciona a bandeira 'CABAL / OUTROS' como cartão de débito,
--            permitindo registrá-la nos lançamentos de caixa.
-- Idempotente: o INSERT só é executado se o registro ainda não existir.

INSERT INTO bandeiras_cartao (nome, tipo, ativo)
SELECT 'CABAL / OUTROS', 'DEBITO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM bandeiras_cartao WHERE nome = 'CABAL / OUTROS' AND tipo = 'DEBITO'
);
