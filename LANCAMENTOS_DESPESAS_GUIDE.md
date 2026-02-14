# Sistema de Lançamento de Despesas

## 📋 Visão Geral

O sistema de Lançamento de Despesas permite registrar, gerenciar e acompanhar todas as despesas da empresa de forma organizada e hierárquica.

## 🏗️ Estrutura Hierárquica

O sistema utiliza uma estrutura de 3 níveis:

```
Título de Despesa
    ↓
Categoria
    ↓
Subcategoria (opcional)
```

**Exemplo:**
```
VEICULOS EMPRESA (Título)
    └── FIORINO (Categoria)
        ├── DOCUMENTOS IPVA/MULTA (Subcategoria)
        ├── ABASTECIMENTOS (Subcategoria)
        └── MANUTENÇÃO (Subcategoria)
```

## 🚀 Funcionalidades

### 1. Listar Lançamentos
**URL:** `/lancamentos_despesas/`

**Características:**
- ✅ Visualização em tabela responsiva
- ✅ Filtros por:
  - Data início e fim
  - Título
  - Categoria
- ✅ Totalização automática
- ✅ 9 colunas de informação:
  - ID
  - Data
  - Título
  - Categoria
  - Subcategoria
  - Fornecedor
  - Valor (formatado R$)
  - Observação
  - Ações (Editar, Excluir)

**Exemplo de Uso:**
```
Filtrar despesas de 01/01/2026 a 31/01/2026
Título: VEICULOS EMPRESA
Categoria: FIORINO
→ Ver total gasto com Fiorino em janeiro
```

### 2. Novo Lançamento
**URL:** `/lancamentos_despesas/novo`

**Campos do Formulário:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| Data | Date | Sim | Data da despesa |
| Título | Select | Sim | Título hierárquico |
| Categoria | Select | Sim | Categoria dentro do título |
| Subcategoria | Select | Não | Subcategoria (se existir) |
| Valor | Text | Sim | Valor em formato brasileiro (1.500,00) |
| Fornecedor | Text | Não | Nome do fornecedor ou prestador |
| Observação | Textarea | Não | Detalhes adicionais |

**Seleção Hierárquica Dinâmica:**

1. Seleciona Título → Carrega Categorias via AJAX
2. Seleciona Categoria → Carrega Subcategorias via AJAX
3. Subcategoria é opcional

**Exemplo:**
```javascript
// Ao selecionar "VEICULOS EMPRESA"
→ Categorias disponíveis: FIORINO, POP

// Ao selecionar "FIORINO"  
→ Subcategorias disponíveis: DOCUMENTOS, ABASTECIMENTOS, MANUTENÇÃO

// Pode deixar subcategoria vazia se não precisar
```

### 3. Editar Lançamento
**URL:** `/lancamentos_despesas/editar/<id>`

**Características:**
- ✅ Pré-preenchimento de todos os campos
- ✅ Mantém seleções hierárquicas
- ✅ Mesmo sistema dinâmico do formulário novo
- ✅ Atualização preserva histórico (atualizado_em)

### 4. Excluir Lançamento
**URL:** `POST /lancamentos_despesas/excluir/<id>`

**Características:**
- ✅ Confirmação antes de excluir
- ✅ Exclusão física do registro
- ✅ Mensagem de feedback

## 🔧 Arquitetura Técnica

### Banco de Dados

**Tabela:** `lancamentos_despesas`

```sql
CREATE TABLE lancamentos_despesas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data DATE NOT NULL,
    titulo_id INT NOT NULL,
    categoria_id INT NOT NULL,
    subcategoria_id INT NULL,
    valor DECIMAL(10, 2) NOT NULL,
    fornecedor VARCHAR(255) NULL,
    observacao TEXT NULL,
    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
    atualizado_em DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (titulo_id) REFERENCES titulos_despesas(id),
    FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id),
    FOREIGN KEY (subcategoria_id) REFERENCES subcategorias_despesas(id)
);
```

