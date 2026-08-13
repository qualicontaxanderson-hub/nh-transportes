# 🔍 Depuração: TROCO PIX (AUTO) - Logs Detalhados

## 📊 Situação Atual

Baseado nos logs do console F12 fornecidos:

```
Dados recebidos do get_vendas_dia: Object
Verificando receita: tipoNome="TROCO PIX (AUTO)", readonly=true
Atualizando TROCO PIX: tipoNome="TROCO PIX (AUTO)", valor=1000
```

**O sistema está:**
- ✅ Recebendo dados da API
- ✅ Identificando o campo "TROCO PIX (AUTO)" corretamente
- ✅ Tentando atualizar com valor=1000
- ✅ Mostrando R$ 1.000,00 no formulário

## 🔧 Novos Logs Adicionados

Para ajudar a identificar exatamente o que está acontecendo, adicionei logs mais detalhados. Após atualizar a página, você verá:

### 1. Dados Completos da API
```javascript
Dados recebidos do get_vendas_dia: {vendas_posto: ..., arla: ..., troco_pix: ...}
Valor específico de troco_pix: 1000
Cheques AUTO: [{tipo: 'A_VISTA', valor: 2000, ...}]
```

### 2. Processo de Atualização do Campo
```javascript
Atualizando TROCO PIX: tipoNome="TROCO PIX (AUTO)", valor=1000
Valor formatado: R$ 1.000,00
Valor atribuído ao input: R$ 1.000,00
```

## 📋 Como Coletar Informações Detalhadas

### Passo 1: Limpar Console
1. Abra o DevTools (F12)
2. Vá para a aba **Console**
3. Clique no ícone 🚫 para limpar o console

### Passo 2: Recarregar a Página
1. Pressione F5 ou Ctrl+R para recarregar
2. Ou clique em "Novo Lançamento" novamente

### Passo 3: Selecionar Cliente e Data
1. Selecione: **POSTO NOVO HORIZONTE GOIATUBA LTDA**
2. Selecione Data: **02/01/2026**
3. Aguarde o carregamento automático

### Passo 4: Copiar TODOS os Logs
Copie TODA a saída do console, incluindo:
- `Dados recebidos do get_vendas_dia:`
- `Valor específico de troco_pix:`
- `Cheques AUTO:`
- Todos os logs de "Verificando receita"
- Todos os logs de "Atualizando TROCO PIX"

## 🎯 O Que Estamos Procurando

### Cenário 1: Valor Correto na API mas Não Aparece
Se você ver:
```
Valor específico de troco_pix: 1000
Valor formatado: R$ 1.000,00
Valor atribuído ao input: R$ 1.000,00
```
**Mas o campo mostra R$ 0,00** → Problema com a atualização do DOM

### Cenário 2: API Retorna 0 ou null
Se você ver:
```
Valor específico de troco_pix: 0
```
ou
```
Valor específico de troco_pix: null
```
**→ Problema no backend (routes/lancamentos_caixa.py)**

### Cenário 3: API Não Retorna Campo troco_pix
Se `troco_pix` não aparecer no objeto:
```
Dados recebidos: {vendas_posto: 44294.17, arla: 114.52, lubrificantes: 0}
Valor específico de troco_pix: undefined
```
**→ Problema na query SQL do backend**

## 🔍 Verificações Adicionais

### Verificar se Existem Dados no Banco
Execute no banco de dados:

```sql
-- Verificar se há registros de troco_pix para esta data e cliente
SELECT 
    id, 
    cliente_id, 
    data, 
    troco_pix, 
    cheque_valor,
    cheque_tipo
FROM troco_pix 
WHERE cliente_id = (SELECT id FROM clientes WHERE razao_social = 'POSTO NOVO HORIZONTE GOIATUBA LTDA')
  AND data = '2026-01-02'
ORDER BY id DESC;
```

**Resultado esperado:**
```
+----+------------+------------+-----------+--------------+-------------+
| id | cliente_id | data       | troco_pix | cheque_valor | cheque_tipo |
+----+------------+------------+-----------+--------------+-------------+
| 14 | XX         | 2026-01-02 | 1000.00   | 2000.00      | A_VISTA     |
+----+------------+------------+-----------+--------------+-------------+
```

### Testar API Diretamente
No navegador, abra:
```
https://app.postonovohorizonte.com.br/lancamentos_caixa/get_vendas_dia?cliente_id=[ID]&data=2026-01-02
```

**Resposta esperada:**
```json
{
  "vendas_posto": 44294.17,
  "arla": 114.52,
  "lubrificantes": 0,
  "troco_pix": 1000.00,
  "cheques_auto": [
    {
      "troco_pix_id": 14,
      "tipo": "A_VISTA",
      "valor": 2000.00,
      "descricao": "AUTO - Cheque À Vista - Troco PIX #14"
    }
  ]
}
```

## 📸 Screenshot Solicitado

Por favor, tire um screenshot mostrando:
1. A página completa do formulário
2. O console do navegador (F12) com TODOS os logs
3. A parte do formulário que mostra:
   - TROCO PIX (AUTO) com seu valor
   - Total de Receitas
   - Cheques À Vista

## 🆘 Possíveis Soluções

### Se o problema for cache do navegador:
1. Pressione Ctrl+Shift+R (ou Cmd+Shift+R no Mac) para recarregar sem cache
2. Ou limpe o cache do navegador

### Se o problema for na renderização:
O sistema pode estar atualizando o valor internamente, mas não visualmente. Neste caso, precisaremos forçar um refresh do campo.

### Se o problema for timing:
Pode haver uma condição de corrida onde o campo é atualizado antes de ser renderizado. Precisaremos adicionar um setTimeout ou esperar o campo estar pronto.

## 📞 Próximos Passos

1. ✅ Execute os passos acima para coletar logs detalhados
2. ✅ Tire screenshots do formulário e console
3. ✅ Execute a query SQL no banco de dados
4. ✅ Teste a API diretamente no navegador
5. ✅ Envie todas essas informações para análise

Com essas informações, poderemos identificar exatamente onde está o problema e corrigi-lo rapidamente!

---
**Data:** 03/02/2026
**Status:** 🔍 Investigando
**Logs Detalhados:** ✅ Adicionados no commit 3e9d292
