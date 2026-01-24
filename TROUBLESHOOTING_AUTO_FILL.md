# Guia de Solução de Problemas - Auto-preenchimento de Comissão e Empréstimos

Este guia ajuda a diagnosticar problemas quando os campos de Comissão e EMPRÉSTIMOS não estão sendo preenchidos automaticamente em `/lancamentos-funcionarios/novo`.

## Pré-requisitos

### Para Comissão aparecer:
1. ✅ Rubrica "Comissão" deve existir na tabela `rubricas` com `ativo = 1`
2. ✅ Motoristas devem ter `paga_comissao = 1` na tabela `motoristas`
3. ✅ Fretes devem ter valores em `comissao_motorista` para o mês selecionado

### Para EMPRÉSTIMOS aparecer:
1. ✅ Rubrica "EMPRÉSTIMOS" deve existir na tabela `rubricas` com `ativo = 1`
2. ✅ Empréstimos devem estar cadastrados com status `ATIVO`
3. ✅ Parcelas devem estar criadas para o mês selecionado

## Diagnóstico Passo a Passo

### PASSO 1: Verificar Rubricas

```sql
-- Verificar se as rubricas existem
SELECT id, nome, tipo, ativo, ordem 
FROM rubricas 
WHERE nome IN ('Comissão', 'EMPRÉSTIMOS') 
ORDER BY nome;
```

**Resultado esperado:**
```
id  | nome         | tipo       | ativo | ordem
----|--------------|------------|-------|------
10  | Comissão     | BENEFICIO  | 1     | 10
15  | EMPRÉSTIMOS  | DESCONTO   | 1     | 15
```

**Se não aparecer**, execute:
```sql
-- Criar ou ativar rubrica Comissão
INSERT INTO rubricas (nome, descricao, tipo, percentualouvalorfixo, ativo, ordem) 
VALUES ('Comissão', 'Comissão sobre vendas/fretes', 'BENEFICIO', 'VALOR_FIXO', 1, 10)
ON DUPLICATE KEY UPDATE ativo = 1;

-- Criar ou ativar rubrica EMPRÉSTIMOS  
INSERT INTO rubricas (nome, descricao, tipo, percentualouvalorfixo, ativo, ordem) 
VALUES ('EMPRÉSTIMOS', 'Descontos de empréstimos', 'DESCONTO', 'VALOR_FIXO', 1, 15)
ON DUPLICATE KEY UPDATE ativo = 1;
```

### PASSO 2: Verificar Comissões de Motoristas

```sql
-- Verificar motoristas que pagam comissão
SELECT id, nome, paga_comissao 
FROM motoristas 
WHERE paga_comissao = 1;
```

```sql
-- Verificar comissões por motorista em um mês específico
-- Exemplo: Janeiro/2026
SELECT 
    m.id as motorista_id,
    m.nome as motorista_nome,
    COUNT(f.id) as total_fretes,
    SUM(f.comissao_motorista) as comissao_total,
    f.clientes_id
FROM motoristas m
LEFT JOIN fretes f ON m.id = f.motoristas_id 
    AND f.data_frete >= '2026-01-01' 
    AND f.data_frete <= '2026-01-31'
WHERE m.paga_comissao = 1
GROUP BY m.id, m.nome, f.clientes_id
HAVING comissao_total > 0;
```

**Resultado esperado:**
```
motorista_id | motorista_nome | total_fretes | comissao_total | clientes_id
-------------|----------------|--------------|----------------|-------------
1            | João Silva     | 5            | 500.00         | 1
2            | Maria Santos   | 3            | 350.00         | 1
```

### PASSO 3: Verificar Empréstimos Ativos

```sql
-- Listar empréstimos ativos
SELECT 
    e.id,
    e.funcionario_id,
    f.nome as funcionario_nome,
    e.descricao,
    e.valor_total,
    e.quantidade_parcelas,
    e.mes_inicio_desconto,
    e.status
FROM emprestimos e
INNER JOIN funcionarios f ON e.funcionario_id = f.id
WHERE e.status = 'ATIVO'
ORDER BY e.funcionario_id;
```

