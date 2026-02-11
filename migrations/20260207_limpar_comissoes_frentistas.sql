-- Migration: Limpar comissões incorretas de frentistas
-- Data: 2026-02-07
-- Descrição: Remove comissões que foram salvas incorretamente para funcionários que não são motoristas

-- IMPORTANTE: O sistema tem duas tabelas - 'funcionarios' e 'motoristas'
-- Comissões devem existir APENAS para IDs que estão na tabela 'motoristas'
-- Se o ID está na tabela 'funcionarios', NÃO deve ter comissão

-- ===========================================
-- ETAPA 1: VERIFICAR QUANTOS REGISTROS SERÃO AFETADOS
-- ===========================================
SELECT COUNT(*) as total_a_deletar
FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid IN (SELECT id FROM funcionarios);  -- Se está em funcionarios, não deve ter comissão

-- ===========================================
-- ETAPA 2: VERIFICAR QUAIS FUNCIONÁRIOS SERÃO AFETADOS
-- ===========================================
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
AND l.funcionarioid IN (SELECT id FROM funcionarios)  -- Se está em funcionarios, não deve ter comissão
ORDER BY l.mes DESC, f.nome;

-- ===========================================
-- ETAPA 3: EXECUTAR DELETE (APENAS APÓS VERIFICAR OS DADOS ACIMA)
-- ===========================================
-- DELETAR comissões de funcionários que não são motoristas
DELETE FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid IN (SELECT id FROM funcionarios);  -- Se está em funcionarios, não deve ter comissão

-- ===========================================
-- ETAPA 4: VERIFICAR RESULTADO
-- ===========================================
-- ===========================================
-- ETAPA 4: VERIFICAR RESULTADO
-- ===========================================
SELECT COUNT(*) as total_comissoes_restantes
FROM lancamentosfuncionarios_v2 l
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'));

-- ===========================================
-- ETAPA 5: VERIFICAR FUNCIONÁRIOS COM COMISSÕES (devem ser apenas motoristas)
-- ===========================================
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

-- ===========================================
-- RESULTADO ESPERADO APÓS DELETE:
-- ===========================================
-- Etapa 4 (total_comissoes_restantes): Apenas comissões de motoristas
-- Etapa 5: Lista deve conter APENAS nomes com tipo 'Motorista'
-- Se ainda aparecer tipo 'Funcionário', executar o script novamente
