# 🗄️ ALTERAÇÕES NO BANCO DE DADOS - Sistema TROCO PIX

## 📋 RESUMO

Este documento detalha **exatamente** o que precisa ser alterado no banco de dados MySQL para o sistema TROCO PIX funcionar com os tipos AUTO e MANUAL.

---

## ⚠️ IMPORTANTE: O QUE SERÁ ALTERADO

A migration vai modificar a tabela `tipos_receita_caixa` que já existe no seu banco de dados.

### Estado ATUAL da tabela:
```sql
SELECT * FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

**Resultado atual (antes da migration):**
```
+----+------------+--------+-------+
| id | nome       | tipo   | ativo |
+----+------------+--------+-------+
| 24 | TROCO PIX  | MANUAL |     1 |
+----+------------+--------+-------+
```

### Estado DEPOIS da migration:
```
+----+---------------------+--------+-------+
| id | nome                | tipo   | ativo |
+----+---------------------+--------+-------+
| 24 | TROCO PIX (MANUAL)  | MANUAL |     1 |  ← Nome alterado
| 25 | TROCO PIX (AUTO)    | AUTO   |     1 |  ← Nova linha criada
+----+---------------------+--------+-------+
```

---

## 📝 COMANDOS SQL QUE SERÃO EXECUTADOS

### Comando 1: Renomear o registro existente
```sql
UPDATE tipos_receita_caixa 
SET tipo = 'MANUAL', nome = 'TROCO PIX (MANUAL)'
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = 'MANUAL');
```

**O que faz:**
- Encontra o registro com nome = 'TROCO PIX'
- Altera o nome para 'TROCO PIX (MANUAL)'
- Garante que o tipo seja 'MANUAL'

**Impacto:**
- ✅ Não apaga nenhum dado
- ✅ Apenas renomeia o registro existente
- ✅ Mantém o ID original (provavelmente 24)
- ✅ Mantém compatibilidade com dados existentes

**Linhas afetadas:** 1 registro

---

### Comando 2: Inserir novo tipo AUTO
```sql
INSERT INTO tipos_receita_caixa (nome, tipo, ativo) 
SELECT 'TROCO PIX (AUTO)', 'AUTO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM tipos_receita_caixa 
    WHERE nome = 'TROCO PIX (AUTO)' AND tipo = 'AUTO'
);
```

**O que faz:**
- Insere um NOVO registro com nome = 'TROCO PIX (AUTO)'
- Define tipo = 'AUTO' (preenchimento automático)
- Define ativo = 1 (habilitado)
- Só insere se ainda não existir (proteção contra duplicação)

**Impacto:**
- ✅ Cria um novo registro na tabela
- ✅ Não afeta registros existentes
- ✅ Idempotente (pode executar múltiplas vezes sem problemas)

**Linhas afetadas:** 1 novo registro

---

## 🔍 COMO VERIFICAR SE ESTÁ CORRETO

### ANTES de executar a migration:
```sql
-- Ver estado atual
SELECT id, nome, tipo, ativo 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;

-- Contar registros
SELECT COUNT(*) as total 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%';
```

**Resultado esperado ANTES:**
```
total: 1
```

### DEPOIS de executar a migration:
```sql
-- Ver estado depois
SELECT id, nome, tipo, ativo 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;

-- Contar registros
SELECT COUNT(*) as total 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%';
```

**Resultado esperado DEPOIS:**
```
total: 2
```

---

## 📊 DETALHES DA TABELA tipos_receita_caixa

### Estrutura da tabela:
```sql
DESC tipos_receita_caixa;
```

**Resultado:**
```
+------------+--------------+------+-----+-------------------+----------------+
| Field      | Type         | Null | Key | Default           | Extra          |
+------------+--------------+------+-----+-------------------+----------------+
| id         | int          | NO   | PRI | NULL              | auto_increment |
| nome       | varchar(100) | NO   |     | NULL              |                |
| tipo       | varchar(30)  | YES  | MUL | NULL              |                |
| ativo      | tinyint(1)   | NO   |     | 1                 |                |
| criado_em  | timestamp    | YES  |     | CURRENT_TIMESTAMP |                |
+------------+--------------+------+-----+-------------------+----------------+
```

### Campos utilizados:
- **id**: Identificador único (auto incremento)
- **nome**: Nome do tipo de receita (ex: "TROCO PIX (AUTO)")
- **tipo**: Classificação AUTO ou MANUAL
- **ativo**: Se está ativo (1) ou inativo (0)
- **criado_em**: Data/hora de criação

---

## 🚀 COMO EXECUTAR A MIGRATION

### Opção 1: Via linha de comando MySQL
```bash
# Conectar ao banco
mysql -u SEU_USUARIO -p SEU_BANCO_DE_DADOS

