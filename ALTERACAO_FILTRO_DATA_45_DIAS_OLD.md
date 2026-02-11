# 📅 Alteração: Filtro de Data - 45 Dias

## 🎯 Mudança Implementada

### Antes
O filtro de data na listagem (`/lancamentos_caixa/`) iniciava no **primeiro dia do mês atual**.

**Exemplo:**
- Hoje: 03/02/2026
- Data início: 01/02/2026 (primeiro dia do mês)
- Data fim: 03/02/2026 (hoje)
- Período: ~3 dias

**Problema:** Período muito curto, não permitia visualizar lançamentos anteriores para conferência.

### Depois
O filtro de data agora inicia **45 dias antes da data atual**.

**Exemplo:**
- Hoje: 03/02/2026
- Data início: 20/12/2025 (45 dias atrás)
- Data fim: 03/02/2026 (hoje)
- Período: 45 dias

**Benefício:** Período adequado para conferência e auditoria dos lançamentos recentes.

---

## 💻 Implementação

### Código Alterado

**Arquivo:** `routes/lancamentos_caixa.py`  
**Função:** `lista()`  
**Linhas:** 53-58

#### Antes:
```python
# Default to current month if no filters provided
from datetime import date
hoje = date.today()
primeiro_dia_mes = hoje.replace(day=1)
data_inicio_default = primeiro_dia_mes.strftime('%Y-%m-%d')
data_fim_default = hoje.strftime('%Y-%m-%d')
```

#### Depois:
```python
# Default to 45 days before today if no filters provided
from datetime import date
hoje = date.today()
data_45_dias_atras = hoje - timedelta(days=45)
data_inicio_default = data_45_dias_atras.strftime('%Y-%m-%d')
data_fim_default = hoje.strftime('%Y-%m-%d')
```

### Import Adicionado

**Arquivo:** `routes/lancamentos_caixa.py`  
**Linha:** 5

```python
from datetime import datetime, timedelta  # timedelta adicionado
```

---

## 🔍 Como Funciona

### 1. Acesso Inicial
Quando você acessa `/lancamentos_caixa/` **SEM** parâmetros na URL:
- Sistema calcula automaticamente: `hoje - 45 dias`
- Define como data_inicio
- Define data_fim como hoje

### 2. Com Parâmetros
Se você acessa com filtros na URL (ex: `/lancamentos_caixa/?data_inicio=2026-01-01&data_fim=2026-01-31`):
- Sistema usa os parâmetros fornecidos
- Ignora o padrão de 45 dias

### 3. Lógica do Código
```python
# Get filters from query string
filtros = {
    'data_inicio': request.args.get('data_inicio', data_inicio_default),  # Usa parâmetro ou padrão
    'data_fim': request.args.get('data_fim', data_fim_default),            # Usa parâmetro ou padrão
    'cliente_id': request.args.get('cliente_id', '')
}
```

---

## 📊 Exemplos Práticos

### Exemplo 1: Acesso em 03/02/2026
```python
hoje = date(2026, 2, 3)
data_45_dias_atras = date(2026, 2, 3) - timedelta(days=45)
# data_45_dias_atras = date(2025, 12, 20)

data_inicio_default = '2025-12-20'
data_fim_default = '2026-02-03'
```

**Resultado:** Mostra lançamentos de 20/12/2025 até 03/02/2026

### Exemplo 2: Acesso em 15/03/2026
```python
hoje = date(2026, 3, 15)
data_45_dias_atras = date(2026, 3, 15) - timedelta(days=45)
# data_45_dias_atras = date(2026, 1, 29)

data_inicio_default = '2026-01-29'
data_fim_default = '2026-03-15'
```

**Resultado:** Mostra lançamentos de 29/01/2026 até 15/03/2026

### Exemplo 3: Virada de ano
```python
hoje = date(2026, 1, 10)
data_45_dias_atras = date(2026, 1, 10) - timedelta(days=45)
# data_45_dias_atras = date(2025, 11, 26)

data_inicio_default = '2025-11-26'
data_fim_default = '2026-01-10'
```

**Resultado:** Mostra lançamentos de 26/11/2025 até 10/01/2026

---

## ✅ Benefícios

### 1. Conferência Adequada
- ✅ Visualiza lançamentos dos últimos 45 dias
- ✅ Período suficiente para auditorias
- ✅ Cobre mais de um mês completo

### 2. Desempenho
- ✅ Não carrega todos os lançamentos históricos
- ✅ Período limitado mantém performance
- ✅ Queries mais rápidas

### 3. Flexibilidade
- ✅ Usuário pode alterar o filtro manualmente
- ✅ Campos de data permanecem editáveis
- ✅ Padrão inteligente, não obrigatório

### 4. Casos de Uso
- ✅ Conferência mensal de fechamentos
- ✅ Análise de tendências recentes
- ✅ Comparação período anterior
- ✅ Auditoria de últimos 45 dias

---

## 🎨 Interface

### Formulário de Filtro

A interface **não muda**, apenas o valor padrão:

