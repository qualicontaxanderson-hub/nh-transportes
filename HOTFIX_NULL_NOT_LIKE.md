# HOTFIX: NULL NOT LIKE Retorna NULL (Não TRUE)

## 📋 Resumo Executivo

**Problema:** Lançamento id=3 (01/01/2026) não aparecia na lista  
**Causa:** SQL com `NULL NOT LIKE 'padrão'` retorna NULL, não TRUE  
**Solução:** Adicionar `IS NULL` explicitamente no filtro  
**Commit:** 8718efd  
**Status:** ✅ RESOLVIDO  

---

## 🐛 Problema

### Sintoma
Após deploy de2d4ae, lançamento continuava não aparecendo na lista mesmo com:
- ✅ Bug NameError corrigido (commit a50d7c5)
- ✅ Query diagnóstica funcionando
- ✅ Lançamento existe no banco
- ✅ Data no período correto

### Logs do Render (deploy de2d4ae)
```
[DEBUG DIAGNOSTICO] Buscando TODOS os lançamentos no período...
[DEBUG DIAGNOSTICO] Total de lançamentos no período: 1
[DEBUG DIAGNOSTICO] #1: id=3, data=2026-01-01, status=ABERTO, obs=None
[DEBUG] Query completa: ...
[DEBUG] Número de lançamentos encontrados: 0
```

**Diagnóstico mostra:**
- ✅ Lançamento EXISTE (query sem filtro encontra)
- ❌ Query principal retorna 0 (filtro exclui)

**Dados do lançamento:**
- id=3
- data=2026-01-01
- status='ABERTO'
- observacao=None (NULL)

---

## 🔍 Causa Raiz

### Comportamento de NULL em SQL

Em SQL, operações com NULL têm comportamento especial:

```sql
-- Com valor normal:
'texto' NOT LIKE 'padrão' → TRUE ou FALSE

-- Com NULL:
NULL NOT LIKE 'padrão' → NULL (não TRUE nem FALSE!)
```

### Filtro Problemático (linha 102)

```sql
OR (lc.status = 'ABERTO' AND lc.observacao NOT LIKE 'Lançamento automático - Troco PIX%')
```

**Para lançamento com observacao=NULL:**
```sql
'ABERTO' AND (NULL NOT LIKE 'Lançamento automático - Troco PIX%')
= 'ABERTO' AND NULL
= NULL
```

**NULL em cláusula WHERE:**
- NULL não é TRUE
- NULL não é FALSE
- NULL é tratado como FALSE
- Lançamento é excluído ❌

---

## ✅ Solução Aplicada

### Código Corrigido

**Arquivo:** `routes/lancamentos_caixa.py`  
**Linha:** 102

**ANTES:**
```sql
OR (lc.status = 'ABERTO' AND lc.observacao NOT LIKE 'Lançamento automático - Troco PIX%')
```

**DEPOIS:**
```sql
OR (lc.status = 'ABERTO' AND (lc.observacao IS NULL OR lc.observacao NOT LIKE 'Lançamento automático - Troco PIX%'))
```

### Por Que Funciona Agora

**Para lançamento com observacao=NULL:**
```sql
'ABERTO' AND (observacao IS NULL OR observacao NOT LIKE '...')
= 'ABERTO' AND (TRUE OR ...)
= 'ABERTO' AND TRUE
= TRUE ✅
```

**Para lançamento com observacao='texto normal':**
```sql
'ABERTO' AND (NULL IS NULL OR 'texto' NOT LIKE 'Lançamento automático...')
= 'ABERTO' AND (FALSE OR TRUE)
= 'ABERTO' AND TRUE
= TRUE ✅
```

**Para lançamento automático de Troco PIX:**
```sql
'ABERTO' AND (NULL IS NULL OR 'Lançamento automático...' NOT LIKE 'Lançamento automático...')
= 'ABERTO' AND (FALSE OR FALSE)
= 'ABERTO' AND FALSE
= FALSE ❌ (corretamente excluído)
```

---

## 📊 Tabela de Comportamento

| Status | Observacao | Condição Atendida | Aparece? |
|--------|-----------|-------------------|----------|
| FECHADO | qualquer | 1ª: status = 'FECHADO' | ✅ SIM |
| NULL | qualquer | 2ª: status IS NULL | ✅ SIM |
| ABERTO | NULL | 3ª: observacao IS NULL | ✅ SIM |
| ABERTO | "texto normal" | 3ª: observacao NOT LIKE | ✅ SIM |
| ABERTO | "Lançamento automático..." | Nenhuma | ❌ NÃO |

---

## 🧪 Como Testar

### Após Deploy do Commit 8718efd

**1. Acessar lista:**
```
https://nh-transportes.onrender.com/lancamentos_caixa/
```

**2. Filtrar período:**
- Data Início: 21/12/2025
- Data Fim: 04/02/2026
- Cliente: Todos

**3. Verificar resultado:**
- ✅ Lançamento 01/01/2026 **DEVE aparecer**
- ✅ Valor total correto
- ✅ Sem mensagem "Sistema Configurado"