# Executar a migration
source /home/runner/work/nh-transportes/nh-transportes/migrations/20260203_add_troco_pix_auto.sql;

# Verificar resultado
SELECT * FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

### Opção 2: Copiar e colar os comandos
```sql
-- 1. Conectar ao banco de dados
USE seu_banco_de_dados;

-- 2. Renomear o existente
UPDATE tipos_receita_caixa 
SET tipo = 'MANUAL', nome = 'TROCO PIX (MANUAL)'
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = 'MANUAL');

-- 3. Inserir o novo tipo AUTO
INSERT INTO tipos_receita_caixa (nome, tipo, ativo) 
SELECT 'TROCO PIX (AUTO)', 'AUTO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM tipos_receita_caixa 
    WHERE nome = 'TROCO PIX (AUTO)' AND tipo = 'AUTO'
);

-- 4. Verificar resultado
SELECT * FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

### Opção 3: Via ferramenta visual (phpMyAdmin, Workbench, etc.)
1. Abrir a ferramenta
2. Selecionar o banco de dados
3. Ir na aba "SQL" ou "Query"
4. Colar os comandos acima
5. Executar
6. Verificar o resultado

---

## ⚠️ AVISOS E PRECAUÇÕES

### ✅ SEGURO - Pode executar sem medo:
- ✅ Não apaga nenhum dado
- ✅ Não remove nenhuma tabela
- ✅ Não altera estrutura de tabelas
- ✅ Apenas adiciona/modifica registros
- ✅ Idempotente (pode executar múltiplas vezes)

### ⚠️ CUIDADOS:
- ⚠️ **Fazer backup antes** (recomendado, mas não obrigatório)
- ⚠️ **Testar em ambiente de desenvolvimento primeiro** (se possível)
- ⚠️ **Verificar se a tabela tipos_receita_caixa existe**

### ❌ O QUE NÃO FAZ:
- ❌ Não altera tabela troco_pix
- ❌ Não altera tabela lancamentos_caixa
- ❌ Não apaga dados de receitas existentes
- ❌ Não afeta transações já registradas

---

## 🔄 COMO REVERTER (Se necessário)

Se por algum motivo precisar desfazer a migration:

```sql
-- 1. Remover o tipo AUTO
DELETE FROM tipos_receita_caixa 
WHERE nome = 'TROCO PIX (AUTO)';

-- 2. Restaurar nome original
UPDATE tipos_receita_caixa 
SET nome = 'TROCO PIX'
WHERE nome = 'TROCO PIX (MANUAL)';

-- 3. Verificar
SELECT * FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

**Resultado após reverter:**
```
+----+------------+--------+-------+
| id | nome       | tipo   | ativo |
+----+------------+--------+-------+
| 24 | TROCO PIX  | MANUAL |     1 |
+----+------------+--------+-------+
```

---

## 📈 IMPACTO NO SISTEMA

### O que acontece depois da migration:

#### 1. No Fechamento de Caixa (lancamentos_caixa/novo):
**Antes:**
```
Receitas e Entradas:
├─ VENDAS POSTO       [Auto]
├─ ARLA               [Auto]
├─ LUBRIFICANTES      [Auto]
├─ TROCO PIX          [Manual]  ← Um único campo
├─ EMPRESTIMOS        [Manual]
└─ OUTROS             [Manual]
```

**Depois:**
```
Receitas e Entradas:
├─ VENDAS POSTO       [Auto]
├─ ARLA               [Auto]
├─ LUBRIFICANTES      [Auto]
├─ TROCO PIX (AUTO)   [Auto]   ← Preenchido automaticamente
├─ RECEBIMENTOS       [Manual]
├─ TROCO PIX (MANUAL) [Manual] ← Usuário pode digitar
├─ EMPRESTIMOS        [Manual]
└─ OUTROS             [Manual]
```