**Índices:**
- `idx_lancamentos_despesas_data` - Para filtros por data
- `idx_lancamentos_despesas_titulo` - Para filtros por título
- `idx_lancamentos_despesas_categoria` - Para filtros por categoria
- `idx_lancamentos_despesas_subcategoria` - Para joins

### APIs Internas

#### 1. API de Categorias
```
GET /lancamentos_despesas/api/categorias/<titulo_id>
```

**Resposta:**
```json
[
    {"id": 1, "nome": "FIORINO"},
    {"id": 2, "nome": "POP"}
]
```

#### 2. API de Subcategorias
```
GET /lancamentos_despesas/api/subcategorias/<categoria_id>
```

**Resposta:**
```json
[
    {"id": 1, "nome": "DOCUMENTOS IPVA/MULTA"},
    {"id": 2, "nome": "ABASTECIMENTOS"},
    {"id": 3, "nome": "MANUTENÇÃO"}
]
```

### Helpers

#### parse_brazilian_currency()
Converte valores brasileiros para Decimal:

```python
parse_brazilian_currency("1.500,00") → Decimal("1500.00")
parse_brazilian_currency("R$ 2.000,50") → Decimal("2000.50")
```

#### validate_lancamento_input()
Valida campos obrigatórios:

```python
validate_lancamento_input(data, titulo_id, categoria_id, valor)
→ (is_valid: bool, errors: list)
```

## 📊 Fluxo de Uso

### Cenário: Registrar Abastecimento da Fiorino

```
1. Acessa: Lançamentos → Despesas
2. Clica: "Novo Lançamento"
3. Preenche:
   - Data: 14/02/2026
   - Título: VEICULOS EMPRESA
   - Categoria: FIORINO (carrega automaticamente)
   - Subcategoria: ABASTECIMENTOS (carrega automaticamente)
   - Valor: 350,00
   - Fornecedor: Posto Shell BR-153
   - Observação: Abastecimento completo
4. Clica: "Salvar"
5. Retorna para lista com mensagem de sucesso
```

### Cenário: Filtrar Despesas de Veículos

```
1. Acessa: Lançamentos → Despesas
2. Na seção "Filtros":
   - Data Início: 01/01/2026
   - Data Fim: 31/01/2026
   - Título: VEICULOS EMPRESA
   - Categoria: (Todas)
3. Clica: "Filtrar"
4. Ver tabela filtrada com total no header
5. Exportar ou analisar dados
```

## 🎨 Interface

### Lista de Lançamentos

```
┌────────────────────────────────────────────────────────────────┐
│ 🪙 Lançamentos de Despesas          [➕ Novo Lançamento]      │
├────────────────────────────────────────────────────────────────┤
│ 🔍 Filtros                                                      │
│   Data Início: [____] Data Fim: [____]                         │
│   Título: [VEICULOS EMPRESA ▼] Categoria: [FIORINO ▼]         │
│   [🔎 Filtrar] [✖ Limpar]                                     │
├────────────────────────────────────────────────────────────────┤
│ 📋 Lista de Lançamentos              Total: R$ 15.847,32       │
│                                                                 │
│ ID | Data | Título | Categoria | Subcat | Fornec | Valor      │
│ 15 | 14/02| VEIC.. | FIORINO   | ABAST  | Shell  | R$ 350,00  │
│ 14 | 12/02| VEIC.. | FIORINO   | MANUT  | Mecâni | R$ 1.200,00│
│ 13 | 10/02| VEIC.. | POP       | ABAST  | BR     | R$ 280,50  │
└────────────────────────────────────────────────────────────────┘
```

### Formulário Novo Lançamento

