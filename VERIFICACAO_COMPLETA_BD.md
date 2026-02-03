# ✅ VERIFICAÇÃO COMPLETA: TROCO PIX (AUTO) e CHEQUES no Banco de Dados

## 🎯 SITUAÇÃO ATUAL

Você executou a migration e criou com sucesso:
```
✅ TROCO PIX (AUTO) - ID: 10
```

Agora vamos verificar também os **CHEQUES** (formas de pagamento).

---

## 📋 PARTE 1: VERIFICAR TROCO PIX (AUTO)

### Query 1.1: Ver registro criado
```sql
SELECT * FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;
```

**Resultado esperado:**
```
+----+---------------------+--------+-------+---------------------+
| id | nome                | tipo   | ativo | criado_em           |
+----+---------------------+--------+-------+---------------------+
|  9 | TROCO PIX (MANUAL)  | MANUAL |     1 | 2026-01-26 10:00:00 |
| 10 | TROCO PIX (AUTO)    | AUTO   |     1 | 2026-02-03 13:30:00 |
+----+---------------------+--------+-------+---------------------+
```

✅ **CONFERIDO!** O registro ID 10 foi criado corretamente.

---

## 📋 PARTE 2: VERIFICAR CHEQUES (Formas de Pagamento)

Os CHEQUES ficam na tabela `formas_pagamento_caixa`, não em `tipos_receita_caixa`.

### Query 2.1: Verificar se a tabela existe
```sql
SHOW TABLES LIKE 'formas_pagamento_caixa';
```

**Resultado esperado:**
```
+-------------------------------------+
| Tables_in_[database]                |
+-------------------------------------+
| formas_pagamento_caixa              |
+-------------------------------------+
```

### Query 2.2: Ver estrutura da tabela
```sql
DESC formas_pagamento_caixa;
```

**Resultado esperado:**
```
+------------+--------------------------------------------------+------+-----+-------------------+-------+
| Field      | Type                                             | Null | Key | Default           | Extra |
+------------+--------------------------------------------------+------+-----+-------------------+-------+
| id         | int                                              | NO   | PRI | NULL              | auto_increment |
| nome       | varchar(100)                                     | NO   |     | NULL              |       |
| tipo       | enum('DEPOSITO_ESPECIE','DEPOSITO_CHEQUE_VISTA',|      |     | NULL              |       |
|            |      'DEPOSITO_CHEQUE_PRAZO','PIX','PRAZO',     |      |     |                   |       |
|            |      'CARTAO','RETIRADA_PAGAMENTO')             | YES  | MUL | NULL              |       |
| ativo      | tinyint(1)                                       | NO   |     | 1                 |       |
| criado_em  | timestamp                                        | YES  |     | CURRENT_TIMESTAMP |       |
+------------+--------------------------------------------------+------+-----+-------------------+-------+
```

### Query 2.3: Verificar CHEQUES cadastrados (PRINCIPAL)
```sql
SELECT id, nome, tipo, ativo 
FROM formas_pagamento_caixa 
WHERE tipo IN ('DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
  AND ativo = 1
ORDER BY tipo, id;
```

**Resultado esperado:**
```
+----+-----------------------------+-------------------------+-------+
| id | nome                        | tipo                    | ativo |
+----+-----------------------------+-------------------------+-------+
|  3 | Depósito em Cheque À Vista  | DEPOSITO_CHEQUE_VISTA   |     1 |
|  4 | Depósito em Cheque A Prazo  | DEPOSITO_CHEQUE_PRAZO   |     1 |
+----+-----------------------------+-------------------------+-------+
```

✅ **IMPORTANTE:** Estes 2 registros DEVEM existir para o sistema funcionar!

### Query 2.4: Verificar TODAS as formas de pagamento
```sql
SELECT id, nome, tipo, ativo 
FROM formas_pagamento_caixa 
ORDER BY 
  CASE tipo
    WHEN 'DEPOSITO_ESPECIE' THEN 1
    WHEN 'DEPOSITO_CHEQUE_VISTA' THEN 2
    WHEN 'DEPOSITO_CHEQUE_PRAZO' THEN 3
    WHEN 'PIX' THEN 4
    WHEN 'PRAZO' THEN 5
    WHEN 'CARTAO' THEN 6
    WHEN 'RETIRADA_PAGAMENTO' THEN 7
    ELSE 8
  END,
  id;
```

