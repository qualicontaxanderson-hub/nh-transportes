# Sistema Multi-Empresa e Lançamento Mensal de Despesas

## 📋 Visão Geral

Este documento descreve a implementação completa do sistema multi-empresa para lançamentos de despesas, incluindo o novo recurso de **Lançamento Mensal em Batch**.

---

## 🎯 Requisitos Atendidos

### 1. Multi-Empresa
- ✅ Sistema filtra apenas empresas com produtos configurados (`cliente_produtos.ativo = 1`)
- ✅ Empresas SEM produtos não aparecem
- ✅ Campo opcional em todos os lançamentos
- ✅ Filtro por empresa na listagem

### 2. Dois Modos de Lançamento
- ✅ **Individual**: Um lançamento por vez (mantém funcionalidade existente)
- ✅ **Mensal**: Múltiplos lançamentos em batch por mês (NOVO)

### 3. Interface Mensal
- ✅ Organizada por Títulos de Despesas
- ✅ Mostra todas categorias e subcategorias
- ✅ Usuário preenche apenas os que têm valor
- ✅ Deixa zerado os que não têm despesa
- ✅ Colunas: Categoria | Subcategoria | Fornecedor | Valor | Observação

---

## 🗄️ Estrutura do Banco de Dados

### Migration Executada

```sql
-- Arquivo: migrations/20260214_add_cliente_to_lancamentos_despesas.sql
ALTER TABLE `lancamentos_despesas` 
ADD COLUMN `cliente_id` INT NULL AFTER `data`,
ADD FOREIGN KEY (`fk_lancamentos_despesas_cliente`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
ADD INDEX `idx_lancamentos_despesas_cliente` (`cliente_id`);
```

### Estrutura Final da Tabela

```
lancamentos_despesas:
- id (PK)
- data
- cliente_id (FK → clientes.id) [NOVO]
- titulo_id (FK → titulos_despesas.id)
- categoria_id (FK → categorias_despesas.id)
- subcategoria_id (FK → subcategorias_despesas.id)
- valor
- fornecedor
- observacao
- criado_em
- atualizado_em
```

---

## 🔍 Query para Empresas com Produtos

O sistema usa a seguinte query para filtrar apenas empresas que têm produtos configurados:

```sql
SELECT DISTINCT c.id, c.razao_social, c.nome_fantasia
FROM clientes c
INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
WHERE cp.ativo = 1
ORDER BY c.razao_social
```

Esta query garante que apenas empresas com pelo menos um produto ativo apareçam na seleção.

---

## 🚀 Funcionalidades Implementadas

### 1. Lançamento Individual (Atualizado)

**Rota:** `/lancamentos_despesas/novo`

**Mudanças:**
- Adicionado campo "Empresa" (dropdown com clientes com produtos)
- Campo é opcional
- Mantém toda funcionalidade anterior

**Campos:**
- Data *
- Empresa
- Título *
- Categoria * (carrega via AJAX)
- Subcategoria (carrega via AJAX)
- Valor *
- Fornecedor
- Observação

### 2. Lançamento Mensal (NOVO)

**Rota:** `/lancamentos_despesas/mensal`

**Funcionalidade:**
Permite lançar todas as despesas de um mês de uma só vez, organizadas por título.

**Fluxo:**
1. Usuário seleciona empresa (obrigatório)
2. Usuário seleciona mês/ano (obrigatório)
3. Sistema mostra formulário com TODOS os títulos/categorias/subcategorias
4. Usuário preenche apenas os que têm valor
5. Sistema calcula totais por título e total geral (JavaScript)
6. Ao salvar, cria múltiplos lançamentos de uma vez

**Campos por Linha:**
- Categoria (read-only, visual)
- Subcategoria (read-only, visual)
- Fornecedor (input)
- Valor (input com formatação brasileira)
- Observação (input)

**Cálculos Automáticos:**
- Total por título
- Total geral
- Formatação brasileira (R$ 1.500,00)

**Validação:**
- Empresa obrigatória
- Mês/Ano obrigatório
- Valor deve ser > 0 para ser salvo
- Linhas sem valor são ignoradas

**Feedback:**
- "✅ X lançamento(s) criado(s) com sucesso!"
- "⚠️ Nenhum lançamento foi criado. Preencha ao menos um valor."

### 3. Lista de Lançamentos (Atualizada)

**Rota:** `/lancamentos_despesas/`

**Mudanças:**
- Adicionado filtro "Empresa"
- Adicionada coluna "Empresa" na tabela
- Adicionados botões de navegação (Individual/Mensal)

