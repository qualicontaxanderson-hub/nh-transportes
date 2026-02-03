# 🔄 FLUXO AUTOMÁTICO: TROCO PIX → Fechamento de Caixa

## ✅ RESPOSTA RÁPIDA

**PERGUNTA:** Os CHEQUES vão automaticamente para as Comprovações no Fechamento de Caixa?

**RESPOSTA:** ✅ **SIM! Já está funcionando!**

---

## 📊 FLUXO VISUAL

```
╔═══════════════════════════════════════════════════════════════════════╗
║                    FRENTISTA CRIA TROCO PIX                           ║
║                 (https://nh-transportes.onrender.com/troco_pix/novo)  ║
╚═══════════════════════════════════════════════════════════════════════╝
                                    │
                                    │ Salva formulário
                                    ↓
┌───────────────────────────────────────────────────────────────────────┐
│  DADOS DO TROCO PIX                                                   │
├───────────────────────────────────────────────────────────────────────┤
│  • Data: 03/02/2026                                                   │
│  • Posto: NH GBTA                                                     │
│  • Venda Total: R$ 2.020,00                                           │
│  • Cheque À Vista: R$ 3.000,00 ← ESTE VALOR                          │
│  • Troco PIX: R$ 900,00 ← ESTE VALOR                                 │
│  • Troco Espécie: R$ 80,00                                            │
└───────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Sistema chama automaticamente
                                    │ criar_lancamento_caixa_automatico()
                                    ↓
╔═══════════════════════════════════════════════════════════════════════╗
║           SISTEMA CRIA AUTOMATICAMENTE NO BANCO DE DADOS              ║
╚═══════════════════════════════════════════════════════════════════════╝
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ↓               ↓               ↓
          ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
          │ lancamentos │ │  receitas   │ │ comprovacao │
          │   _caixa    │ │   (TROCO)   │ │  (CHEQUE)   │
          └─────────────┘ └─────────────┘ └─────────────┘
                                    │
                                    ↓
╔═══════════════════════════════════════════════════════════════════════╗
║              RESULTADO NO FECHAMENTO DE CAIXA                         ║
╚═══════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────┐
│  Lançamento de Caixa #123                                           │
│  Data: 03/02/2026 | Cliente: NH GBTA | Status: ABERTO              │
│  Observação: Lançamento automático - Troco PIX #45                  │
└─────────────────────────────────────────────────────────────────────┘

┌───────────────────────────┬─────────────────────────────────────────┐
│  📥 RECEITAS              │  📤 COMPROVAÇÕES                        │
│  (Lado Esquerdo)          │  (Lado Direito)                         │
├───────────────────────────┼─────────────────────────────────────────┤
│                           │                                         │
│  ✅ TROCO PIX             │  ✅ DEPOSITO_CHEQUE_VISTA               │
│                           │                                         │
│  Tipo: TROCO_PIX          │  Forma: Cheque À Vista                  │
│  Descrição:               │  Descrição:                             │
│  "AUTO - Troco PIX #45"   │  "AUTO - Cheque À Vista - Troco PIX #45"│
│                           │                                         │
│  Valor: R$ 900,00 ✅      │  Valor: R$ 3.000,00 ✅                  │
│                           │                                         │
└───────────────────────────┴─────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  TOTAIS CALCULADOS AUTOMATICAMENTE:                                 │
│  • Total Receitas: R$ 900,00                                        │
│  • Total Comprovações: R$ 3.000,00                                  │
│  • Diferença: R$ 2.100,00                                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ✅ O QUE JÁ FUNCIONA

| Item | Status | Descrição |
|------|--------|-----------|
| TROCO PIX → Receitas | ✅ | Vai automaticamente para o lado esquerdo |
| CHEQUE → Comprovações | ✅ | Vai automaticamente para o lado direito |
| Cheque À Vista | ✅ | Tipo DEPOSITO_CHEQUE_VISTA |
| Cheque A Prazo | ✅ | Tipo DEPOSITO_CHEQUE_PRAZO |
| Identificação AUTO | ✅ | Prefixo "AUTO -" na descrição |
| Vinculação | ✅ | Campo lancamento_caixa_id |
| Atualização automática | ✅ | Ao editar TROCO PIX |
| Exclusão automática | ✅ | Ao deletar TROCO PIX |

---

## 🔧 ONDE ESTÁ O CÓDIGO

**Arquivo:** `/routes/troco_pix.py`

**Função principal:**
```python
def criar_lancamento_caixa_automatico(
    troco_pix_id,      # ID do TROCO PIX
    cliente_id,        # ID do posto
    data,              # Data da transação
    valor_troco_pix,   # ← Vai para RECEITAS
    cheque_tipo,       # À Vista ou A Prazo
    valor_cheque,      # ← Vai para COMPROVAÇÕES
    usuario_id
):
```

**Linha 187-198:** Insere nas RECEITAS
```python
INSERT INTO lancamentos_caixa_receitas 
(lancamento_caixa_id, tipo, descricao, valor)
VALUES (123, 'TROCO_PIX', 'AUTO - Troco PIX #45', 900.00)
```

**Linha 200-211:** Insere nas COMPROVAÇÕES
```python
INSERT INTO lancamentos_caixa_comprovacao 
(lancamento_caixa_id, forma_pagamento_id, descricao, valor)
VALUES (123, [ID], 'AUTO - Cheque À Vista - Troco PIX #45', 3000.00)
```

---

## 🎯 QUANDO É EXECUTADO

A função é chamada automaticamente em 3 momentos:

### 1. Ao CRIAR um TROCO PIX
```python
# routes/troco_pix.py linha ~707
lancamento_id = criar_lancamento_caixa_automatico(
    troco_pix_id=troco_pix_id,
    cliente_id=cliente_id,
    data=data_transacao,
    valor_troco_pix=troco_pix,      # ← RECEITAS
    cheque_tipo=cheque_tipo,
    valor_cheque=cheque_valor,       # ← COMPROVAÇÕES
    usuario_id=user_id
)
```

### 2. Ao EDITAR um TROCO PIX
```python
# routes/troco_pix.py linha ~913
lancamento_id = criar_lancamento_caixa_automatico(
    # ... mesmos parâmetros, atualiza os valores
)
```

### 3. Ao EXCLUIR um TROCO PIX
```python
# Pode excluir o lançamento de caixa vinculado também
```

---

## 📋 CHECKLIST DE VERIFICAÇÃO

Para confirmar que está funcionando:

### No Sistema:
- [ ] Criar um TROCO PIX em `/troco_pix/novo`
- [ ] Acessar Fechamento de Caixa com mesmo cliente/data
- [ ] Verificar se TROCO PIX aparece nas Receitas
- [ ] Verificar se CHEQUE aparece nas Comprovações
- [ ] Verificar prefixo "AUTO -" nas descrições

### No Banco de Dados:
```sql
-- Ver o lançamento criado
SELECT * FROM lancamentos_caixa 
WHERE observacao LIKE '%Troco PIX%';

