# ✅ RESPOSTA: Query de Verificação do Sistema Automático

## ❓ SUA PERGUNTA

> "Essa query seria para o Cheque Automático?"

```sql
SELECT 
    (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') as tem_pix_auto,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) as tem_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) as tem_cheque_prazo;
```

---

## ✅ RESPOSTA: SIM! É para o Sistema Automático Completo

Essa query verifica se o **SISTEMA AUTOMÁTICO** está configurado corretamente para integrar TROCO PIX com Fechamento de Caixa.

---

## 🎯 O QUE CADA CAMPO VERIFICA

### 1️⃣ tem_pix_auto (TROCO PIX Automático)
```
Verifica: TROCO PIX (AUTO) existe?
Tabela: tipos_receita_caixa
Usado para: Preencher automaticamente as RECEITAS
```

**Se = 1:** ✅ TROCO PIX vai automaticamente para o lado ESQUERDO (Receitas)  
**Se = 0:** ❌ TROCO PIX não será preenchido automaticamente

---

### 2️⃣ tem_cheque_vista (CHEQUE À Vista Automático)
```
Verifica: DEPOSITO_CHEQUE_VISTA existe e está ativo?
Tabela: formas_pagamento_caixa
Usado para: Criar CHEQUE À Vista nas COMPROVAÇÕES
```

**Se = 1:** ✅ Cheques À Vista vão automaticamente para o lado DIREITO (Comprovações)  
**Se = 0:** ❌ Cheques À Vista não funcionarão

---

### 3️⃣ tem_cheque_prazo (CHEQUE A Prazo Automático)
```
Verifica: DEPOSITO_CHEQUE_PRAZO existe e está ativo?
Tabela: formas_pagamento_caixa
Usado para: Criar CHEQUE A Prazo nas COMPROVAÇÕES
```

**Se = 1:** ✅ Cheques A Prazo vão automaticamente para o lado DIREITO (Comprovações)  
**Se = 0:** ❌ Cheques A Prazo não funcionarão

---

## 📊 FLUXO DO SISTEMA AUTOMÁTICO

```
╔═══════════════════════════════════════════════════════════════════╗
║                FRENTISTA CRIA TROCO PIX                            ║
║              /troco_pix/novo (Tela do Sistema)                    ║
╚═══════════════════════════════════════════════════════════════════╝
                            ↓
                     Dados preenchidos:
                     • Venda: R$ 2.020,00
                     • Cheque À Vista: R$ 3.000,00
                     • Troco PIX: R$ 900,00
                            ↓
              Sistema AUTOMATICAMENTE verifica:
                            ↓
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ↓                       ↓                       ↓
tem_pix_auto = 1?    tem_cheque_vista = 1?  tem_cheque_prazo = 1?
    │                       │                       │
    ↓                       ↓                       ↓
   ✅ SIM                  ✅ SIM                  ✅ SIM
    │                       │                       │
    └───────────────────────┼───────────────────────┘
                            ↓
              Sistema AUTOMATICAMENTE cria:
                            ↓
┌──────────────────────────────────────────────────────────────────┐
│              FECHAMENTO DE CAIXA (AUTOMÁTICO)                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  📥 RECEITAS (Lado Esquerdo)      📤 COMPROVAÇÕES (Lado Direito)│
│  ─────────────────────────        ──────────────────────────    │
│                                                                  │
│  TROCO PIX (AUTO)                 DEPOSITO_CHEQUE_VISTA         │
│  ↑ usa tem_pix_auto              ↑ usa tem_cheque_vista        │
│                                                                  │
│  Valor: R$ 900,00 ✅              Valor: R$ 3.000,00 ✅         │
│                                                                  │
│  Descrição:                       Descrição:                    │
│  AUTO - Troco PIX #45             AUTO - Cheque À Vista -       │
│                                   Troco PIX #45                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## ✅ RESULTADO IDEAL

### Query retorna:
```
+──────────────┬──────────────────┬───────────────────┐
│ tem_pix_auto │ tem_cheque_vista │ tem_cheque_prazo  │
├──────────────┼──────────────────┼───────────────────┤
│      1       │        1         │         1         │
└──────────────┴──────────────────┴───────────────────┘
```

### Significa:
- ✅ **Sistema automático COMPLETO**
- ✅ TROCO PIX vai automaticamente para RECEITAS
- ✅ CHEQUES vão automaticamente para COMPROVAÇÕES
- ✅ Integração funcionando 100%

---

## ⚠️ SE ALGUM VALOR FOR 0

### Exemplo de problema:
```
+──────────────┬──────────────────┬───────────────────┐
│ tem_pix_auto │ tem_cheque_vista │ tem_cheque_prazo  │
├──────────────┼──────────────────┼───────────────────┤
│      1       │        0         │         0         │ ❌ PROBLEMA!
└──────────────┴──────────────────┴───────────────────┘
```

### O que acontece:
- ✅ TROCO PIX funciona (tem_pix_auto = 1)
- ❌ CHEQUES NÃO funcionam (tem_cheque_vista = 0, tem_cheque_prazo = 0)
- ❌ Sistema não consegue criar lançamento de caixa
- ❌ Erro: "Forma de pagamento não encontrada"

### Solução:
```bash
# Execute o script de correção
mysql -u usuario -p banco < CRIAR_CHEQUES.sql
```

---

## 🔧 ONDE O CÓDIGO USA ISSO

### Arquivo: `/routes/troco_pix.py`
### Função: `criar_lancamento_caixa_automatico()`

**Linha 141-158: Busca o tipo de CHEQUE**
```python
# Buscar forma de pagamento para cheque
if cheque_tipo == 'À Vista':
    forma_tipo = 'DEPOSITO_CHEQUE_VISTA'  # ← usa tem_cheque_vista
