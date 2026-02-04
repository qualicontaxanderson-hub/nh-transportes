# Correção: Filtro de Status FECHADO e Cartões Detalhados no WhatsApp

## 📋 Resumo das Correções

Este documento descreve duas correções importantes no sistema de Lançamentos de Caixa:

1. **Filtro de Status FECHADO na Listagem** - Lançamentos automáticos de Troco PIX não aparecem mais na lista
2. **Cartões Detalhados no WhatsApp** - Exportação mostra cada bandeira de cartão separadamente

---

## 🔧 Correção 1: Filtro de Status FECHADO

### Problema Original

Quando um Troco PIX era cadastrado em `/troco_pix/novo`, o sistema criava automaticamente um lançamento de caixa com `status='ABERTO'`. Esse lançamento aparecia na listagem `/lancamentos_caixa/`, causando confusão:

- ❌ Aparecia como "lançamento aberto" na lista
- ❌ Não era um fechamento completo de caixa
- ❌ Usuários tentavam editá-lo pensando ser um lançamento normal
- ❌ Poluía a lista com itens não finalizados

### Por que isso acontecia?

O lançamento automático é criado em `routes/troco_pix.py` linha 174:

```python
cursor.execute("""
    INSERT INTO lancamentos_caixa 
    (data, cliente_id, usuario_id, observacao, total_receitas, total_comprovacao, diferenca, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, 'ABERTO')
""", ...)
```

A listagem em `routes/lancamentos_caixa.py` buscava TODOS os lançamentos, sem filtrar por status.

### Solução Implementada

Adicionado filtro na query da listagem (linha 96):

```python
# Build filter conditions
where_conditions = []
params = []

# SEMPRE filtrar apenas lançamentos FECHADOS (não mostrar automáticos de Troco PIX)
where_conditions.append("lc.status = 'FECHADO'")

if filtros['data_inicio']:
    where_conditions.append("lc.data >= %s")
    params.append(filtros['data_inicio'])
# ... outros filtros
```

### Como Funciona Agora

1. **Criar Troco PIX** → Lançamento criado com `status='ABERTO'`
2. **Lista de Lançamentos** → Mostra APENAS `status='FECHADO'`
3. **Novo Fechamento** → API `get_vendas_dia()` busca Troco PIX (ABERTO) e inclui automaticamente
4. **Salvar Fechamento** → Atualiza status para `FECHADO`

### Diagrama do Fluxo

```
┌─────────────────────┐
│ Criar Troco PIX     │
│ /troco_pix/novo     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────┐
│ Lançamento Automático       │
│ status = 'ABERTO'           │
│ (não aparece na lista)      │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ Criar Fechamento            │
│ /lancamentos_caixa/novo     │
│ (API inclui Troco PIX AUTO) │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ Salvar Fechamento           │
│ status = 'FECHADO'          │
│ (AGORA aparece na lista)    │
└─────────────────────────────┘
```

### Benefícios

✅ **Lista limpa** - Apenas fechamentos completos  
✅ **Sem confusão** - Lançamentos AUTO ficam invisíveis até serem finalizados  
✅ **Processo transparente** - Troco PIX incluído automaticamente no fechamento  
✅ **Integridade** - Dados não são perdidos, apenas filtrados na visualização  

---

## 💳 Correção 2: Cartões Detalhados no WhatsApp

### Problema Original

Ao copiar o fechamento para WhatsApp em `/lancamentos_caixa/visualizar/3`, os cartões apareciam apenas como totais:

```
• Cartão Débito: R$ 5.547,26
• Cartão Crédito: R$ 3.316,39
```

Isso não permitia conferir os valores por bandeira (ELO, MASTERCARD, VISA, etc.).

### Solução Implementada

Modificado o template `visualizar.html` (linhas 418-433) para iterar sobre cada cartão:

**Código Anterior:**
```jinja
{% set cartoes_debito = comprovacoes|selectattr('forma_tipo', 'equalto', 'CARTAO')|selectattr('cartao_tipo', 'equalto', 'DEBITO')|list %}
{% if cartoes_debito|length > 0 %}
{% set total_debito = cartoes_debito|map(attribute='valor')|map('float')|sum %}
texto += `• Cartão Débito: R$ {{ total_debito }}\n`;
{% endif %}
```

**Código Novo:**
```jinja
{% set cartoes_debito = comprovacoes|selectattr('forma_tipo', 'equalto', 'CARTAO')|selectattr('cartao_tipo', 'equalto', 'DEBITO')|list %}
{% if cartoes_debito|length > 0 %}
{% set total_debito = cartoes_debito|map(attribute='valor')|map('float')|sum %}
texto += `• Cartão Débito:\n`;
{% for cartao in cartoes_debito %}
texto += `  - {{ cartao.cartao_nome }}: R$ {{ cartao.valor }}\n`;
{% endfor %}
texto += `  Subtotal: R$ {{ total_debito }}\n`;
{% endif %}
```

### Exemplo de Saída WhatsApp

**Antes:**
```
✅ *COMPROVAÇÃO PARA FECHAMENTO*
━━━━━━━━━━━━━━━━━━━━
• PRAZO: R$ 806,05
• RECEBIMENTO VIA PIX: R$ 2.368,36
• Depósitos em Espécie (1): R$ 2.875,00
• Cartão Débito: R$ 5.547,26
• Cartão Crédito: R$ 3.316,39
```

