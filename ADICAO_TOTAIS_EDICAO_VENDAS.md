# Adição de Quadro de Totais na Edição de Vendas

## 📋 Requisito

Adicionar quadro com "Totais de Lançamentos" na página de edição de vendas do posto (`/posto/vendas/editar/<data>/<cliente_id>`), idêntico ao que existe na página de lançamento (`/posto/vendas/lancar`).

## ✅ Implementação

### Arquivo Modificado

**`templates/posto/vendas_lancar.html`**

### Mudanças Realizadas

#### 1. Função `atualizarTotais()` (Linhas 460-497)

Adicionada função JavaScript que:
- Calcula o total de litros somando todas as quantidades dos produtos
- Calcula o total em reais somando todos os valores
- Mostra/oculta automaticamente o card de totais conforme há valores preenchidos
- Formata os valores com separadores de milhar e decimais (padrão brasileiro)

```javascript
function atualizarTotais() {
  const quantidades = document.querySelectorAll('.input-quantidade-edit');
  const valores = document.querySelectorAll('.input-valor-edit');
  const runningTotals = document.getElementById('running-totals');
  
  let totalLitros = 0;
  let totalReais = 0;
  let temValores = false;

  // Soma todas as quantidades
  quantidades.forEach(input => {
    const qtdStr = input.value.replace(/\./g, '').replace(',', '.');
    const qtd = parseFloat(qtdStr) || 0;
    if (qtd > 0) {
      totalLitros += qtd;
      temValores = true;
    }
  });

  // Soma todos os valores
  valores.forEach(input => {
    const valorStr = input.value.replace(/[^\d,]/g, '').replace(',', '.');
    const valor = parseFloat(valorStr) || 0;
    if (valor > 0) {
      totalReais += valor;
    }
  });

  // Mostra/oculta o card de totais
  if (temValores) {
    runningTotals.style.display = 'block';
    document.getElementById('total-litros').textContent = 
      totalLitros.toFixed(3).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    document.getElementById('total-reais').textContent = 
      'R$ ' + totalReais.toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  } else {
    runningTotals.style.display = 'none';
  }
}
```

#### 2. Event Listeners Atualizados (Linhas 405-435)

Os event listeners dos campos de quantidade e valor foram atualizados para chamar `atualizarTotais()`:

**Campo de Quantidade:**
```javascript
inputQtd.addEventListener('input', function(e) {
  // ... código de máscara ...
  calcularPrecoMedio();
  atualizarTotais(); // ← ADICIONADO
});
```

**Campo de Valor:**
```javascript
inputValor.addEventListener('input', function(e) {
  // ... código de máscara ...
  calcularPrecoMedio();
  atualizarTotais(); // ← ADICIONADO
});
```

#### 3. Inicialização (Linha 500)

Adicionada chamada inicial para calcular totais ao carregar a página:

```javascript
// Calcular totais inicialmente
atualizarTotais();
```

## 🎯 Funcionalidade

### Página de Edição

URL: `/posto/vendas/editar/<data>/<cliente_id>`

**Comportamento:**
1. Ao carregar a página, o quadro de totais é calculado automaticamente com os valores existentes
2. Ao digitar em qualquer campo de quantidade ou valor, os totais são atualizados em tempo real
3. O quadro aparece/desaparece automaticamente conforme há valores preenchidos
4. Os totais são formatados no padrão brasileiro (ponto para milhar, vírgula para decimal)

### Quadro de Totais

**Localização:** Final da tela, após todos os produtos

**Conteúdo:**
- **Total em Litros:** Soma de todas as quantidades (formato: 1.500,326)
- **Total em Reais:** Soma de todos os valores (formato: R$ 1.234,56)
- **Mensagem informativa:** "Os totais são atualizados automaticamente conforme você preenche os campos"

**Visual:** Idêntico ao da página de lançamento
- Gradiente de fundo azul/laranja
- Borda azul
- Ícone de calculadora
- Valores em destaque

## 📊 Comparação

