# Guia: Limpeza de Dados de Comissões

## Problema

Comissões foram salvas incorretamente no banco de dados para funcionários que não são motoristas (frentistas).

**Sintomas:**
- João, Roberta e outros frentistas aparecem com comissões na página detalhe
- Marcos e Valmir (motoristas) podem não aparecer se não tiverem lançamentos salvos

## Causa Raiz

Comissões foram salvas no banco antes das validações corretas serem implementadas. O código atual já filtra corretamente, mas os dados ruins no banco ainda aparecem.

## Soluções

### Opção 1: Script SQL (Recomendado para DBA)

Execute o script de migration:

```bash
mysql -h <host> -u <user> -p <database> < migrations/20260207_limpar_comissoes_frentistas.sql
```

**Vantagens:**
- Execução direta no banco
- Permite verificação antes de deletar
- Mostra exatamente quais registros serão afetados

**Queries do Script:**

1. **Verificar quantos serão deletados:**
```sql
SELECT COUNT(*) as total_a_deletar
FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid NOT IN (SELECT id FROM motoristas);
```

2. **Ver funcionários afetados:**
```sql
SELECT 
    l.funcionarioid,
    f.nome as funcionario_nome,
    r.nome as rubrica_nome,
    l.valor,
    l.mes
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN rubricas r ON l.rubricaid = r.id
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND l.funcionarioid NOT IN (SELECT id FROM motoristas);
```

3. **Executar limpeza:**
```sql
DELETE FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
AND funcionarioid NOT IN (SELECT id FROM motoristas);
```

### Opção 2: Rota Administrativa (Recomendado para Devs)

Use a rota administrativa via API:

**Endpoint:** `POST /lancamentos-funcionarios/admin/limpar-comissoes-frentistas`

**Autenticação:** Requer login como admin

**Como usar:**

1. **Via navegador (DevTools Console):**
```javascript
fetch('/lancamentos-funcionarios/admin/limpar-comissoes-frentistas', {
  method: 'POST',
  credentials: 'include'
})
.then(r => r.json())
.then(data => console.log(data));
```

2. **Via curl:**
```bash
curl -X POST https://nh-transportes.onrender.com/lancamentos-funcionarios/admin/limpar-comissoes-frentistas \
  -H "Cookie: session=YOUR_SESSION_COOKIE" \
  -H "Content-Type: application/json"
```

**Resposta de Sucesso:**
```json
{
  "success": true,
  "message": "Limpeza concluída com sucesso!",
  "registros_esperados": 3,
  "registros_deletados": 3
}
```

**Resposta de Erro:**
```json
{
  "success": false,
  "error": "descrição do erro"
}
```

## Validação Pós-Limpeza

Após executar a limpeza, valide os resultados:

### 1. Verificar Total de Comissões

```sql
SELECT COUNT(*) as total_comissoes
FROM lancamentosfuncionarios_v2
WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'));
```

### 2. Listar Funcionários com Comissões

**Deveriam aparecer apenas motoristas:**

```sql
SELECT DISTINCT
    COALESCE(f.nome, m.nome) as funcionario_nome,
    CASE 
        WHEN m.id IS NOT NULL THEN 'Motorista'
        ELSE 'Funcionário'
    END as tipo
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
WHERE l.rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
ORDER BY tipo, funcionario_nome;
```

### 3. Acessar Página Detalhe

Acesse: `https://nh-transportes.onrender.com/lancamentos-funcionarios/detalhe/01-2026/1`

**Verificar:**
- ✅ Marcos e Valmir (motoristas) aparecem com comissões
- ✅ João, Roberta (frentistas) NÃO têm comissões

## Prevenção Futura

O código atual já tem as seguintes proteções:

### 1. Filtro na Página Detalhe (linhas 358-359)

```python
if is_comissao and func_id not in motoristas:
    continue  # Skip commission for non-motorista
```

### 2. Filtro na Página Editar (templates)

Comissões só são pré-preenchidas se:
```javascript
if ((rubrica.nome === 'Comissão' || rubrica.nome === 'Comissão / Aj. Custo') && isMotorista)
```

### 3. API de Comissões

Endpoint `/get-comissoes/<cliente_id>/<mes>` retorna comissões apenas para motoristas.

## Troubleshooting

### Problema: "Motoristas ainda não aparecem"

**Causa:** Motoristas não têm lançamentos salvos no banco.

**Solução:** O código já adiciona comissões via API automaticamente. Verifique:
1. API `/get-comissoes/` está funcionando?
2. Endpoint correto está sendo chamado? (deve ser `get_comissoes`, não `get_comissoes_motoristas`)

### Problema: "Comissões ainda aparecem para frentistas"

**Causa 1:** Código antigo ainda deployado.
**Solução:** Fazer deploy da branch `copilot/fix-merge-issue-39`

**Causa 2:** Dados não foram limpos.
**Solução:** Executar uma das opções de limpeza acima.

**Causa 3:** IDs não correspondem.
**Solução:** Verificar que IDs em `motoristas` correspondem aos IDs em `lancamentosfuncionarios_v2`.

### Problema: "Erro 401 ao chamar rota administrativa"

**Causa:** Não está autenticado como admin.

**Solução:** 
1. Fazer login como admin
2. Obter cookie de sessão
3. Incluir no header da requisição

## Segurança

- ✅ Rota administrativa requer `@login_required`
- ✅ Rota administrativa requer `@admin_required`
- ✅ Script SQL tem queries de verificação antes de deletar
- ✅ Operação é reversível (se houver backup)

## Histórico

- **2026-02-07:** Criação do script e rota administrativa
- **2026-02-07:** Múltiplas tentativas de correção do bug
- **2026-02-02:** Identificação inicial do problema

## Referências

- `migrations/20260207_limpar_comissoes_frentistas.sql`
- `routes/lancamentos_funcionarios.py` (linhas 537-584)
- Documentação das correções anteriores na branch
