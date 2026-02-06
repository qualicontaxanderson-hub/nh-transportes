# Correção: Botão Detalhe e Adição do Botão Editar em Lançamentos de Funcionários

**Data:** 06/02/2026  
**Status:** ✅ COMPLETO

---

## 📋 Resumo

Dois problemas foram reportados e resolvidos na página de lançamentos de funcionários:

1. ❌ **Botão "Detalhe" não funcionava** → ✅ CORRIGIDO
2. ❌ **Faltava botão "EDITAR"** → ✅ IMPLEMENTADO

---

## 🐛 Problema 1: Botão "Detalhe" Não Funcionava

### Sintoma

Ao clicar no botão "Detalhe" na lista de lançamentos, a página não carregava ou mostrava dados incompletos, especialmente para motoristas que recebem comissões.

### Causa Raiz

A query SQL na rota `/detalhe` usava `INNER JOIN` apenas com a tabela `funcionarios`:

```python
# CÓDIGO PROBLEMÁTICO (linha 318)
cursor.execute("""
    SELECT 
        l.*,
        f.nome as funcionario_nome,  # ❌ Só pega de funcionarios
        r.nome as rubrica_nome,
        r.tipo as rubrica_tipo,
        v.caminhao
    FROM lancamentosfuncionarios_v2 l
    INNER JOIN funcionarios f ON l.funcionarioid = f.id  # ❌ INNER JOIN exclui motoristas
    INNER JOIN rubricas r ON l.rubricaid = r.id
    LEFT JOIN veiculos v ON l.caminhaoid = v.id
    WHERE l.mes = %s AND l.clienteid = %s
    ORDER BY f.nome, r.ordem
""", (mes, cliente_id))
```

**Problema:** 
- `INNER JOIN funcionarios` só retorna registros quando `funcionarioid` existe em `funcionarios`
- Motoristas estão na tabela `motoristas`, não em `funcionarios`
- Lançamentos de motoristas eram **excluídos** da consulta

### Solução

Alterada query para usar `LEFT JOIN` com **ambas** as tabelas:

```python
# CÓDIGO CORRIGIDO
cursor.execute("""
    SELECT 
        l.*,
        COALESCE(f.nome, m.nome) as funcionario_nome,  # ✅ Tenta funcionarios, depois motoristas
        r.nome as rubrica_nome,
        r.tipo as rubrica_tipo,
        v.caminhao
    FROM lancamentosfuncionarios_v2 l
    LEFT JOIN funcionarios f ON l.funcionarioid = f.id  # ✅ LEFT JOIN não exclui
    LEFT JOIN motoristas m ON l.funcionarioid = m.id    # ✅ Também busca em motoristas
    INNER JOIN rubricas r ON l.rubricaid = r.id
    LEFT JOIN veiculos v ON l.caminhaoid = v.id
    WHERE l.mes = %s AND l.clienteid = %s
    ORDER BY COALESCE(f.nome, m.nome), r.ordem  # ✅ Ordena pelo nome encontrado
""", (mes, cliente_id))
```

**Mudanças:**
1. ✅ `LEFT JOIN funcionarios` - não exclui se não encontrar
2. ✅ `LEFT JOIN motoristas` - busca também em motoristas
3. ✅ `COALESCE(f.nome, m.nome)` - pega o nome que existir
4. ✅ Ordenação também usa `COALESCE`

**Resultado:** Agora mostra **todos** os lançamentos, tanto de funcionários quanto de motoristas.

---

## ➕ Problema 2: Faltava Botão "EDITAR"

### Necessidade

Usuários precisavam editar lançamentos já criados, mas não havia opção para isso. Só podiam:
- ✅ Ver lista de lançamentos
- ✅ Ver detalhes (após correção)
- ❌ **Editar** valores (FALTAVA)

### Solução Implementada

Criada nova rota `/editar` e adicionado botão na lista.

---

## 🔧 Implementação da Rota `/editar`

### Nova Rota

```python
@bp.route('/editar/<mes>/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(mes, cliente_id):
    """Edit existing payroll entries for a specific month and client"""
```

