-- Migration: Limpar comissões incorretas de frentistas
-- Data: 2026-02-07
-- Descrição: Remove comissões que foram salvas incorretamente para funcionários que não são motoristas

-- ANTES DE EXECUTAR, VERIFICAR QUANTOS REGISTROS SERÃO AFETADOS:
SELECT COUNT(*) as total_a_deletar
FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid NOT IN (SELECT id FROM motoristas);

-- VERIFICAR QUAIS FUNCIONÁRIOS SERÃO AFETADOS:
SELECT 
    l.id,
    l.funcionarioid,
    f.nome as funcionario_nome,
    r.nome as rubrica_nome,
    l.valor,
    l.mes,
    c.razao_social as cliente_nome
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN rubricas r ON l.rubricaid = r.id
LEFT JOIN clientes c ON l.clienteid = c.id
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND l.funcionarioid NOT IN (SELECT id FROM motoristas)
ORDER BY l.mes DESC, f.nome;

-- EXECUTAR APENAS APÓS VERIFICAR OS DADOS ACIMA:
-- DELETAR comissões de funcionários que não são motoristas
DELETE FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid NOT IN (SELECT id FROM motoristas);

-- VERIFICAR RESULTADO:
SELECT COUNT(*) as total_comissoes_restantes
FROM lancamentosfuncionarios_v2 l
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'));

-- VERIFICAR FUNCIONÁRIOS COM COMISSÕES (devem ser apenas motoristas):
SELECT 
    f.nome as funcionario_nome,
    'Funcionário' as tipo
FROM lancamentosfuncionarios_v2 l
JOIN funcionarios f ON l.funcionarioid = f.id
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
UNION
SELECT 
    m.nome as funcionario_nome,
    'Motorista' as tipo
FROM lancamentosfuncionarios_v2 l
JOIN motoristas m ON l.funcionarioid = m.id
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
ORDER BY tipo, funcionario_nome;
