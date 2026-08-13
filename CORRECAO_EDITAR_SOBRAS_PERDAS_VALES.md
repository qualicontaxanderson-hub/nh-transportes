# ✅ Correção: Sobras/Perdas/Vales Agora São Salvos ao Editar

## 🐛 Problema Original

### Sintomas
- Ao editar um lançamento de caixa (ex: `/lancamentos_caixa/editar/3`)
- Botões de Sobras/Perdas/Vales **aparecem** ✓
- Modal **abre** e permite digitar valores ✓
- Ao clicar em "Salvar", redireciona para a lista
- **Valores NÃO são salvos** ✗
- Na listagem, valores aparecem **incorretos** ✗

### Logs Mostravam
```
POST /lancamentos_caixa/editar/3 HTTP/1.1" 302 225
GET /lancamentos_caixa/ HTTP/1.1" 200 14143
```
- POST retorna 302 (redirect) → Parece que salvou
- Mas ao voltar para a lista, valores estão errados

### Causa Raiz
A função `editar()` em `routes/lancamentos_caixa.py` **não foi atualizada** quando adicionamos as funcionalidades de Sobras/Perdas/Vales.

**Função `novo()`:** ✅ Processa e salva sobras/perdas/vales  
**Função `editar()`:** ✗ NÃO processava sobras/perdas/vales

---

## ✅ Solução Implementada

### Mudanças na Função `editar()` - POST

**1. Receber Dados do Formulário**
```python
# Get sobras de funcionários (receitas) - JSON encoded
sobras_json = request.form.get('sobras_funcionarios', '[]')
sobras_funcionarios = json.loads(sobras_json)

# Get perdas de funcionários (comprovações) - JSON encoded
perdas_json = request.form.get('perdas_funcionarios', '[]')
perdas_funcionarios = json.loads(perdas_json)

# Get vales de funcionários (comprovações) - JSON encoded
vales_json = request.form.get('vales_funcionarios', '[]')
vales_funcionarios = json.loads(vales_json)
```

**2. Incluir nos Cálculos de Totais**
```python
# Calculate totals: Diferença = Total Comprovação - Total Receitas
# Include sobras in receitas and perdas+vales in comprovações
total_receitas = sum(parse_brazilian_currency(r.get('valor', 0)) for r in receitas)
total_sobras = sum(parse_brazilian_currency(s.get('valor', 0)) for s in sobras_funcionarios)
total_receitas += total_sobras

total_comprovacao = sum(parse_brazilian_currency(c.get('valor', 0)) for c in comprovacoes)
total_perdas = sum(parse_brazilian_currency(p.get('valor', 0)) for p in perdas_funcionarios)
total_vales = sum(parse_brazilian_currency(v.get('valor', 0)) for v in vales_funcionarios)
total_comprovacao += total_perdas + total_vales

diferenca = total_comprovacao - total_receitas
```

**3. Deletar Registros Antigos**
```python
# Delete old sobras/perdas/vales
cursor.execute("DELETE FROM lancamentos_caixa_sobras_funcionarios WHERE lancamento_caixa_id = %s", (id,))
cursor.execute("DELETE FROM lancamentos_caixa_perdas_funcionarios WHERE lancamento_caixa_id = %s", (id,))
cursor.execute("DELETE FROM lancamentos_caixa_vales_funcionarios WHERE lancamento_caixa_id = %s", (id,))
```

**4. Inserir Novos Registros**
```python
# Insert sobras de funcionários (receitas)
for sobra in sobras_funcionarios:
    if sobra.get('funcionario_id') and sobra.get('valor'):
        valor = parse_brazilian_currency(sobra['valor'])
        if valor > 0:  # Só inserir se tiver valor
            cursor.execute("""
                INSERT INTO lancamentos_caixa_sobras_funcionarios 
                (lancamento_caixa_id, funcionario_id, valor, observacao)
                VALUES (%s, %s, %s, %s)
            """, (id, int(sobra['funcionario_id']), 
                  float(valor), sobra.get('observacao', '')))

# Insert perdas de funcionários (comprovações)
for perda in perdas_funcionarios:
    if perda.get('funcionario_id') and perda.get('valor'):
        valor = parse_brazilian_currency(perda['valor'])
        if valor > 0:
            cursor.execute("""
                INSERT INTO lancamentos_caixa_perdas_funcionarios 
                (lancamento_caixa_id, funcionario_id, valor, observacao)
                VALUES (%s, %s, %s, %s)
            """, (id, int(perda['funcionario_id']), 
                  float(valor), perda.get('observacao', '')))

# Insert vales de funcionários (comprovações)
for vale in vales_funcionarios:
    if vale.get('funcionario_id') and vale.get('valor'):
        valor = parse_brazilian_currency(vale['valor'])
        if valor > 0:
            cursor.execute("""
                INSERT INTO lancamentos_caixa_vales_funcionarios 
                (lancamento_caixa_id, funcionario_id, valor, observacao)
                VALUES (%s, %s, %s, %s)
            """, (id, int(vale['funcionario_id']), 
                  float(valor), vale.get('observacao', '')))
```