else:  # A Prazo
    forma_tipo = 'DEPOSITO_CHEQUE_PRAZO'  # ← usa tem_cheque_prazo

cursor.execute("""
    SELECT id FROM formas_pagamento_caixa 
    WHERE tipo = %s AND ativo = 1
    LIMIT 1
""", (forma_tipo,))

forma_pagamento = cursor.fetchone()
if not forma_pagamento:
    print(f"[AVISO] Forma de pagamento {forma_tipo} não encontrada")
    return None  # ← FALHA se não encontrar!
```

**Se a query retornar 0 para tem_cheque_vista ou tem_cheque_prazo:**
→ `forma_pagamento` será `None`
→ Sistema retorna `None` (falha)
→ Lançamento de caixa NÃO é criado
→ TROCO PIX não integra com Fechamento de Caixa

---

## 📋 TABELA DE DEPENDÊNCIAS

| Campo | Tabela | Usado Para | Obrigatório |
|-------|--------|------------|-------------|
| tem_pix_auto | tipos_receita_caixa | RECEITAS automáticas | ✅ SIM |
| tem_cheque_vista | formas_pagamento_caixa | COMPROVAÇÕES (À Vista) | ✅ SIM |
| tem_cheque_prazo | formas_pagamento_caixa | COMPROVAÇÕES (A Prazo) | ✅ SIM |

**Todos os 3 devem retornar 1 para o sistema funcionar!**

---

## 🎯 RESUMO EXECUTIVO

### PERGUNTA:
> "Isso aqui seria para o Cheque Automático?"

### RESPOSTA:
**SIM! Mas não é só para o CHEQUE Automático.**

É para o **SISTEMA AUTOMÁTICO COMPLETO** que inclui:
1. ✅ **TROCO PIX Automático** (tem_pix_auto)
2. ✅ **CHEQUE À Vista Automático** (tem_cheque_vista)
3. ✅ **CHEQUE A Prazo Automático** (tem_cheque_prazo)

### O QUE FAZ:
Verifica se todos os componentes necessários para a integração automática TROCO PIX → Fechamento de Caixa estão configurados.

### QUANDO USAR:
- Antes de criar um TROCO PIX
- Após executar migrations
- Para diagnosticar problemas
- Para confirmar que está tudo OK

### COMO INTERPRETAR:
- **Todos = 1** → ✅ Sistema automático funcionando 100%
- **Algum = 0** → ❌ Precisa executar `CRIAR_CHEQUES.sql`

---

## 💡 EXEMPLOS PRÁTICOS

### Exemplo 1: Tudo OK ✅
```sql
-- Query executada
SELECT ... ;

-- Resultado
tem_pix_auto: 1 ✅
tem_cheque_vista: 1 ✅
tem_cheque_prazo: 1 ✅

-- Significa
Sistema automático está COMPLETO!
Pode criar TROCO PIX normalmente.
```

### Exemplo 2: Falta CHEQUES ❌
```sql
-- Query executada
SELECT ... ;

-- Resultado
tem_pix_auto: 1 ✅
tem_cheque_vista: 0 ❌
tem_cheque_prazo: 0 ❌

-- Significa
TROCO PIX (AUTO) existe, mas CHEQUES faltam.
Sistema NÃO funcionará corretamente.

-- Solução
Execute: CRIAR_CHEQUES.sql
```

### Exemplo 3: Falta tudo ❌
```sql
-- Query executada
SELECT ... ;

-- Resultado
tem_pix_auto: 0 ❌
tem_cheque_vista: 0 ❌
tem_cheque_prazo: 0 ❌

-- Significa
Sistema automático NÃO está configurado.

-- Solução
1. Execute: migrations/20260203_add_troco_pix_auto.sql
2. Execute: CRIAR_CHEQUES.sql
3. Execute a query novamente para confirmar
```

---

## 🔍 OUTRAS QUERIES ÚTEIS

### Ver detalhes do TROCO PIX (AUTO):
```sql
SELECT * FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)';
```

### Ver detalhes dos CHEQUES:
```sql
SELECT id, nome, tipo, ativo 
FROM formas_pagamento_caixa 
WHERE tipo IN ('DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO');
```

### Ver TUDO de uma vez:
```bash
mysql -u usuario -p banco < VERIFICAR_BANCO.sql
```

---

## ✅ CONCLUSÃO

**SIM, essa query é para verificar o SISTEMA AUTOMÁTICO completo:**

1. **TROCO PIX Automático** (tem_pix_auto)
2. **CHEQUE À Vista Automático** (tem_cheque_vista) ← SUA PERGUNTA
3. **CHEQUE A Prazo Automático** (tem_cheque_prazo) ← SUA PERGUNTA

Todos os 3 componentes trabalham juntos para criar automaticamente o Fechamento de Caixa quando um frentista lança um TROCO PIX.

**Todos devem retornar 1 para funcionar!** ✅

---

**Data:** 03/02/2026  
**Status:** Query verifica sistema automático completo  
**Ação:** Execute e garanta que todos retornem 1

---

**FIM DO DOCUMENTO**
