# 🔍 Verificação: Registros Duplicados em tipos_receita_caixa

## Problema Identificado

Analisando os logs do console:
```
Verificando receita: tipoNome="TROCO PIX (AUTO)", readonly=true
Verificando receita: tipoNome="TROCO PIX", readonly=false
```

Isso mostra que existem **DOIS** registros diferentes:
1. `TROCO PIX (AUTO)` - tipo AUTO (readonly=true)
2. `TROCO PIX` - sem tipo ou tipo MANUAL (readonly=false)

## Query de Verificação

Execute esta query no banco de dados para verificar:

```sql
-- Ver todos os registros de TROCO PIX em tipos_receita_caixa
SELECT 
    id,
    nome,
    tipo,
    ativo,
    ordem
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY nome;
```

## Resultados Esperados

### ✅ CORRETO (após migration completa):
```
+----+---------------------+--------+-------+-------+
| id | nome                | tipo   | ativo | ordem |
+----+---------------------+--------+-------+-------+
| XX | TROCO PIX (AUTO)    | AUTO   | 1     | NULL  |
| YY | TROCO PIX (MANUAL)  | MANUAL | 1     | NULL  |
+----+---------------------+--------+-------+-------+
```

### ❌ PROBLEMA (migration incompleta):
```
+----+---------------------+--------+-------+-------+
| id | nome                | tipo   | ativo | ordem |
+----+---------------------+--------+-------+-------+
| XX | TROCO PIX           | MANUAL | 1     | NULL  |  ← Nome não atualizado!
| YY | TROCO PIX (AUTO)    | AUTO   | 1     | NULL  |
+----+---------------------+--------+-------+-------+
```

ou

```
+----+---------------------+--------+-------+-------+
| id | nome                | tipo   | ativo | ordem |
+----+---------------------+--------+-------+-------+
| XX | TROCO PIX           | NULL   | 1     | NULL  |  ← Tipo NULL!
| YY | TROCO PIX (AUTO)    | AUTO   | 1     | NULL  |
| ZZ | TROCO PIX (MANUAL)  | MANUAL | 1     | NULL  |
+----+---------------------+--------+-------+-------+
```

## Solução

### Se há registro "TROCO PIX" sem tipo ou nome incorreto:

```sql
-- Opção 1: Atualizar o registro antigo para ter o nome correto
UPDATE tipos_receita_caixa 
SET nome = 'TROCO PIX (MANUAL)', tipo = 'MANUAL'
WHERE nome = 'TROCO PIX' AND tipo IS NULL;

-- Opção 2: Desativar o registro antigo duplicado
UPDATE tipos_receita_caixa 
SET ativo = 0
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = '');

-- Opção 3: Deletar o registro duplicado (use com cuidado!)
DELETE FROM tipos_receita_caixa 
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = '');
```

### Verificar após correção:

```sql
-- Deve retornar apenas 2 registros ativos
SELECT COUNT(*) as total
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%' AND ativo = 1;
-- Esperado: total = 2

-- Verificar os nomes
SELECT nome, tipo 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%' AND ativo = 1;
-- Esperado:
-- TROCO PIX (AUTO)    | AUTO
-- TROCO PIX (MANUAL)  | MANUAL
```

## Re-executar Migration

Se a migration não foi executada completamente, execute:

```bash
mysql -u root -p railway < migrations/20260203_add_troco_pix_auto.sql
```

## Após Correção

1. Recarregue a página do formulário (F5)
2. Verifique no console se ainda aparece "TROCO PIX" (sem AUTO ou MANUAL)
3. Deve aparecer apenas:
   - `TROCO PIX (AUTO)` - readonly=true
   - `TROCO PIX (MANUAL)` - readonly=false

---
**Status:** 🔍 Aguardando verificação do banco de dados
**Ação:** Execute as queries acima e envie os resultados