```html
<form method="GET" class="row g-2 align-items-end mb-3">
    <div class="col-md-2">
        <label class="form-label">Data Início</label>
        <input type="date" name="data_inicio" class="form-control form-control-sm" 
               value="{{ filtros.data_inicio }}">  <!-- Agora tem valor de 45 dias atrás -->
    </div>
    <div class="col-md-2">
        <label class="form-label">Data Fim</label>
        <input type="date" name="data_fim" class="form-control form-control-sm" 
               value="{{ filtros.data_fim }}">      <!-- Hoje -->
    </div>
    <!-- ... outros campos ... -->
</form>
```

### Visual
```
┌─────────────────────────────────────────────────────┐
│ Filtros                                             │
├─────────────────────────────────────────────────────┤
│ Data Início: [20/12/2025] ← 45 dias antes          │
│ Data Fim:    [03/02/2026] ← hoje                   │
│ Cliente:     [Selecione...]                         │
│                                                     │
│ [Filtrar] [Limpar]                                  │
└─────────────────────────────────────────────────────┘
```

---

## 🧪 Testes

### Teste 1: Acesso Direto
1. Acesse `/lancamentos_caixa/`
2. ✅ Data início deve ser 45 dias atrás
3. ✅ Data fim deve ser hoje
4. ✅ Lançamentos dentro do período aparecem

### Teste 2: Com Parâmetros
1. Acesse `/lancamentos_caixa/?data_inicio=2026-01-01&data_fim=2026-01-31`
2. ✅ Data início deve ser 01/01/2026 (parâmetro)
3. ✅ Data fim deve ser 31/01/2026 (parâmetro)
4. ✅ Ignora padrão de 45 dias

### Teste 3: Alterar Manualmente
1. Acesse `/lancamentos_caixa/`
2. Altere data início no formulário
3. Clique em Filtrar
4. ✅ Nova data é aplicada
5. ✅ Padrão não interfere

### Teste 4: Limpar Filtros
1. Acesse com filtros personalizados
2. Clique em "Limpar"
3. ✅ Volta para `/lancamentos_caixa/` sem parâmetros
4. ✅ Padrão de 45 dias é reaplicado

---

## 📋 Comportamento Completo

### Fluxo de Decisão
```
Usuário acessa /lancamentos_caixa/
    │
    ├─→ TEM parâmetro data_inicio na URL?
    │   ├─→ SIM: Usa valor do parâmetro
    │   └─→ NÃO: Usa data_inicio_default (hoje - 45 dias)
    │
    └─→ TEM parâmetro data_fim na URL?
        ├─→ SIM: Usa valor do parâmetro
        └─→ NÃO: Usa data_fim_default (hoje)
```

### Query SQL
```python
where_conditions = []
params = []

if filtros['data_inicio']:
    where_conditions.append("lc.data >= %s")
    params.append(filtros['data_inicio'])  # Usa data de 45 dias atrás (padrão)

if filtros['data_fim']:
    where_conditions.append("lc.data <= %s")
    params.append(filtros['data_fim'])      # Usa hoje (padrão)

where_clause = "WHERE " + " AND ".join(where_conditions)
```

**SQL Resultante:**
```sql
SELECT lc.*, u.username as usuario_nome, c.razao_social as cliente_nome
FROM lancamentos_caixa lc
LEFT JOIN usuarios u ON lc.usuario_id = u.id
LEFT JOIN clientes c ON lc.cliente_id = c.id
WHERE lc.data >= '2025-12-20'  -- 45 dias atrás
  AND lc.data <= '2026-02-03'  -- hoje
ORDER BY lc.data DESC, lc.id DESC
```

---

## 🔄 Comparação: Antes vs Depois

### Tabela Comparativa

| Aspecto                | Antes (Início do Mês) | Depois (45 dias)      |
|------------------------|----------------------|----------------------|
| Período típico         | 3-30 dias            | 45 dias              |
| Cobre mês anterior?    | ❌ Não               | ✅ Sim               |
| Adequado para auditoria| ❌ Limitado          | ✅ Adequado          |
| Performance            | ✅ Ótima             | ✅ Ótima             |
| Flexibilidade          | ✅ Editável          | ✅ Editável          |

### Cenários de Uso

**Cenário 1: Conferência Mensal**
- Antes: Tinha que alterar filtro manualmente
- Depois: ✅ Já mostra período adequado

**Cenário 2: Auditoria Trimestral**
- Antes: Via apenas últimos dias
- Depois: ✅ Vê últimos 45 dias de uma vez

**Cenário 3: Início do Mês**
- Antes: Mostrava apenas 1-3 dias
- Depois: ✅ Mostra 45 dias completos

---

## 💡 Dicas de Uso

### Para Conferência Diária
- Acesse `/lancamentos_caixa/`
- Veja lançamentos recentes automaticamente
- Não precisa ajustar filtros

### Para Período Específico
- Use os campos de data manualmente
- Defina início e fim desejados
- Clique em "Filtrar"

### Para Limpar Filtros
- Clique no botão "Limpar"
- Ou acesse `/lancamentos_caixa/` diretamente
- Sistema volta para padrão de 45 dias

---

**Status:** ✅ **IMPLEMENTADO**  
**Data:** 03/02/2026  
**Commit:** 00556c0  
**Branch:** copilot/fix-troco-pix-auto-error  
**Impacto:** Melhoria na usabilidade e conferência de lançamentos
