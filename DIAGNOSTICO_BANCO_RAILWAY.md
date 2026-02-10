# 📊 DIAGNÓSTICO DO BANCO DE DADOS RAILWAY

## 🎯 O QUE CONSULTAR NO BANCO

### Problema Atual:
- Listagem mostra: 1 FRENTISTA, 6 MOTORISTAS
- Deveria mostrar: 7 FRENTISTAS, 2 MOTORISTAS

### Objetivo:
Verificar se o banco de dados está configurado corretamente para a query funcionar.

---

## 📋 QUERIES DE DIAGNÓSTICO

### 1. Verificar Estrutura da Tabela `funcionarios`

```sql
-- Ver estrutura da tabela
DESCRIBE funcionarios;

-- Ou
SHOW COLUMNS FROM funcionarios;
```

**O que verificar:**
- ✅ Existe coluna `categoria`?
- ✅ Tipo: VARCHAR ou CHAR?
- ✅ Pode ser NULL?

---

### 2. Ver Dados da Tabela `funcionarios`

```sql
-- Ver todos os funcionários
SELECT 
    id,
    nome,
    categoria,
    CASE 
        WHEN categoria IS NULL THEN '⚠️ NULL'
        WHEN categoria = '' THEN '⚠️ VAZIO'
        ELSE categoria
    END as status_categoria
FROM funcionarios
ORDER BY id;
```

**O que deve ter:**
- ✅ 7+ funcionários (BRENA, ERIK, JOÃO, LUCIENE, MARCOS HENRIQUE, ROBERTA, RODRIGO)
- ✅ Campo `categoria` = 'FRENTISTA' ou 'FRENTISTAS'
- ❌ Se `categoria` = NULL → PROBLEMA!

---

### 3. Ver Dados da Tabela `motoristas`

```sql
-- Ver todos os motoristas
SELECT 
    id,
    nome
FROM motoristas
ORDER BY id;
```

**O que deve ter:**
- ✅ 2 motoristas: MARCOS ANTONIO e VALMIR
- ✅ IDs específicos (ex: 4 e 6)

---

### 4. Verificar Sobreposição de IDs

```sql
-- Verificar se IDs existem em ambas as tabelas
SELECT 
    f.id as func_id,
    f.nome as func_nome,
    f.categoria as func_categoria,
    m.id as mot_id,
    m.nome as mot_nome,
    CASE 
        WHEN f.id IS NOT NULL AND m.id IS NOT NULL THEN '⚠️ AMBAS TABELAS'
        WHEN f.id IS NOT NULL THEN '✅ SÓ FUNCIONARIOS'
        WHEN m.id IS NOT NULL THEN '✅ SÓ MOTORISTAS'
    END as status
FROM funcionarios f
FULL OUTER JOIN motoristas m ON f.id = m.id
ORDER BY COALESCE(f.id, m.id);
```

**O que verificar:**
- ❌ Se IDs aparecem em "AMBAS TABELAS" → PROBLEMA!
- ✅ Idealmente: IDs únicos em cada tabela

---

### 5. Verificar Lançamentos

```sql
-- Ver lançamentos do mês 01/2026
SELECT 
    l.funcionarioid,
    COUNT(*) as qtd_lancamentos,
    SUM(l.valor) as total_valor,
    f.nome as func_nome,
    f.categoria as func_categoria,
    m.nome as mot_nome
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
WHERE l.mes = '01/2026' AND l.clienteid = 1
GROUP BY l.funcionarioid, f.nome, f.categoria, m.nome
ORDER BY l.funcionarioid;
```

**O que deve ter:**
- ✅ 9 funcionários (7 frentistas + 2 motoristas)
- ✅ Cada um com lançamentos
- ✅ Categoria correta para cada um

---

### 6. Simular a Query do Sistema

```sql
-- Esta é a query que o sistema usa
SELECT 
    sub.mes,
    sub.cliente_nome,
    sub.categoria,
    COUNT(DISTINCT sub.funcionarioid) as total_funcionarios,
    SUM(sub.valor) as total_valor
FROM (
    SELECT 
        l.mes,
        c.razao_social as cliente_nome,
        l.funcionarioid,
        CASE 
            WHEN f.id IS NOT NULL THEN COALESCE(f.categoria, 'FRENTISTAS')
            WHEN m.id IS NOT NULL THEN 'MOTORISTAS'
            ELSE 'OUTROS'
        END as categoria,
        l.valor
    FROM lancamentosfuncionarios_v2 l
    LEFT JOIN clientes c ON l.clienteid = c.id
    LEFT JOIN funcionarios f ON l.funcionarioid = f.id
    LEFT JOIN motoristas m ON l.funcionarioid = m.id
    WHERE l.mes = '01/2026' AND l.clienteid = 1
) as sub
GROUP BY sub.mes, sub.cliente_nome, sub.categoria
ORDER BY sub.mes DESC, sub.categoria;
```

