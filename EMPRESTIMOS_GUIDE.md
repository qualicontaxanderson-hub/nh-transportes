# Guia de Uso: Sistema de Empréstimos

## Visão Geral

O sistema de empréstimos permite gerenciar empréstimos concedidos a funcionários, com controle automático de parcelas e integração com os lançamentos mensais.

## Como Funciona

### 1. Cadastrar um Novo Empréstimo

**Navegação:** Menu Lançamentos → Empréstimos → Novo Empréstimo

**Campos obrigatórios:**
- **Funcionário**: Selecione o funcionário que receberá o empréstimo
- **Cliente/Empresa**: Será preenchido automaticamente ao selecionar o funcionário
- **Data do Empréstimo**: Data em que o empréstimo foi concedido
- **Mês Início Desconto**: Mês em que começarão os descontos (formato: MM/AAAA)
  - Exemplo: 01/2026 para começar em Janeiro de 2026
- **Quantidade de Parcelas**: Número total de parcelas (1-60)
- **Valor Total**: Valor total do empréstimo
  - O sistema calculará automaticamente o valor de cada parcela

**Campos opcionais:**
- **Descrição**: Observações ou motivo do empréstimo

**Exemplo:**
```
Funcionário: João Silva
Data do Empréstimo: 16/12/2025
Mês Início Desconto: 01/2026
Valor Total: R$ 1.000,00
Quantidade de Parcelas: 10
Descrição: Empréstimo para despesas médicas

→ Valor da Parcela (calculado): R$ 100,00
```

### 2. Como os Descontos Funcionam

O sistema gera automaticamente as parcelas do empréstimo:

**Janeiro/2026**: Parcela 1/10 = R$ 100,00  
**Fevereiro/2026**: Parcela 2/10 = R$ 100,00  
**Março/2026**: Parcela 3/10 = R$ 100,00  
...  
**Outubro/2026**: Parcela 10/10 = R$ 100,00

### 3. Integração com Lançamentos de Funcionários

Quando você criar um novo lançamento mensal:

1. Acesse: **Lançamentos → Lançamentos Funcionários → Novo Lançamento**
2. Selecione o **Cliente** e o **Mês/Ano** de referência
3. O sistema automaticamente:
   - Carrega todos os funcionários
   - **Busca empréstimos ativos** para cada funcionário no mês selecionado
   - **Preenche automaticamente** a coluna "EMPRÉSTIMOS" com:
     - Valor da parcela do mês
     - Indicador de progresso (ex: "Parcela: 1/10")

**Exemplo visual no formulário:**
```
Nome            | Categoria  | Salário Base | EMPRÉSTIMOS    | ...
João Silva      | FRENTISTA  | 2.500,00     | 100,00         | ...
                                             Parcela: 1/10
```

### 4. Gerenciar Empréstimos Existentes

**Listar Empréstimos:**
- Menu: Lançamentos → Empréstimos
- Filtros disponíveis:
  - Status (Ativo, Quitado, Cancelado)
  - Funcionário

**Editar Empréstimo:**
- Clique no botão de editar (ícone de lápis)
- Você pode alterar:
  - **Status**: Ativo, Quitado, Cancelado
  - **Descrição**
- Visualize todas as parcelas com status de pagamento

**Excluir Empréstimo:**
- Só é possível excluir empréstimos sem parcelas pagas
- Para empréstimos com parcelas pagas, altere o status para "CANCELADO"

### 5. Status dos Empréstimos

- **ATIVO**: Empréstimo em andamento com parcelas pendentes
- **QUITADO**: Todas as parcelas foram pagas
- **CANCELADO**: Empréstimo foi cancelado

### 6. Múltiplos Empréstimos

Um funcionário pode ter múltiplos empréstimos ativos simultaneamente. Neste caso:
- O sistema soma todos os valores das parcelas do mês
- Exibe todos os empréstimos ativos: "Parcela: 1/10, 3/12"

**Exemplo:**
```
Empréstimo 1: R$ 1.000,00 em 10x (Janeiro a Outubro/2026)
Empréstimo 2: R$ 600,00 em 12x (Março/2026 a Fevereiro/2027)

Em Março/2026:
- Parcela Empréstimo 1: R$ 100,00 (3/10)
- Parcela Empréstimo 2: R$ 50,00 (1/12)
- Total descontado: R$ 150,00
- Exibido: "Parcela: 3/10, 1/12"
```

## Perguntas Frequentes

**Q: O que acontece se eu deletar um empréstimo?**
R: Só é possível deletar empréstimos sem parcelas pagas. Empréstimos com parcelas já pagas devem ser marcados como "CANCELADO".

**Q: Posso alterar o valor de uma parcela específica?**
R: Não. As parcelas são calculadas automaticamente dividindo o valor total pela quantidade de parcelas. Para ajustes, cancele o empréstimo atual e crie um novo.

**Q: O desconto é automático?**
R: O sistema preenche automaticamente o valor no formulário de lançamentos, mas o usuário ainda precisa salvar o lançamento mensal. O sistema não faz descontos automáticos sem intervenção do usuário.

**Q: Como sei quais parcelas foram pagas?**
R: Na tela de edição do empréstimo, você pode ver todas as parcelas com seus status (Pago/Pendente) e datas de pagamento.

## Banco de Dados

### Tabelas Criadas

**emprestimos:**
- Armazena informações principais do empréstimo
- Relacionado com funcionários e clientes

**emprestimos_parcelas:**
- Armazena cada parcela individualmente
- Permite rastreamento detalhado de pagamentos

### Migração

Execute o script SQL localizado em:
```
migrations/20260123_add_emprestimos_table.sql
```

Este script cria as tabelas necessárias com todos os índices e foreign keys.

## Suporte Técnico

Para problemas ou dúvidas adicionais, consulte os logs da aplicação ou entre em contato com o suporte técnico.
