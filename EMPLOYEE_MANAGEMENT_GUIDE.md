# Sistema de Gestão de Funcionários - NH Transportes

## Visão Geral

Este documento descreve o novo módulo de gestão de funcionários e folha de pagamento implementado no sistema NH Transportes.

## Funcionalidades Implementadas

### 1. Cadastro de Funcionários

O sistema permite cadastrar funcionários completos com todos os campos necessários:

- **Campos Principais:**
  - Nome completo
  - Cliente/Empresa (opcional)
  - Categoria (MOTORISTA, FRENTISTA, etc.)
  
- **Documentação:**
  - CPF
  - Telefone
  - E-mail
  
- **Informações Profissionais:**
  - Cargo
  - Data de Admissão
  - Data de Saída
  - Salário Base

**Acesso:** Menu → Funcionários → Novo Funcionário

### 2. Categorias de Funcionários

Permite criar e gerenciar categorias de funcionários customizadas:

- **Categorias Padrão:**
  - MOTORISTA - Motorista de caminhão
  - FRENTISTA - Atendente de posto
  - ADMINISTRATIVO - Pessoal administrativo
  - MECÂNICO - Mecânico de veículos

**Acesso:** Menu → Categorias de Funcionários

### 3. Rubricas (Componentes Salariais)

Sistema de rubricas para composição da folha de pagamento:

- **Rubricas Padrão:**
  1. SALÁRIO BASE - Salário base mensal
  2. VALE ALIMENTAÇÃO - Vale alimentação
  3. FGTS - Fundo de Garantia do Tempo de Serviço
  4. BENEFÍCIO SOCIAL - Benefício social
  5. ODONTO BENEFÍCIO - Plano odontológico
  6. FÉRIAS - Férias
  7. 13º SALÁRIO - 13º salário
  8. RESCISÃO - Rescisão contratual
  9. EMPRÉSTIMOS - Empréstimos e adiantamentos

- **Tipos de Rubrica:**
  - SALARIO - Salário base
  - BENEFICIO - Benefícios diversos
  - DESCONTO - Descontos aplicados
  - IMPOSTO - Impostos e contribuições
  - ADIANTAMENTO - Adiantamentos
  - OUTRO - Outros tipos

- **Forma de Cálculo:**
  - VALOR_FIXO - Valor fixo mensal
  - PERCENTUAL - Percentual sobre base de cálculo

**Acesso:** Menu → Rubricas

### 4. Lançamentos Mensais de Folha de Pagamento

Sistema para realizar lançamentos mensais da folha de pagamento:

**Fluxo de Trabalho:**

1. **Criar Novo Lançamento**
   - Selecionar o mês de referência (formato: JAN/2026)
   - Por padrão, sugere o mês anterior
   - Selecionar o Cliente/Empresa

2. **Preencher Valores**
   - O sistema carrega automaticamente todos os funcionários do cliente
   - Exibe todas as rubricas cadastradas
   - Para cada funcionário, preencher os valores de cada rubrica
   - O salário base é pré-preenchido automaticamente
   - Deixe em branco ou zero para rubricas não aplicáveis

3. **Cálculo Automático**
   - O sistema calcula automaticamente o total líquido
   - Descontos e impostos são subtraídos
   - Benefícios e salários são somados

4. **Visualização**
   - Lista de lançamentos agrupados por mês/cliente
   - Detalhamento por funcionário
   - Visualização das rubricas aplicadas

**Acesso:** Menu → Lançamentos de Funcionários

### 5. Vinculação de Veículos (Motoristas)

Para funcionários da categoria MOTORISTA, é possível vincular veículos:

- Selecionar qual caminhão o motorista dirige
- Definir data de início e fim do vínculo
- Marcar como veículo principal

**Acesso:** Funcionários → Lista → Editar Motorista → Vincular Veículo

## Estrutura do Banco de Dados

### Tabelas Criadas

1. **categorias_funcionarios**
   - Armazena as categorias de funcionários
   - Campos: id, cliente_id, nome, descricao, ativo, criado_em

2. **rubricas**
   - Armazena os componentes salariais
   - Campos: id, nome, descricao, tipo, percentual_ou_valor_fixo, ativo, ordem, criado_em

3. **funcionariocategoria_rubricas**
   - Relaciona categorias com rubricas
   - Campos: id, categoria_id, rubrica_id, valor_ou_percentual, descricao, ativo, criado_em

4. **funcionarios**
   - Armazena os dados completos dos funcionários
   - Campos: id, nome, cliente_id, categoria_id, cpf, telefone, email, cargo, data_admissao, data_saida, salario_base, ativo, criado_em

5. **funcionariomotoristaveiculos**
   - Relaciona motoristas com veículos
   - Campos: id, funcionario_id, veiculo_id, data_inicio, data_fim, principal, ativo, criado_em

6. **lancamentos_funcionarios_v2**
   - Armazena os lançamentos mensais da folha
   - Campos: id, cliente_id, funcionario_id, mes, rubrica_id, valor, percentual, referencia, observacao, caminhao_id, status_lancamento, data_vencimento, data_pagamento, criado_em, atualizado_em

### Alterações em Tabelas Existentes

**motoristas**
- Adicionados campos: email, cargo, data_admissao, data_saida, data_cadastro

## Migração do Banco de Dados

Para aplicar as mudanças no banco de dados, execute o arquivo de migração:

```bash
mysql -u usuario -p database_name < migrations/20260121_create_employee_management_system.sql
```

## Próximos Passos

1. Executar a migração do banco de dados
2. Testar o cadastro de funcionários
3. Configurar as rubricas de acordo com a necessidade da empresa
4. Criar categorias customizadas se necessário
5. Iniciar os lançamentos mensais

## Suporte Técnico

Para questões ou problemas com o sistema, entre em contato com a equipe de desenvolvimento.