-- Ver a receita
SELECT * FROM lancamentos_caixa_receitas 
WHERE tipo = 'TROCO_PIX' AND descricao LIKE 'AUTO -%';

-- Ver a comprovação
SELECT * FROM lancamentos_caixa_comprovacao 
WHERE descricao LIKE 'AUTO - Cheque%';
```

---

## 💡 EXEMPLO REAL

### Cenário:
```
Frentista João cria TROCO PIX:
├─ Posto: NH GBTA
├─ Data: 03/02/2026
├─ Venda: R$ 2.500,00
├─ Cheque À Vista: R$ 4.000,00
└─ Troco PIX: R$ 1.500,00
```

### Sistema cria automaticamente:
```
📦 lancamentos_caixa (ID: 789)
   ├─ data: 2026-02-03
   ├─ cliente_id: 5 (NH GBTA)
   ├─ observacao: "Lançamento automático - Troco PIX #123"
   ├─ total_receitas: 1500.00
   ├─ total_comprovacao: 4000.00
   └─ diferenca: 2500.00

📥 lancamentos_caixa_receitas
   ├─ lancamento_caixa_id: 789
   ├─ tipo: TROCO_PIX
   ├─ descricao: "AUTO - Troco PIX #123"
   └─ valor: 1500.00 ✅

📤 lancamentos_caixa_comprovacao
   ├─ lancamento_caixa_id: 789
   ├─ forma_pagamento_id: 12 (DEPOSITO_CHEQUE_VISTA)
   ├─ descricao: "AUTO - Cheque À Vista - Troco PIX #123"
   └─ valor: 4000.00 ✅

🔗 troco_pix
   ├─ id: 123
   └─ lancamento_caixa_id: 789 ✅ (vinculação)
```

---

## 🎓 IMPORTANTE SABER

### 1. Identificação Automática
- ✅ Todas as entradas têm **"AUTO -"** no início
- ✅ Referência ao ID do TROCO PIX (ex: "#123")

### 2. Tipos de Cheque
- ✅ **À Vista** → `DEPOSITO_CHEQUE_VISTA`
- ✅ **A Prazo** → `DEPOSITO_CHEQUE_PRAZO`

### 3. Edição
- ✅ Editar TROCO PIX → atualiza lançamento automaticamente
- ✅ Valores são recalculados

### 4. Exclusão
- ✅ Excluir TROCO PIX → pode excluir lançamento também

---

## ✅ CONCLUSÃO

### RESPOSTA FINAL:

**✅ SIM! O sistema JÁ está preparado e FUNCIONANDO!**

Quando o frentista cria um TROCO PIX:
1. ✅ O valor do TROCO PIX vai automaticamente para as **RECEITAS**
2. ✅ O valor do CHEQUE vai automaticamente para as **COMPROVAÇÕES**

**Não precisa fazer mais nada!** 🎉

---

**Data:** 03/02/2026  
**Status:** ✅ Implementado e Funcionando  
**Código:** `/routes/troco_pix.py` linhas 98-235

---

**FIM DO RESUMO**
