# 📋 SCHEMA DO BANCO DE DADOS RAILWAY
## O que precisa ter para o sistema funcionar

---

## 🎯 RESUMO RÁPIDO (2 min)

Para a URL https://nh-transportes.onrender.com/lancamentos-funcionarios/ funcionar, você precisa ter:

### 3 TABELAS:
1. **funcionarios** - com coluna `categoria`
2. **motoristas** - com dados dos motoristas
3. **lancamentosfuncionarios_v2** - com os lançamentos

### DADOS MÍNIMOS:
- ✅ 7 funcionários com `categoria='FRENTISTA'`
- ✅ 2 motoristas cadastrados
- ✅ 9 lançamentos para o mês 01/2026

---

## 📊 ESTRUTURA DAS TABELAS

### 1. Tabela: `funcionarios`

**Colunas obrigatórias:**
```sql
id                INT PRIMARY KEY
nome              VARCHAR(255)
categoria         VARCHAR(50)     ← IMPORTANTE! Deve existir e estar preenchida
cpf               VARCHAR(14)
salario           DECIMAL(10,2)
-- outras colunas podem existir
```

**Dados necessários (7 frentistas):**
```
ID | Nome                           | Categoria
1  | BRENA NETALY TAVARES           | FRENTISTA
2  | ERIK GOMES TEIXEIRA            | FRENTISTA
3  | JOÃO BATISTA DO NASCIMENTO     | FRENTISTA
4  | LUCIENE SANTOS SILVA           | FRENTISTA
5  | MARCOS HENRIQUE MELAURO FILHO  | FRENTISTA
6  | ROBERTA FERREIRA               | FRENTISTA
7  | RODRIGO CUNHA DA SILVA         | FRENTISTA
```

**IMPORTANTE:**
- Campo `categoria` DEVE existir
- Campo `categoria` NÃO pode ser NULL
- Valor deve ser 'FRENTISTA' (ou variação como 'FRENTISTAS')

---

### 2. Tabela: `motoristas`

**Colunas obrigatórias:**
```sql
id         INT PRIMARY KEY
nome       VARCHAR(255)
cpf        VARCHAR(14)
-- outras colunas podem existir
```

**Dados necessários (2 motoristas):**
```
ID | Nome
4  | MARCOS ANTONIO
6  | VALMIR
```

**NOTA:** IDs podem ser diferentes, mas deve ter 2 motoristas.

---

### 3. Tabela: `lancamentosfuncionarios_v2`

**Colunas obrigatórias:**
```sql
id                INT PRIMARY KEY
funcionarioid     INT             ← ID do funcionário (1-7) ou motorista (4, 6)
mes               VARCHAR(10)     ← Formato: '01/2026'
clienteid         INT             ← ID do cliente
valor             DECIMAL(10,2)   ← Valor do lançamento
statuslancamento  VARCHAR(50)     ← Ex: 'PENDENTE'
-- outras colunas podem existir
```

**Dados necessários (lançamentos para 9 funcionários):**
```
FuncionarioID | Mês     | ClienteID | Qtd Lançamentos | Total Aproximado
1             | 01/2026 | 1         | ~2              | R$ 3.554,97
2             | 01/2026 | 1         | ~2              | R$ 3.298,10
3             | 01/2026 | 1         | ~2              | R$ 3.594,57
4             | 01/2026 | 1         | ~2              | R$ 3.014,44
5             | 01/2026 | 1         | ~2              | R$ 3.618,88
6             | 01/2026 | 1         | ~2              | R$ 3.014,44
7             | 01/2026 | 1         | ~1              | R$ 1.863,02
-- Motoristas (IDs podem estar também em funcionarios)
4             | 01/2026 | 1         | ~2              | R$ 3.014,44
6             | 01/2026 | 1         | ~2              | R$ 3.594,01
```

**TOTAL ESPERADO:**
- 9 funcionários/motoristas com lançamentos
- Soma: ~R$ 29.572,43

---

## 📋 TEMPLATE PARA VOCÊ PREENCHER

Copie este template, preencha com os dados do SEU banco Railway e mande aqui:

```
==== DADOS DO MEU BANCO RAILWAY ====

DATA DA CONSULTA: [coloque data/hora]

1. FUNCIONARIOS:
ID | Nome                           | Categoria
1  | [seu dado]                     | [seu dado]
2  | [seu dado]                     | [seu dado]
3  | [seu dado]                     | [seu dado]
4  | [seu dado]                     | [seu dado]
5  | [seu dado]                     | [seu dado]
6  | [seu dado]                     | [seu dado]
7  | [seu dado]                     | [seu dado]

TOTAL: [X] funcionários

2. MOTORISTAS:
ID | Nome
4  | [seu dado]
6  | [seu dado]

TOTAL: [X] motoristas

3. LANCAMENTOS (01/2026, Cliente=1):
FuncionarioID | Qtd Lançamentos | Total (R$)
1             | [X]             | [valor]
2             | [X]             | [valor]
3             | [X]             | [valor]
4             | [X]             | [valor]
5             | [X]             | [valor]
6             | [X]             | [valor]
7             | [X]             | [valor]
-- Motoristas
4             | [X]             | [valor]
6             | [X]             | [valor]

TOTAL: [X] funcionários/motoristas com lançamentos
SOMA TOTAL: R$ [valor]

========================================
```

---

## 🔍 COMO CONSULTAR SEU BANCO

Execute estas 3 queries simples no Railway e cole os resultados no template acima:

### Query 1: Ver funcionários
```sql
SELECT id, nome, categoria 
FROM funcionarios 
ORDER BY id;
```

### Query 2: Ver motoristas
```sql
SELECT id, nome 
FROM motoristas 
ORDER BY id;
```

### Query 3: Ver lançamentos
```sql
SELECT 
    funcionarioid,
    COUNT(*) as qtd_lancamentos,
    SUM(valor) as total_valor
FROM lancamentosfuncionarios_v2
WHERE mes = '01/2026' AND clienteid = 1
GROUP BY funcionarioid
ORDER BY funcionarioid;
```

---

## ✅ CHECKLIST DE VALIDAÇÃO

Marque SIM ou NÃO para cada item:

- [ ] **SIM/NÃO** - Coluna `categoria` existe na tabela `funcionarios`?
- [ ] **SIM/NÃO** - Coluna `categoria` NÃO é NULL para os funcionários?
- [ ] **SIM/NÃO** - Campo `categoria` tem valor 'FRENTISTA' (ou similar)?
- [ ] **SIM/NÃO** - Tenho 7 ou mais funcionários cadastrados?
- [ ] **SIM/NÃO** - Tenho 2 motoristas cadastrados?
- [ ] **SIM/NÃO** - Tenho lançamentos para o mês '01/2026'?
- [ ] **SIM/NÃO** - Tenho lançamentos para clienteid = 1?
- [ ] **SIM/NÃO** - Tenho 9 funcionários/motoristas com lançamentos?
- [ ] **SIM/NÃO** - Soma dos valores é aproximadamente R$ 29.572?
- [ ] **SIM/NÃO** - Deploy do código foi feito (commit 75/76)?

**Se TODOS são SIM:**
✅ Banco está correto! Problema pode ser no código/deploy.

**Se ALGUM é NÃO:**
⚠️ Banco precisa ser corrigido! Me mande os dados que eu te ajudo.

---

## 🎯 RESULTADO ESPERADO

Quando tudo estiver correto, a query do sistema deve retornar:

```
Categoria  | Total Funcionários | Valor Total
-----------|--------------------|---------------
FRENTISTA  | 7                  | R$ 23.263,98
MOTORISTAS | 2                  | R$ 6.308,45
```

**Total:** 9 funcionários

---

## 🚨 PROBLEMAS COMUNS

### Problema 1: Coluna categoria não existe
**Sintoma:** Erro "Unknown column 'categoria'"

**Solução:**
```sql
ALTER TABLE funcionarios ADD COLUMN categoria VARCHAR(50);
UPDATE funcionarios SET categoria = 'FRENTISTA';
```

---

### Problema 2: Campo categoria está NULL
**Sintoma:** Funcionários aparecem como MOTORISTAS

**Solução:**
```sql
UPDATE funcionarios SET categoria = 'FRENTISTA' WHERE categoria IS NULL;
```

---

### Problema 3: Não tem lançamentos
**Sintoma:** Query retorna vazio

**Solução:**
Verifique se lançamentos existem e se mês/cliente estão corretos.

---

### Problema 4: Banco correto mas sistema errado
**Sintoma:** Tudo OK no banco, mas URL mostra errado

**Solução:**
1. Verificar se deploy foi feito (commit 75 ou 76)
2. Fazer merge da branch: `copilot/fix-merge-issue-39`
3. Aguardar deploy do Render
4. Limpar cache do navegador

---

## 📤 PRÓXIMO PASSO

1. **Execute as 3 queries** no seu banco Railway
2. **Copie o template** acima
3. **Preencha com seus dados**
4. **Mande aqui** - cole tudo em uma mensagem
5. **Aguarde** - eu valido e confirmo se está correto!

Se houver algum problema, eu te digo exatamente o que precisa corrigir.

---

**Simples assim!** 🎯📋✅

---

**Arquivo criado em:** 10/02/2026  
**Branch:** copilot/fix-merge-issue-39  
**Commit:** 78
