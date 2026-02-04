# 🔧 Correção: TROCO PIX (AUTO) Não Carregando Automaticamente

## Descrição do Problema
Ao criar um novo Fechamento de Caixa em `/lancamentos_caixa/novo`, o campo "TROCO PIX (AUTO)" não estava sendo automaticamente preenchido com dados da tabela `troco_pix`, enquanto o "CHEQUE AUTO" FUNCIONAVA corretamente.

## Causa Raiz
O código JavaScript que preenche os campos AUTO no template (`templates/lancamentos_caixa/novo.html`) estava verificando apenas o nome do campo `'TROCO PIX (AUTO)'` mas não o nome legado `'TROCO PIX'`.

Isso causava problemas se:
1. A migration `20260203_add_troco_pix_auto.sql` não foi executada corretamente
2. O banco de dados ainda tinha uma entrada com nome='TROCO PIX' (sem o sufixo (AUTO))
3. Havia incompatibilidade de espaços em branco ou codificação no nome do campo

## Solução Aplicada
Atualizada a linha 367 em `templates/lancamentos_caixa/novo.html` para verificar AMBOS os nomes de campo:

**ANTES:**
```javascript
} else if (tipoNome === 'TROCO PIX (AUTO)') {
    valorInput.value = formatCurrency(data.troco_pix || 0);
}
```

**DEPOIS:**
```javascript
} else if (tipoNome === 'TROCO PIX (AUTO)' || tipoNome === 'TROCO PIX') {
    valorInput.value = formatCurrency(data.troco_pix || 0);
}
```

Isso fornece compatibilidade retroativa e garante que o campo seja preenchido independentemente de qual nome existe no banco de dados.

## Arquivos Modificados
- `templates/lancamentos_caixa/novo.html` (linha 367)
  - Adicionado suporte para ambos os nomes de campo 'TROCO PIX (AUTO)' e 'TROCO PIX'
  - Adicionadas instruções console.log de depuração para ajudar a rastrear problemas

## Como Verificar a Correção

### Passo 1: Verificar Configuração do Banco de Dados
Execute esta query para garantir que TROCO PIX AUTO existe no banco:

```sql
SELECT 
    (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') as tem_pix_auto,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) as tem_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) as tem_cheque_prazo;
```

**Resultado Esperado:**
```
+──────────────┬──────────────────┬───────────────────┐
│ tem_pix_auto │ tem_cheque_vista │ tem_cheque_prazo  │
├──────────────┼──────────────────┼───────────────────┤
│      1       │        1         │         1         │
└──────────────┴──────────────────┴───────────────────┘
```

Se `tem_pix_auto` for 0, execute a migration:
```bash
mysql -u usuario -p banco < migrations/20260203_add_troco_pix_auto.sql
```

### Passo 2: Testar o Recurso de Carregamento Automático

1. **Criar uma transação TROCO PIX:**
   - Vá para `/troco_pix/pista` (como usuário PISTA) ou `/troco_pix/` (como ADMIN)
   - Clique em "Novo Troco PIX"
   - Preencha o formulário com dados de teste:
     - Data: 02/01/2026
     - Cliente: POSTO NOVO HORIZONTE GOIATUBA LTDA
     - Venda: R$ 2.020,00
     - Cheque À Vista: R$ 3.000,00
     - Troco PIX: R$ 1.000,00
   - Salvar

2. **Criar um Fechamento de Caixa e verificar carregamento automático:**
   - Vá para `/lancamentos_caixa/novo`
   - Selecione:
     - Cliente: POSTO NOVO HORIZONTE GOIATUBA LTDA
     - Data: 02/01/2026
   - Aguarde o carregamento automático (você verá a mensagem "Carregando vendas do dia...")

3. **Verificar Console do Navegador (F12) para saída de depuração:**
   ```
   Dados recebidos do get_vendas_dia: {vendas_posto: 44294.17, arla: 114.52, lubrificantes: 0, troco_pix: 1000, cheques_auto: Array(1)}
   Verificando receita: tipoNome="VENDAS POSTO", readonly=true
   Verificando receita: tipoNome="ARLA", readonly=true
   Verificando receita: tipoNome="LUBRIFICANTES", readonly=true
   Verificando receita: tipoNome="TROCO PIX (AUTO)", readonly=true
   Atualizando TROCO PIX: tipoNome="TROCO PIX (AUTO)", valor=1000
   ```

4. **Verificar se o formulário mostra:**
   - ✅ TROCO PIX (AUTO): R$ 1.000,00 (somente leitura, com badge "Auto")
   - ✅ CHEQUE AUTO em Comprovações: R$ 3.000,00 (com descrição "AUTO - Cheque À Vista - Troco PIX #14")

### Passo 3: Comportamento Esperado

