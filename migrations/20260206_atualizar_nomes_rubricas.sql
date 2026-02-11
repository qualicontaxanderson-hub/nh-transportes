-- Migration: Atualizar nomes de rubricas
-- Data: 2026-02-06
-- Descrição: Atualizar padronização dos nomes das rubricas conforme solicitado

-- Alterar "Comissão" para "Comissão / Aj. Custo"
UPDATE rubricas 
SET nome = 'Comissão / Aj. Custo'
WHERE nome = 'Comissão';

-- Alterar "EMPRÉSTIMOS" para "Empréstimos" (ajustar capitalização)
UPDATE rubricas 
SET nome = 'Empréstimos'
WHERE nome = 'EMPRÉSTIMOS';

-- Verificar as alterações
SELECT id, nome, descricao, tipo 
FROM rubricas 
WHERE nome IN ('Comissão / Aj. Custo', 'Empréstimos')
ORDER BY nome;
