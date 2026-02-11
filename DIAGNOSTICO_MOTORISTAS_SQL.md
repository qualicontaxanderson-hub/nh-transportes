# 🔍 DIAGNÓSTICO: Por Que Motoristas Não Aparecem

## 📊 SITUAÇÃO ATUAL

**Problema:** Apenas 7 FRENTISTAS aparecem na listagem. MOTORISTAS não aparecem.

**Código:** Está correto com exclusão mútua (`m.id IS NOT NULL AND f.id IS NULL`).

**Conclusão:** Problema provavelmente está nos DADOS do banco.

---

## 🚨 SCRIPT SQL DE DIAGNÓSTICO

Execute este script SQL no banco de dados para identificar o problema:

```sql
-- ============================================
-- DIAGNÓSTICO COMPLETO - MOTORISTAS
-- ============================================

-- 1. VERIFICAR LANÇAMENTOS DO MÊS 01/2026
-- ============================================
SELECT 
    'LANÇAMENTOS' as TIPO,
    l.id,
    l.funcionarioid,
    l.mes,
    l.valor,
    l.statuslancamento
FROM lancamentosfuncionarios_v2 l
WHERE l.mes = '01/2026'
ORDER BY l.funcionarioid;

-- Resultado Esperado: 
-- Deve haver lançamentos para 9 funcionários diferentes
-- IDs devem incluir os 2 motoristas


-- 2. VERIFICAR TABELA FUNCIONARIOS
-- ============================================
SELECT 
    'FUNCIONARIOS' as TIPO,
    f.id,
    f.nome,
    f.categoriaid
FROM funcionarios f
WHERE f.id IN (
    SELECT DISTINCT funcionarioid 
    FROM lancamentosfuncionarios_v2 
    WHERE mes = '01/2026'
)
ORDER BY f.id;

-- Resultado Esperado:
-- Deve mostrar os 7 frentistas
-- Pode ou não mostrar os 2 motoristas (depende da arquitetura)


-- 3. VERIFICAR TABELA MOTORISTAS
-- ============================================
SELECT 
    'MOTORISTAS' as TIPO,
    m.id,
    m.nome
FROM motoristas m
ORDER BY m.id;

-- Resultado Esperado:
-- Deve mostrar Marcos Antonio e Valmir
-- Anote os IDs deles


-- 4. DIAGNÓSTICO DE CLASSIFICAÇÃO (MAIS IMPORTANTE!)
-- ============================================
SELECT 
    l.funcionarioid,
    COUNT(DISTINCT l.id) as qtd_lancamentos,
    f.id as func_id,
    f.nome as func_nome,
    m.id as mot_id,
    m.nome as mot_nome,
    CASE 
        WHEN m.id IS NOT NULL AND f.id IS NULL THEN 'MOTORISTAS ✅'
        WHEN f.id IS NOT NULL AND m.id IS NULL THEN 'FRENTISTAS ✅'
        WHEN f.id IS NOT NULL AND m.id IS NOT NULL THEN 'AMBAS TABELAS ⚠️'
        ELSE 'NENHUMA TABELA ❌'
    END as status_tabelas,
    CASE 
        WHEN m.id IS NOT NULL AND f.id IS NULL THEN 'MOTORISTAS'
        WHEN f.id IS NOT NULL THEN 'FRENTISTAS'
        ELSE 'OUTROS'
    END as classificacao_atual
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
WHERE l.mes = '01/2026'
GROUP BY l.funcionarioid, f.id, f.nome, m.id, m.nome
ORDER BY l.funcionarioid;

-- ANÁLISE DO RESULTADO:
-- Se aparecer "AMBAS TABELAS ⚠️" para os motoristas:
--   → Problema identificado! Motoristas estão em funcionarios também
--   → Solução: Priorizar motoristas (remover `AND f.id IS NULL`)
--
-- Se aparecer "NENHUMA TABELA ❌" para algum ID:
--   → IDs não correspondem! Problema de relacionamento
--   → Solução: Corrigir IDs no banco ou na query
--
-- Se motoristas não aparecerem nesta lista:
--   → Não há lançamentos para motoristas!
--   → Solução: Criar lançamentos para os motoristas


-- 5. VERIFICAR CATEGORIAS
-- ============================================
SELECT 
    c.id,
    c.nome as categoria_nome
FROM categoriasfuncionarios c
ORDER BY c.id;

-- Resultado: Ver quais IDs correspondem a cada categoria


-- 6. CONTAGEM FINAL (DEVE BATER COM A TELA)
-- ============================================
SELECT 
    CASE 
        WHEN m.id IS NOT NULL AND f.id IS NULL THEN 'MOTORISTAS'
        WHEN f.id IS NOT NULL THEN 'FRENTISTAS'
        ELSE 'OUTROS'
    END as categoria,
    COUNT(DISTINCT l.funcionarioid) as total_funcionarios,
    SUM(l.valor) as valor_total
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
WHERE l.mes = '01/2026' AND l.clienteid = 1
GROUP BY categoria
ORDER BY categoria;

-- Resultado na tela atual:
-- FRENTISTAS: 7 funcionários
-- MOTORISTAS: (não aparece)
--
-- Resultado esperado:
-- FRENTISTAS: 7 funcionários
-- MOTORISTAS: 2 funcionários
```

