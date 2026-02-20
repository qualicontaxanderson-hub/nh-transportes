# Interface do Sistema de Despesas - Documentação Visual

## 📱 Páginas Implementadas

### 1. Página Principal - Lista de Títulos (`/despesas/`)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ Dashboard > Despesas                                                          ║
║                                                                               ║
║ 🏦 Gestão de Despesas                           [+ Novo Título]              ║
║                                                                               ║
║ ┌─────────────────────────────────┬─────────────────────────────────┐       ║
║ │ 📁 DESPESAS OPERACIONAIS        │ 📁 IMPOSTOS                      │       ║
║ │ Despesas operacionais da empresa│ Impostos e taxas governamentais  │       ║
║ │ [24 categoria(s)]               │ [12 categoria(s)]                │       ║
║ │                [Ver Categorias >]│                [Ver Categorias >]│       ║
║ └─────────────────────────────────┴─────────────────────────────────┘       ║
║                                                                               ║
║ ┌─────────────────────────────────┬─────────────────────────────────┐       ║
║ │ 📁 FINANCEIRO                   │ 📁 DESPESAS POSTO                │       ║
║ │ Despesas financeiras e bancárias│ Despesas do posto de combustível │       ║
║ │ [8 categoria(s)]                │ [8 categoria(s)]                 │       ║
║ │                [Ver Categorias >]│                [Ver Categorias >]│       ║
║ └─────────────────────────────────┴─────────────────────────────────┘       ║
║                                                                               ║
║ ... (mais 5 títulos)                                                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**Características:**
- Cards responsivos (3 colunas em telas grandes, 2 em médias, 1 em pequenas)
- Hover effect para melhor feedback visual
- Contador de categorias em cada título
- Botões de editar/excluir para admin (no canto superior direito de cada card)

---

### 2. Detalhes do Título - Lista de Categorias (`/despesas/titulo/1`)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ Dashboard > Despesas > DESPESAS OPERACIONAIS                                 ║
║                                                                               ║
║ 📁 DESPESAS OPERACIONAIS                        [+ Nova Categoria]           ║
║                                                                               ║
║ ℹ Despesas operacionais da empresa                                           ║
║                                                                               ║
║ ┌──────────────────────────────────────────────────────────────────────────┐ ║
║ │ Categorias                                                                │ ║
║ ├──────────────────────┬───────────────┬──────┬────────────────────────────┤ ║
║ │ Nome                 │ Subcategorias │ Ordem│ Ações                       │ ║
║ ├──────────────────────┼───────────────┼──────┼────────────────────────────┤ ║
║ │ 📁 ADVOGADO          │ 0             │ 1    │ [👁][✏][🗑]                │ ║
║ │ 📁 CONTADOR          │ 0             │ 2    │ [👁][✏][🗑]                │ ║
║ │ 📁 ALUGUEL           │ 0             │ 3    │ [👁][✏][🗑]                │ ║
║ │ ...                  │ ...           │ ...  │ ...                         │ ║
║ │ 📁 TELEFONE MÓVEL    │ 0             │ 23   │ [👁][✏][🗑]                │ ║
║ │ 📁 PROPAGANDAS       │ 0             │ 24   │ [👁][✏][🗑]                │ ║
║ └──────────────────────┴───────────────┴──────┴────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**Características:**
- Tabela responsiva com todas as categorias
- Contador de subcategorias
- Campo ordem para organização
- Botões de ação: Ver (👁), Editar (✏), Excluir (🗑)
- Links clicáveis para navegar às subcategorias

---

