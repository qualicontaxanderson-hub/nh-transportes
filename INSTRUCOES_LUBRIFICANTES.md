# INSTRUÇÕES PARA IMPLEMENTAÇÃO DA FUNCIONALIDADE LUBRIFICANTES

## VISÃO GERAL
Este documento contém todas as instruções necessárias para implementar a funcionalidade de controle de **LUBRIFICANTES** no sistema NH Transportes. A funcionalidade é similar ao módulo ARLA já existente.

## 1. BANCO DE DADOS

### 1.1. Executar a Migration SQL
Execute o arquivo de migration localizado em:
```
migrations/20260121_add_lubrificantes_tables.sql
```

Este arquivo cria as seguintes tabelas:

#### Tabela: `lubrificantes_produtos`
Armazena o cadastro de produtos de lubrificantes.
- **id**: Identificador único (auto increment)
- **nome**: Nome do produto (VARCHAR 200)
- **descricao**: Descrição opcional (TEXT)
- **unidade_medida**: Unidade de medida (L=litros, KG=quilos, UN=unidade)
- **ativo**: Status do produto (1=ativo, 0=inativo)
- **criado_em**: Data de criação

#### Tabela: `lubrificantes_saldo_inicial`
Armazena o estoque inicial por cliente e produto.
- **id**: Identificador único
- **data**: Data do saldo inicial
- **produto_id**: Referência ao produto
- **cliente_id**: Referência ao cliente (Config Posto)
- **volume_inicial**: Volume/quantidade inicial em estoque
- **preco_medio_compra**: Preço médio de compra
- **encerrante_inicial**: Encerrante inicial (opcional)
- **criado_em**: Data de criação

#### Tabela: `lubrificantes_compras`
Registra as compras de lubrificantes.
- **id**: Identificador único
- **data**: Data da compra
- **produto_id**: Referência ao produto
- **cliente_id**: Referência ao cliente
- **quantidade**: Quantidade comprada
- **preco_compra**: Preço unitário de compra
- **fornecedor**: Nome do fornecedor (opcional)
- **nota_fiscal**: Número da nota fiscal (opcional)
- **observacao**: Observações (opcional)
- **criado_em**: Data de criação

#### Tabela: `lubrificantes_precos_venda`
Histórico de preços de venda.
- **id**: Identificador único
- **data_inicio**: Data de início da vigência
- **produto_id**: Referência ao produto
- **cliente_id**: Referência ao cliente
- **preco_venda**: Preço de venda unitário
- **data_fim**: Data fim da vigência (NULL = vigente)
- **criado_em**: Data de criação

#### Tabela: `lubrificantes_lancamentos`
Lançamentos diários de vendas.
- **id**: Identificador único
- **data**: Data da venda
- **produto_id**: Referência ao produto
- **cliente_id**: Referência ao cliente
- **quantidade_vendida**: Quantidade vendida
- **preco_venda_aplicado**: Preço de venda no momento
- **encerrante_final**: Encerrante final (opcional)
- **observacao**: Observações (opcional)
- **criado_em**: Data de criação
- **UNIQUE KEY**: (data, produto_id, cliente_id) - Garante um lançamento por dia/produto/cliente

### 1.2. Produto Padrão
A migration já cria automaticamente um produto chamado **"PRODUTOS"** que serve como produto genérico inicial. No futuro, você pode cadastrar produtos mais específicos como:
- ÓLEO MOTOR 15W40
- ÓLEO HIDRÁULICO
- GRAXA
- etc.

## 2. ESTRUTURA DE CÓDIGO CRIADA

### 2.1. Blueprint Flask
Arquivo: `routes/lubrificantes.py`
- Contém todas as rotas para gerenciar a funcionalidade
- Similar ao blueprint `arla.py`

### 2.2. Templates HTML
Diretório: `templates/lubrificantes/`
Arquivos criados:
- `index.html` - Página principal com resumo e movimentações
- `produtos.html` - Lista de produtos cadastrados
- `novo_produto.html` - Formulário para novo produto
- `editar_produto.html` - Formulário para editar produto
- `saldo_inicial.html` - Cadastro de estoque inicial
- `compras.html` - Registro de compras
- `preco_venda.html` - Definição de preços
- `lancamento.html` - Lançamentos diários de vendas

### 2.3. Navegação Atualizada
O menu foi atualizado com:
- **Menu "Cadastros"**: Link para "Lubrificantes" (cadastro de produtos)
- **Menu "Lançamentos"**: Link para "Lubrificantes" (lançamentos e movimentações)

## 3. FUNCIONALIDADES IMPLEMENTADAS

### 3.1. Cadastro de Produtos
- Acesse: **Cadastros → Lubrificantes**
- Cadastre produtos de lubrificantes (nome, descrição, unidade de medida)
- Produto padrão "PRODUTOS" já está cadastrado
- Preparado para futuro cadastro de produtos específicos com valores

### 3.2. Saldo Inicial
- Acesse: **Lançamentos → Lubrificantes → Saldo Inicial**
- Cadastre o estoque inicial por cliente e produto
- Campos: data, volume inicial, preço médio, encerrante inicial (opcional)