```
┌────────────────────────────────────────────────────────────────┐
│ ➕ Novo Lançamento de Despesa                                  │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Data *          Título *              Categoria *               │
│ [14/02/2026]    [VEICULOS EMPRESA ▼]  [FIORINO ▼]             │
│                                                                 │
│ Subcategoria                                                    │
│ [ABASTECIMENTOS ▼] (Opcional)                                  │
│                                                                 │
│ Valor *                  Fornecedor                            │
│ [350,00]                 [Posto Shell BR-153____________]       │
│ Formato: 1.500,00                                              │
│                                                                 │
│ Observação                                                      │
│ [Abastecimento completo com gasolina premium           ]       │
│ [________________________________________________]              │
│                                                                 │
│ [⬅ Voltar]                              [💾 Salvar]           │
└────────────────────────────────────────────────────────────────┘
```

## 🔒 Segurança

### Controle de Acesso
- ✅ Apenas usuários **ADMIN** têm acesso
- ✅ Decorator `@admin_required` em todas as rotas
- ✅ Verificação também nos templates
- ✅ Menu visível apenas para ADMIN

### Validação
- ✅ Validação server-side de todos os campos
- ✅ Validação client-side para UX
- ✅ SQL parametrizado (previne injection)
- ✅ Sanitização de inputs

### Integridade
- ✅ Foreign keys garantem relacionamentos válidos
- ✅ Não permite excluir títulos/categorias com lançamentos
- ✅ Valores sempre em formato decimal correto

## 📈 Relatórios e Análises

### Possíveis Análises

1. **Total por Título:**
```sql
SELECT t.nome, SUM(ld.valor) as total
FROM lancamentos_despesas ld
JOIN titulos_despesas t ON ld.titulo_id = t.id
WHERE ld.data BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY t.nome;
```

2. **Total por Categoria:**
```sql
SELECT c.nome, SUM(ld.valor) as total
FROM lancamentos_despesas ld
JOIN categorias_despesas c ON ld.categoria_id = c.id
WHERE ld.data BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY c.nome;
```

3. **Despesas por Veículo:**
```sql
SELECT c.nome as veiculo, 
       s.nome as tipo,
       SUM(ld.valor) as total
FROM lancamentos_despesas ld
JOIN titulos_despesas t ON ld.titulo_id = t.id
JOIN categorias_despesas c ON ld.categoria_id = c.id
LEFT JOIN subcategorias_despesas s ON ld.subcategoria_id = s.id
WHERE t.nome = 'VEICULOS EMPRESA'
  AND ld.data BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY c.nome, s.nome;
```

## 🚀 Próximos Passos (Futuras Melhorias)

### Possíveis Extensões:

1. **Dashboard de Despesas:**
   - Gráficos de pizza por título
   - Evolução temporal
   - Comparação mensal

2. **Exportação:**
   - Excel/CSV
   - PDF com totalizações
   - Relatórios customizados

3. **Anexos:**
   - Upload de notas fiscais
   - Comprovantes de pagamento
   - Fotos de recibos

4. **Aprovação:**
   - Workflow de aprovação
   - Histórico de alterações
   - Comentários em lançamentos

5. **Integração:**
   - Integração com contas a pagar
   - Vinculação com fornecedores
   - Alertas de vencimento

## 📞 Suporte

Para dúvidas ou problemas:
1. Verificar se a migration foi executada
2. Conferir permissões de ADMIN
3. Verificar logs do Flask
4. Consultar documentação adicional

## ✅ Checklist de Deploy

- [ ] Executar migration `20260214_add_lancamentos_despesas.sql`
- [ ] Verificar que blueprint foi registrado
- [ ] Testar acesso ao menu (apenas ADMIN deve ver)
- [ ] Testar criação de lançamento
- [ ] Testar filtros
- [ ] Testar edição
- [ ] Testar exclusão
- [ ] Verificar totalização
- [ ] Testar seleção hierárquica (AJAX)

---

**Versão:** 1.0  
**Data:** 14/02/2026  
**Status:** ✅ Implementado e Funcional