### 3. Detalhes da Categoria - Lista de Subcategorias (`/despesas/categoria/50`)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ Dashboard > Despesas > CAMINHÕES > VEICULO CARRETA MODELO SCANIA R500        ║
║                                                                               ║
║ 📁 VEICULO CARRETA MODELO SCANIA R500            [+ Nova Subcategoria]       ║
║                                                                               ║
║ ┌──────────────────────────────────────────────────────────────────────────┐ ║
║ │ Subcategorias                                                             │ ║
║ ├────────────────────────────────┬──────┬───────────────────────────────────┤ ║
║ │ Nome                           │ Ordem│ Ações                              │ ║
║ ├────────────────────────────────┼──────┼───────────────────────────────────┤ ║
║ │ 🏷 FATURAMENTO DO VEICULOS     │ 1    │ [✏][🗑]                           │ ║
║ │ 🏷 MOTORISTA                   │ 2    │ [✏][🗑]                           │ ║
║ │ 🏷 MOTORISTA ADICIONAL         │ 3    │ [✏][🗑]                           │ ║
║ │ 🏷 COMISSÃO DO MOTORISTA       │ 4    │ [✏][🗑]                           │ ║
║ │ 🏷 FGTS                        │ 5    │ [✏][🗑]                           │ ║
║ │ ...                            │ ...  │ ...                                │ ║
║ │ 🏷 SEGURO                      │ 19   │ [✏][🗑]                           │ ║
║ └────────────────────────────────┴──────┴───────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**Características:**
- Lista completa de subcategorias
- Possibilidade de editar e excluir
- Organização por ordem
- Breadcrumb mostra caminho completo

---

### 4. Formulário de Título (`/despesas/titulos/novo`)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ Dashboard > Despesas > Novo Título                                            ║
║                                                                               ║
║ ┌──────────────────────────────────────────────────────────────────────────┐ ║
║ │ 📁 Novo Título de Despesa                                                 │ ║
║ ├──────────────────────────────────────────────────────────────────────────┤ ║
║ │                                                                           │ ║
║ │ Nome do Título *                                                          │ ║
║ │ ┌───────────────────────────────────┐  Ordem                             │ ║
║ │ │                                   │  ┌──────┐                           │ ║
║ │ └───────────────────────────────────┘  │  0   │                           │ ║
║ │                                        └──────┘                           │ ║
║ │ Descrição                                                                 │ ║
║ │ ┌───────────────────────────────────────────────────────────┐             │ ║
║ │ │                                                           │             │ ║
║ │ │                                                           │             │ ║
║ │ └───────────────────────────────────────────────────────────┘             │ ║
║ │                                                                           │ ║
║ │ [← Voltar]                                          [💾 Salvar]           │ ║
║ └──────────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**Características:**
- Formulário limpo e intuitivo
- Campo ordem para organização
- Validação de campos obrigatórios (*)
- Botões de ação claros

---

### 5. Formulário de Categoria (`/despesas/categorias/nova?titulo_id=1`)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ Dashboard > Despesas > Nova Categoria                                         ║
║                                                                               ║
║ ┌──────────────────────────────────────────────────────────────────────────┐ ║
║ │ 📁 Nova Categoria de Despesa                                              │ ║
║ ├──────────────────────────────────────────────────────────────────────────┤ ║
║ │                                                                           │ ║
║ │ Título *                                                                  │ ║
║ │ ┌───────────────────────────────────────┐                                │ ║
║ │ │ DESPESAS OPERACIONAIS ▼               │                                │ ║
║ │ └───────────────────────────────────────┘                                │ ║
║ │                                                                           │ ║
║ │ Nome da Categoria *                       Ordem                           │ ║
║ │ ┌───────────────────────────────────┐  ┌──────┐                          │ ║
║ │ │                                   │  │  0   │                          │ ║
║ │ └───────────────────────────────────┘  └──────┘                          │ ║
║ │                                                                           │ ║
║ │ [← Voltar]                                          [💾 Salvar]           │ ║
║ └──────────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**Características:**
- Dropdown com todos os títulos disponíveis
- Pré-seleção do título quando vindo de uma página de título
- Campos de validação

---

### 6. Formulário de Subcategoria (`/despesas/subcategorias/nova?categoria_id=50`)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║ Dashboard > Despesas > Nova Subcategoria                                      ║
║                                                                               ║
║ ┌──────────────────────────────────────────────────────────────────────────┐ ║
║ │ 🏷 Nova Subcategoria de Despesa                                           │ ║
║ ├──────────────────────────────────────────────────────────────────────────┤ ║
║ │                                                                           │ ║
║ │ ℹ Criando subcategoria para: CAMINHÕES > VEICULO CARRETA MODELO SCANIA   │ ║
║ │                                                                           │ ║
║ │ Categoria *                                                               │ ║
║ │ ┌───────────────────────────────────────────────────────────┐            │ ║
║ │ │ CAMINHÕES > VEICULO CARRETA MODELO SCANIA R500 ▼          │            │ ║
║ │ └───────────────────────────────────────────────────────────┘            │ ║
║ │                                                                           │ ║
║ │ Nome da Subcategoria *                Ordem                               │ ║
║ │ ┌───────────────────────────────────┐  ┌──────┐                          │ ║
║ │ │                                   │  │  0   │                          │ ║
║ │ └───────────────────────────────────┘  └──────┘                          │ ║
║ │                                                                           │ ║
║ │ [← Voltar]                                          [💾 Salvar]           │ ║
║ └──────────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**Características:**
- Alert informativo mostrando caminho completo
- Dropdown com formato "Título > Categoria"
- Pré-seleção quando vindo de uma categoria específica