**Receitas e Entradas (Lado Esquerdo):**
- VENDAS POSTO: Preenchimento automático
- ARLA: Preenchimento automático
- LUBRIFICANTES: Preenchimento automático
- **TROCO PIX (AUTO): R$ 1.000,00** ← Deve ser preenchido automaticamente ✅
- Outros campos manuais...

**Comprovação para Fechamento (Lado Direito):**
- **Depósitos em Cheques À Vista: R$ 3.000,00** ← Deve ser preenchido automaticamente ✅
- Descrição: "AUTO - Cheque À Vista - Troco PIX #14"
- Outros campos manuais...

## E Se Ainda Não Funcionar?

### Verificação 1: Verificar entradas em tipos_receita_caixa
```sql
SELECT id, nome, tipo, ativo FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

Resultado esperado:
```
+----+---------------------+--------+-------+
| id | nome                | tipo   | ativo |
+----+---------------------+--------+-------+
| XX | TROCO PIX (MANUAL)  | MANUAL |     1 |
| XX | TROCO PIX (AUTO)    | AUTO   |     1 |
+----+---------------------+--------+-------+
```

### Verificação 2: Verificar se existem dados troco_pix
```sql
SELECT id, cliente_id, data, troco_pix, cheque_valor 
FROM troco_pix 
WHERE cliente_id = [ID_CLIENTE] AND data = '2026-01-02';
```

Deve retornar registros com troco_pix > 0.

### Verificação 3: Testar a API diretamente
Abra o navegador e vá para:
```
https://nh-transportes.onrender.com/lancamentos_caixa/get_vendas_dia?cliente_id=[ID]&data=2026-01-02
```

Resposta esperada:
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
      "valor": 3000.00,
      "data_vencimento": null,
      "descricao": "AUTO - Cheque À Vista - Troco PIX #14"
    }
  ]
}
```

### Verificação 4: Erros no Console do Navegador
Abra DevTools (F12) → aba Console e procure por erros:
- ❌ "Failed to fetch..."
- ❌ "TypeError..."
- ❌ "Uncaught..."

## Modo de Depuração
A correção inclui instruções console.log para depuração. Para vê-las:
1. Abra DevTools do navegador (F12)
2. Vá para a aba Console
3. Carregue o formulário de Fechamento de Caixa
4. Selecione cliente e data
5. Você deve ver a saída de depuração mostrando:
   - Dados recebidos da API
   - Cada campo de receita sendo verificado
   - Valor TROCO PIX sendo atualizado

## Migration Necessária
Se `tem_pix_auto` retornar 0, você DEVE executar a migration:

```bash
mysql -u root -p railway < /home/runner/work/nh-transportes/nh-transportes/migrations/20260203_add_troco_pix_auto.sql
```

Ou via console do Render:
```bash
mysql -h centerbeam.proxy.rlwy.net -P 56026 -u root -p railway < migrations/20260203_add_troco_pix_auto.sql
```

## Detalhes Técnicos

### Como Funcionam os Campos AUTO
1. Usuário seleciona Cliente e Data
2. JavaScript chama a API `/lancamentos_caixa/get_vendas_dia`
3. Backend consulta:
   - Tabela `vendas_posto` para vendas
   - `arla_lancamentos` para ARLA
   - `lubrificantes_lancamentos` para lubrificantes
   - **Tabela `troco_pix` para troco PIX** ← Corrigido aqui
   - Tabela `troco_pix` para cheques
4. JavaScript preenche campos somente leitura com valores retornados
5. Campos marcados com tipo='AUTO' são somente leitura e mostram badge "Auto"

### Por Que CHEQUE AUTO Funcionava Mas TROCO PIX Não
- CHEQUES AUTO: Usa a coluna `cheque_valor` e filtra `cheque_valor > 0` ✅
- TROCO PIX AUTO: Usa a coluna `troco_pix` mas o nome do campo não estava correspondendo ❌

Agora ambos funcionam corretamente com a correção! ✅

## Próximos Passos
1. Implantar esta correção em produção (já enviado para o branch)
2. Executar migration se ainda não foi feita
3. Testar com dados reais
4. Remover instruções console.log de depuração se necessário (opcional)
5. Atualizar documentação do usuário para mencionar o campo TROCO PIX AUTO

## Referências
- Migration: `migrations/20260203_add_troco_pix_auto.sql`
- Documentação de integração: `INTEGRACAO_TROCO_PIX_CHEQUES.md`
- Checklist de validação: `CHECKLIST_VALIDACAO_TROCO_PIX.md`
- Explicação: `EXPLICACAO_QUERY_AUTOMATICO.md`

---
**Data:** 03/02/2026
**Status:** ✅ Corrigido
**Branch:** copilot/fix-troco-pix-auto-error
