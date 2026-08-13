# Correção do Erro 404 ao Editar/Visualizar Lançamentos de Funcionários

## Resumo

- **Tipo:** Bug crítico
- **Severidade:** 🚨 CRÍTICA (impedia uso de funcionalidades)
- **Status:** ✅ CORRIGIDO
- **Data:** 06/02/2026

## Problema Reportado

Ao clicar nos botões "Detalhe" ou "Editar" na lista de lançamentos de funcionários, o sistema retornava erro **404 Not Found**.

### Erro nos Logs:

```
GET /lancamentos-funcionarios/editar/01/2026/1 HTTP/1.1" 404
```

### URL Acessada:
```
https://app.postonovohorizonte.com.br/lancamentos-funcionarios/editar/01/2026/1
```

## Causa Raiz

### O Problema:

O campo `mes` no banco de dados está armazenado no formato **"01/2026"** (mês/ano com barra).

Quando passamos esse valor para `url_for()` no template:
```python
url_for('lancamentos_funcionarios.editar', mes='01/2026', cliente_id=1)
```

O Flask interpreta a **barra (/)** como um **separador de segmentos** na URL, gerando:
```
/lancamentos-funcionarios/editar/01/2026/1
                               ↓   ↓    ↓
                           seg1 seg2 seg3
```

Mas a rota foi definida para receber apenas **2 segmentos**:
```python
@bp.route('/editar/<mes>/<int:cliente_id>')
                    ↓        ↓
                  seg1     seg2
```

### Diagrama do Problema:

```
Banco de dados:  mes = "01/2026"
                      ↓
Template:        url_for(..., mes='01/2026', ...)
                      ↓
Flask routing:   interpreta "/" como separador
                      ↓
URL gerada:      /editar/01/2026/1  (3 segmentos!)
                         ↓   ↓   ↓
Rota esperada:   /editar/<mes>/<id>  (2 segmentos!)
                      ↓
Resultado:       404 Not Found ❌
```

## Solução Implementada

### Estratégia:

Substituir a **barra (/)** por **hífen (-)** nas URLs:
- **De:** "01/2026" → URL com 3 segmentos ❌
- **Para:** "01-2026" → URL com 2 segmentos ✅

### Implementação:

#### 1. Template `lista.html`

Adicionar filtro `|replace('/', '-')` ao gerar URLs:

**Antes (quebrado):**
```html
<a href="{{ url_for('lancamentos_funcionarios.detalhe', mes=lanc.mes, cliente_id=lanc.clienteid) }}">
    Detalhe
</a>
<a href="{{ url_for('lancamentos_funcionarios.editar', mes=lanc.mes, cliente_id=lanc.clienteid) }}">
    Editar
</a>
```

**Depois (funciona):**
```html
<a href="{{ url_for('lancamentos_funcionarios.detalhe', mes=lanc.mes|replace('/', '-'), cliente_id=lanc.clienteid) }}">
    Detalhe
</a>
<a href="{{ url_for('lancamentos_funcionarios.editar', mes=lanc.mes|replace('/', '-'), cliente_id=lanc.clienteid) }}">
    Editar
</a>
```

#### 2. Rotas `lancamentos_funcionarios.py`

Converter o formato de volta dentro das rotas:

**Rota `detalhe` (linha 304):**
```python
@bp.route('/detalhe/<mes>/<int:cliente_id>')
@login_required
def detalhe(mes, cliente_id):
    """Show detailed view of payroll entries for a specific month and client"""
    # Converte formato URL (01-2026) → formato DB (01/2026)
    mes = mes.replace('-', '/')
    
    # ... resto do código usa mes='01/2026'
```

**Rota `editar` (linha 361):**
```python
@bp.route('/editar/<mes>/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(mes, cliente_id):
    """Edit existing payroll entries for a specific month and client"""
    # Converte formato URL (01-2026) → formato DB (01/2026)
    mes = mes.replace('-', '/')
    
    # ... resto do código usa mes='01/2026'
```

## Como Funciona Agora

### Fluxo Completo:

```
1. Banco de dados: armazena "01/2026"
        ↓
2. Template (lista): converte para "01-2026" ao gerar URL
        ↓
3. URL gerada: /editar/01-2026/1 (2 segmentos ✅)
        ↓
4. Flask routing: faz match com @bp.route('/editar/<mes>/<int:cliente_id>')
        ↓
5. Rota Python: recebe mes="01-2026"
        ↓
6. Conversão: mes = mes.replace('-', '/') → mes="01/2026"
        ↓
7. Query SQL: usa "01/2026" para buscar no banco
        ↓
8. Resultado: dados corretos retornados ✅
```

