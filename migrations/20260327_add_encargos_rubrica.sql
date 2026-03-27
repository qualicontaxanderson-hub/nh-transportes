-- Migration: 20260327_add_encargos_rubrica
-- Description: Adds 'Encargos' rubrica between Comissão and EMPRÉSTIMOS.
--   New column order: ... Comissão (10), Encargos (11), EMPRÉSTIMOS (12)
--   EMPRÉSTIMOS is bumped from 9→12 to stay last (subtracts from Total).
--   Comissão is pinned at 10 to stay before Encargos.

-- Pin Comissão at ordem=10 (in case DB differs from seed)
UPDATE rubricas SET ordem = 10 WHERE nome IN ('Comissão', 'Comissão / Aj. Custo') AND ativo = 1;

-- Move EMPRÉSTIMOS to ordem=12 so it appears after Encargos
UPDATE rubricas SET ordem = 12 WHERE nome = 'EMPRÉSTIMOS' AND ativo = 1;

-- Insert Encargos (idempotent)
INSERT INTO rubricas (nome, descricao, tipo, percentualouvalorfixo, ordem, ativo)
VALUES ('Encargos', 'Encargos trabalhistas', 'OUTRO', 'VALOR_FIXO', 11, 1)
ON DUPLICATE KEY UPDATE ordem = 11, ativo = 1;
