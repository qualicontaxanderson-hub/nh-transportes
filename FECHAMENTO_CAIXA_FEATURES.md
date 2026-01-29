# Sistema de Fechamento de Caixa - Guia de Funcionalidades Avançadas

## 📋 Visão Geral

O sistema de Fechamento de Caixa foi aprimorado com funcionalidades avançadas que automatizam o processo de fechamento diário, integrando dados de vendas e facilitando o registro de comprovações.

## ✨ Funcionalidades Implementadas

### 1. Seleção de Cliente

**Localização**: Primeiro campo do formulário "Informações Gerais"

**Funcionalidade**:
- Dropdown obrigatório que lista todos os clientes ativos
- Ordenado alfabeticamente por nome fantasia
- Necessário para buscar as vendas do dia

**Como usar**:
1. Acesse **Lançamentos → Fechamento de Caixa → NOVO**
2. Selecione o cliente no primeiro campo
3. As vendas do cliente serão carregadas automaticamente ao selecionar a data

---

### 2. Sugestão Automática de Data

**Funcionalidade**:
- Sistema busca automaticamente o último fechamento de caixa cadastrado
- Preenche o campo "Data" com o dia seguinte
- Facilita o fluxo sequencial de fechamentos diários

**Exemplo**:
- Último fechamento: 02/01/2026
- Data sugerida: 03/01/2026

**Nota**: Você pode alterar a data manualmente se necessário.

---

### 3. Auto-Preenchimento de Receitas

**Funcionalidade**:
Ao selecionar cliente e data, o sistema automaticamente:
1. Busca as vendas do dia nas tabelas correspondentes
2. Calcula os totais
3. Adiciona os itens na seção "Receitas e Entradas"
4. Bloqueia os campos para evitar edição manual

**Fontes de Dados**:

#### 3.1 Vendas do Posto
- **Tabela**: `vendas_posto`
- **Cálculo**: `SUM(valor_total)`
- **Filtros**: `cliente_id = X AND data_movimento = Y`
- **Tipo de Receita**: "Vendas do Posto"

#### 3.2 ARLA
- **Tabela**: `arla_lancamentos`
- **Cálculo**: `SUM(quantidade_vendida * preco_venda_aplicado)`
- **Filtros**: `cliente_id = X AND data = Y`
- **Tipo de Receita**: "ARLA"

#### 3.3 Lubrificantes
- **Tabela**: `lubrificantes_lancamentos` (quando disponível)
- **Cálculo**: `SUM(quantidade * preco_venda)`
- **Filtros**: `cliente_id = X AND data = Y`
- **Tipo de Receita**: "Lubrificantes"

**Identificação Visual**:
- Campos auto-preenchidos têm fundo cinza claro
- São marcados com badge azul "Auto"
- Não podem ser editados manualmente
- São automaticamente incluídos no fechamento

**Receitas Manuais**:
Você ainda pode adicionar receitas manualmente clicando em "Adicionar Receita":
- Troco PIX
- Empréstimos
- Outros

---

### 4. Botão para Adicionar Formas de Pagamento

**Localização**: Ao lado do label "Forma Pagamento" na seção "Comprovação para Fechamento"

**Funcionalidade**:
- Ícone <i class="bi bi-plus-circle-fill"></i> clicável
- Abre `/caixa/novo` em nova aba
- Permite criar novas formas de pagamento sem sair do formulário
- Após criar, basta dar F5 para atualizar a lista

**Como usar**:
1. Na seção "Comprovação para Fechamento", clique em "Adicionar Comprovação"
2. Clique no ícone + ao lado de "Forma Pagamento"
3. Uma nova aba abrirá com o formulário de cadastro
4. Cadastre a nova forma (ex: "PIX Banco X")
5. Volte para a aba do fechamento e atualize (F5)

---

### 5. Filtro Dinâmico de Cartões

**Funcionalidade**:
- O campo "Cartão" aparece **apenas** quando a forma de pagamento selecionada é do tipo cartão
- Economiza espaço na tela
- Evita confusão

**Detecção Automática**:
O sistema identifica formas de pagamento relacionadas a cartões quando o campo `tipo` contém:
- "CARTAO"
- "CART"
- "DEBITO"
- "CREDITO"

**Exemplo**:
- Seleciona "Dinheiro" → Campo Cartão **não aparece**
- Seleciona "Cartão de Crédito" → Campo Cartão **aparece**
- Seleciona "Débito Visa" → Campo Cartão **aparece**

---

## 🗄️ Migração de Banco de Dados

### Arquivo de Migration

**Nome**: `migrations/20260125_add_cliente_id_to_lancamentos_caixa.sql`

**O que faz**:
- Adiciona coluna `cliente_id` INT NULL na tabela `lancamentos_caixa`
- Cria índice para melhorar performance
- Adiciona foreign key para `clientes(id)` com ON DELETE SET NULL

### Como Executar