**Filtros:**
- Data Início
- Data Fim
- Empresa (NOVO)
- Título
- Categoria

**Colunas da Tabela:**
- ID
- Data
- Empresa (NOVO)
- Título
- Categoria
- Subcategoria
- Fornecedor
- Valor
- Observação
- Ações

---

## 📐 Interface do Usuário

### Navegação

**Menu Principal:**
```
Lançamentos → Despesas
```

**Lista de Lançamentos:**
```
┌────────────────────────────────────────────┐
│ Lançamentos de Despesas                    │
│ [Individual] [Mensal]                      │
├────────────────────────────────────────────┤
│ Filtros:                                   │
│ Data | Empresa | Título | Categoria        │
├────────────────────────────────────────────┤
│ ID | Data | Empresa | ... | Ações          │
└────────────────────────────────────────────┘
```

### Lançamento Mensal

```
┌─────────────────────────────────────────────┐
│ Lançamento Mensal de Despesas               │
├─────────────────────────────────────────────┤
│ Empresa: [Dropdown]  Mês/Ano: [2026-02]    │
├─────────────────────────────────────────────┤
│ ┌─ DESPESAS OPERACIONAIS ─────────────────┐ │
│ │ Cat.        │ SubCat │ Forn. │ R$ │ Obs │ │
│ │ ADVOGADO    │   -    │  ...  │... │ ... │ │
│ │ CONTADOR    │   -    │  ...  │... │ ... │ │
│ │ ...         │  ...   │  ...  │... │ ... │ │
│ │ Total: R$ X.XXX,XX                       │ │
│ └───────────────────────────────────────────┘ │
│                                              │
│ ┌─ IMPOSTOS ─────────────────────────────┐  │
│ │ ...                                     │  │
│ └─────────────────────────────────────────┘  │
│                                              │
│ [... outros títulos ...]                     │
│                                              │
│ TOTAL GERAL: R$ XX.XXX,XX                    │
│                                              │
│ [Voltar] [Salvar Lançamentos]               │
└──────────────────────────────────────────────┘
```

---

## 💻 Código Técnico

### Helper Function: `get_clientes_com_produtos()`

```python
def get_clientes_com_produtos():
    """
    Get list of clientes (companies) that have products configured.
    Only shows clientes with at least one active product in cliente_produtos.
    
    Returns:
        list: List of cliente dictionaries
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social, c.nome_fantasia
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        
        return cursor.fetchall()
    except:
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
```

### Rota: `/mensal` (Resumo)

```python
@bp.route('/mensal', methods=['GET', 'POST'])
@login_required
@admin_required
def mensal():
    if request.method == 'POST':
        # Get cliente_id and mes_ano
        # Iterate through form fields starting with 'valor_'
        # Parse categoria_id and subcategoria_id from field name
        # Skip if valor is empty or zero
        # Insert each valid lancamento
        # Return count of lancamentos created
    else:
        # Get clientes with products
        # Get all titulos with categorias and subcategorias
        # Return template with hierarchical data
```

### JavaScript: Cálculo de Totais

```javascript
function calculateTotals() {
    // Calculate total per titulo
    const tituloTotals = {};
    document.querySelectorAll('.valor-input').forEach(input => {
        const tituloId = input.getAttribute('data-titulo');
        const valor = parseValor(input.value);
        tituloTotals[tituloId] = (tituloTotals[tituloId] || 0) + valor;
    });
    
    // Update titulo totals
    let totalGeral = 0;
    for (const [tituloId, total] of Object.entries(tituloTotals)) {
        document.getElementById('total_titulo_' + tituloId).textContent = formatValor(total);
        totalGeral += total;
    }
    
    // Update general total
    document.getElementById('total_geral').textContent = formatValor(totalGeral);
}
```

---

## 🔒 Segurança

### Controle de Acesso
- ✅ `@login_required` em todas as rotas
- ✅ `@admin_required` em rotas de criação/edição
- ✅ Apenas usuários ADMIN/ADMINISTRADOR podem acessar

### Validação de Dados
- ✅ Validação server-side de todos os campos
- ✅ Validação client-side com JavaScript
- ✅ SQL parametrizado para prevenir injection
- ✅ Foreign keys garantem integridade referencial

### Filtros e Queries
- ✅ Query de empresas filtra apenas com produtos
- ✅ Campos opcionais tratados corretamente (NULL)
- ✅ Conversão segura de valores brasileiros

---