```sql
-- Verificar parcelas para um mês específico
-- Exemplo: Fevereiro/2026 (formato: MM-YYYY)
SELECT 
    e.id as emprestimo_id,
    e.funcionario_id,
    f.nome as funcionario_nome,
    e.descricao,
    p.numero_parcela,
    p.mes_referencia,
    p.valor as valor_parcela,
    p.pago,
    e.quantidade_parcelas
FROM emprestimos e
INNER JOIN emprestimos_parcelas p ON e.id = p.emprestimo_id
INNER JOIN funcionarios f ON e.funcionario_id = f.id
WHERE e.status = 'ATIVO'
    AND p.mes_referencia = '02-2026'
ORDER BY e.funcionario_id, p.numero_parcela;
```

**Resultado esperado:**
```
emprestimo_id | funcionario_id | funcionario_nome | descricao  | numero_parcela | mes_referencia | valor_parcela | pago | quantidade_parcelas
--------------|----------------|------------------|------------|----------------|----------------|---------------|------|--------------------
1             | 3              | Pedro Costa      | Compras    | 1              | 02-2026        | 100.00        | 0    | 10
2             | 5              | Ana Lima         | Emergência | 2              | 02-2026        | 50.00         | 0    | 12
```

### PASSO 4: Testar as APIs Manualmente

Abra o navegador e teste diretamente as URLs (substitua pelos IDs reais):

**API de Comissões:**
```
https://nh-transportes.onrender.com/lancamentos-funcionarios/get-comissoes/1/01-2026
```

**Resposta esperada:**
```json
{
  "1": 500.00,
  "2": 350.00
}
```
*(Onde as chaves são motorista_id e valores são comissão total)*

**API de Empréstimos:**
```
https://nh-transportes.onrender.com/emprestimos/get-emprestimos-ativos/3/01-2026
```

**Resposta esperada:**
```json
[
  {
    "id": 1,
    "descricao": "Compras",
    "valor_total": 1000.00,
    "quantidade_parcelas": 10,
    "numero_parcela": 1,
    "valor_parcela": 100.00,
    "pago": 0
  }
]
```

### PASSO 5: Verificar Console do Navegador

1. Acesse `/lancamentos-funcionarios/novo`
2. Pressione F12 para abrir DevTools
3. Vá na aba **Console**
4. Selecione um cliente e um mês
5. Verifique se há erros em vermelho

**Erros comuns:**

```
Failed to fetch loans for funcionario X: ...
```
→ Problema na API de empréstimos

```
Error fetching commissions: ...
```
→ Problema na API de comissões

### PASSO 6: Verificar Network (Rede)

1. No DevTools (F12), vá na aba **Network**
2. Selecione cliente e mês
3. Procure pelas chamadas:
   - `get-comissoes`
   - `get-emprestimos-ativos`
   - `get-funcionarios`

4. Clique em cada chamada e verifique:
   - **Status**: Deve ser 200 (OK)
   - **Response**: Deve retornar dados JSON
   - **Preview**: Visualize os dados retornados

**Se Status for 500:**
→ Erro no servidor. Verifique os logs do Render.

**Se Response estiver vazio `{}`:**
→ Não há dados para aquele cliente/mês. Verifique os dados no banco.

## Soluções Rápidas

### Problema: Coluna Comissão não aparece na tabela

**Solução:**
```sql
UPDATE rubricas SET nome = 'Comissão', ativo = 1 WHERE nome = 'COMISSÃO';
-- OU
INSERT INTO rubricas (nome, descricao, tipo, percentualouvalorfixo, ativo, ordem) 
VALUES ('Comissão', 'Comissão sobre vendas/fretes', 'BENEFICIO', 'VALOR_FIXO', 1, 10)
ON DUPLICATE KEY UPDATE ativo = 1;
```

