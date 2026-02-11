# Alteração de Filtro de Data e Permissões SUPERVISOR - Lubrificantes

## 📋 Resumo das Alterações

Data: 2026-02-05

### Mudanças Implementadas:

1. **Filtro de Data Alterado de "Mês Atual" para "Últimos 45 Dias"**
2. **Permissões SUPERVISOR para Lubrificantes Adicionadas**
3. **Menu SUPERVISOR Atualizado**

---

## 🎯 Requisitos Originais

### 1. Alterar Filtro de Data (3 URLs)

**Antes:** Mostravam dados do mês corrente apenas  
**Depois:** Mostram dados dos últimos 45 dias

URLs afetadas:
- `/arla/`
- `/posto/vendas`
- `/lubrificantes/`

### 2. Liberar Acesso SUPERVISOR

Adicionar acesso para nível SUPERVISOR em:
- `/lubrificantes/`
- `/lubrificantes/produtos`

---

## 💻 Mudanças Técnicas

### 1. Filtro de Data - 45 Dias

**Mudança Implementada:**
```python
# ANTES (mês atual):
primeiro_dia_mes = date(hoje.year, hoje.month, 1)
ultimo_dia_mes = date(hoje.year, hoje.month, ultimo_dia)

# DEPOIS (últimos 45 dias):
data_inicio_45_dias = hoje - timedelta(days=45)
data_fim_45_dias = hoje
```

### 2. Permissões SUPERVISOR

**Decorator adicionado:**
```python
from utils.decorators import supervisor_or_admin_required

@bp.route('/')
@login_required
@supervisor_or_admin_required  # ← NOVO
def index():
    ...
```

### 3. Menu SUPERVISOR Atualizado

**Novos links adicionados:**
- Cadastros → Produtos Lubrificantes
- Lançamentos → Lubrificantes

---

## 📊 Resultado Final

| URL | Filtro Padrão | Acesso SUPERVISOR |
|-----|---------------|-------------------|
| `/arla/` | 45 dias ✅ | ✅ |
| `/posto/vendas` | 45 dias ✅ | ✅ |
| `/lubrificantes/` | 45 dias ✅ | ✅ **NOVO** |
| `/lubrificantes/produtos` | N/A | ✅ **NOVO** |

**Menu SUPERVISOR:** 11 seções totais (antes: 9)

---

## ✅ Status

**COMPLETO E PRONTO PARA USO** 🚀
