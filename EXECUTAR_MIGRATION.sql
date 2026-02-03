-- ============================================================================
-- MIGRATION: TROCO PIX - Separar AUTO e MANUAL
-- Data: 03/02/2026
-- Descrição: Cria tipos AUTO e MANUAL para TROCO PIX no Fechamento de Caixa
-- ============================================================================

-- ANTES DE EXECUTAR, verificar estado atual:
-- SELECT * FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';

-- ============================================================================
-- COMANDO 1: Renomear registro existente para MANUAL
-- ============================================================================
-- O que faz: Renomeia "TROCO PIX" para "TROCO PIX (MANUAL)"
-- Impacto: Modifica 1 registro existente
-- Segurança: NÃO apaga nenhum dado

UPDATE tipos_receita_caixa 
SET tipo = 'MANUAL', 
    nome = 'TROCO PIX (MANUAL)'
WHERE nome = 'TROCO PIX' 
  AND (tipo IS NULL OR tipo = 'MANUAL');

-- Verificar resultado do UPDATE:
-- SELECT ROW_COUNT() as linhas_modificadas;
-- Esperado: 1 linha modificada

-- ============================================================================
-- COMANDO 2: Criar novo registro AUTO
-- ============================================================================
-- O que faz: Insere novo tipo "TROCO PIX (AUTO)" 
-- Impacto: Adiciona 1 novo registro
-- Segurança: Só insere se ainda não existir (idempotente)

INSERT INTO tipos_receita_caixa (nome, tipo, ativo) 
SELECT 'TROCO PIX (AUTO)', 'AUTO', 1
WHERE NOT EXISTS (
    SELECT 1 
    FROM tipos_receita_caixa 
    WHERE nome = 'TROCO PIX (AUTO)' 
      AND tipo = 'AUTO'
);

-- Verificar resultado do INSERT:
-- SELECT ROW_COUNT() as linhas_inseridas;
-- Esperado: 1 linha inserida

-- ============================================================================
-- VERIFICAÇÃO FINAL - Execute este comando para confirmar que funcionou
-- ============================================================================

SELECT 
    id,
    nome,
    tipo,
    ativo,
    criado_em
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;

-- RESULTADO ESPERADO:
-- +----+---------------------+--------+-------+---------------------+
-- | id | nome                | tipo   | ativo | criado_em           |
-- +----+---------------------+--------+-------+---------------------+
-- | 24 | TROCO PIX (MANUAL)  | MANUAL |     1 | 2026-01-26 10:00:00 |
-- | 25 | TROCO PIX (AUTO)    | AUTO   |     1 | 2026-02-03 13:30:00 |
-- +----+---------------------+--------+-------+---------------------+
-- Total: 2 linhas

-- ============================================================================
-- RESUMO DA EXECUÇÃO
-- ============================================================================
-- ✅ Comando 1 (UPDATE): Modifica 1 registro
-- ✅ Comando 2 (INSERT): Adiciona 1 registro
-- ✅ Total: 2 registros afetados
-- ✅ Nenhum dado apagado
-- ✅ Tempo de execução: < 1 segundo
-- ============================================================================

-- PARA REVERTER (se necessário):
-- DELETE FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)';
-- UPDATE tipos_receita_caixa SET nome = 'TROCO PIX' WHERE nome = 'TROCO PIX (MANUAL)';

-- FIM DA MIGRATION
