-- ============================================================================
-- SCRIPT DE CORREÇÃO: Criar CHEQUES se não existirem
-- Data: 03/02/2026
-- Descrição: Garante que os tipos de CHEQUE existam em formas_pagamento_caixa
-- ============================================================================

-- USE seu_banco_de_dados; -- Descomente e ajuste o nome do banco

-- ============================================================================
-- VERIFICAR ANTES DE EXECUTAR
-- ============================================================================

SELECT '=== Verificando estado atual ===' as '';

SELECT 
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA') as tem_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO') as tem_cheque_prazo;

-- ============================================================================
-- INSERIR CHEQUE À VISTA (se não existir)
-- ============================================================================

SELECT '' as '';
SELECT '▶ Inserindo CHEQUE À VISTA (se ainda não existir)...' as '';

INSERT INTO formas_pagamento_caixa (nome, tipo, ativo)
SELECT 'Depósito em Cheque À Vista', 'DEPOSITO_CHEQUE_VISTA', 1
WHERE NOT EXISTS (
    SELECT 1 FROM formas_pagamento_caixa 
    WHERE tipo = 'DEPOSITO_CHEQUE_VISTA'
);

SELECT CONCAT('Linhas afetadas: ', ROW_COUNT()) as resultado;

-- ============================================================================
-- INSERIR CHEQUE A PRAZO (se não existir)
-- ============================================================================

SELECT '' as '';
SELECT '▶ Inserindo CHEQUE A PRAZO (se ainda não existir)...' as '';

INSERT INTO formas_pagamento_caixa (nome, tipo, ativo)
SELECT 'Depósito em Cheque A Prazo', 'DEPOSITO_CHEQUE_PRAZO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM formas_pagamento_caixa 
    WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO'
);

SELECT CONCAT('Linhas afetadas: ', ROW_COUNT()) as resultado;

-- ============================================================================
-- VERIFICAR DEPOIS DE EXECUTAR
-- ============================================================================

SELECT '' as '';
SELECT '=== Conferindo registros criados ===' as '';
SELECT '' as '';

SELECT id, nome, tipo, ativo
FROM formas_pagamento_caixa 
WHERE tipo IN ('DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
ORDER BY tipo;

-- ============================================================================
-- RESULTADO FINAL
-- ============================================================================

SELECT '' as '';
SELECT '=== RESULTADO FINAL ===' as '';

SELECT 
    CASE 
        WHEN (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) >= 1 
         AND (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) >= 1
        THEN '✅ CHEQUES CONFIGURADOS CORRETAMENTE!'
        ELSE '❌ ERRO: CHEQUES NÃO FORAM CRIADOS'
    END as status_final;

-- ============================================================================
-- OBSERVAÇÕES:
-- ============================================================================
-- 
-- Este script é IDEMPOTENTE (pode ser executado múltiplas vezes sem problemas)
-- 
-- Se os registros já existirem, nenhuma linha será inserida (ROW_COUNT = 0)
-- Se os registros não existirem, serão criados (ROW_COUNT = 1 para cada)
-- 
-- ============================================================================

-- FIM DO SCRIPT