### Método GET - Carregar Dados Existentes

```python
if request.method == 'GET':
    # ... get clientes e rubricas ...
    
    # Get existing lancamentos for this month and client
    cursor.execute("""
        SELECT funcionarioid, rubricaid, valor
        FROM lancamentosfuncionarios_v2
        WHERE mes = %s AND clienteid = %s
    """, (mes, cliente_id))
    lancamentos_existentes = cursor.fetchall()
    
    # Convert to dict for easy lookup: {funcionario_id: {rubrica_id: valor}}
    valores_existentes = {}
    for lanc in lancamentos_existentes:
        func_id = lanc['funcionarioid']
        if func_id not in valores_existentes:
            valores_existentes[func_id] = {}
        valores_existentes[func_id][lanc['rubricaid']] = float(lanc['valor'])
    
    return render_template('lancamentos_funcionarios/novo.html', 
                         mes_padrao=mes,
                         cliente_selecionado=cliente_id,
                         clientes=clientes,
                         rubricas=rubricas,
                         valores_existentes=valores_existentes,
                         modo_edicao=True)  # ✅ Flag para indicar modo edição
```

**Estrutura `valores_existentes`:**
```python
{
    1: {  # funcionario_id
        5: 1500.00,  # rubrica_id: valor
        6: 200.00,
        7: -50.00
    },
    2: {
        5: 2000.00,
        8: 150.00
    }
}
```

### Método POST - Atualizar Valores

```python
if request.method == 'POST':
    # ... mesmo código que a rota /novo ...
    # Usa ON DUPLICATE KEY UPDATE, então atualiza se já existir
    
    cursor.execute("""
        INSERT INTO lancamentosfuncionarios_v2 (...)
        VALUES (...)
        ON DUPLICATE KEY UPDATE 
            valor = VALUES(valor),
            atualizadoem = CURRENT_TIMESTAMP
    """, ...)
    
    flash('Lançamentos atualizados com sucesso!', 'success')
    return redirect(url_for('lancamentos_funcionarios.lista'))
```

---

## 🎨 Adaptações no Template

### Template `novo.html` Adaptado

O template `novo.html` foi modificado para funcionar em **dois modos**:

#### 1. Título Dinâmico

```html
<!-- ANTES -->
<h2>Novo Lançamento de Funcionários</h2>

<!-- DEPOIS -->
<h2>{% if modo_edicao %}Editar{% else %}Novo{% endif %} Lançamento de Funcionários</h2>
```

#### 2. Cor do Header

```html
<!-- Laranja para novo, Amarelo para edição -->
<div class="card-header" style="background:{% if modo_edicao %}#ffc107{% else %}#ff9800{% endif %};">
```

#### 3. Campos Desabilitados em Edição

```html
<!-- Mês não pode ser alterado em edição -->
<input type="text" name="mes" ... {% if modo_edicao %}readonly{% endif %}>

<!-- Cliente não pode ser alterado em edição -->
<select name="clienteid" ... {% if modo_edicao %}disabled{% endif %}>
{% if modo_edicao %}
<input type="hidden" name="clienteid" value="{{ cliente_selecionado }}">
{% endif %}
```

#### 4. JavaScript - Variáveis para Edição

```javascript
const valoresExistentes = {{ valores_existentes|tojson|safe if valores_existentes else '{}' }};
const modoEdicao = {{ 'true' if modo_edicao else 'false' }};
```

#### 5. JavaScript - Pré-preenchimento de Valores