#### 2. Dados salvos em lancamentos_caixa_receitas:

**Registro AUTO** (criado automaticamente pelo sistema):
```sql
INSERT INTO lancamentos_caixa_receitas 
(lancamento_caixa_id, tipo, descricao, valor)
VALUES (123, 'TROCO_PIX', 'AUTO - Troco PIX #45', 900.00);
```

**Registro MANUAL** (digitado pelo usuário):
```sql
INSERT INTO lancamentos_caixa_receitas 
(lancamento_caixa_id, tipo, descricao, valor)
VALUES (123, 'TROCO_PIX', 'Ajuste manual', 100.00);
```

**Ambos são salvos separadamente!**

---

## ✅ CHECKLIST DE VERIFICAÇÃO

Depois de executar a migration, verificar:

- [ ] Comando 1 (UPDATE) executou com sucesso
- [ ] Comando 2 (INSERT) executou com sucesso
- [ ] Existem 2 registros com nome contendo "TROCO PIX"
- [ ] Um registro tem tipo = 'AUTO'
- [ ] Um registro tem tipo = 'MANUAL'
- [ ] Ambos têm ativo = 1
- [ ] Não apareceu nenhum erro SQL
- [ ] A tela de Fechamento de Caixa carrega normalmente

---

## 🎯 RESUMO FINAL

### O que a migration FAZ:
1. ✅ Renomeia "TROCO PIX" para "TROCO PIX (MANUAL)"
2. ✅ Cria novo registro "TROCO PIX (AUTO)"
3. ✅ Define tipo correto para cada um (MANUAL/AUTO)

### O que NÃO faz:
- ❌ Não apaga dados
- ❌ Não altera estrutura de tabelas
- ❌ Não modifica transações existentes

### Total de registros afetados:
- **1 registro modificado** (UPDATE)
- **1 registro inserido** (INSERT)
- **Total: 2 operações**

### Tempo estimado de execução:
- **< 1 segundo** (comandos são muito rápidos)

---

## 📞 DÚVIDAS FREQUENTES

### P: Vou perder dados?
**R:** NÃO. A migration apenas adiciona e renomeia registros. Não apaga nada.

### P: Preciso parar o sistema?
**R:** Recomendado, mas não obrigatório. As operações são rápidas.

### P: E se já tiver executado antes?
**R:** Sem problema! A migration é idempotente (não duplica registros).

### P: Como sei que funcionou?
**R:** Execute: `SELECT * FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';`
Deve retornar 2 linhas.

### P: Posso executar em produção direto?
**R:** Sim, é seguro. Mas recomendo testar em desenvolvimento primeiro.

---

## 📄 ARQUIVO DA MIGRATION

**Localização:** `/home/runner/work/nh-transportes/nh-transportes/migrations/20260203_add_troco_pix_auto.sql`

**Conteúdo completo:**
```sql
-- ================================================
-- Migration: Add TROCO PIX AUTO type
-- Date: 2026-02-03
-- Description: Adds AUTO type for TROCO PIX to distinguish automatic entries
--              from manual entries in cash closure (Fechamento de Caixa)
-- ================================================

-- First, check if TROCO PIX already exists and update it to be MANUAL
UPDATE tipos_receita_caixa 
SET tipo = 'MANUAL', nome = 'TROCO PIX (MANUAL)'
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = 'MANUAL');

-- Insert AUTO version of TROCO PIX
INSERT INTO tipos_receita_caixa (nome, tipo, ativo) 
SELECT 'TROCO PIX (AUTO)', 'AUTO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM tipos_receita_caixa 
    WHERE nome = 'TROCO PIX (AUTO)' AND tipo = 'AUTO'
);

-- ================================================
-- End of Migration
-- ================================================
```

---

**Data do Documento:** 03/02/2026  
**Status:** ✅ Pronto para executar  
**Risco:** 🟢 Baixo (apenas adiciona/modifica registros)

---

**FIM DO DOCUMENTO**
