# 📋 Guia Completo: Consultas e Alterações no Banco de Dados

**Data:** 07/02/2026  
**Versão:** 1.0  
**Status:** Pronto para uso

---

## 📊 RESUMO EXECUTIVO

### ✅ Resposta: SIM, há consultas e alterações necessárias!

**O que fazer:**
1. **CONSULTAR** - Verificar estado atual (8 queries)
2. **ALTERAR** - Deletar comissões incorretas (1 script)
3. **VALIDAR** - Confirmar correções (6 queries)
4. **MANTER** - Queries preventivas (5 queries)

---

## 📖 ÍNDICE

1. [Seção 1: Verificação do Estado Atual](#seção-1-verificação-do-estado-atual)
2. [Seção 2: Limpeza Necessária](#seção-2-limpeza-necessária)
3. [Seção 3: Validação Pós-Limpeza](#seção-3-validação-pós-limpeza)
4. [Seção 4: Manutenção Preventiva](#seção-4-manutenção-preventiva)
5. [Seção 5: Comandos Prontos](#seção-5-comandos-prontos)

---

## SEÇÃO 1: Verificação do Estado Atual

### Query 1: Listar Comissões de Frentistas (INCORRETAS)

```sql
-- Ver quais FRENTISTAS têm comissões (deveria ser 0)
SELECT 
    f.nome as funcionario_nome,
    'Funcionário' as tipo,
    r.nome as rubrica_nome,
    l.valor,
    l.mes,
    l.clienteid
FROM lancamentosfuncionarios_v2 l
INNER JOIN funcionarios f ON l.funcionarioid = f.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')
ORDER BY f.nome, l.mes;
```

**Resultado Esperado:** 
- João, Roberta, Rodrigo (se houver comissões incorretas)
- Deveria retornar 0 linhas após limpeza

### Query 2: Listar Comissões de Motoristas (CORRETAS)

```sql
-- Ver quais MOTORISTAS têm comissões (OK)
SELECT 
    m.nome as motorista_nome,
    'Motorista' as tipo,
    r.nome as rubrica_nome,
    l.valor,
    l.mes,
    l.clienteid
FROM lancamentosfuncionarios_v2 l
INNER JOIN motoristas m ON l.funcionarioid = m.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')
ORDER BY m.nome, l.mes;
```

**Resultado Esperado:**
- Marcos Antonio, Valmir, REM Transportes
- Estes devem SEMPRE aparecer

### Query 3: Contar Funcionários por Tipo

```sql
-- Total de funcionários vs motoristas
SELECT 
    'Funcionários' as tipo,
    COUNT(*) as total
FROM funcionarios
UNION ALL
SELECT 
    'Motoristas' as tipo,
    COUNT(*) as total
FROM motoristas;
```

### Query 4: Funcionários com Comissões (Todos)

```sql
-- Ver TODOS que têm comissões (funcionários + motoristas)
SELECT 
    l.funcionarioid,
    COALESCE(f.nome, m.nome) as nome,
    CASE 
        WHEN f.id IS NOT NULL THEN 'Funcionário'
        WHEN m.id IS NOT NULL THEN 'Motorista'
        ELSE 'Desconhecido'
    END as tipo,
    r.nome as rubrica,
    SUM(l.valor) as total_comissoes,
    COUNT(*) as num_lancamentos
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')
GROUP BY l.funcionarioid, nome, tipo, r.nome
ORDER BY tipo, nome;
```

### Query 5: Detalhes por Funcionário (Mês 01/2026, Cliente 1)

```sql
-- Ver lançamentos específicos do mês 01/2026, cliente 1
SELECT 
    l.funcionarioid,
    COALESCE(f.nome, m.nome) as funcionario_nome,
    CASE 
        WHEN f.id IS NOT NULL THEN 'Funcionário'
        WHEN m.id IS NOT NULL THEN 'Motorista'
    END as tipo,
    r.nome as rubrica_nome,
    l.valor,
    l.mes,
    l.statuslancamento
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE l.mes = '01/2026' 
  AND l.clienteid = 1
  AND r.nome IN ('Comissão', 'Comissão / Aj. Custo')
ORDER BY tipo, funcionario_nome;
```

### Query 6: Verificar Lançamentos Duplicados

```sql
-- Encontrar lançamentos duplicados (mesma combinação)
SELECT 
    funcionarioid,
    mes,
    clienteid,
    rubricaid,
    COUNT(*) as num_duplicados
FROM lancamentosfuncionarios_v2
GROUP BY funcionarioid, mes, clienteid, rubricaid
HAVING COUNT(*) > 1;
```

**Resultado Esperado:** Nenhuma linha (não deve haver duplicados)

### Query 7: Listar Todas as Rubricas

```sql
-- Ver todas as rubricas disponíveis
SELECT 
    id,
    nome,
    tipo,
    descricao
FROM rubricas
ORDER BY tipo, nome;
```

### Query 8: Verificar Integridade de IDs

```sql
-- Ver se há IDs que existem em ambas tabelas (improvável mas possível)
SELECT 
    f.id,
    f.nome as nome_funcionario,
    m.nome as nome_motorista
FROM funcionarios f
INNER JOIN motoristas m ON f.id = m.id;
```

**Resultado Esperado:** Nenhuma linha (IDs não devem se sobrepor)

---

## SEÇÃO 2: Limpeza Necessária

### ⚠️ ATENÇÃO: Sempre faça backup antes de deletar!

### Passo 1: Backup (RECOMENDADO)

```sql
-- Criar backup da tabela antes de deletar
CREATE TABLE lancamentosfuncionarios_v2_backup_20260207 AS 
SELECT * FROM lancamentosfuncionarios_v2;
```

### Passo 2: Verificar Quantos Serão Deletados

```sql
-- Contar quantos registros serão deletados
SELECT COUNT(*) as registros_a_deletar
FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (
    SELECT id FROM rubricas 
    WHERE nome IN ('Comissão', 'Comissão / Aj. Custo')
)
AND funcionarioid IN (
    SELECT id FROM funcionarios
);
```

**Resultado Esperado:** 3 (João, Roberta, Rodrigo)

### Passo 3: Ver Detalhes Antes de Deletar

```sql
-- Ver exatamente o que será deletado
SELECT 
    l.id as lancamento_id,
    f.nome as funcionario_nome,
    r.nome as rubrica_nome,
    l.valor,
    l.mes,
    l.clienteid
FROM lancamentosfuncionarios_v2 l
INNER JOIN funcionarios f ON l.funcionarioid = f.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo');
```

### Passo 4: DELETAR Comissões Incorretas

```sql
-- ⚠️ ATENÇÃO: Esta query DELETA dados permanentemente!
-- Execute apenas após confirmar os passos anteriores

DELETE FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (
    SELECT id FROM rubricas 
    WHERE nome IN ('Comissão', 'Comissão / Aj. Custo')
)
AND funcionarioid IN (
    SELECT id FROM funcionarios
);

-- Verificar quantas linhas foram deletadas
SELECT ROW_COUNT() as linhas_deletadas;
```

### Passo 5: Se Algo Der Errado (Rollback)

```sql
-- Se precisar desfazer, restaurar do backup
-- (Apenas se fez backup no Passo 1)
INSERT INTO lancamentosfuncionarios_v2
SELECT * FROM lancamentosfuncionarios_v2_backup_20260207
WHERE id NOT IN (SELECT id FROM lancamentosfuncionarios_v2);
```

---

## SEÇÃO 3: Validação Pós-Limpeza

### Query 1: Confirmar que Frentistas Não Têm Comissões

```sql
-- Deve retornar 0 linhas
SELECT 
    f.nome,
    r.nome as rubrica,
    l.valor
FROM lancamentosfuncionarios_v2 l
INNER JOIN funcionarios f ON l.funcionarioid = f.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo');
```

**✅ Sucesso:** 0 linhas retornadas

### Query 2: Confirmar que Motoristas Mantêm Comissões

```sql
-- Deve retornar Marcos, Valmir, etc.
SELECT 
    m.nome,
    r.nome as rubrica,
    l.valor,
    l.mes
FROM lancamentosfuncionarios_v2 l
INNER JOIN motoristas m ON l.funcionarioid = m.id
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')
ORDER BY m.nome, l.mes;
```

**✅ Sucesso:** Motoristas aparecem com suas comissões

### Query 3: Total de Comissões por Mês

```sql
-- Ver total de comissões por mês
SELECT 
    l.mes,
    COUNT(*) as num_lancamentos,
    SUM(l.valor) as total_comissoes,
    COUNT(DISTINCT l.funcionarioid) as num_funcionarios
FROM lancamentosfuncionarios_v2 l
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')
GROUP BY l.mes
ORDER BY l.mes;
```

### Query 4: Total de Comissões por Cliente

```sql
-- Ver total de comissões por cliente
SELECT 
    l.clienteid,
    c.nome as cliente_nome,
    COUNT(*) as num_lancamentos,
    SUM(l.valor) as total_comissoes
FROM lancamentosfuncionarios_v2 l
INNER JOIN rubricas r ON l.rubricaid = r.id
INNER JOIN clientes c ON l.clienteid = c.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')
GROUP BY l.clienteid, c.nome
ORDER BY total_comissoes DESC;
```

### Query 5: Listar Todos os Funcionários e Status

```sql
-- Ver todos os funcionários e se têm comissões
SELECT 
    f.id,
    f.nome,
    'Funcionário' as tipo,
    COALESCE(SUM(l.valor), 0) as total_comissoes,
    COUNT(l.id) as num_comissoes
FROM funcionarios f
LEFT JOIN lancamentosfuncionarios_v2 l ON f.id = l.funcionarioid
LEFT JOIN rubricas r ON l.rubricaid = r.id AND r.nome IN ('Comissão', 'Comissão / Aj. Custo')
GROUP BY f.id, f.nome

UNION ALL

SELECT 
    m.id,
    m.nome,
    'Motorista' as tipo,
    COALESCE(SUM(l.valor), 0) as total_comissoes,
    COUNT(l.id) as num_comissoes
FROM motoristas m
LEFT JOIN lancamentosfuncionarios_v2 l ON m.id = l.funcionarioid
LEFT JOIN rubricas r ON l.rubricaid = r.id AND r.nome IN ('Comissão', 'Comissão / Aj. Custo')
GROUP BY m.id, m.nome

ORDER BY tipo, nome;
```

### Query 6: Comparação Antes/Depois

```sql
-- Se fez backup, comparar antes vs depois
SELECT 
    'ANTES' as momento,
    COUNT(*) as total_comissoes
FROM lancamentosfuncionarios_v2_backup_20260207 l
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo')

UNION ALL

SELECT 
    'DEPOIS' as momento,
    COUNT(*) as total_comissoes
FROM lancamentosfuncionarios_v2 l
INNER JOIN rubricas r ON l.rubricaid = r.id
WHERE r.nome IN ('Comissão', 'Comissão / Aj. Custo');
```

---

## SEÇÃO 4: Manutenção Preventiva

### Query 1: Encontrar Registros Órfãos

```sql
-- Lançamentos com funcionarioid que não existe em nenhuma tabela
SELECT 
    l.id,
    l.funcionarioid,
    l.mes,
    l.valor
FROM lancamentosfuncionarios_v2 l
WHERE l.funcionarioid NOT IN (SELECT id FROM funcionarios)
  AND l.funcionarioid NOT IN (SELECT id FROM motoristas);
```

**Resultado Esperado:** 0 linhas

### Query 2: Verificar Constraints

```sql
-- Ver constraints da tabela
SHOW CREATE TABLE lancamentosfuncionarios_v2;
```

### Query 3: Verificar Índices

```sql
-- Ver índices da tabela
SHOW INDEX FROM lancamentosfuncionarios_v2;
```

### Query 4: Estatísticas da Tabela

```sql
-- Ver estatísticas e tamanho
SELECT 
    TABLE_NAME,
    TABLE_ROWS,
    DATA_LENGTH / 1024 / 1024 as tamanho_mb,
    INDEX_LENGTH / 1024 / 1024 as indice_mb
FROM information_schema.TABLES
WHERE TABLE_NAME = 'lancamentosfuncionarios_v2';
```

### Query 5: Analisar Performance

```sql
-- Analisar tabela para otimizar queries
ANALYZE TABLE lancamentosfuncionarios_v2;
```

---

## SEÇÃO 5: Comandos Prontos

### Comando Completo de Limpeza (Copiar e Executar)

```bash
# Conectar ao banco
mysql -h <host> -u <user> -p <database>

# Dentro do MySQL, executar:
```

```sql
-- 1. Backup
CREATE TABLE lancamentosfuncionarios_v2_backup_20260207 AS 
SELECT * FROM lancamentosfuncionarios_v2;

-- 2. Verificar quantos
SELECT COUNT(*) FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid IN (SELECT id FROM funcionarios);

-- 3. Deletar
DELETE FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid IN (SELECT id FROM funcionarios);

-- 4. Confirmar
SELECT COUNT(*) FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid IN (SELECT id FROM funcionarios);
-- Deve retornar 0
```

### Ou Usar o Script SQL Existente

```bash
# Executar script SQL que já está no repositório
mysql -h <host> -u <user> -p <database> < migrations/20260207_limpar_comissoes_frentistas.sql
```

---

## 📋 CHECKLIST DE EXECUÇÃO

### Antes de Executar:
- [ ] Fazer backup do banco completo
- [ ] Executar queries de verificação (Seção 1)
- [ ] Confirmar que há comissões incorretas
- [ ] Notificar equipe sobre manutenção

### Durante Execução:
- [ ] Executar backup da tabela (Seção 2, Passo 1)
- [ ] Verificar quantos serão deletados (Seção 2, Passo 2)
- [ ] Executar DELETE (Seção 2, Passo 4)
- [ ] Verificar ROW_COUNT

### Após Execução:
- [ ] Executar queries de validação (Seção 3)
- [ ] Confirmar 0 comissões para frentistas
- [ ] Confirmar motoristas mantêm comissões
- [ ] Testar aplicação (página detalhe e editar)
- [ ] Documentar resultado

---

## 🎯 RESULTADO ESPERADO FINAL

Após executar todas as alterações:

### Página `/detalhe/01-2026/1`:
- ✅ João: SEM comissão
- ✅ Roberta: SEM comissão
- ✅ Rodrigo: 1.000,00 (manual, OK)
- ✅ Valmir: COM comissão (automática)
- ✅ Marcos Antonio: COM comissão (automática)

### Banco de Dados:
- ✅ 0 comissões para funcionários (tabela `funcionarios`)
- ✅ N comissões para motoristas (tabela `motoristas`)
- ✅ Sem duplicados
- ✅ Sem registros órfãos

---

## 📞 SUPORTE

### Em Caso de Dúvida:
1. Revisar documentação: `README_BRANCH.md`
2. Ver instruções: `INSTRUCOES_DEPLOY_E_LIMPEZA.md`
3. Consultar lógica SQL: `CORRECAO_QUERY_SQL_LIMPEZA.md`

### Em Caso de Problema:
1. NÃO PANICAR
2. Se fez backup: restaurar
3. Consultar logs do MySQL
4. Reverter para versão anterior se necessário

---

**Guia criado em:** 07/02/2026  
**Versão:** 1.0  
**Idioma:** 100% Português 🇧🇷  
**Status:** ✅ Pronto para uso