```bash
mysql -u usuario -p database_name < migrations/20260125_add_cliente_id_to_lancamentos_caixa.sql
```

**Importante**: Esta migration deve ser executada **ANTES** de usar as novas funcionalidades.

### Impacto em Dados Existentes

- Registros antigos terão `cliente_id = NULL`
- Não haverá perda de dados
- Sistema continua funcionando normalmente

---

## 🔧 API Endpoint

### GET /lancamentos_caixa/api/vendas_dia

**Descrição**: Retorna os totais de vendas para um cliente em uma data específica

**Parâmetros**:
- `cliente_id` (integer, obrigatório)
- `data` (date, obrigatório) - formato: YYYY-MM-DD

**Resposta**:
```json
{
  "vendas_posto": 1500.00,
  "arla": 850.50,
  "lubrificantes": 320.00
}
```

**Exemplo de Uso**:
```javascript
fetch(`/lancamentos_caixa/api/vendas_dia?cliente_id=47&data=2026-01-25`)
  .then(response => response.json())
  .then(data => console.log(data));
```

---

## 📖 Fluxo de Trabalho Recomendado

### Passo a Passo para Criar um Fechamento

1. **Acesse o Formulário**
   - Menu: Lançamentos → Fechamento de Caixa
   - Clique em "NOVO"

2. **Selecione o Cliente**
   - Escolha o cliente no dropdown
   - Obrigatório para carregar vendas

3. **Confirme/Ajuste a Data**
   - Data sugerida é automaticamente preenchida
   - Ajuste se necessário

4. **Vendas Carregadas Automaticamente**
   - Sistema busca e preenche:
     * Vendas do Posto
     * ARLA
     * Lubrificantes (se disponível)
   - Valores são somente leitura

5. **Adicione Receitas Manuais** (se houver)
   - Clique em "Adicionar Receita"
   - Selecione o tipo (Troco PIX, Empréstimos, etc.)
   - Informe descrição e valor

6. **Adicione as Comprovações**
   - Clique em "Adicionar Comprovação"
   - Selecione a forma de pagamento
   - Se for cartão, selecione a bandeira
   - Informe o valor

7. **Revise os Totais**
   - Total Receitas: soma de todas as entradas
   - Total Comprovação: soma de todas as comprovações
   - Diferença: deve ser próximo de zero

8. **Salve o Fechamento**
   - Clique em "Salvar Lançamento"
   - Sistema valida e salva todos os dados

---

## ⚠️ Observações Importantes

### Campos Bloqueados

Os seguintes campos são auto-preenchidos e **não podem ser editados**:
- Vendas do Posto (quando há vendas no dia)
- ARLA (quando há vendas no dia)
- Lubrificantes (quando há vendas no dia)

**Motivo**: Garantir integridade dos dados e evitar discrepâncias entre sistemas.

### Atualização Automática

As vendas são carregadas automaticamente nos seguintes casos:
- Ao selecionar o cliente
- Ao alterar a data
- Ao carregar a página (se cliente e data já estiverem preenchidos)

### Performance

O sistema é otimizado com:
- Índices nas tabelas principais
- Queries agregadas (SUM) eficientes
- Cache de dropdown data

---

## 🐛 Troubleshooting

### Vendas não aparecem automaticamente

**Possíveis causas**:
1. Cliente não tem vendas naquela data
2. Migration não foi executada
3. Dados não estão nas tabelas corretas

**Solução**:
- Verifique se há vendas no dia no sistema
- Execute a migration se ainda não executou
- Verifique os logs do navegador (F12 → Console)

### Erro ao salvar

**Possível causa**: Coluna `cliente_id` não existe

**Solução**:
```bash
mysql -u usuario -p database < migrations/20260125_add_cliente_id_to_lancamentos_caixa.sql
```

### Campo Cartão não aparece

**Causa**: Forma de pagamento não tem `tipo` definido ou não contém keywords de cartão

**Solução**:
1. Acesse Cadastros → Formas Pagamento Caixa
2. Edite a forma de pagamento
3. Preencha o campo `tipo` com "CARTAO", "DEBITO" ou "CREDITO"

---

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique esta documentação
2. Consulte `CAIXA_SETUP_GUIDE.md` para configuração inicial
3. Verifique os logs da aplicação
4. Entre em contato com o suporte técnico

---

## 📝 Changelog

### v2.0 - 2026-01-25

**Novidades**:
- ✅ Seleção obrigatória de cliente
- ✅ Sugestão automática de próxima data
- ✅ Auto-preenchimento de vendas do dia
- ✅ Botão para adicionar formas de pagamento
- ✅ Filtro dinâmico de cartões
- ✅ API endpoint para buscar vendas
- ✅ Migration para adicionar cliente_id

**Melhorias**:
- Interface mais intuitiva
- Menos erros de digitação
- Processo mais rápido
- Melhor rastreabilidade por cliente

---

**Última atualização**: 25/01/2026
**Versão**: 2.0