**Resultado esperado:**
```
FRENTISTA (ou FRENTISTAS) | 7 | R$ 23.263,98
MOTORISTAS                | 2 | R$ 6.308,45
```

---

## 🔍 PROBLEMAS COMUNS E SOLUÇÕES

### Problema 1: Campo `categoria` Não Existe

**Sintoma:** Erro "Unknown column 'categoria'"

**Solução:** Adicionar coluna
```sql
ALTER TABLE funcionarios ADD COLUMN categoria VARCHAR(50);
```

---

### Problema 2: Campo `categoria` Está NULL

**Sintoma:** Todos classificados como MOTORISTAS

**Verificar:**
```sql
SELECT COUNT(*) as total,
       SUM(CASE WHEN categoria IS NULL THEN 1 ELSE 0 END) as nulls,
       SUM(CASE WHEN categoria IS NOT NULL THEN 1 ELSE 0 END) as preenchidos
FROM funcionarios;
```

**Solução:** Preencher categoria
```sql
UPDATE funcionarios 
SET categoria = 'FRENTISTA' 
WHERE categoria IS NULL OR categoria = '';
```

---

### Problema 3: IDs Sobrepostos

**Sintoma:** Funcionários classificados incorretamente

**Verificar:** Query 4 acima

**Solução:** Depende do caso
- Remover duplicatas
- Ajustar IDs
- Ou aceitar sobreposição (query COALESCE já trata)

---

### Problema 4: Valores Diferentes

**Sintoma:** Categoria tem valores inconsistentes

**Verificar:**
```sql
SELECT DISTINCT categoria 
FROM funcionarios 
WHERE categoria IS NOT NULL;
```

**Possíveis valores:**
- 'FRENTISTA' (singular)
- 'FRENTISTAS' (plural)
- Outros

**Solução:** Padronizar
```sql
UPDATE funcionarios 
SET categoria = 'FRENTISTA' 
WHERE categoria IN ('FRENTISTAS', 'frentista', 'Frentista');
```

---

## ✅ CHECKLIST DE VALIDAÇÃO

### Estrutura:
- [ ] Tabela `funcionarios` existe
- [ ] Coluna `categoria` existe
- [ ] Tabela `motoristas` existe
- [ ] Tabela `lancamentosfuncionarios_v2` existe

### Dados:
- [ ] 7+ funcionários na tabela `funcionarios`
- [ ] 2 motoristas na tabela `motoristas`
- [ ] Campo `categoria` preenchido (não NULL)
- [ ] Lançamentos existem para 9 funcionários

### Consistência:
- [ ] IDs não duplicados (ou sobreposição aceitável)
- [ ] Categoria padronizada ('FRENTISTA' ou 'FRENTISTAS')
- [ ] Valores corretos nos lançamentos
- [ ] Query de simulação retorna 7 FRENTISTAS + 2 MOTORISTAS

---

## 📊 RESULTADO ESPERADO

Após correções, a query deve retornar:

```
Mês      | Cliente                | Categoria  | Total | Valor
---------|------------------------|------------|-------|------------
01/2026  | POSTO NOVO HORIZONTE   | FRENTISTA  | 7     | R$ 23.263,98
01/2026  | POSTO NOVO HORIZONTE   | MOTORISTAS | 2     | R$ 6.308,45
```

**Total:** 9 funcionários

---

## 🔧 PRÓXIMOS PASSOS

1. **Executar queries de diagnóstico** (1-6)
2. **Identificar problemas** usando checklist
3. **Aplicar correções SQL** conforme necessário
4. **Validar** com query de simulação (Query 6)
5. **Fazer deploy** do código se ainda não foi feito
6. **Validar** em produção

---

## 📝 NOTAS IMPORTANTES

### Sobre o Código:
A query no código (commit 75) já está CORRETA:
```sql
WHEN f.id IS NOT NULL THEN COALESCE(f.categoria, 'FRENTISTAS')
```

Esta query trata NULL automaticamente, então mesmo se `categoria` estiver NULL, funcionará.

### Sobre IDs Sobrepostos:
A query prioriza `funcionarios` sobre `motoristas`, então mesmo com IDs sobrepostos, funcionários serão classificados corretamente.

### Se Tudo Estiver Correto no Banco:
- Verificar se deploy foi feito (commit 75)
- Verificar logs do Render
- Limpar cache do navegador

---

## 🚀 FERRAMENTAS

### Google Colab:
Veja o arquivo `diagnostico_banco.ipynb` para executar todas essas queries automaticamente com visualizações.

### Acesso Railway:
```bash
# Via CLI
railway connect

# Via MySQL client
mysql -h <host> -u <user> -p<password> <database>
```

---

**Criado em:** 10/02/2026  
**Versão:** 1.0  
**Branch:** copilot/fix-merge-issue-39  
**Commit:** 76