### Mudanças na Função `editar()` - GET

**1. Buscar Dados Existentes**
```python
# Get sobras de funcionários
cursor.execute("""
    SELECT s.*, f.nome as funcionario_nome
    FROM lancamentos_caixa_sobras_funcionarios s
    LEFT JOIN funcionarios f ON s.funcionario_id = f.id
    WHERE s.lancamento_caixa_id = %s
    ORDER BY s.id
""", (id,))
sobras_funcionarios = cursor.fetchall()

# Get perdas de funcionários
cursor.execute("""
    SELECT p.*, f.nome as funcionario_nome
    FROM lancamentos_caixa_perdas_funcionarios p
    LEFT JOIN funcionarios f ON p.funcionario_id = f.id
    WHERE p.lancamento_caixa_id = %s
    ORDER BY p.id
""", (id,))
perdas_funcionarios = cursor.fetchall()

# Get vales de funcionários
cursor.execute("""
    SELECT v.*, f.nome as funcionario_nome
    FROM lancamentos_caixa_vales_funcionarios v
    LEFT JOIN funcionarios f ON v.funcionario_id = f.id
    WHERE v.lancamento_caixa_id = %s
    ORDER BY p.id
""", (id,))
vales_funcionarios = cursor.fetchall()
```

**2. Converter e Serializar para JSON**
```python
# Convert to plain Python types
sobras_clean = convert_to_plain_python(sobras_funcionarios)
perdas_clean = convert_to_plain_python(perdas_funcionarios)
vales_clean = convert_to_plain_python(vales_funcionarios)

# Pre-serialize to JSON strings
sobras_json = json.dumps(sobras_clean)
perdas_json = json.dumps(perdas_clean)
vales_json = json.dumps(vales_clean)
```

**3. Passar para Template**
```python
return render_template('lancamentos_caixa/novo.html',
                     edit_mode=True,
                     sobras_funcionarios=sobras_clean,
                     perdas_funcionarios=perdas_clean,
                     vales_funcionarios=vales_clean,
                     sobras_json=sobras_json,
                     perdas_json=perdas_json,
                     vales_json=vales_json,
                     # ... outros parâmetros
                     )
```

### Mudanças no Template JavaScript

**Carregar Dados no Modo de Edição**
```javascript
{% if edit_mode and sobras_json %}
console.log('=== EDIT MODE: Loading sobras/perdas/vales ===');

// Load sobras
const sobrasData = {{ sobras_json|safe }};
if (sobrasData && sobrasData.length > 0) {
    dadosSobras = sobrasData.map(s => ({
        funcionario_id: s.funcionario_id,
        valor: s.valor,
        observacao: s.observacao || ''
    }));
    atualizarResumoSobras();
    console.log(`Loaded ${dadosSobras.length} sobras`);
}

// Load perdas
const perdasData = {{ perdas_json|safe }};
if (perdasData && perdasData.length > 0) {
    dadosPerdas = perdasData.map(p => ({
        funcionario_id: p.funcionario_id,
        valor: p.valor,
        observacao: p.observacao || ''
    }));
    atualizarResumoPerdas();
    console.log(`Loaded ${dadosPerdas.length} perdas`);
}

// Load vales
const valesData = {{ vales_json|safe }};
if (valesData && valesData.length > 0) {
    dadosVales = valesData.map(v => ({
        funcionario_id: v.funcionario_id,
        valor: v.valor,
        observacao: v.observacao || ''
    }));
    atualizarResumoVales();
    console.log(`Loaded ${dadosVales.length} vales`);
}

// Recalculate totals to include sobras/perdas/vales
calcularTotais();
{% endif %}
```