```javascript
// Check for existing values in edit mode (PRIORIDADE 1)
if (modoEdicao && valoresExistentes[func.id] && valoresExistentes[func.id][rubrica.id]) {
    defaultValue = Math.round(valoresExistentes[func.id][rubrica.id] * 100);
}
// Auto-fill salary base (PRIORIDADE 2)
else if (rubrica.nome === 'SALÁRIO BASE' && func.salario_base) {
    defaultValue = func.salario_base;
}
// Auto-fill commission (PRIORIDADE 3)
else if ((rubrica.nome === 'Comissão' || rubrica.nome === 'Comissão / Aj. Custo') && isMotorista) {
    if (comissaoValue) {
        defaultValue = Math.round(comissaoValue * 100);
    }
    isReadonly = true;
}
// Auto-fill loans (PRIORIDADE 4)
else if ((rubrica.nome === 'EMPRÉSTIMOS' || rubrica.nome === 'Empréstimos') && loanData) {
    defaultValue = Math.round(loanData.valor * 100);
    isReadonly = true;
}
```

**Lógica de Prioridade:**
1. Valores já salvos (modo edição) → **mais importante**
2. Salário base cadastrado
3. Comissões de fretes do mês
4. Parcelas de empréstimos

#### 6. JavaScript - Auto-carregar em Edição

```javascript
// In edit mode, automatically load funcionarios
if (modoEdicao) {
    const clienteSelect = document.getElementById('clienteid');
    if (clienteSelect.value) {
        checkAndLoadFuncionarios();  // Carrega automaticamente
    }
}
```

---

## 🎯 Botão "Editar" na Lista

### Template `lista.html`

```html
<td>
    <!-- Botão Detalhe (já existia) -->
    <a href="{{ url_for('lancamentos_funcionarios.detalhe', mes=lanc.mes, cliente_id=lanc.clienteid) }}" 
       class="btn btn-sm btn-info" title="Ver Detalhes">
        <i class="bi bi-eye"></i> Detalhe
    </a>
    
    <!-- Botão Editar (NOVO) -->
    <a href="{{ url_for('lancamentos_funcionarios.editar', mes=lanc.mes, cliente_id=lanc.clienteid) }}" 
       class="btn btn-sm btn-warning" title="Editar Lançamento">
        <i class="bi bi-pencil"></i> Editar
    </a>
</td>
```

**Visual:**
- Botão amarelo (warning)
- Ícone de lápis
- Ao lado do botão azul "Detalhe"

---

## 📁 Mudanças por Arquivo

### 1. `routes/lancamentos_funcionarios.py`

**Linha 302-324:** Corrigida query da rota `detalhe`
- Adicionado `LEFT JOIN motoristas`
- Usado `COALESCE(f.nome, m.nome)`

**Linha 356-441:** Nova rota `editar` completa
- Método GET: carrega valores existentes
- Método POST: atualiza valores
- 86 linhas adicionadas

### 2. `templates/lancamentos_funcionarios/lista.html`

**Linha 88-91:** Adicionado botão "Editar"
- 4 linhas adicionadas

### 3. `templates/lancamentos_funcionarios/novo.html`

**Linhas 1-37:** Adaptado header para modo edição
- Título dinâmico
- Cor dinâmica
- Campos readonly/disabled em edição

**Linhas 128-132:** Variáveis JavaScript
- `valoresExistentes`
- `modoEdicao`

**Linhas 305-333:** Lógica de pré-preenchimento
- Prioridade para valores existentes
- Mantém auto-fill de salário/comissão/empréstimo

**Linhas 414-422:** Auto-carregar em edição
- Dispara carregamento automático

---

## 📊 Comparação Antes/Depois

| Funcionalidade | Antes | Depois |
|----------------|-------|--------|
| **Botão Detalhe funciona** | ❌ Não | ✅ Sim |
| **Motoristas aparecem** | ❌ Não | ✅ Sim |
| **Botão Editar existe** | ❌ Não | ✅ Sim |
| **Editar valores** | ❌ Impossível | ✅ Funciona |
| **Pré-preenchimento** | ❌ Não | ✅ Automático |
| **Modo vs Criação** | ❌ Confunde | ✅ Claro |

---

## 🧪 Testes de Validação

### Teste 1: Botão Detalhe com Funcionários

1. Criar lançamento para cliente X mês Y com funcionários
2. Na lista, clicar em "Detalhe"
3. ✅ Página deve carregar
4. ✅ Deve mostrar todos os funcionários
5. ✅ Deve mostrar valores corretos

