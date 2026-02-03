-- ============================================================================
-- SCRIPT DE VERIFICAÇÃO COMPLETA
-- TROCO PIX (AUTO) + CHEQUES
-- ============================================================================

-- USE seu_banco_de_dados; -- Descomente e ajuste o nome do banco

-- ============================================================================
-- PARTE 1: VERIFICAR TROCO PIX (AUTO)
-- ============================================================================

SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         VERIFICAÇÃO: TROCO PIX (AUTO)                ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

-- Ver todos os tipos TROCO PIX
SELECT id, nome, tipo, ativo, criado_em
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;

SELECT '' as '';
SELECT 'Esperado: 2 linhas (MANUAL e AUTO)' as '';
SELECT '' as '';

-- ============================================================================
-- PARTE 2: VERIFICAR CHEQUES (Formas de Pagamento)
-- ============================================================================

SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         VERIFICAÇÃO: CHEQUES                          ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

-- Ver formas de pagamento de CHEQUES
SELECT id, nome, tipo, ativo
FROM formas_pagamento_caixa 
WHERE tipo IN ('DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
ORDER BY tipo;

SELECT '' as '';
SELECT 'Esperado: 2 linhas (À Vista e A Prazo)' as '';
SELECT '' as '';

-- ============================================================================
-- PARTE 3: CONTADORES
-- ============================================================================

SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         CONTADORES                                    ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

SELECT 
    (SELECT COUNT(*) FROM tipos_receita_caixa 
     WHERE nome LIKE '%TROCO PIX%') as total_troco_pix,
    (SELECT COUNT(*) FROM tipos_receita_caixa 
     WHERE nome = 'TROCO PIX (AUTO)') as total_pix_auto,
    (SELECT COUNT(*) FROM tipos_receita_caixa 
     WHERE nome = 'TROCO PIX (MANUAL)') as total_pix_manual,
    (SELECT COUNT(*) FROM formas_pagamento_caixa 
     WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) as total_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa 
     WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) as total_cheque_prazo;

SELECT '' as '';
SELECT 'Esperado: total_troco_pix=2, total_pix_auto=1, total_pix_manual=1,' as '';
SELECT '          total_cheque_vista=1, total_cheque_prazo=1' as '';
SELECT '' as '';

-- ============================================================================
-- PARTE 4: STATUS GERAL
-- ============================================================================

SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         STATUS GERAL                                  ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

SELECT 
    CASE 
        WHEN (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') = 1 
        THEN '✅ TROCO PIX (AUTO) OK'
        ELSE '❌ TROCO PIX (AUTO) FALTANDO'
    END as status_troco_pix_auto,
    CASE 
        WHEN (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (MANUAL)') = 1 
        THEN '✅ TROCO PIX (MANUAL) OK'
        ELSE '❌ TROCO PIX (MANUAL) FALTANDO'
    END as status_troco_pix_manual,
    CASE 
        WHEN (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) >= 1 
        THEN '✅ CHEQUE À VISTA OK'
        ELSE '❌ CHEQUE À VISTA FALTANDO'
    END as status_cheque_vista,
    CASE 
        WHEN (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) >= 1 
        THEN '✅ CHEQUE A PRAZO OK'
        ELSE '❌ CHEQUE A PRAZO FALTANDO'
    END as status_cheque_prazo;

SELECT '' as '';

-- ============================================================================
-- PARTE 5: DETALHES DOS REGISTROS (se existirem)
-- ============================================================================

SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         DETALHES: TROCO PIX (AUTO)                   ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

SELECT * FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)';

SELECT '' as '';
SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         DETALHES: CHEQUE À VISTA                      ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

SELECT * FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1;

SELECT '' as '';
SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         DETALHES: CHEQUE A PRAZO                      ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

SELECT * FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1;

-- ============================================================================
-- PARTE 6: TESTE DE INTEGRAÇÃO (simulando código)
-- ============================================================================

SELECT '' as '';
SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         TESTE: Busca que o código faz                ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

-- Teste 1: O que o código busca para CHEQUE À VISTA
SELECT '>>> Busca para CHEQUE À VISTA (cheque_tipo = "À Vista"):' as '';
SELECT id, nome, tipo 
FROM formas_pagamento_caixa 
WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1
LIMIT 1;

SELECT '' as '';

-- Teste 2: O que o código busca para CHEQUE A PRAZO
SELECT '>>> Busca para CHEQUE A PRAZO (cheque_tipo = "A Prazo"):' as '';
SELECT id, nome, tipo 
FROM formas_pagamento_caixa 
WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1
LIMIT 1;

SELECT '' as '';

-- ============================================================================
-- PARTE 7: RESULTADO FINAL
-- ============================================================================

SELECT '╔═══════════════════════════════════════════════════════╗' as '';
SELECT '║         RESULTADO FINAL                               ║' as '';
SELECT '╚═══════════════════════════════════════════════════════╝' as '';
SELECT '' as '';

SELECT 
    CASE 
        WHEN (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') = 1 
         AND (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (MANUAL)') = 1
         AND (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) >= 1
         AND (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) >= 1
        THEN '🎉 TUDO CONFIGURADO CORRETAMENTE!'
        ELSE '⚠️ FALTAM ALGUNS REGISTROS - Veja o status acima'
    END as resultado_final;

SELECT '' as '';
SELECT '============================================================================' as '';
SELECT 'FIM DA VERIFICAÇÃO' as '';
SELECT '============================================================================' as '';

-- ============================================================================
-- OBSERVAÇÕES:
-- ============================================================================
-- 
-- Se algum item estiver faltando (❌), execute os scripts de correção:
--
-- Para criar TROCO PIX (AUTO):
--   Execute: migrations/20260203_add_troco_pix_auto.sql
--
-- Para criar CHEQUES:
--   Execute: migrations/20260121_add_caixa_tables.sql
--   ou
--   Execute: migrations/20260125_alter_formas_pagamento_add_tipo.sql
--
-- ============================================================================