### 3.3. Compras
- Acesse: **Lançamentos → Lubrificantes → Nova Compra**
- Registre compras de lubrificantes
- Campos: data, cliente, produto, quantidade, preço, fornecedor, nota fiscal

### 3.4. Preços de Venda
- Acesse: **Lançamentos → Lubrificantes → Alterar Preço**
- Defina ou altere preços de venda por produto e cliente
- Mantém histórico de preços com datas de vigência

### 3.5. Lançamentos de Vendas
- Acesse: **Lançamentos → Lubrificantes → Novo Lançamento**
- Registre vendas diárias de lubrificantes
- Sistema aplica automaticamente o preço vigente
- Campos: data, cliente, produto, quantidade vendida, encerrante (opcional)

### 3.6. Painel Principal
- Acesse: **Lançamentos → Lubrificantes**
- Visualize:
  - Saldo inicial cadastrado
  - Preço de venda atual
  - Estoque atual (calculado: saldo inicial + compras - vendas)
  - Filtros por período (mensal padrão), cliente e produto
  - Total de compras e vendas do período
  - Tabela de movimentações (compras e vendas)
- **Filtro de Cliente**: Mostra apenas clientes configurados no Config Posto (mesma lógica do ARLA)

## 4. FLUXO DE USO RECOMENDADO

### Primeiro Uso:
1. **Cadastrar Produtos** (opcional, pois já existe "PRODUTOS" padrão)
   - Menu: Cadastros → Lubrificantes
   - Cadastre produtos específicos se necessário

2. **Configurar Clientes no Posto** (se ainda não configurado)
   - Menu: Lançamentos → Config. Produtos Posto
   - Ative os clientes que irão trabalhar com lubrificantes

3. **Cadastrar Saldo Inicial**
   - Menu: Lançamentos → Lubrificantes → Saldo Inicial
   - Defina o estoque inicial para cada cliente/produto

4. **Definir Preço de Venda**
   - Menu: Lançamentos → Lubrificantes → Alterar Preço
   - Configure o preço de venda para cada produto/cliente

### Uso Diário:
5. **Registrar Compras** (quando houver)
   - Menu: Lançamentos → Lubrificantes → Nova Compra

6. **Registrar Vendas**
   - Menu: Lançamentos → Lubrificantes → Novo Lançamento
   - Faça lançamentos diários de vendas

7. **Acompanhar Movimentações**
   - Menu: Lançamentos → Lubrificantes
   - Visualize estoque atual, compras, vendas e histórico

## 5. CARACTERÍSTICAS IMPORTANTES

### Filtros:
- **Período**: Por padrão, mostra o mês atual. Pode ser alterado.
- **Cliente**: Filtra apenas clientes configurados no Config Posto.
- **Produto**: Filtra por produto específico.

### Cálculo de Estoque:
```
Estoque Atual = Saldo Inicial + Total de Compras - Total de Vendas
```

### Controles:
- Um lançamento por dia/cliente/produto (constraint no banco)
- Preços aplicados automaticamente com base na data vigente
- Suporte a múltiplos produtos de lubrificantes
- Suporte a múltiplos clientes

### Relatórios:
- Total de quantidade e valor de compras no período
- Total de quantidade e valor de vendas no período
- Tabela unificada de movimentações

## 6. PREPARAÇÃO PARA O FUTURO

O sistema está preparado para:
- **Cadastrar produtos específicos** além do "PRODUTOS" genérico
- **Definir preços de venda por produto** de forma individualizada
- **Controlar estoque separado por produto** e cliente
- **Manter histórico completo** de preços, compras e vendas
- **Expandir funcionalidades** similares ao módulo ARLA

## 7. OBSERVAÇÕES TÉCNICAS

### Banco de Dados:
- Todas as tabelas utilizam `InnoDB` com charset `utf8mb4`
- Foreign keys com `ON DELETE RESTRICT` para segurança
- Índices em campos de busca e filtro
- Decimal(10,2) para valores monetários e quantidades

### Compatibilidade:
- Interface similar ao módulo ARLA
- Mesma lógica de filtro de clientes (Config Posto)
- Padrões de código consistentes com o resto do sistema

### Blueprint:
- Auto-registro via `routes/__init__.py`
- Conexão direta ao banco (mesmo padrão do ARLA)
- Tratamento de erros e mensagens flash

## 8. TROUBLESHOOTING

### Problema: Menu não aparece
- Verifique se o arquivo `routes/lubrificantes.py` existe
- Reinicie o servidor Flask
- Verifique logs de erro no console

### Problema: Erro ao acessar páginas
- Execute a migration SQL no banco de dados
- Verifique permissões de usuário no banco
- Confira se todas as tabelas foram criadas

### Problema: Clientes não aparecem nos filtros
- Verifique se os clientes estão cadastrados
- Verifique se os clientes têm produtos ativos no Config Posto
- Tabela: `cliente_produtos` deve ter registros com `ativo = 1`

## 9. CONTATO E SUPORTE

Para dúvidas ou problemas com a implementação, consulte:
- Documentação do módulo ARLA (similar)
- Logs do sistema Flask
- Estrutura de banco de dados

---

**Data da Criação**: 21/01/2026  
**Versão**: 1.0  
**Desenvolvido para**: NH Transportes - Sistema de Gestão
