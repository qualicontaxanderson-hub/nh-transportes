# 🚀 COMO USAR AS FERRAMENTAS DE DIAGNÓSTICO

## Para diagnosticar o Banco de Dados Railway

---

## 📋 GUIA RÁPIDO

### Você tem 2 ferramentas:

1. **diagnostico_banco.ipynb** → Google Colab (Automático) ⭐ RECOMENDADO
2. **DIAGNOSTICO_BANCO_RAILWAY.md** → Guia Manual

---

## ⭐ OPÇÃO 1: GOOGLE COLAB (AUTOMÁTICO)

### 🎯 Passo a Passo:

#### 1. Abrir Google Colab
```
https://colab.research.google.com/
```

#### 2. Fazer Upload do Notebook
- Clicar em **File → Upload notebook**
- Selecionar: `diagnostico_banco.ipynb`
- Ou arrastar o arquivo para o Colab

#### 3. Pegar Credenciais do Railway

No Railway:
- Acessar seu projeto
- Ir em **Database**
- Copiar:
  - Host (ex: mysql.railway.internal)
  - Port (geralmente 3306)
  - User (geralmente root)
  - Password
  - Database name (geralmente railway)

#### 4. Configurar no Colab

Na **Célula 2** do notebook, preencher:

```python
DB_CONFIG = {
    'host': 'seu-host-aqui.railway.app',
    'port': 3306,
    'user': 'root',
    'password': 'sua-senha-aqui',
    'database': 'railway'
}
```

#### 5. Executar

- Clicar em **Runtime → Run all**
- Ou executar célula por célula com **Shift + Enter**

#### 6. Ver Resultados

O notebook vai:
- ✅ Conectar ao banco
- ✅ Executar 6 diagnósticos
- ✅ Identificar problemas
- ✅ Mostrar recomendações
- ✅ Exibir resultado esperado vs atual

---

## 📖 OPÇÃO 2: CONSULTA MANUAL

### 🎯 Passo a Passo:

#### 1. Abrir Arquivo
Abrir: `DIAGNOSTICO_BANCO_RAILWAY.md`

#### 2. Conectar ao Railway

```bash
# Via Railway CLI
railway connect

# Ou via MySQL Client
mysql -h seu-host.railway.app -u root -p database_name
```

#### 3. Executar Queries

Copiar e executar as 6 queries principais do arquivo:

**Query 1: Estrutura**
```sql
SHOW COLUMNS FROM funcionarios;
```

**Query 2: Funcionários**
```sql
SELECT id, nome, categoria FROM funcionarios;
```

**Query 3: Motoristas**
```sql
SELECT id, nome FROM motoristas;
```

**Query 4: Sobreposição**
```sql
-- Ver query completa no arquivo
```

**Query 5: Lançamentos**
```sql
-- Ver query completa no arquivo
```

**Query 6: Simulação Sistema**
```sql
-- Ver query completa no arquivo
```

#### 4. Interpretar Resultados

Ver seção "Como Interpretar" no arquivo markdown.

---

## 🔍 O QUE VOCÊ VAI DESCOBRIR:

### ✅ Se o banco está correto:
- Coluna `categoria` existe?
- Valores preenchidos?
- 7 frentistas + 2 motoristas?

### ⚠️ Se há problemas:
- Campo NULL?
- Coluna não existe?
- IDs duplicados?
- Lançamentos faltando?

### 🔧 Correções automáticas:
- SQLs prontos para executar
- Recomendações específicas
- Passo a passo de correção

---

## 📊 RESULTADO ESPERADO

### Após diagnóstico, deve mostrar:

```
╔════════════╦═══════════════╦════════════════╗
║ Categoria  ║ Total Func    ║ Valor Total    ║
╠════════════╬═══════════════╬════════════════╣
║ FRENTISTA  ║ 7             ║ R$ 23.263,98   ║
║ MOTORISTAS ║ 2             ║ R$ 6.308,45    ║
╚════════════╩═══════════════╩════════════════╝
```

**Total:** 9 funcionários

---

## 🚨 PROBLEMAS COMUNS

### 1. Categoria NULL

**Você verá:**
```
⚠️ 7 funcionários com categoria NULL
```

**Correção:**
```sql
UPDATE funcionarios SET categoria = 'FRENTISTA' WHERE categoria IS NULL;
```

---

### 2. Coluna Não Existe

**Você verá:**
```
❌ Coluna 'categoria' não existe
```

**Correção:**
```sql
ALTER TABLE funcionarios ADD COLUMN categoria VARCHAR(50);
UPDATE funcionarios SET categoria = 'FRENTISTA';
```

---

### 3. Banco Correto mas Sistema Errado

**Você verá:**
```
✅ Banco de dados está correto!
```

**Mas sistema ainda mostra errado.**

**Solução:**
1. Verificar se deploy foi feito (commit 75/76)
2. Fazer merge da branch: `copilot/fix-merge-issue-39`
3. Aguardar deploy do Render
4. Limpar cache do navegador

---

## 📋 CHECKLIST DE USO

### Antes de começar:
- [ ] Credenciais do Railway em mãos
- [ ] Acesso ao banco de dados
- [ ] Google Colab aberto (Opção 1)
- [ ] Ou MySQL client instalado (Opção 2)

### Durante diagnóstico:
- [ ] Upload do notebook (Opção 1)
- [ ] Configurar credenciais
- [ ] Executar todas as células
- [ ] Ler resultados com atenção

### Após diagnóstico:
- [ ] Identificar problemas (se houver)
- [ ] Executar correções SQL
- [ ] Validar correções
- [ ] Fazer deploy se necessário
- [ ] Validar em produção

---

## 🎯 RESUMO

### Escolha sua ferramenta:

**Google Colab (Recomendado):**
- ✅ Automático
- ✅ Visual
- ✅ Completo
- ✅ Recomendações automáticas

**Manual (Alternativa):**
- ✅ Controle total
- ✅ Query por query
- ✅ Análise detalhada
- ✅ Não precisa Colab

---

## 📞 SUPORTE

### Se tiver dúvidas:

1. **Ler documentos:**
   - DIAGNOSTICO_BANCO_RAILWAY.md (completo)
   - diagnostico_banco.ipynb (comentado)

2. **Ver exemplos:**
   - Queries de exemplo no markdown
   - Código comentado no notebook

3. **Problemas comuns:**
   - Seção específica nos arquivos
   - Soluções prontas

---

## 🎊 ÚLTIMA PALAVRA

**Use o Google Colab!**

É a forma mais rápida e fácil de:
1. Diagnosticar o banco
2. Identificar problemas
3. Ver correções
4. Validar resultado

**Tempo estimado:** 5-10 minutos

**Resultado:** Banco validado e problemas identificados

---

**Boa sorte! 🚀**

**Arquivo criado em:** 10/02/2026  
**Branch:** copilot/fix-merge-issue-39  
**Commit:** 76