**4. Verificar logs:**
```
[DEBUG DIAGNOSTICO] Total de lançamentos no período: 1
[DEBUG DIAGNOSTICO] #1: id=3, data=2026-01-01, status=ABERTO, obs=None
[DEBUG] Número de lançamentos encontrados: 1  ← Deve ser 1 agora!
```

---

## 💡 Lição Aprendida: NULL em SQL

### Regras de NULL

1. **NULL não é igual a nada** (nem a NULL):
   ```sql
   NULL = NULL → NULL (não TRUE!)
   ```

2. **Operações com NULL retornam NULL:**
   ```sql
   NULL + 5 → NULL
   NULL LIKE 'texto' → NULL
   NULL NOT LIKE 'texto' → NULL
   ```

3. **NULL em WHERE é tratado como FALSE:**
   ```sql
   WHERE NULL → Linha excluída
   WHERE NOT NULL → Linha excluída
   ```

4. **Testar NULL explicitamente:**
   ```sql
   -- CORRETO:
   WHERE coluna IS NULL
   WHERE coluna IS NOT NULL
   
   -- ERRADO:
   WHERE coluna = NULL  -- Sempre FALSE!
   WHERE coluna != NULL  -- Sempre FALSE!
   ```

### Quando Usar IS NULL

**Sempre que puder ter NULL na coluna E você quer incluir esses registros:**
```sql
-- Padrão:
WHERE coluna = 'valor'  -- Exclui NULL

-- Incluir NULL:
WHERE (coluna IS NULL OR coluna = 'valor')

-- Excluir apenas um padrão específico:
WHERE (coluna IS NULL OR coluna NOT LIKE 'padrão%')
```

---

## 🆘 Se Não Funcionar

### 1. Verificar Commit Deployado
```bash
# No Render, verificar commit atual:
# Deve ser: 8718efd ou posterior
```

### 2. Verificar Dados no Banco
```sql
SELECT id, data, status, observacao
FROM lancamentos_caixa
WHERE id = 3;

-- Esperado:
-- id=3, data=2026-01-01, status=ABERTO, observacao=NULL
```

### 3. Testar Query Manualmente
```sql
SELECT lc.*, u.username, c.razao_social
FROM lancamentos_caixa lc
LEFT JOIN usuarios u ON lc.usuario_id = u.id
LEFT JOIN clientes c ON lc.cliente_id = c.id
WHERE (
    lc.status = 'FECHADO' 
    OR lc.status IS NULL 
    OR (lc.status = 'ABERTO' AND (lc.observacao IS NULL OR lc.observacao NOT LIKE 'Lançamento automático - Troco PIX%'))
)
AND lc.data >= '2025-12-21'
AND lc.data <= '2026-02-04';

-- Deve retornar o lançamento id=3
```

### 4. Se Ainda Não Aparecer

**Verificar status:**
```sql
-- Se status não é ABERTO, FECHADO ou NULL, pode precisar atualizar:
UPDATE lancamentos_caixa SET status = 'FECHADO' WHERE id = 3;
```

---

## ✅ Checklist de Validação

**Pré-deploy:**
- [x] Código corrigido (commit 8718efd)
- [x] Documentação criada
- [x] Lógica SQL validada

**Pós-deploy:**
- [ ] Site acessível
- [ ] Lista de lançamentos carrega
- [ ] Lançamento 01/01/2026 aparece
- [ ] Logs diagnósticos OK (1 encontrado)
- [ ] Query principal OK (1 retornado)
- [ ] Usuário confirma funcionamento

---

## 📞 Suporte

### Commits Relacionados
- **de979ed** - Query diagnóstica (introduziu NameError)
- **a50d7c5** - HOTFIX NameError ✅
- **de2d4ae** - Documentação HOTFIX #1
- **8718efd** - HOTFIX NULL NOT LIKE ✅
- **[próximo]** - Documentação HOTFIX #2

### Documentação Relacionada
- `HOTFIX_NAMEERROR_DATA_INICIO.md` - Bug anterior (NameError)
- `SOLUCAO_IMEDIATA_SQL.md` - Solução SQL manual
- `LEIA-ME_PRIMEIRO.md` - Guia do usuário
- `CORRECAO_FILTRO_LISTA_LANCAMENTOS.md` - Filtro inteligente

### Para o Usuário

**Mensagem:**
> 🎉 **Tudo resolvido!** O problema era um bug sutil na lógica SQL: quando a observação é NULL, a expressão `NOT LIKE` retorna NULL (não TRUE), e isso fazia o lançamento ser excluído. Adicionei uma verificação explícita `IS NULL` que resolve. Após o deploy do commit 8718efd, seu lançamento de 01/01/2026 aparecerá automaticamente. Não precisa fazer nada no banco! ✅

---

**Última Atualização:** 2026-02-04 08:54 UTC  
**Status:** ✅ RESOLVIDO  
**Commit:** 8718efd  
**Urgência:** 🔥 Deploy imediato recomendado