**Resultado esperado completo:**
```
+----+-----------------------------+-------------------------+-------+
| id | nome                        | tipo                    | ativo |
+----+-----------------------------+-------------------------+-------+
|  1 | Depósito em Espécie         | DEPOSITO_ESPECIE        |     1 |
|  3 | Depósito em Cheque À Vista  | DEPOSITO_CHEQUE_VISTA   |     1 | ← ESSENCIAL
|  4 | Depósito em Cheque A Prazo  | DEPOSITO_CHEQUE_PRAZO   |     1 | ← ESSENCIAL
|  2 | Recebimentos PIX            | PIX                     |     1 |
|  5 | Prazo                       | PRAZO                   |     1 |
|  6 | Cartão de Débito            | CARTAO                  |     1 |
|  7 | Cartão de Crédito           | CARTAO                  |     1 |
|  8 | Retiradas para Pagamento    | RETIRADA_PAGAMENTO      |     1 |
+----+-----------------------------+-------------------------+-------+
```

---

## 🔍 PARTE 3: TESTE COMPLETO DE INTEGRAÇÃO

### Query 3.1: Testar se o código encontra os CHEQUES
```sql
-- Teste CHEQUE À VISTA (usado quando cheque_tipo = 'À Vista')
SELECT id, nome, tipo 
FROM formas_pagamento_caixa 
WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' 
  AND ativo = 1
LIMIT 1;
```

**Resultado esperado:**
```
+----+-----------------------------+-------------------------+
| id | nome                        | tipo                    |
+----+-----------------------------+-------------------------+
|  3 | Depósito em Cheque À Vista  | DEPOSITO_CHEQUE_VISTA   |
+----+-----------------------------+-------------------------+
```

### Query 3.2: Testar CHEQUE A PRAZO
```sql
-- Teste CHEQUE A PRAZO (usado quando cheque_tipo = 'A Prazo')
SELECT id, nome, tipo 
FROM formas_pagamento_caixa 
WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' 
  AND ativo = 1
LIMIT 1;
```

**Resultado esperado:**
```
+----+-----------------------------+-------------------------+
| id | nome                        | tipo                    |
+----+-----------------------------+-------------------------+
|  4 | Depósito em Cheque A Prazo  | DEPOSITO_CHEQUE_PRAZO   |
+----+-----------------------------+-------------------------+
```

---

## ⚠️ SE OS CHEQUES NÃO EXISTIREM

Se as queries acima retornarem **0 linhas**, você precisa criar os registros:

### Script para criar CHEQUES (se necessário)
```sql
-- Inserir Cheque À Vista
INSERT INTO formas_pagamento_caixa (nome, tipo, ativo)
SELECT 'Depósito em Cheque À Vista', 'DEPOSITO_CHEQUE_VISTA', 1
WHERE NOT EXISTS (
    SELECT 1 FROM formas_pagamento_caixa 
    WHERE tipo = 'DEPOSITO_CHEQUE_VISTA'
);

-- Inserir Cheque A Prazo
INSERT INTO formas_pagamento_caixa (nome, tipo, ativo)
SELECT 'Depósito em Cheque A Prazo', 'DEPOSITO_CHEQUE_PRAZO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM formas_pagamento_caixa 
    WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO'
);

-- Verificar resultado
SELECT id, nome, tipo, ativo 
FROM formas_pagamento_caixa 
WHERE tipo IN ('DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO');
```

---

## 📊 PARTE 4: VERIFICAÇÃO FINAL COMPLETA

Execute este script completo para verificar tudo de uma vez:

