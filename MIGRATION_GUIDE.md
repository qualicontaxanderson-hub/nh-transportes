# Melhorias da Página de Quilometragem - Guia de Migração

## Alterações Implementadas

Este PR implementa as seguintes melhorias na página de Quilometragem para corresponder à funcionalidade da página Posto/Vendas:

### 1. Filtro Padrão do Mês Atual ✅
- A página agora filtra automaticamente os dados para mostrar apenas o mês atual por padrão
- Os usuários ainda podem alterar o intervalo de datas usando os filtros

### 2. Seção de Resumo Aprimorada ✅
- Agora mostra um formato de tabela (similar ao posto/vendas) com:
  - **Quantidade de Abastecimentos**: Número de abastecimentos por veículo
  - **Total Litros**: Total de litros abastecidos (com 3 casas decimais)
  - **KMs Rodados**: Total de quilômetros rodados
  - **Valor Total**: Custo total de combustível
  - **Média km/l**: Consumo médio de combustível por veículo
- Apenas veículos que foram realmente abastecidos são mostrados no resumo

### 3. Novo Campo: Valor Produtos Diversos ✅
- Adicionado um novo campo opcional para rastrear despesas com outros produtos (não apenas combustível)
- Pode ser deixado em branco se não for usado
- Aparece tanto no formulário quanto na visualização de lista

### 4. Formatação Automática de Números ✅
- **Valor Combustível & KM Final**: Formata automaticamente com 2 casas decimais
  - Exemplo: digitando `100000` exibe como `1.000,00`
  - Exemplo: digitando `10000` exibe como `100,00`
- **Litros Abastecidos**: Formata automaticamente com 3 casas decimais
  - Exemplo: digitando `10000` exibe como `10,000`
  - Exemplo: digitando `1000` exibe como `1,000`
- **Valor Produtos Diversos**: Mesma formatação que Valor Combustível (2 casas decimais)

## Migração de Banco de Dados Necessária

Antes de implantar esta atualização, você **DEVE** executar a seguinte migração SQL:

```sql
ALTER TABLE quilometragem
ADD COLUMN valor_produtos_diversos DECIMAL(10,2) DEFAULT 0.00
COMMENT 'Valor gasto com produtos diversos (não combustível)';
```

### Como Aplicar a Migração:

#### Opção 1: Usando o arquivo de migração
```bash
mysql -h [HOST] -P [PORT] -u [USER] -p[PASSWORD] [DATABASE] < migrations/20260121_add_produtos_diversos_quilometragem.sql
```

#### Opção 2: Executar diretamente no MySQL
1. Conecte-se ao seu banco de dados MySQL
2. Selecione o banco de dados `railway` (ou o nome do seu banco)
3. Execute o comando ALTER TABLE acima

### Verificação
Após executar a migração, verifique se foi bem-sucedida:
```sql
DESCRIBE quilometragem;
```

Você deverá ver a nova coluna `valor_produtos_diversos` na estrutura da tabela.

## Capturas de Tela

### Demonstração de Formatação de Números (Antes de preencher)
![Demo de Formatação - Inicial](https://github.com/user-attachments/assets/0900f892-d804-4173-8ac2-28da1c80df0a)

### Demonstração de Formatação de Números (Após preencher)
![Demo de Formatação - Preenchida](https://github.com/user-attachments/assets/6a5b872b-503f-4bad-a129-74c3e311ce50)

Como mostrado nas capturas de tela:
- **KM Final**: 100000 → **1.000,00** (2 decimais)
- **Valor Combustível**: 10000 → **100,00** (2 decimais)
- **Litros Abastecidos**: 10000 → **10,000** (3 decimais)
- **Valor Produtos Diversos**: 5000 → **50,00** (2 decimais)

## Arquivos Modificados

1. **routes/quilometragem.py**
   - Adicionado filtro de data padrão para o mês atual
   - Atualizada consulta de resumo para incluir contagem de abastecimentos
   - Alterado LEFT JOIN para INNER JOIN para mostrar apenas veículos com abastecimentos
   - Adicionado tratamento para o campo `valor_produtos_diversos`

2. **templates/quilometragem/lista.html**
   - Melhorada seção de resumo com formato de tabela
   - Adicionada coluna "Produtos Diversos" à tabela principal
   - Estilo aprimorado para corresponder à página posto/vendas

3. **templates/quilometragem/novo.html**
   - Adicionado campo "Valor Produtos Diversos"
   - Implementada formatação automática de números com JavaScript
   - Adicionadas dicas úteis para os usuários sobre a formatação

4. **templates/quilometragem/editar.html**
   - Adicionado campo "Valor Produtos Diversos" para edição

5. **migrations/20260121_add_produtos_diversos_quilometragem.sql**
   - Novo arquivo de migração para adicionar a coluna no banco de dados

## Testes

Todo o código foi validado:
- ✅ Verificação de sintaxe Python aprovada
- ✅ Verificação de sintaxe de template Jinja2 aprovada
- ✅ Verificação de sintaxe JavaScript aprovada
- ✅ Funções de formatação de números testadas e funcionando

## Passos para Implantação

1. **Antes da implantação**: Execute a migração do banco de dados (veja acima)
2. Implante o código atualizado
3. Teste a página para garantir:
   - Filtro de data padrão funciona (mostra mês atual)
   - Seção de resumo exibe corretamente
   - Formatação de números funciona no formulário
   - Novo campo "Produtos Diversos" aparece e é opcional
   - Dados existentes são exibidos corretamente

## Observações

- O campo `valor_produtos_diversos` é **opcional** e pode ser deixado em branco
- Quando deixado em branco, o padrão é 0.00 no banco de dados
- O campo não será mostrado na lista se o valor for 0 ou NULL
- Todos os registros de quilometragem existentes terão este campo definido como 0.00 por padrão