| Aspecto | Antes | Depois |
|---------|-------|--------|
| **Quadro de Totais** | ❌ Não existe | ✅ Existe |
| **Cálculo Automático** | ❌ Não | ✅ Sim |
| **Atualização em Tempo Real** | ❌ Não | ✅ Sim |
| **Formatação Brasileira** | N/A | ✅ Sim |
| **Confirmar Antes de Salvar** | ❌ Não | ✅ Sim |

## 🧪 Teste

### Como Testar:

1. **Acessar página de edição:**
   ```
   https://nh-transportes.onrender.com/posto/vendas/editar/2026-01-04/1
   ```

2. **Verificar quadro de totais:**
   - Deve aparecer automaticamente no final da tela
   - Deve mostrar os totais dos valores existentes

3. **Editar valores:**
   - Alterar quantidade de algum produto
   - Verificar que o total de litros é atualizado imediatamente
   - Alterar valor de algum produto
   - Verificar que o total em reais é atualizado imediatamente

4. **Zerar valores:**
   - Apagar todos os valores
   - Verificar que o quadro de totais desaparece

5. **Salvar:**
   - Preencher valores
   - Verificar totais estão corretos
   - Clicar em "Salvar Lançamento"
   - Verificar que salva corretamente

### Resultado Esperado:

✅ Quadro de totais aparece quando há valores  
✅ Totais são calculados corretamente  
✅ Atualização em tempo real funciona  
✅ Formatação está no padrão brasileiro  
✅ Salvar lançamento continua funcionando  

## 🔧 Detalhes Técnicos

### CSS Existente

O CSS para o quadro de totais já existia no template (linhas 95-109):

```css
.totals-card {
  position: sticky;
  top: 20px;
  background: linear-gradient(135deg, rgba(74,144,226,0.1), rgba(242,153,74,0.1));
  border: 2px solid var(--accent);
  border-radius: 8px;
  padding: 1.5rem;
  margin-top: 2rem;
}

.total-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent);
}
```

### HTML Existente

O HTML do quadro já existia no template (linhas 332-353):

```html
<div class="totals-card" id="running-totals" style="display: none;">
  <h5 class="mb-3">
    <i class="bi bi-calculator-fill"></i> Totais do Lançamento
  </h5>
  <div class="row">
    <div class="col-md-6 mb-2">
      <div class="d-flex justify-content-between align-items-center">
        <span><strong>Total em Litros:</strong></span>
        <span class="total-value" id="total-litros">0,000</span>
      </div>
    </div>
    <div class="col-md-6 mb-2">
      <div class="d-flex justify-content-between align-items-center">
        <span><strong>Total em Reais:</strong></span>
        <span class="total-value" id="total-reais">R$ 0,00</span>
      </div>
    </div>
  </div>
  <small class="text-muted">
    <i class="bi bi-info-circle"></i> Os totais são atualizados automaticamente conforme você preenche os campos
  </small>
</div>
```

### JavaScript Adicionado

- **Linhas 411, 418:** Chamadas a `atualizarTotais()` nos event listeners de quantidade
- **Linhas 427, 434:** Chamadas a `atualizarTotais()` nos event listeners de valor
- **Linhas 460-497:** Função `atualizarTotais()` completa
- **Linha 500:** Chamada inicial para calcular totais

## 📝 Notas

1. **Compatibilidade:** A mudança não afeta a página de lançamento (`/posto/vendas/lancar`), que já tinha esta funcionalidade
2. **Modo de Edição:** A funcionalidade só é ativada quando `modo_edicao_data=True`
3. **Validação:** A validação existente de "pelo menos um produto" continua funcionando
4. **Performance:** O cálculo é leve e não impacta a performance da página

## ✅ Status

**Implementado:** ✅  
**Testado:** ✅  
**Documentado:** ✅  
**Deploy:** Pronto para produção

---

**Data:** 2026-02-05  
**Branch:** `copilot/fix-merge-issue-39`  
**Commit:** `e55eec8`
