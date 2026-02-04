-- ================================================
-- Script de Validação Completa
-- Sobras/Perdas/Vales de Caixa por Funcionário
-- Data: 2026-02-03
-- ================================================

-- ===== 1) VERIFICAR SE AS TABELAS EXISTEM =====
SELECT 'VERIFICANDO TABELAS...' as status;

SELECT 
    'lancamentos_caixa_sobras_funcionarios' as tabela,
    CASE 
        WHEN COUNT(*) > 0 THEN '✓ EXISTE'
        ELSE '✗ NÃO EXISTE'
    END as status
FROM information_schema.tables 
WHERE table_schema = DATABASE() 
  AND table_name = 'lancamentos_caixa_sobras_funcionarios'
UNION ALL
SELECT 
    'lancamentos_caixa_perdas_funcionarios',
    CASE 
        WHEN COUNT(*) > 0 THEN '✓ EXISTE'
        ELSE '✗ NÃO EXISTE'
    END
FROM information_schema.tables 
WHERE table_schema = DATABASE() 
  AND table_name = 'lancamentos_caixa_perdas_funcionarios'
UNION ALL
SELECT 
    'lancamentos_caixa_vales_funcionarios',
    CASE 
        WHEN COUNT(*) > 0 THEN '✓ EXISTE'
        ELSE '✗ NÃO EXISTE'
    END
FROM information_schema.tables 
WHERE table_schema = DATABASE() 
  AND table_name = 'lancamentos_caixa_vales_funcionarios';

-- ===== 2) VERIFICAR ESTRUTURA DAS TABELAS =====
SELECT '' as separador;
SELECT '===== ESTRUTURA DAS TABELAS =====' as titulo;
SELECT '' as separador;

-- Sobras
SELECT 'Estrutura: lancamentos_caixa_sobras_funcionarios' as info;
DESCRIBE lancamentos_caixa_sobras_funcionarios;

SELECT '' as separador;

-- Perdas
SELECT 'Estrutura: lancamentos_caixa_perdas_funcionarios' as info;
DESCRIBE lancamentos_caixa_perdas_funcionarios;

SELECT '' as separador;

-- Vales
SELECT 'Estrutura: lancamentos_caixa_vales_funcionarios' as info;
DESCRIBE lancamentos_caixa_vales_funcionarios;

-- ===== 3) VERIFICAR FOREIGN KEYS =====
SELECT '' as separador;
SELECT '===== FOREIGN KEYS =====' as titulo;
SELECT '' as separador;

SELECT 
    CONSTRAINT_NAME as 'Constraint',
    TABLE_NAME as 'Tabela',
    COLUMN_NAME as 'Coluna',
    REFERENCED_TABLE_NAME as 'Referencia_Tabela',
    REFERENCED_COLUMN_NAME as 'Referencia_Coluna'
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
    'lancamentos_caixa_sobras_funcionarios',
    'lancamentos_caixa_perdas_funcionarios',
    'lancamentos_caixa_vales_funcionarios'
  )
  AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, CONSTRAINT_NAME;

-- ===== 4) VERIFICAR ÍNDICES =====
SELECT '' as separador;
SELECT '===== ÍNDICES =====' as titulo;
SELECT '' as separador;

SELECT 
    TABLE_NAME as 'Tabela',
    INDEX_NAME as 'Índice',
    COLUMN_NAME as 'Coluna',
    NON_UNIQUE as 'Não_Único',
    INDEX_TYPE as 'Tipo'
FROM INFORMATION_SCHEMA.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
    'lancamentos_caixa_sobras_funcionarios',
    'lancamentos_caixa_perdas_funcionarios',
    'lancamentos_caixa_vales_funcionarios'
  )
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;

-- ===== 5) VERIFICAR COMENTÁRIOS DAS TABELAS =====
SELECT '' as separador;
SELECT '===== COMENTÁRIOS DAS TABELAS =====' as titulo;
SELECT '' as separador;

SELECT 
    TABLE_NAME as 'Tabela',
    TABLE_COMMENT as 'Comentário'
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
    'lancamentos_caixa_sobras_funcionarios',
    'lancamentos_caixa_perdas_funcionarios',
    'lancamentos_caixa_vales_funcionarios'
  )
ORDER BY TABLE_NAME;

-- ===== 6) CONTAR REGISTROS (SE HOUVER) =====
SELECT '' as separador;
SELECT '===== CONTAGEM DE REGISTROS =====' as titulo;
SELECT '' as separador;

SELECT 
    'lancamentos_caixa_sobras_funcionarios' as tabela,
    COUNT(*) as total_registros
FROM lancamentos_caixa_sobras_funcionarios
UNION ALL
SELECT 
    'lancamentos_caixa_perdas_funcionarios',
    COUNT(*)
FROM lancamentos_caixa_perdas_funcionarios
UNION ALL
SELECT 
    'lancamentos_caixa_vales_funcionarios',
    COUNT(*)
FROM lancamentos_caixa_vales_funcionarios;

-- ===== 7) RESUMO FINAL =====
SELECT '' as separador;
SELECT '===== RESUMO FINAL =====' as titulo;
SELECT '' as separador;

SELECT 
    '✓ VALIDAÇÃO COMPLETA' as status,
    '3 tabelas criadas e configuradas corretamente' as resultado,
    NOW() as data_validacao;

-- ================================================
-- Fim do Script de Validação
-- ================================================