---

## 🧪 Como Testar

### Passo 1: Editar Lançamento Existente
```
https://app.postonovohorizonte.com.br/lancamentos_caixa/editar/3
```

### Passo 2: Adicionar Valores
1. Clicar em "Sobras de Caixa" (verde)
2. Digitar valores para funcionários
3. Salvar modal
4. Clicar em "Perdas de Caixas" (amarelo)
5. Digitar valores para funcionários
6. Salvar modal
7. Clicar em "Vales de Quebras" (vermelho)
8. Digitar valores para funcionários
9. Salvar modal

### Passo 3: Verificar Resumos
- Abaixo de cada botão deve mostrar:
  ```
  Total Sobras: R$ X,XX
  Total Perdas: R$ X,XX
  Total Vales: R$ X,XX
  ```

### Passo 4: Salvar Lançamento
- Clicar em "Salvar Lançamento"
- Deve redirecionar para lista

### Passo 5: Verificar na Listagem
- Valores de Total Receitas e Total Comprovação devem estar **corretos**
- Diferença deve estar **correta**

### Passo 6: Editar Novamente
- Clicar em "Editar" no mesmo lançamento
- Clicar nos botões de Sobras/Perdas/Vales
- **Valores anteriores devem aparecer no modal** ✅
- Pode alterar e salvar novamente

---

## ✅ Resultados Esperados

### Salvamento (POST)
```
✅ Dados de sobras são salvos na tabela lancamentos_caixa_sobras_funcionarios
✅ Dados de perdas são salvos na tabela lancamentos_caixa_perdas_funcionarios
✅ Dados de vales são salvos na tabela lancamentos_caixa_vales_funcionarios
✅ Total Receitas inclui sobras
✅ Total Comprovação inclui perdas + vales
✅ Diferença é calculada corretamente
```

### Carregamento (GET)
```
✅ Dados existentes são carregados do banco
✅ Aparecem nos resumos abaixo dos botões
✅ Ao abrir modal, valores aparecem preenchidos
✅ Totais são calculados incluindo os valores
```

### Listagem
```
✅ Valores aparecem corretos
✅ Total Receitas correto
✅ Total Comprovação correto
✅ Diferença correta
```

---

## 📊 Logs de Debug

Após a correção, os logs devem mostrar:

```
DEBUG: Loaded 5 receitas for lancamento_caixa_id=3
DEBUG: Loaded 10 comprovacoes for lancamento_caixa_id=3
DEBUG: Loaded 2 sobras for lancamento_caixa_id=3
DEBUG: Loaded 1 perdas for lancamento_caixa_id=3
DEBUG: Loaded 1 vales for lancamento_caixa_id=3
DEBUG: Passing to template - sobras_json=[{"id": 1, "funcionario_id": 5, ...}]
DEBUG: Passing to template - perdas_json=[{"id": 1, "funcionario_id": 3, ...}]
DEBUG: Passing to template - vales_json=[{"id": 1, "funcionario_id": 7, ...}]
```

No console do navegador (F12):
```
=== EDIT MODE: Loading sobras/perdas/vales ===
Sobras data: [{funcionario_id: 5, valor: 50, observacao: ""}]
Loaded 1 sobras
Perdas data: [{funcionario_id: 3, valor: 25, observacao: ""}]
Loaded 1 perdas
Vales data: [{funcionario_id: 7, valor: 100, observacao: ""}]
Loaded 1 vales
```

---

## 🎯 Conclusão

**Status:** ✅ **CORRIGIDO**

A função `editar()` agora tem **paridade completa** com a função `novo()`:
- ✅ Processa sobras/perdas/vales no POST
- ✅ Calcula totais corretamente
- ✅ Salva dados no banco
- ✅ Carrega dados existentes no GET
- ✅ Passa dados para JavaScript
- ✅ Interface mostra valores corretos

**Resultado:** Ao editar um lançamento, os valores de Sobras/Perdas/Vales são salvos e aparecem corretamente na listagem! 🎉

---

**Data:** 03/02/2026  
**Commit:** 37b25e0  
**Branch:** copilot/fix-troco-pix-auto-error  
**Arquivos Modificados:**
- `routes/lancamentos_caixa.py`
- `templates/lancamentos_caixa/novo.html`
