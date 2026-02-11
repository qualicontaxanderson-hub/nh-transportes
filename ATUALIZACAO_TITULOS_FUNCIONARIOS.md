# Atualização dos Títulos da Tabela de Funcionários e Lançamentos

## Resumo

Este documento descreve as alterações realizadas para padronizar os títulos na tabela de "Funcionários e Lançamentos" na página `/lancamentos-funcionarios/novo`.

## Objetivo

Melhorar a padronização e clareza dos títulos das colunas, seguindo as solicitações:
1. Alterar "Comissão" para "Comissão / Aj. Custo"
2. Alterar "EMPRÉSTIMOS" para "Empréstimos" (padronizar capitalização)
3. Alterar "TOTAL" para "Total" (padronizar capitalização)
4. Alterar "TOTAIS:" para "Totais:" (padronizar capitalização)

## Mudanças Implementadas

### 1. Template HTML

**Arquivo:** `templates/lancamentos_funcionarios/novo.html`

#### Cabeçalhos da Tabela

**Linha 81 - Coluna Total:**
```html
<!-- ANTES -->
<th style="min-width: 120px;">TOTAL</th>

<!-- DEPOIS -->
<th style="min-width: 120px;">Total</th>
```

**Linha 413 - Rodapé Totais:**
```html
<!-- ANTES -->
<td colspan="2" class="text-end"><strong>TOTAIS:</strong></td>

<!-- DEPOIS -->
<td colspan="2" class="text-end"><strong>Totais:</strong></td>
```

#### Referências no JavaScript

**Linha 312 - Verificação da Rubrica Comissão:**
```javascript
// ANTES
else if (rubrica.nome === 'Comissão' && isMotorista) {

// DEPOIS
else if (rubrica.nome === 'Comissão / Aj. Custo' && isMotorista) {
```

**Linha 320 - Verificação da Rubrica Empréstimos:**
```javascript
// ANTES
else if (rubrica.nome === 'EMPRÉSTIMOS' && loanData) {

// DEPOIS
else if (rubrica.nome === 'Empréstimos' && loanData) {
```

### 2. Banco de Dados

**Arquivo:** `migrations/20260206_atualizar_nomes_rubricas.sql`

Script SQL criado para atualizar os nomes das rubricas no banco de dados:

```sql
-- Alterar "Comissão" para "Comissão / Aj. Custo"
UPDATE rubricas 
SET nome = 'Comissão / Aj. Custo'
WHERE nome = 'Comissão';

-- Alterar "EMPRÉSTIMOS" para "Empréstimos"
UPDATE rubricas 
SET nome = 'Empréstimos'
WHERE nome = 'EMPRÉSTIMOS';
```

## Tabela de Comparação

| Item | Antes | Depois |
|------|-------|--------|
| Rubrica Comissão | `Comissão` | `Comissão / Aj. Custo` ✅ |
| Rubrica Empréstimos | `EMPRÉSTIMOS` | `Empréstimos` ✅ |
| Coluna Total | `TOTAL` | `Total` ✅ |
| Rodapé Totais | `TOTAIS:` | `Totais:` ✅ |

## Como Aplicar as Mudanças

### Passo 1: Deploy do Código

As mudanças no template HTML já estão no código e serão aplicadas automaticamente no próximo deploy.

### Passo 2: Aplicar Migration SQL

Execute o script SQL para atualizar os nomes das rubricas no banco de dados:

```bash
# Conectar ao banco de dados
mysql -h <host> -u <usuario> -p <nome_banco>

# Executar o script
source migrations/20260206_atualizar_nomes_rubricas.sql
```

**OU via linha de comando:**

```bash
mysql -h <host> -u <usuario> -p <nome_banco> < migrations/20260206_atualizar_nomes_rubricas.sql
```

### Passo 3: Verificar as Mudanças

Após aplicar o script SQL, verificar se as alterações foram aplicadas corretamente:

```sql
SELECT id, nome, descricao, tipo 
FROM rubricas 
WHERE nome IN ('Comissão / Aj. Custo', 'Empréstimos')
ORDER BY nome;
```

**Resultado esperado:**
```
+----+----------------------+--------------------------------+----------+
| id | nome                 | descricao                      | tipo     |
+----+----------------------+--------------------------------+----------+
| 10 | Comissão / Aj. Custo | Comissão sobre vendas/fretes  | BENEFICIO|
| 9  | Empréstimos          | Empréstimos e adiantamentos    | DESCONTO |
+----+----------------------+--------------------------------+----------+
```

## Impacto

### Funcionalidades Afetadas

1. **Página de Novo Lançamento de Funcionários** (`/lancamentos-funcionarios/novo`)
   - Cabeçalhos da tabela
   - Rodapé de totais
   - Preenchimento automático de comissões para motoristas
   - Preenchimento automático de empréstimos

### Compatibilidade

- ✅ **Retrocompatível:** As mudanças não quebram funcionalidades existentes
- ✅ **Lançamentos anteriores:** Não são afetados (as rubricas são identificadas por ID no banco)
- ✅ **Cálculos:** Mantidos inalterados (apenas os nomes de exibição mudaram)

### Benefícios

1. **Padronização:** Uso consistente de maiúsculas e minúsculas
2. **Clareza:** Nome "Comissão / Aj. Custo" mais descritivo
3. **Profissionalismo:** Apresentação mais polida dos dados

## Testes Recomendados

Após aplicar as mudanças, realizar os seguintes testes:

### Teste 1: Verificar Títulos
1. Acessar `/lancamentos-funcionarios/novo`
2. Selecionar um cliente e mês
3. Verificar que os títulos aparecem corretos:
   - ✅ "Total" (não "TOTAL")
   - ✅ "Comissão / Aj. Custo" (não "Comissão")
   - ✅ "Empréstimos" (não "EMPRÉSTIMOS")
   - ✅ "Totais:" (não "TOTAIS:")

### Teste 2: Comissões de Motoristas
1. Selecionar um cliente que tem motoristas
2. Verificar que a coluna "Comissão / Aj. Custo" é preenchida automaticamente
3. Verificar que o campo está readonly (somente leitura)
4. ✅ Funcionalidade mantida

### Teste 3: Empréstimos
1. Selecionar um funcionário que tem empréstimos ativos
2. Verificar que a coluna "Empréstimos" é preenchida automaticamente
3. Verificar que mostra "Parcela: X/Y" abaixo do valor
4. ✅ Funcionalidade mantida

### Teste 4: Cálculo de Totais
1. Preencher valores em diferentes rubricas
2. Verificar que a coluna "Total" calcula corretamente
3. Verificar que a linha "Totais:" no rodapé soma corretamente
4. ✅ Cálculos mantidos

## Rollback (Se Necessário)

Caso seja necessário reverter as mudanças no banco de dados:

```sql
-- Reverter "Comissão / Aj. Custo" para "Comissão"
UPDATE rubricas 
SET nome = 'Comissão'
WHERE nome = 'Comissão / Aj. Custo';

-- Reverter "Empréstimos" para "EMPRÉSTIMOS"
UPDATE rubricas 
SET nome = 'EMPRÉSTIMOS'
WHERE nome = 'Empréstimos';
```

E fazer rollback do código para o commit anterior.

## Conclusão

As alterações foram implementadas com sucesso para padronizar os títulos da tabela de Funcionários e Lançamentos. As mudanças melhoram a apresentação visual e mantêm toda a funcionalidade existente.

---

**Data da Implementação:** 2026-02-06  
**Arquivos Modificados:**
- `templates/lancamentos_funcionarios/novo.html`
- `migrations/20260206_atualizar_nomes_rubricas.sql` (novo)

**Status:** ✅ Pronto para deploy
