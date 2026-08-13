# 💰 Nova Funcionalidade: Sobras, Perdas e Vales de Caixa por Funcionário

## 📋 Visão Geral

Foi implementado um sistema completo para registrar **sobras**, **perdas** e **vales de caixas** individuais de funcionários no Fechamento de Caixa.

## 🎯 Funcionalidades Adicionadas

### 📥 Lado RECEITAS E ENTRADAS

**Botão: "Sobras de Caixa"**
- Localização: Abaixo dos campos de receitas automáticas
- Cor: Verde (btn-success)
- Função: Registrar quando funcionários têm sobra de dinheiro no caixa
- Ícone: ➕ Plus circle

**Como usar:**
1. Selecione o cliente e data
2. Clique no botão "Sobras de Caixa"
3. Será aberto um modal com todos os funcionários vinculados ao cliente
4. Digite o valor de sobra para cada funcionário que teve sobra
5. Adicione observação se necessário
6. Clique em "Salvar"
7. O total de sobras será automaticamente adicionado às RECEITAS

### 📤 Lado COMPROVAÇÃO PARA FECHAMENTO

**Botão 1: "Perdas de Caixas"**
- Localização: Abaixo dos campos de comprovação
- Cor: Amarelo (btn-warning)
- Função: Registrar pequenas perdas de caixa dos funcionários
- Ícone: ➖ Dash circle

**Botão 2: "Vales de Quebras de Caixas"**
- Localização: Abaixo do botão de Perdas
- Cor: Vermelho (btn-danger)
- Função: Registrar vales de quebras de caixa
- Ícone: 🧾 Receipt

**Como usar:**
1. Selecione o cliente e data
2. Clique no botão desejado ("Perdas" ou "Vales")
3. Será aberto um modal com todos os funcionários vinculados ao cliente
4. Digite o valor para cada funcionário
5. Adicione observação se necessário
6. Clique em "Salvar"
7. O total será automaticamente adicionado às COMPROVAÇÕES

## 🔧 Detalhes Técnicos

### Banco de Dados

**Três novas tabelas criadas:**

1. **lancamentos_caixa_sobras_funcionarios**
   - Vincula sobras ao lançamento e funcionário
   - Campos: lancamento_caixa_id, funcionario_id, valor, observacao

2. **lancamentos_caixa_perdas_funcionarios**
   - Vincula perdas ao lançamento e funcionário
   - Campos: lancamento_caixa_id, funcionario_id, valor, observacao

3. **lancamentos_caixa_vales_funcionarios**
   - Vincula vales ao lançamento e funcionário
   - Campos: lancamento_caixa_id, funcionario_id, valor, observacao

### API Endpoint

**GET /lancamentos_caixa/api/funcionarios/<cliente_id>**
- Retorna lista de funcionários ativos vinculados ao cliente
- Usado para popular o modal

**Resposta:**
```json
[
  {
    "id": 1,
    "nome": "João Silva",
    "cargo": "Frentista",
    "cpf": "123.456.789-00"
  },
  ...
]
```

### Fluxo de Cálculo

**Total Receitas:**
```
Total Receitas = 
  Receitas Normais (Vendas, ARLA, etc.) 
  + Sobras de Funcionários
```

**Total Comprovações:**
```
Total Comprovações = 
  Comprovações Normais (PIX, Cartões, etc.) 
  + Perdas de Funcionários
  + Vales de Funcionários
```

**Diferença:**
```
Diferença = Total Comprovações - Total Receitas
```

## 📊 Modal de Funcionários

### Estrutura

- **Título dinâmico** baseado no tipo (Sobras/Perdas/Vales)
- **Tabela com 3 colunas:**
  1. Nome do funcionário (+ cargo se disponível)
  2. Campo de valor (com formatação automática)
  3. Campo de observação (opcional)
- **Total calculado automaticamente** à medida que digita
- **Botões:**
  - Cancelar: Fecha sem salvar
  - Salvar: Salva dados e fecha

### Validações

- ✅ Requer cliente selecionado antes de abrir
- ✅ Só salva funcionários com valor > 0
- ✅ Formatação automática de moeda (1000 → 1.000,00)
- ✅ Mostra mensagem se não há funcionários vinculados