---

## 🎨 Design e UX

### Paleta de Cores
- **Primário**: #1D63A5 (Azul NH Transportes)
- **Sucesso**: #28a745 (Verde)
- **Atenção**: #ffc107 (Amarelo)
- **Perigo**: #dc3545 (Vermelho)
- **Info**: #17a2b8 (Ciano)

### Ícones (Bootstrap Icons)
- 📁 `bi-folder-fill` - Títulos
- 📁 `bi-folder` - Categorias
- 🏷 `bi-tag` - Subcategorias
- 👁 `bi-eye` - Ver
- ✏ `bi-pencil` - Editar
- 🗑 `bi-trash` - Excluir
- 💾 `bi-save` - Salvar
- ➕ `bi-plus-circle` - Adicionar

### Responsividade
- **Desktop (>1200px)**: 3 colunas de cards
- **Tablet (768px-1199px)**: 2 colunas de cards
- **Mobile (<768px)**: 1 coluna, menu hambúrguer

### Animações
- Hover em cards: Elevação suave (translateY -4px)
- Transições: 0.2s ease
- Feedbacks visuais em botões

---

## 📱 Acesso ao Menu

### Navbar - Dropdown "Cadastros"
```
┌─────────────────────────────────────────┐
│ ⚙ Cadastros ▼                           │
├─────────────────────────────────────────┤
│ 👤 Clientes                              │
│ 🏢 Fornecedores                          │
│ 📦 Produtos                              │
│ 👨‍✈️ Motoristas                            │
│ 🚚 Veículos                              │
│ 🗺 Origens/Destinos                      │
│ ───────────────────────────────────────  │
│ 💰 Despesas                        ◄─────┤ NOVO!
│ 👥 Funcionários                          │
│ 🏷 Categorias Funcionários               │
│ 📋 Rubricas                              │
│ ───────────────────────────────────────  │
│ 💳 Cartões                               │
│ ... (outros itens)                       │
└─────────────────────────────────────────┘
```

**Posição**: Acima de "Funcionários" conforme especificado

---

## ✨ Feedback do Usuário

### Mensagens de Sucesso
```
✓ Título criado com sucesso!
✓ Categoria atualizada com sucesso!
✓ Subcategoria desativada com sucesso!
```

### Confirmações
```
⚠ Tem certeza que deseja desativar este título?
⚠ Tem certeza que deseja desativar esta categoria?
```

### Estados Vazios
```
ℹ Nenhum título de despesa cadastrado ainda.
  Clique aqui para criar o primeiro título.
```

---

## 🔄 Fluxo de Navegação

```
Dashboard
   │
   └─> Despesas (Lista de Títulos)
          │
          ├─> Ver Título (DESPESAS OPERACIONAIS)
          │      │
          │      ├─> Ver Categoria (ADVOGADO)
          │      │      └─> (sem subcategorias)
          │      │
          │      └─> Editar Categoria
          │             └─> Voltar ao Título
          │
          ├─> Ver Título (CAMINHÕES)
          │      │
          │      └─> Ver Categoria (SCANIA R500)
          │             │
          │             ├─> Ver Subcategorias (19 items)
          │             │      └─> Editar Subcategoria
          │             │             └─> Voltar à Categoria
          │             │
          │             └─> Nova Subcategoria
          │                    └─> Salvar → Voltar à Categoria
          │
          ├─> Novo Título
          │      └─> Salvar → Lista de Títulos
          │
          └─> Editar Título
                 └─> Salvar → Lista de Títulos
```

---

**Nota**: Esta é uma representação em ASCII. A interface real usa Bootstrap 5 com estilos modernos e responsivos.