---

## 📋 INTERPRETAÇÃO DOS RESULTADOS

### Cenário 1: Motoristas em AMBAS as Tabelas ⚠️

**Se a query 4 mostrar que motoristas têm `func_id` E `mot_id` preenchidos:**

**Problema:** Motoristas estão cadastrados nas duas tabelas.

**Causa:** A condição `m.id IS NOT NULL AND f.id IS NULL` é sempre FALSE para eles.

**Solução:** Mudar para priorizar motoristas:
```sql
CASE 
    WHEN m.id IS NOT NULL THEN 'MOTORISTAS'  -- Remove AND f.id IS NULL
    WHEN f.id IS NOT NULL THEN 'FRENTISTAS'
    ELSE 'OUTROS'
END
```

### Cenário 2: IDs Não Correspondem ❌

**Se motoristas não aparecerem na query 4:**

**Problema:** IDs em `lancamentosfuncionarios_v2.funcionarioid` não batem com `motoristas.id`.

**Possíveis Causas:**
- Lançamentos foram criados com IDs errados
- Tabela motoristas tem IDs diferentes
- Não há lançamentos para motoristas

**Solução:** Corrigir os IDs ou criar lançamentos corretos.

### Cenário 3: Sem Lançamentos de Motoristas

**Se não houver lançamentos com funcionarioid dos motoristas:**

**Problema:** Lançamentos dos motoristas não existem no banco.

**Solução:** Criar os lançamentos para os 2 motoristas.

---

## 🚀 AÇÃO IMEDIATA

### 1. EXECUTAR SCRIPT SQL (5 min)

Copiar e executar todo o script SQL acima no banco de dados.

### 2. ANALISAR RESULTADO DA QUERY 4 (2 min)

Esta é a query mais importante! Ela mostra exatamente o que está acontecendo.

### 3. APLICAR SOLUÇÃO (5 min)

Baseado no resultado, aplicar a correção apropriada.

### 4. INFORMAR RESULTADO (1 min)

Enviar o resultado da Query 4 para que possamos aplicar a solução correta.

---

## ✅ RESUMO

**Pergunta:** "Precisa de alguma coisa do Banco de Dados?"

**Resposta:** **SIM!** 

**Ação:** Execute o script SQL acima e envie o resultado da **Query 4** (Diagnóstico de Classificação).

**Com esse resultado, poderemos:**
1. Identificar o problema exato
2. Aplicar a correção específica
3. Fazer deploy da solução
4. Ver os 2 motoristas aparecerem! ✅

---

## 📞 PRÓXIMO PASSO

**EXECUTAR:** Query 4 do script acima

**ENVIAR:** Resultado completo da Query 4

**AGUARDAR:** Correção específica baseada no diagnóstico

---

**Arquivo:** DIAGNOSTICO_MOTORISTAS_SQL.md  
**Status:** Aguardando resultado do diagnóstico SQL