```sql
-- ============================================================================
-- VERIFICAÇÃO COMPLETA: TROCO PIX (AUTO) + CHEQUES
-- ============================================================================

-- 1. TROCO PIX (AUTO)
SELECT '=== TROCO PIX ===' as '';
SELECT id, nome, tipo, ativo 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;

-- 2. CHEQUES
SELECT '=== CHEQUES ===' as '';
SELECT id, nome, tipo, ativo 
FROM formas_pagamento_caixa 
WHERE tipo IN ('DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
ORDER BY tipo;

-- 3. CONTAGEM
SELECT '=== CONTADORES ===' as '';
SELECT 
    (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%') as total_troco_pix,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA') as total_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO') as total_cheque_prazo;

-- 4. STATUS FINAL
SELECT '=== STATUS ===' as '';
SELECT 
    CASE 
        WHEN (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') = 1 
        THEN '✅ TROCO PIX (AUTO) OK'
        ELSE '❌ TROCO PIX (AUTO) FALTANDO'
    END as status_troco_pix,
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
```

---

## ✅ CHECKLIST DE VERIFICAÇÃO

Execute e marque cada item:

### TROCO PIX:
- [ ] Query retorna 2 linhas (MANUAL e AUTO)
- [ ] Registro com nome 'TROCO PIX (AUTO)' existe
- [ ] Tipo = 'AUTO'
- [ ] Ativo = 1

### CHEQUES:
- [ ] Tabela formas_pagamento_caixa existe
- [ ] Coluna 'tipo' existe na tabela
- [ ] Registro com tipo 'DEPOSITO_CHEQUE_VISTA' existe e ativo = 1
- [ ] Registro com tipo 'DEPOSITO_CHEQUE_PRAZO' existe e ativo = 1

### INTEGRAÇÃO:
- [ ] Query para buscar CHEQUE À VISTA retorna resultado
- [ ] Query para buscar CHEQUE A PRAZO retorna resultado
- [ ] IDs dos cheques são números válidos (não NULL)

---

## 🎯 RESULTADO ESPERADO FINAL

```
=== TROCO PIX ===
✅ 2 registros encontrados:
   - TROCO PIX (MANUAL) - ID: 9
   - TROCO PIX (AUTO) - ID: 10

=== CHEQUES ===
✅ 2 registros encontrados:
   - DEPOSITO_CHEQUE_VISTA - ID: 3
   - DEPOSITO_CHEQUE_PRAZO - ID: 4

=== STATUS ===
✅ TROCO PIX (AUTO) OK
✅ CHEQUE À VISTA OK
✅ CHEQUE A PRAZO OK

🎉 TUDO CONFIGURADO CORRETAMENTE!
```

---

## 🔧 CÓDIGO QUE USA OS CHEQUES

**Arquivo:** `/routes/troco_pix.py` (linhas 141-158)

```python
# Buscar forma de pagamento para cheque
if cheque_tipo == 'À Vista':
    forma_tipo = 'DEPOSITO_CHEQUE_VISTA'
else:  # A Prazo
    forma_tipo = 'DEPOSITO_CHEQUE_PRAZO'

cursor.execute("""
    SELECT id FROM formas_pagamento_caixa 
    WHERE tipo = %s AND ativo = 1
    LIMIT 1
""", (forma_tipo,))

forma_pagamento = cursor.fetchone()
if not forma_pagamento:
    print(f"[AVISO] Forma de pagamento {forma_tipo} não encontrada")
    return None

forma_pagamento_id = forma_pagamento['id']
```

Este código **PRECISA** encontrar os registros de CHEQUE para funcionar!

---

## 📝 RESUMO RÁPIDO

### O que você já tem:
✅ TROCO PIX (AUTO) - ID: 10 (CRIADO!)

### O que precisa verificar:
❓ DEPOSITO_CHEQUE_VISTA (deve existir na tabela formas_pagamento_caixa)
❓ DEPOSITO_CHEQUE_PRAZO (deve existir na tabela formas_pagamento_caixa)

### Como verificar RÁPIDO:
```sql
-- Execute esta query única:
SELECT 
    (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') as tem_pix_auto,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) as tem_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) as tem_cheque_prazo;
```

**Resultado esperado:**
```
+--------------+------------------+-------------------+
| tem_pix_auto | tem_cheque_vista | tem_cheque_prazo |
+--------------+------------------+-------------------+
|            1 |                1 |                1  |
+--------------+------------------+-------------------+
```

Se todos os valores forem **1**, está tudo OK! ✅

---

**Data:** 03/02/2026  
**Status:** TROCO PIX (AUTO) ✅ | CHEQUES ❓ (precisa verificar)

---

**FIM DO DOCUMENTO**