## Comparação Antes/Depois

| Aspecto | Antes | Depois |
|---------|-------|--------|
| **Formato no Banco** | 01/2026 | 01/2026 (mantido) |
| **Template gera** | 01/2026 | 01-2026 |
| **URL gerada** | /editar/01/2026/1 | /editar/01-2026/1 |
| **Segmentos na URL** | 3 (quebrado) | 2 (correto) |
| **Match da rota** | ❌ Falha (404) | ✅ Sucesso |
| **Rota recebe** | N/A | 01-2026 |
| **Conversão na rota** | N/A | 01-2026 → 01/2026 |
| **Query usa** | N/A | 01/2026 |
| **Botão Detalhe** | ❌ 404 | ✅ Funciona |
| **Botão Editar** | ❌ 404 | ✅ Funciona |

## Benefícios

1. ✅ **URLs funcionam** - Ambos botões "Detalhe" e "Editar" funcionam
2. ✅ **Compatível com Flask** - Routing funciona com 2 segmentos
3. ✅ **Sem mudança no banco** - Formato "01/2026" é mantido
4. ✅ **Mudança mínima** - Apenas 4 linhas modificadas
5. ✅ **Transparente** - Usuário não percebe diferença
6. ✅ **Sem quebra** - Código existente continua funcionando
7. ✅ **Performance** - Nenhum impacto, conversão é instantânea

## Testes de Validação

### Teste 1: Botão "Detalhe"
1. Acessar `/lancamentos-funcionarios/`
2. Clicar no botão "Detalhe" de qualquer lançamento
3. **Resultado esperado:** Página de detalhes carrega corretamente ✅
4. **URL gerada:** `/detalhe/01-2026/1` (formato correto)

### Teste 2: Botão "Editar"
1. Acessar `/lancamentos-funcionarios/`
2. Clicar no botão "Editar" de qualquer lançamento
3. **Resultado esperado:** Página de edição carrega corretamente ✅
4. **URL gerada:** `/editar/01-2026/1` (formato correto)
5. Valores devem estar pré-preenchidos

### Teste 3: Verificar URL
1. Passar o mouse sobre os botões "Detalhe" e "Editar"
2. **Verificar no browser (canto inferior):**
   - URL deve mostrar `/detalhe/01-2026/1`
   - URL deve mostrar `/editar/01-2026/1`
3. **NÃO deve mostrar:** `/detalhe/01/2026/1` (3 segmentos)

### Teste 4: Verificar Dados
1. Clicar em "Detalhe" ou "Editar"
2. **Resultado esperado:** Dados do mês correto são carregados
3. Verificar que o mês mostrado é "01/2026" (formato do banco mantido)

## Compatibilidade

### URLs Antigas
Se alguém tiver URLs antigas salvas no formato `/editar/01/2026/1`, elas **não funcionarão mais**. Mas isso é esperado porque elas **nunca funcionaram** (sempre davam 404).

### Formato de Dados
O formato no banco de dados **não muda**. Continua sendo "01/2026".

### Código Existente
Todo código que **lê** o campo `mes` do banco continua funcionando normalmente, pois o formato "01/2026" é mantido.

## Mudanças Técnicas

### Arquivos Modificados:

1. **`templates/lancamentos_funcionarios/lista.html`**
   - Linhas 86, 89
   - Adicionado filtro `|replace('/', '-')`

2. **`routes/lancamentos_funcionarios.py`**
   - Linha 304 (rota `detalhe`)
   - Linha 361 (rota `editar`)
   - Adicionado `mes = mes.replace('-', '/')`

### Total de Mudanças:
- 2 arquivos
- 4 linhas adicionadas/modificadas
- 0 linhas removidas

## Conclusão

Bug **crítico** que impedia o uso dos botões "Detalhe" e "Editar" foi **corrigido** com uma solução **simples** e **elegante**:

- ✅ Substitui barra por hífen nas URLs (template)
- ✅ Converte de volta nas rotas (Python)
- ✅ Mantém formato original no banco
- ✅ Sem efeitos colaterais
- ✅ Mudança mínima (4 linhas)

**Status Final:** ✅ CORRIGIDO - Pronto para deploy em produção

---

**Data de Correção:** 06/02/2026  
**Desenvolvedor:** GitHub Copilot  
**Branch:** copilot/fix-merge-issue-39  
**Documentação:** 100% em Português 🇧🇷
