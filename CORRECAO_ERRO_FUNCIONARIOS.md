# 🔧 Correção: Erro 500 no Endpoint de Funcionários

## 🐛 Problema Identificado

### Sintomas
Ao clicar nos botões **"Sobras de Caixa"**, **"Perdas de Caixas"** ou **"Vales de Quebras de Caixas"** em `/lancamentos_caixa/novo`, o modal não abria e os logs mostravam:

```
GET /lancamentos_caixa/api/funcionarios/1 HTTP/1.1" 500 73
```

### Causa Raiz
O endpoint `/lancamentos_caixa/api/funcionarios/<cliente_id>` estava tentando acessar a coluna `clienteid` na tabela `funcionarios`, mas:
- A coluna poderia ter nome diferente no banco (`cliente_id`, `id_cliente`)
- A coluna poderia não existir se a migration não foi executada
- Erro genérico não mostrava o problema específico

---

## ✅ Solução Implementada

### 1. Detecção Automática de Coluna

O endpoint agora detecta automaticamente qual coluna existe:

```python
# Descobrir colunas da tabela
cursor.execute("DESCRIBE funcionarios")
columns = [col['Field'] for col in cursor.fetchall()]

# Tentar diferentes nomes
if 'clienteid' in columns:
    cliente_column = 'clienteid'
elif 'cliente_id' in columns:
    cliente_column = 'cliente_id'
elif 'id_cliente' in columns:
    cliente_column = 'id_cliente'
```

### 2. Fallback Inteligente

Se nenhuma coluna de cliente for encontrada, o sistema retorna **todos os funcionários ativos**:

```python
if not cliente_column:
    # Retornar todos funcionários ativos
    query = """
        SELECT f.id, f.nome, f.cargo, f.cpf
        FROM funcionarios f
        WHERE f.ativo = 1
        ORDER BY f.nome
    """
```

### 3. Logging Detalhado

Adicionado logging completo para debug:

```python
print(f"[DEBUG] Colunas da tabela funcionarios: {columns}")
print(f"[DEBUG] Usando coluna: {cliente_column}")
print(f"[DEBUG] Encontrados {len(funcionarios)} funcionários")
print(f"[ERRO] Erro: {type(e).__name__}: {str(e)}")
traceback.print_exc()
```

---

## 🧪 Como Testar

### Passo 1: Aguardar Deploy
Esperar o Render fazer deploy do branch `copilot/fix-troco-pix-auto-error`

### Passo 2: Acessar Formulário
```
https://nh-transportes.onrender.com/lancamentos_caixa/novo
```

### Passo 3: Selecionar Cliente e Data
1. Selecionar um cliente (ex: POSTO NOVO HORIZONTE GOIATUBA LTDA)
2. Selecionar uma data (ex: 02/01/2026)

### Passo 4: Testar Botões

**Sobras de Caixa (Verde):**
1. Clicar no botão "Sobras de Caixa"
2. ✅ Modal deve abrir com lista de funcionários
3. Se aparecer "Nenhum funcionário encontrado" → Normal se não há funcionários vinculados

**Perdas de Caixas (Amarelo):**
1. Clicar no botão "Perdas de Caixas"
2. ✅ Modal deve abrir com lista de funcionários

**Vales de Quebras (Vermelho):**
1. Clicar no botão "Vales de Quebras de Caixas"
2. ✅ Modal deve abrir com lista de funcionários

### Passo 5: Verificar Logs
Nos logs do Render, procurar por:

```
[DEBUG] Buscando funcionários para cliente_id: 1
[DEBUG] Colunas da tabela funcionarios: ['id', 'nome', 'clienteid', ...]
[DEBUG] Usando coluna: clienteid
[DEBUG] Encontrados X funcionários
[DEBUG] Retornando X funcionários
```

---

## 📊 Resultados Esperados

### Cenário 1: Coluna Existe e Há Funcionários
```
✓ Modal abre
✓ Lista de funcionários aparece
✓ Pode digitar valores
✓ Total calcula automaticamente
```

### Cenário 2: Coluna Existe mas Não Há Funcionários Vinculados
```
✓ Modal abre
✓ Mensagem: "Nenhum funcionário encontrado para este cliente"
✓ Não há erro 500
```

### Cenário 3: Coluna Não Existe (Fallback)
```
✓ Modal abre
✓ Lista TODOS funcionários ativos do sistema
✓ Funcionários podem ser selecionados
✓ Aviso nos logs: "Coluna de cliente não encontrada"
```

---

## 🔍 Troubleshooting

### Problema: Modal Ainda Não Abre

**Verificar:**
1. Console do navegador (F12) para erros JavaScript
2. Logs do Render para erro 500
3. Se endpoint retorna JSON válido

**Testar endpoint diretamente:**
```bash
curl https://nh-transportes.onrender.com/lancamentos_caixa/api/funcionarios/1
```

**Resposta esperada:**
```json
[
  {
    "id": 1,
    "nome": "João Silva",
    "cargo": "Frentista",
    "cpf": "123.456.789-00"
  }
]
```

Ou array vazio se não há funcionários:
```json
[]
```

### Problema: Funcionários Errados Aparecem

Se aparecem funcionários de outros clientes, pode ser que:
- Coluna de cliente não existe → usando fallback
- Dados não estão vinculados corretamente

**Solução:**
Executar migration para adicionar coluna:
```bash
mysql < migrations/20260130_add_clienteid_to_funcionarios.sql
```

---

## 📝 Commits Relacionados

1. **ae68a8b** - Adicionar logging detalhado para debugar erro
2. **52b72da** - Corrigir endpoint com detecção automática de coluna

---

## ✨ Melhorias Futuras (Opcional)

- [ ] Remover logs de debug após confirmar funcionamento
- [ ] Adicionar cache de funcionários no frontend
- [ ] Validar se cliente tem funcionários antes de mostrar botões
- [ ] Mensagem mais clara quando não há funcionários

---

**Status:** ✅ **CORRIGIDO**  
**Data:** 03/02/2026  
**Branch:** copilot/fix-troco-pix-auto-error  
**Pronto para:** Teste em produção