**Depois:**
```
✅ *COMPROVAÇÃO PARA FECHAMENTO*
━━━━━━━━━━━━━━━━━━━━
• PRAZO: R$ 806,05
• RECEBIMENTO VIA PIX: R$ 2.368,36
• Depósitos em Espécie (1): R$ 2.875,00
• Cartão Débito:
  - ELO: R$ 902,79
  - MASTERCARD: R$ 2.241,75
  - VISA: R$ 2.402,72
  Subtotal: R$ 5.547,26
• Cartão Crédito:
  - ELO: R$ 202,04
  - MASTERCARD: R$ 2.683,25
  - VISA: R$ 431,10
  Subtotal: R$ 3.316,39
```

### Benefícios

✅ **Auditoria facilitada** - Ver valores por bandeira  
✅ **Conferência precisa** - Comparar com relatórios das operadoras  
✅ **Transparência** - Todos os detalhes visíveis  
✅ **Profissionalismo** - Relatório completo via WhatsApp  

---

## 📊 Comparação Antes/Depois

| Aspecto | Antes | Depois |
|---------|-------|--------|
| **Lançamentos AUTO na lista** | ❌ Apareciam (status ABERTO) | ✅ Não aparecem (filtro por FECHADO) |
| **Clareza da lista** | ❌ Poluída com itens não finalizados | ✅ Apenas fechamentos completos |
| **Cartões no WhatsApp** | ❌ Apenas total por tipo | ✅ Detalhado por bandeira |
| **Conferência com operadoras** | ❌ Difícil | ✅ Fácil (valores por bandeira) |
| **Auditoria** | ❌ Incompleta | ✅ Completa e detalhada |

---

## 🧪 Como Testar

### Teste 1: Verificar Filtro de Status

1. Criar um Troco PIX em `/troco_pix/novo`
2. Acessar `/lancamentos_caixa/`
3. **Resultado esperado:** Lançamento NÃO aparece na lista
4. Criar um fechamento normal em `/lancamentos_caixa/novo`
5. Salvar o fechamento
6. Acessar `/lancamentos_caixa/`
7. **Resultado esperado:** Fechamento APARECE na lista

### Teste 2: Verificar Cartões Detalhados

1. Acessar `/lancamentos_caixa/visualizar/3` (ou outro ID com cartões)
2. Clicar no botão "Copiar para WhatsApp"
3. Colar em um editor de texto
4. **Resultado esperado:**
   - Ver "Cartão Débito:" seguido de lista de bandeiras
   - Ver "Cartão Crédito:" seguido de lista de bandeiras
   - Ver "Subtotal:" após cada lista

### Query SQL para Verificar Status

```sql
-- Ver lançamentos por status
SELECT 
    id,
    data,
    status,
    observacao,
    total_receitas,
    total_comprovacao
FROM lancamentos_caixa
ORDER BY data DESC, id DESC
LIMIT 20;

-- Contar por status
SELECT 
    status,
    COUNT(*) as total
FROM lancamentos_caixa
GROUP BY status;
```

---

## 📝 Arquivos Modificados

### 1. routes/lancamentos_caixa.py
- **Linha 96:** Adicionado filtro `WHERE status = 'FECHADO'`
- **Impacto:** Listagem mostra apenas lançamentos finalizados

### 2. templates/lancamentos_caixa/visualizar.html
- **Linhas 418-433:** Loop detalhado por cartão individual
- **Impacto:** WhatsApp mostra bandeiras separadamente

---

## 🔍 Troubleshooting

### Problema: Lançamentos ainda aparecem na lista

**Possível causa:** Lançamentos antigos com status NULL ou diferente

**Solução:**
```sql
-- Verificar status dos lançamentos
SELECT id, data, status, observacao
FROM lancamentos_caixa
WHERE status IS NULL OR status = '';

-- Atualizar se necessário
UPDATE lancamentos_caixa
SET status = 'FECHADO'
WHERE status IS NULL OR status = ''
  AND total_receitas IS NOT NULL;
```

### Problema: Cartões não aparecem detalhados

**Possível causa:** Dados antigos sem `cartao_nome` preenchido

**Solução:**
```sql
-- Verificar comprovações de cartão
SELECT 
    lcc.*,
    bc.nome as bandeira_nome
FROM lancamentos_caixa_comprovacao lcc
LEFT JOIN bandeiras_cartao bc ON lcc.bandeira_cartao_id = bc.id
WHERE lcc.forma_pagamento_id IN (
    SELECT id FROM formas_pagamento_caixa WHERE tipo = 'CARTAO'
)
LIMIT 20;
```

---

## 📚 Referências

- **Troco PIX:** Ver `routes/troco_pix.py` função `criar_lancamento_caixa_automatico()`
- **Status:** Valores possíveis: 'ABERTO', 'FECHADO'
- **Cartões:** Tabelas: `lancamentos_caixa_comprovacao`, `bandeiras_cartao`

---

## ✅ Checklist de Validação

- [ ] Lançamentos automáticos de Troco PIX não aparecem na lista
- [ ] Fechamentos normais aparecem na lista
- [ ] WhatsApp mostra cartões de débito por bandeira
- [ ] WhatsApp mostra cartões de crédito por bandeira
- [ ] WhatsApp mostra subtotais corretos
- [ ] Filtro de data funciona normalmente (45 dias)
- [ ] Filtro de cliente funciona normalmente

---

**Data da Correção:** 03/02/2026  
**Versão:** 1.0  
**Autor:** Sistema NH Transportes
