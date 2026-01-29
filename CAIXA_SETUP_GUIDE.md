# Guia de Configuração - Sistema de Fechamento de Caixa

## 📋 Visão Geral

O sistema de Fechamento de Caixa foi adicionado ao sistema NH Transportes. Este guia explica como configurar e acessar as funcionalidades.

## 🗄️ Configuração do Banco de Dados

### Passo 1: Executar a Migration

**Se você ainda NÃO tem as tabelas criadas**, execute o arquivo de migration SQL no seu banco de dados:

```bash
mysql -u seu_usuario -p seu_banco_de_dados < migrations/20260121_add_caixa_tables.sql
```

**Se você JÁ tem as tabelas criadas mas está com erro "Unknown column 'tipo'"**, execute a migration de compatibilidade:

```bash
mysql -u seu_usuario -p seu_banco_de_dados < migrations/20260125_alter_formas_pagamento_add_tipo.sql
```

Esta migration adiciona a coluna `tipo` à tabela existente sem perder seus dados.

Ou execute manualmente o conteúdo dos arquivos no seu cliente MySQL.

### Tabelas Criadas

A migration criará as seguintes tabelas:

1. **formas_pagamento_caixa** - Formas de pagamento para o caixa
   - Tipos: Depósito Espécie, Depósito Cheque à Vista, Depósito Cheque à Prazo, PIX, Prazo, Cartões, Retiradas para Pagamento

2. **categorias_despesas** - Categorias de despesas

3. **subcategorias_despesas** - Subcategorias de despesas (relacionadas às categorias)

4. **lancamentos_caixa** - Lançamentos de fechamento de caixa

5. **itens_lancamento_caixa** - Itens individuais de cada lançamento

## 🌐 Acessando no Sistema

Após executar a migration, as funcionalidades estarão disponíveis no menu do sistema:

### Menu "Cadastros"
- **Formas Pagamento Caixa**: `/caixa/`
  - Acesse via: Cadastros → Formas Pagamento Caixa
  - Use para cadastrar as formas de pagamento disponíveis no caixa

### Menu "Lançamentos"
- **Fechamento de Caixa**: `/lancamentos_caixa/`
  - Acesse via: Lançamentos → Fechamento de Caixa
  - Use para criar novos fechamentos de caixa diários

## 📝 Passos para Começar a Usar

### 1. Cadastrar Formas de Pagamento

Antes de fazer lançamentos, você precisa cadastrar as formas de pagamento:

1. Acesse: **Cadastros → Formas Pagamento Caixa**
2. Clique em "Nova Forma de Pagamento"
3. Preencha:
   - Nome (ex: "Dinheiro", "PIX Bradesco", etc.)
   - Tipo (selecione o tipo apropriado)
   - Marque como "Ativo"
4. Salve

Exemplos de formas de pagamento que você pode cadastrar:
- Dinheiro em Espécie
- PIX
- Débito
- Crédito
- Cheque à Vista
- Cheque à Prazo
- Transferência Bancária

### 2. Cadastrar Categorias de Despesas (Opcional)

Se você vai registrar despesas no fechamento:

1. As categorias são gerenciadas dentro do sistema de lançamentos
2. Você pode criar categorias como: Combustível, Manutenção, Salários, etc.

### 3. Fazer um Lançamento de Caixa

1. Acesse: **Lançamentos → Fechamento de Caixa**
2. Clique em "Novo Lançamento"
3. Selecione a data
4. Adicione as receitas do dia por forma de pagamento
5. O sistema calculará automaticamente:
   - Total de receitas
   - Total de comprovação
   - Diferença (se houver)
6. Adicione observações se necessário
7. Salve o lançamento

## 🔍 Funcionalidades Disponíveis

### Formas de Pagamento Caixa
- ✅ Listar todas as formas de pagamento
- ✅ Criar nova forma de pagamento
- ✅ Editar forma de pagamento existente
- ✅ Ativar/Desativar forma de pagamento

### Lançamentos de Caixa
- ✅ Listar todos os lançamentos
- ✅ Criar novo lançamento
- ✅ Visualizar detalhes do lançamento
- ✅ Filtrar por data
- ✅ Cálculo automático de totais e diferenças
- ✅ Status: ABERTO ou FECHADO

## 🎨 Ícones no Menu

- **Formas Pagamento Caixa**: 💰 (ícone: bi-cash-coin, cor laranja)
- **Fechamento de Caixa**: 🧮 (ícone: bi-calculator, cor laranja)

## ⚠️ Importante

- Execute a migration SQL **ANTES** de tentar acessar as funcionalidades
- Sem a migration, as páginas retornarão erro de tabela não encontrada
- Certifique-se de ter as permissões adequadas no banco de dados
- Faça backup do banco de dados antes de executar a migration

## 🆘 Solução de Problemas

### Erro: "Unknown column 'tipo' in 'order clause'"
- **Causa**: A tabela `formas_pagamento_caixa` foi criada sem a coluna `tipo`
- **Solução**: Execute a migration de compatibilidade:
  ```bash
  mysql -u seu_usuario -p seu_banco_de_dados < migrations/20260125_alter_formas_pagamento_add_tipo.sql
  ```
  Esta migration adiciona a coluna `tipo` sem perder seus dados existentes.

### Erro: "Table doesn't exist"
- **Causa**: Migration não foi executada
- **Solução**: Execute o arquivo `migrations/20260121_add_caixa_tables.sql`

### Menu não aparece
- **Causa**: Pode ser necessário fazer logout/login novamente
- **Solução**: Limpe o cache do navegador e faça login novamente

### Erro ao salvar lançamento
- **Causa**: Nenhuma forma de pagamento cadastrada
- **Solução**: Cadastre pelo menos uma forma de pagamento primeiro

## 📞 Suporte

Se você tiver problemas, verifique:
1. ✅ Migration foi executada corretamente
2. ✅ Tabelas foram criadas no banco de dados
3. ✅ Usuário tem permissões para acessar as tabelas
4. ✅ Navegador está atualizado (limpe o cache)