### Teste 2: Botão Detalhe com Motoristas

1. Criar lançamento incluindo motorista com comissão
2. Na lista, clicar em "Detalhe"
3. ✅ Página deve carregar
4. ✅ Deve mostrar motorista
5. ✅ Deve mostrar valor da comissão

### Teste 3: Botão Editar Aparece

1. Acessar `/lancamentos-funcionarios/`
2. ✅ Cada linha deve ter botão amarelo "Editar"
3. ✅ Botão deve estar ao lado do botão "Detalhe"

### Teste 4: Editar Carrega Valores

1. Clicar em "Editar" de um lançamento existente
2. ✅ Página deve carregar
3. ✅ Mês e Cliente devem estar preenchidos e desabilitados
4. ✅ Funcionários devem carregar automaticamente
5. ✅ Valores devem estar pré-preenchidos

### Teste 5: Editar Atualiza Valores

1. Na página de edição, alterar alguns valores
2. Clicar em "Salvar"
3. ✅ Deve redirecionar para lista
4. ✅ Mensagem "Lançamentos atualizados com sucesso!"
5. ✅ Clicar em "Detalhe" deve mostrar valores atualizados

### Teste 6: Editar Não Perde Comissões

1. Editar lançamento que tem motorista com comissão
2. ✅ Comissão deve aparecer (readonly)
3. Alterar outro valor e salvar
4. ✅ Comissão deve ser mantida

---

## ✅ Benefícios

1. **Botão Detalhe Funcional**
   - ✅ Agora mostra funcionários E motoristas
   - ✅ Dados completos e corretos

2. **Funcionalidade de Edição**
   - ✅ Permite corrigir erros
   - ✅ Atualizar valores posteriormente
   - ✅ Não precisa deletar e recriar

3. **UX Melhorada**
   - ✅ Interface clara (Novo vs Editar)
   - ✅ Campos desabilitados onde não pode alterar
   - ✅ Valores pré-preenchidos automaticamente

4. **Integridade de Dados**
   - ✅ Não perde comissões ao editar
   - ✅ Não perde empréstimos ao editar
   - ✅ Mantém histórico (atualizadoem)

5. **Código Robusto**
   - ✅ Reutiliza template (DRY)
   - ✅ Usa ON DUPLICATE KEY UPDATE
   - ✅ Validação dupla (backend + frontend)

6. **Manutenibilidade**
   - ✅ Código bem documentado
   - ✅ Lógica clara e separada
   - ✅ Fácil de entender e modificar

7. **Compatibilidade**
   - ✅ Funciona com rubricas antigas e novas
   - ✅ Funciona com funcionários e motoristas
   - ✅ Não quebra funcionalidades existentes

---

## 📋 Checklist de Deploy

**Pré-deploy:**
- [x] Código implementado
- [x] Sintaxe validada
- [x] Lógica testada
- [x] Documentação criada

**Deploy:**
- [ ] Fazer deploy do código
- [ ] Verificar logs de erro
- [ ] Testar botão "Detalhe"
- [ ] Testar botão "Editar"

**Pós-deploy:**
- [ ] Criar lançamento de teste
- [ ] Verificar detalhes (funcionários + motoristas)
- [ ] Editar lançamento de teste
- [ ] Confirmar que valores são atualizados
- [ ] Validar que comissões/empréstimos não são perdidos

---

## 🎉 Conclusão

**Ambos os problemas foram resolvidos com sucesso:**

1. ✅ **Botão "Detalhe"** agora funciona corretamente
   - Corrigida query SQL
   - Mostra funcionários e motoristas

2. ✅ **Botão "Editar"** foi implementado
   - Nova rota criada
   - Template adaptado
   - Funcionalidade completa

**Status:** 🎉 **100% COMPLETO E PRONTO PARA DEPLOY**

**Data:** 06/02/2026  
**Branch:** `copilot/fix-merge-issue-39`  
**Arquivos:** 3 modificados  
**Linhas:** ~100 adicionadas/modificadas  
**Documentação:** ✅ Completa em Português 🇧🇷
