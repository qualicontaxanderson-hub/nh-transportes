# 🔍 Diagnóstico: Lançamento Não Aparece na Lista

## 📋 Problema Reportado

**Sintoma:** Lançamento foi criado mas não aparece na lista de fechamentos de caixa.

**URL:** https://nh-transportes.onrender.com/lancamentos_caixa/?data_inicio=2025-12-21&data_fim=2026-02-04&cliente_id=

**Filtros Aplicados:**
- Data início: 2025-12-21
- Data fim: 2026-02-04
- Cliente: Todos (vazio)

---

## 🔧 Logging Adicionado (Commit ec05d56)

Para diagnosticar o problema, foram adicionados logs detalhados que mostrarão:

### 1. Query SQL Completa
```
[DEBUG] Query completa: SELECT lc.*, u.username as usuario_nome...
```
- Mostra a query exata sendo executada
- Inclui todas as cláusulas WHERE
- Revela se o filtro de status está correto

### 2. Parâmetros da Query
```
[DEBUG] Parâmetros: ['2025-12-21', '2026-02-04']
```
- Valores sendo passados para a query
- Verifica se datas estão corretas
- Mostra se cliente_id está sendo passado

### 3. Filtros Recebidos
```
[DEBUG] Filtros recebidos: {'data_inicio': '2025-12-21', 'data_fim': '2026-02-04', 'cliente_id': ''}
```
- Confirma o que foi recebido do formulário
- Verifica parsing dos parâmetros

### 4. Resultados da Query
```
[DEBUG] Número de lançamentos encontrados: 3
[DEBUG] Lançamento 1: id=10, data=2026-01-15, status=FECHADO, observacao=Fechamento normal
[DEBUG] Lançamento 2: id=9, data=2026-01-10, status=ABERTO, observacao=Em andamento
[DEBUG] Lançamento 3: id=8, data=2026-01-05, status=ABERTO, observacao=Lançamento automático - Troco PIX #5
```
- Quantos registros a query retornou
- Detalhes dos primeiros 5 lançamentos
- Status e observação (para verificar filtro)

---

## 📊 Como Interpretar os Logs

### Cenário 1: Query Retorna 0 Lançamentos
**Possíveis Causas:**
1. ❌ Não há lançamentos no banco no período especificado
2. ❌ Filtro de status está muito restritivo
3. ❌ Lançamento não foi salvo corretamente

**Ações:**
- Verificar no banco: `SELECT * FROM lancamentos_caixa WHERE data BETWEEN '2025-12-21' AND '2026-02-04'`
- Verificar se lançamento foi realmente criado
- Checar status e observação do lançamento

### Cenário 2: Query Retorna N Lançamentos, Mas Não Aparecem na Tela
**Possíveis Causas:**
1. ❌ Problema no template HTML
2. ❌ JavaScript está filtrando os resultados
3. ❌ CSS está ocultando os elementos

**Ações:**
- Inspecionar HTML da página
- Verificar console JavaScript
- Checar se `lancamentos` está chegando no template

### Cenário 3: Query Retorna Lançamentos, Mas o Específico Não Aparece
**Possíveis Causas:**
1. ❌ Lançamento tem status='ABERTO' e observação como "Lançamento automático - Troco PIX #..."
2. ❌ Data do lançamento está fora do range
3. ❌ Cliente_id diferente (se filtrado)

**Ações:**
- Verificar status e observação do lançamento nos logs
- Confirmar data do lançamento
- Verificar se filtro de cliente está aplicado

---

## 🧪 Como Testar Após Deploy

### 1. Acesse a Lista
```
https://nh-transportes.onrender.com/lancamentos_caixa/
```

### 2. Aplique os Filtros
- Data início: 2025-12-21
- Data fim: 2026-02-04
- Cliente: (deixar vazio ou selecionar)

### 3. Verifique os Logs do Render
```bash
# No dashboard do Render
# Menu: Logs
# Filtrar por [DEBUG]
```

### 4. Analise as Informações

**Query:**
- Está montada corretamente?
- Filtro de status está presente?
- Filtros de data estão corretos?

**Parâmetros:**
- Datas estão no formato correto?
- Valores estão sendo passados?

**Resultados:**
- Quantos lançamentos foram encontrados?
- Qual o status de cada um?
- Qual a observação de cada um?

---

## 🔍 Queries de Diagnóstico Manual

### Ver Todos os Lançamentos (sem filtro)
```sql
SELECT id, data, status, observacao, total_receitas, total_comprovacao
FROM lancamentos_caixa
ORDER BY data DESC, id DESC
LIMIT 20;
```

### Ver Lançamentos no Período
```sql
SELECT id, data, status, observacao, cliente_id
FROM lancamentos_caixa
WHERE data BETWEEN '2025-12-21' AND '2026-02-04'
ORDER BY data DESC;
```

### Ver Lançamento Específico (se souber o ID)
```sql
SELECT *
FROM lancamentos_caixa
WHERE id = 123;  -- substituir pelo ID real
```

### Verificar Filtro de Status
```sql
SELECT id, data, status, observacao,
  CASE 
    WHEN status = 'FECHADO' THEN 'Deve aparecer'
    WHEN status IS NULL THEN 'Deve aparecer'
    WHEN status = 'ABERTO' AND observacao NOT LIKE 'Lançamento automático - Troco PIX%' 
      THEN 'Deve aparecer'
    ELSE 'NÃO deve aparecer (Troco PIX automático)'
  END as visibilidade
FROM lancamentos_caixa
WHERE data BETWEEN '2025-12-21' AND '2026-02-04'
ORDER BY data DESC;
```

---

## ✅ Possíveis Soluções

### Se o Lançamento Existe Mas Não Aparece

**Opção 1: Atualizar Status**
Se o lançamento tem status='ABERTO' com observação automática:
```sql
UPDATE lancamentos_caixa 
SET status = 'FECHADO', 
    observacao = 'Fechamento manual'
WHERE id = 123;  -- substituir pelo ID real
```

**Opção 2: Editar via Interface**
1. Acessar diretamente: `https://nh-transportes.onrender.com/lancamentos_caixa/editar/123`
2. Salvar (mesmo sem alterar nada)
3. Sistema atualizará status para 'FECHADO' automaticamente

**Opção 3: Ajustar Filtro**
Se muitos lançamentos legítimos estão sendo filtrados, considerar ajustar o filtro (mas provavelmente não é necessário).

---

## 📞 Próximos Passos

### Imediato (com logs)
1. ✅ Deploy do código com logs foi feito
2. ⏳ Aguardar acesso do usuário para ver logs
3. 📊 Analisar logs para identificar causa exata
4. 🔧 Aplicar correção específica baseada nos logs

### Após Identificar o Problema
- Corrigir código se necessário
- Atualizar documentação
- Remover logs de debug (ou manter em modo debug)
- Validar solução com usuário

---

## 📚 Documentos Relacionados

- `CORRECAO_FILTRO_LISTA_LANCAMENTOS.md` - Filtro inteligente de status
- `CORRECAO_STATUS_EDITAR_LANCAMENTO.md` - Atualização de status ao editar
- `SOLUCAO_LISTA_VAZIA.md` - Solução para lista vazia

---

## 📝 Status

**Commit:** ec05d56  
**Status:** ⏳ Aguardando logs do deploy  
**Próximo:** Analisar logs e aplicar correção específica

---

**Nota:** Este documento será atualizado após análise dos logs com a causa raiz e solução específica.