### Problema: Coluna EMPRÉSTIMOS não aparece na tabela

**Solução:**
```sql
INSERT INTO rubricas (nome, descricao, tipo, percentualouvalorfixo, ativo, ordem) 
VALUES ('EMPRÉSTIMOS', 'Descontos de empréstimos', 'DESCONTO', 'VALOR_FIXO', 1, 15)
ON DUPLICATE KEY UPDATE ativo = 1;
```

### Problema: Comissão aparece mas não preenche automaticamente

**Causas possíveis:**
1. Motorista não tem `paga_comissao = 1`
2. Não há fretes com comissão para aquele mês
3. Cliente ID não corresponde aos fretes

**Solução:**
```sql
-- Ativar pagamento de comissão para um motorista
UPDATE motoristas SET paga_comissao = 1 WHERE id = X;

-- Verificar se há fretes para o cliente/mês
SELECT f.*, m.nome as motorista_nome
FROM fretes f
INNER JOIN motoristas m ON f.motoristas_id = m.id
WHERE f.clientes_id = X
  AND f.data_frete >= '2026-01-01'
  AND f.data_frete <= '2026-01-31'
  AND f.comissao_motorista > 0;
```

### Problema: EMPRÉSTIMOS aparece mas não preenche automaticamente

**Causas possíveis:**
1. Empréstimo não está com status `ATIVO`
2. Não há parcelas criadas para aquele mês
3. Formato do mês está incorreto

**Solução:**
```sql
-- Verificar status do empréstimo
SELECT id, funcionario_id, status, mes_inicio_desconto 
FROM emprestimos 
WHERE funcionario_id = X;

-- Criar parcelas manualmente (se necessário)
-- Veja o script de criação em migrations/20260123_add_emprestimos_table.sql
```

### Problema: Campo está readonly mas deveria ser editável

**Para Comissão:**
- ✅ Motoristas: Campo deve ser readonly (bloqueado)
- ✅ Outros funcionários: Campo deve ser editável

**Para EMPRÉSTIMOS:**
- ✅ Todos: Campo deve ser readonly (bloqueado)
- Valores vêm do sistema de empréstimos

## Formato de Dados

### Formato do mês
- **No formulário**: `MM/YYYY` (ex: `01/2026`)
- **Na URL/API**: `MM-YYYY` (ex: `01-2026`)
- **No banco (emprestimos_parcelas)**: `MM-YYYY` (ex: `01-2026`)

### Formato de valores
- **No banco**: DECIMAL(12,2) (ex: `100.50`)
- **Na API**: Float (ex: `100.5`)
- **No formulário**: String formatada (ex: `"100,50"`)

## Scripts de Migração

Para garantir que tudo está configurado:

```bash
# Execute todas as migrações na ordem
mysql -u usuario -p database < migrations/20260121_create_employee_management_system.sql
mysql -u usuario -p database < migrations/20260123_add_emprestimos_table.sql
mysql -u usuario -p database < migrations/20260124_ensure_comissao_rubrica.sql
```

## Logs do Servidor

Se nada funcionar, verifique os logs no Render:

1. Acesse o dashboard do Render
2. Vá em "Logs"
3. Procure por:
   - `ERROR in get_comissoes`
   - `ERROR in get_emprestimos_ativos`
   - `ERROR in get_funcionarios`

Os logs mostrarão o erro específico que está ocorrendo.

## Suporte

Se após seguir todos os passos o problema persistir, forneça:

1. ✅ Resultado das queries SQL do PASSO 1, 2 e 3
2. ✅ Screenshot da aba Network mostrando as chamadas de API
3. ✅ Screenshot do Console mostrando erros (se houver)
4. ✅ Qual campo específico não está funcionando (Comissão ou EMPRÉSTIMOS)
5. ✅ Logs do servidor do Render

---

**Última atualização:** 24/Jan/2026