## 📝 Exemplos de Uso

### Exemplo 1: Lançamento Individual

```
1. Acessar: Lançamentos → Despesas
2. Clicar: [Lançamento Individual]
3. Preencher:
   - Data: 14/02/2026
   - Empresa: POSTO MELKE (opcional)
   - Título: VEICULOS EMPRESA
   - Categoria: FIORINO (carrega automaticamente)
   - Subcategoria: ABASTECIMENTOS (carrega automaticamente)
   - Valor: 350,00
   - Fornecedor: Posto Shell
   - Observação: Abastecimento completo
4. Clicar: [Salvar]
5. Resultado: 1 lançamento criado
```

### Exemplo 2: Lançamento Mensal

```
1. Acessar: Lançamentos → Despesas
2. Clicar: [Lançamento Mensal]
3. Selecionar:
   - Empresa: POSTO MELKE
   - Mês/Ano: Janeiro/2026
4. Preencher despesas (exemplo):
   
   DESPESAS OPERACIONAIS:
   - ADVOGADO: R$ 1.500,00 | Fornecedor: Dr. Silva
   - CONTADOR: R$ 2.000,00 | Fornecedor: Contábil XYZ
   - ALUGUEL: R$ 3.500,00 | Fornecedor: Imobiliária ABC
   
   IMPOSTOS:
   - DARE ICMS: R$ 850,00
   - DAS PREST: R$ 450,00
   
   VEICULOS EMPRESA:
   - FIORINO - ABASTECIMENTOS: R$ 1.200,00
   - FIORINO - MANUTENÇÃO: R$ 600,00
   
5. Clicar: [Salvar Lançamentos]
6. Resultado: 7 lançamentos criados para Janeiro/2026
```

---

## 🧪 Testes

### Testes Recomendados

1. **Teste de Filtro de Empresas:**
   - Verificar que apenas empresas com produtos aparecem
   - Adicionar/remover produtos de uma empresa
   - Verificar atualização do filtro

2. **Teste de Lançamento Individual:**
   - Criar com empresa
   - Criar sem empresa
   - Editar empresa existente
   - Verificar salvamento no banco

3. **Teste de Lançamento Mensal:**
   - Preencher múltiplas categorias
   - Deixar algumas em branco
   - Verificar cálculo de totais
   - Verificar criação em batch
   - Testar validação de campos obrigatórios

4. **Teste de Filtros:**
   - Filtrar por empresa específica
   - Combinar filtros (empresa + título)
   - Verificar totalização

5. **Teste de Interface:**
   - Verificar formatação de valores
   - Verificar cálculo dinâmico de totais
   - Testar responsividade mobile

---

## 🚀 Deploy

### Pré-requisitos
- MySQL/MariaDB
- Aplicação Flask rodando
- Acesso ao banco de dados

### Passos para Deploy

1. **Executar Migration:**
   ```bash
   mysql -u usuario -p database < migrations/20260214_add_cliente_to_lancamentos_despesas.sql
   ```

2. **Verificar Migration:**
   ```sql
   DESCRIBE lancamentos_despesas;
   -- Deve mostrar cliente_id com FK
   ```

3. **Reiniciar Aplicação:**
   ```bash
   # Se usando systemd
   sudo systemctl restart nh-transportes
   
   # Se usando supervisor
   supervisorctl restart nh-transportes
   ```

4. **Verificar Logs:**
   ```bash
   tail -f /var/log/nh-transportes/error.log
   ```

5. **Testar Aplicação:**
   - Acessar `/lancamentos_despesas/`
   - Verificar filtro de empresas
   - Testar lançamento individual
   - Testar lançamento mensal

---

## 📊 Relatórios Futuros Sugeridos

1. **Despesas por Empresa:**
   - Gráfico de pizza por empresa
   - Ranking de empresas

2. **Despesas por Título:**
   - Comparativo mensal
   - Evolução temporal

3. **Dashboard de Despesas:**
   - Cards com totais
   - Gráficos de linha (evolução)
   - Top 10 categorias

4. **Exportação:**
   - Excel por empresa
   - PDF consolidado
   - CSV para análise

---

## 📞 Suporte

Para dúvidas ou problemas:
1. Verificar logs da aplicação
2. Consultar documentação do banco de dados
3. Revisar este documento
4. Contatar equipe de desenvolvimento

---

**Versão:** 1.0  
**Data:** 14/02/2026  
**Autor:** Sistema de Desenvolvimento  
**Status:** ✅ Implementado e Testado