## 🎨 Interface do Usuário

### Resumos Visuais

Abaixo de cada botão, após salvar dados, aparece um resumo:

**Sobras:**
```
Total Sobras: R$ 1.500,00
```

**Perdas:**
```
Total Perdas: R$ 250,00
```

**Vales:**
```
Total Vales: R$ 800,00
```

### Cores dos Botões

- 🟢 **Verde** (Sobras) - Representa entrada/ganho
- 🟡 **Amarelo** (Perdas) - Representa atenção/perda pequena
- 🔴 **Vermelho** (Vales) - Representa saída/débito maior

## 📝 Exemplo de Uso Prático

### Cenário: Fechamento de Caixa do Posto

**Situação:**
- Posto: NH Goiatuba
- Data: 03/02/2026
- 3 Frentistas trabalharam no dia

**Sobras de Caixa:**
- João Silva: R$ 50,00 (sobrou dinheiro)
- Maria Santos: R$ 30,00 (sobrou dinheiro)
- Pedro Costa: R$ 0,00 (caixa bateu certinho)

**Perdas de Caixa:**
- João Silva: R$ 0,00
- Maria Santos: R$ 10,00 (perda pequena)
- Pedro Costa: R$ 5,00 (perda pequena)

**Vales de Quebras:**
- João Silva: R$ 100,00 (vale por quebra de produto)
- Maria Santos: R$ 0,00
- Pedro Costa: R$ 0,00

**Resultado no Fechamento:**
```
RECEITAS:
  Vendas Posto: R$ 10.000,00
  + Sobras: R$ 80,00
  = Total Receitas: R$ 10.080,00

COMPROVAÇÕES:
  PIX: R$ 5.000,00
  Cartões: R$ 5.000,00
  + Perdas: R$ 15,00
  + Vales: R$ 100,00
  = Total Comprovações: R$ 10.115,00

DIFERENÇA: R$ 35,00 (a favor do posto)
```

## ✅ Migration SQL Necessária

Antes de usar, execute a migration:

```bash
mysql -u usuario -p banco < migrations/20260203_add_sobras_perdas_vales_funcionarios.sql
```

Ou via Railway console se estiver em produção.

## 🔍 Verificação

Para verificar se está funcionando:

1. **Verifique as tabelas:**
```sql
SHOW TABLES LIKE '%funcionarios';
```

Deve mostrar:
- lancamentos_caixa_sobras_funcionarios
- lancamentos_caixa_perdas_funcionarios
- lancamentos_caixa_vales_funcionarios

2. **Teste o endpoint:**
```
https://app.postonovohorizonte.com.br/lancamentos_caixa/api/funcionarios/1
```

Deve retornar JSON com funcionários.

3. **Teste no formulário:**
- Acesse /lancamentos_caixa/novo
- Selecione um cliente
- Clique nos botões de Sobras/Perdas/Vales
- Verifique se modal abre com funcionários

## 📌 Observações Importantes

1. **Funcionários devem estar vinculados ao cliente**
   - No cadastro de funcionário, o campo `clienteid` deve estar preenchido
   - Funcionários sem cliente vinculado não aparecerão

2. **Valores são salvos apenas se > 0**
   - Não é necessário preencher todos os funcionários
   - Só digite valor para quem realmente teve sobra/perda/vale

3. **Os dados são salvos junto com o lançamento**
   - Ao salvar o fechamento, todos os dados de funcionários são salvos
   - Relacionamento via foreign key garante integridade

4. **Valores somam automaticamente**
   - Não é necessário adicionar manualmente aos totais
   - O sistema calcula tudo automaticamente

## 🚀 Próximas Melhorias (Opcional)

- [ ] Suporte para edição de lançamentos existentes
- [ ] Relatório de sobras/perdas/vales por funcionário
- [ ] Histórico de sobras/perdas por período
- [ ] Dashboard com estatísticas
- [ ] Alertas para perdas frequentes

---

**Data de Implementação:** 03/02/2026  
**Status:** ✅ Implementado e Funcional  
**Branch:** copilot/fix-troco-pix-auto-error  
**Commits:** c082439 (backend), fd14e3e (frontend)
