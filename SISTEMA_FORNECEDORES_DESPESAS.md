# Sistema de Fornecedores de Despesas

## 📋 Visão Geral

Sistema completo para cadastrar e gerenciar fornecedores vinculados a categorias específicas de despesas. Os fornecedores aparecem filtrados por categoria no lançamento mensal de despesas.

---

## 🎯 Problema Resolvido

**Antes:**
- Campo "Fornecedor" era texto livre
- Usuário digitava manualmente toda vez
- Erros de digitação e inconsistências
- Difícil padronizar nomes de fornecedores

**Agora:**
- Campo "Fornecedor" é dropdown com seleção
- Fornecedores pré-cadastrados
- Filtrados automaticamente por categoria
- Padronização e consistência total
- Opção de criar rapidamente sem sair da tela

---

## 🏗️ Arquitetura

### Banco de Dados

```sql
CREATE TABLE despesas_fornecedores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(200) NOT NULL,
    categoria_id INT NOT NULL,
    ativo TINYINT(1) DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id),
    INDEX idx_despesas_fornecedores_categoria (categoria_id),
    INDEX idx_despesas_fornecedores_ativo (ativo)
);
```

### Relacionamentos

```
titulos_despesas (DESPESAS OPERACIONAIS)
  └─ categorias_despesas (ADVOGADO)
       └─ despesas_fornecedores (Silva Advogados, Costa & Assoc.)
```

**Regra:** Cada fornecedor pertence a UMA categoria específica.

---

## 🚀 Funcionalidades

### 1. Cadastro de Fornecedores

**Caminho:** Menu → Cadastros → Despesas Fornecedor

**Ações disponíveis:**
- ✅ Listar todos os fornecedores
- ✅ Criar novo fornecedor
- ✅ Editar fornecedor existente
- ✅ Desativar fornecedor (soft delete)

**Campos do Formulário:**
- **Nome:** Nome completo ou razão social (obrigatório, max 200 chars)
- **Categoria:** Dropdown agrupado por títulos (obrigatório)

**Validação:**
- Não permite duplicatas (mesmo nome + mesma categoria)
- Categoria deve estar ativa
- Nome não pode ser vazio

### 2. Lançamento Mensal com Dropdown

**Caminho:** Menu → Lançamentos → Despesas (Mensal)

**Interface atualizada:**

```
┌──────────────────────────────────────────────────┐
│ Categoria    | Subcategoria | Fornecedor    | R$ │
│──────────────────────────────────────────────────│
│ ADVOGADO     | -            | [Select ▼][+] | .. │
│                               └─ Silva Advogados  │
│                               └─ Costa & Assoc.   │
│                               └─ Juridico XYZ     │
├──────────────────────────────────────────────────┤
│ CONTADOR     | -            | [Select ▼][+] | .. │
│                               └─ Contador Silva   │
│                               └─ Contábil ABC     │
└──────────────────────────────────────────────────┘
```

**Características:**
- Dropdown carrega apenas fornecedores da categoria atual
- AJAX: carregamento automático ao abrir a página
- Botão [+]: criar novo fornecedor sem sair da tela
- Filtro por categoria: cada categoria mostra apenas seus fornecedores

### 3. Criação Rápida Inline

**Funcionamento:**

1. Usuário clica no botão [+] ao lado do dropdown
2. Aparece prompt: "Digite o nome do fornecedor"
3. Usuário digita o nome (ex: "Novo Advogado LTDA")
4. Sistema cria via API
5. Dropdown recarrega automaticamente
6. Novo fornecedor já está disponível

**Benefícios:**
- Não precisa sair da tela de lançamento
- Cadastro instantâneo
- Workflow mais fluido

---

## 💻 Código Técnico

### Routes

**Arquivo:** `routes/despesas_fornecedores.py`

#### Rotas principais:

```python
@bp.route('/')  # Lista
@bp.route('/novo')  # Criar
@bp.route('/editar/<int:id>')  # Editar
@bp.route('/excluir/<int:id>')  # Desativar
```

#### APIs internas:

```python
@bp.route('/api/por-categoria/<int:categoria_id>')
# Retorna fornecedores de uma categoria específica
# Usado pelo AJAX no lançamento mensal

@bp.route('/api/criar-rapido', methods=['POST'])
# Cria fornecedor rapidamente (inline)
# Recebe JSON: {nome, categoria_id}
# Retorna JSON: {success, id, nome, message}
```

### JavaScript

**Arquivo:** `templates/lancamentos_despesas/mensal.html`

#### Funções principais:

```javascript
// Carrega todos os fornecedores ao abrir a página
function loadAllFornecedores()

// Carrega fornecedores de uma categoria específica
function loadFornecedoresPorCategoria(categoriaId)

// Mostra prompt e cria fornecedor
function showAddFornecedorModal(categoriaId, categoriaNome)

// Envia requisição para criar fornecedor
function createFornecedor(categoriaId, nome)
```

#### Fluxo AJAX:

```
1. DOMContentLoaded
   ↓
2. loadAllFornecedores()
   ↓
3. Identifica categorias únicas
   ↓
4. Para cada categoria:
   → Chama loadFornecedoresPorCategoria()
   → Faz fetch para API
   → Popula dropdowns
```

---

## 📊 Exemplos de Uso

### Cenário 1: Cadastrar Fornecedores

**Passo a passo:**

1. Acessar: Menu → Cadastros → Despesas Fornecedor
2. Clicar em "Cadastrar Fornecedor"
3. Preencher:
   - Nome: "Escritório Silva Advogados"
   - Categoria: DESPESAS OPERACIONAIS → ADVOGADO
4. Clicar em "Salvar Fornecedor"
5. Fornecedor criado com sucesso!

**Repetir para outros fornecedores:**
- "Costa & Associados" (ADVOGADO)
- "Contador Silva" (CONTADOR)
- "Engenharia XYZ" (ENGENHEIRO)
- etc.

### Cenário 2: Lançamento Mensal

**Passo a passo:**

1. Acessar: Menu → Lançamentos → Despesas (Mensal)
2. Selecionar empresa e mês/ano
3. Na linha "ADVOGADO":
   - Dropdown mostra apenas:
     * Silva Advogados
     * Costa & Associados
   - Selecionar "Silva Advogados"
   - Preencher valor: R$ 3.500,00
4. Na linha "CONTADOR":
   - Dropdown mostra apenas:
     * Contador Silva
   - Selecionar "Contador Silva"
   - Preencher valor: R$ 1.200,00
5. Salvar lançamentos

**Resultado:**
- 2 lançamentos criados
- Cada um com fornecedor correto
- Dados padronizados

### Cenário 3: Criar Fornecedor Inline

**Situação:** Precisa lançar despesa mas fornecedor não existe

**Passo a passo:**

1. Está no lançamento mensal
2. Na linha "ENGENHEIRO"
3. Dropdown não tem o fornecedor desejado
4. Clicar no botão [+]
5. Digitar: "Engenharia Nova LTDA"
6. Confirmar
7. Sistema cria e recarrega dropdown
8. Selecionar o novo fornecedor
9. Continuar lançamento normalmente

---

## 🔍 Queries SQL Úteis

### Listar fornecedores por categoria

```sql
SELECT 
    df.id,
    df.nome as fornecedor,
    c.nome as categoria,
    t.nome as titulo
FROM despesas_fornecedores df
INNER JOIN categorias_despesas c ON df.categoria_id = c.id
INNER JOIN titulos_despesas t ON c.titulo_id = t.id
WHERE df.ativo = 1
  AND c.id = ?  -- ID da categoria
ORDER BY df.nome;
```

### Contar fornecedores por categoria

```sql
SELECT 
    t.nome as titulo,
    c.nome as categoria,
    COUNT(df.id) as total_fornecedores
FROM categorias_despesas c
INNER JOIN titulos_despesas t ON c.titulo_id = t.id
LEFT JOIN despesas_fornecedores df ON c.id = df.categoria_id AND df.ativo = 1
GROUP BY t.id, c.id
ORDER BY t.nome, c.nome;
```

### Fornecedores mais usados

```sql
SELECT 
    df.nome as fornecedor,
    c.nome as categoria,
    COUNT(ld.id) as total_lancamentos,
    SUM(ld.valor) as valor_total
FROM despesas_fornecedores df
INNER JOIN categorias_despesas c ON df.categoria_id = c.id
LEFT JOIN lancamentos_despesas ld ON ld.fornecedor = df.nome
WHERE df.ativo = 1
GROUP BY df.id
ORDER BY total_lancamentos DESC, valor_total DESC
LIMIT 10;
```

---

## 🔒 Segurança

### Controle de Acesso

- ✅ Apenas ADMIN pode acessar
- ✅ Decorator `@admin_required` em todas as rotas
- ✅ Verificação no template: `{% if nivel_usuario == 'ADMIN' %}`

### Validação de Dados

- ✅ Nome obrigatório (max 200 chars)
- ✅ Categoria obrigatória
- ✅ Verifica duplicatas antes de inserir
- ✅ SQL parametrizado (previne injection)
- ✅ Foreign keys garantem integridade

### Soft Delete

- ✅ Desativar (não deletar): `ativo = 0`
- ✅ Mantém histórico
- ✅ Pode reativar se necessário

---

## 📈 Benefícios

### Para Usuários

1. **Rapidez:** Selecionar é mais rápido que digitar
2. **Padronização:** Nomes sempre consistentes
3. **Menos erros:** Evita typos
4. **Facilidade:** Interface intuitiva
5. **Flexibilidade:** Criar inline quando necessário

### Para Gestão

1. **Controle:** Lista centralizada de fornecedores
2. **Análise:** Saber quais fornecedores são usados
3. **Relatórios:** Agrupar por fornecedor facilmente
4. **Auditoria:** Rastreamento completo
5. **Organização:** Fornecedores por categoria

### Para Sistema

1. **Performance:** Queries otimizadas com índices
2. **Integridade:** Foreign keys mantêm consistência
3. **Escalabilidade:** Suporta milhares de fornecedores
4. **Manutenção:** Código modular e organizado
5. **Extensibilidade:** Fácil adicionar features

---

## 🚀 Deploy

### 1. Migration

```bash
# Conectar ao banco
mysql -u usuario -p database_name

# Executar migration
source migrations/20260215_add_despesas_fornecedores.sql

# Verificar estrutura
DESCRIBE despesas_fornecedores;
```

### 2. Restart App

```bash
# Render.com faz deploy automático
# Ou manualmente:
sudo systemctl restart nh-transportes
```

### 3. Verificação

```bash
# 1. Testar acesso ao módulo
curl https://nh-transportes.onrender.com/despesas/fornecedores/

# 2. Testar API
curl https://nh-transportes.onrender.com/despesas/fornecedores/api/por-categoria/1

# 3. Verificar logs
tail -f /var/log/nh-transportes/app.log
```

### 4. Testes Funcionais

**Checklist:**

- [ ] Acessar lista de fornecedores
- [ ] Criar novo fornecedor
- [ ] Editar fornecedor existente
- [ ] Desativar fornecedor
- [ ] Verificar dropdown no lançamento mensal
- [ ] Testar filtro por categoria
- [ ] Criar fornecedor inline (botão +)
- [ ] Verificar AJAX funcionando
- [ ] Salvar lançamento com fornecedor selecionado

---

## 📝 Notas Técnicas

### Limitações Atuais

1. Fornecedor vinculado a uma categoria apenas
2. Não suporta múltiplas categorias por fornecedor
3. Dropdown não tem busca (nativo do select)

### Melhorias Futuras

1. **Select2/Chosen:** Dropdown com busca
2. **Modal Bootstrap:** Criar fornecedor em modal real (não prompt)
3. **Fornecedores globais:** Opção de criar fornecedor sem categoria
4. **Múltiplas categorias:** Um fornecedor em várias categorias
5. **Campos extras:** Telefone, email, CNPJ
6. **Histórico:** Ver quantos lançamentos usaram o fornecedor
7. **Import/Export:** Importar fornecedores via CSV
8. **Autocomplete:** Sugestões ao digitar

### Performance

- **Índices:** categoria_id, ativo
- **Cache:** Pode adicionar cache para lista de fornecedores
- **Lazy loading:** Carregar fornecedores sob demanda
- **Pagination:** Para mais de 1000 fornecedores por categoria

---

## 🎓 Treinamento

### Para Administradores

**1. Configuração Inicial (10min):**
- Cadastrar fornecedores principais
- Organizar por categoria
- Testar no lançamento mensal

**2. Manutenção Regular:**
- Revisar fornecedores mensalmente
- Desativar não usados
- Adicionar novos conforme necessário

### Para Usuários

**1. Uso Básico (5min):**
- Abrir lançamento mensal
- Selecionar fornecedor no dropdown
- Preencher valor e observação

**2. Criar Fornecedor (2min):**
- Clicar no botão [+]
- Digitar nome
- Continuar lançamento

---

## ✅ Checklist de Validação

### Após Deploy

- [ ] Migration executada com sucesso
- [ ] Tabela `despesas_fornecedores` criada
- [ ] Foreign keys funcionando
- [ ] Menu "Despesas Fornecedor" aparece para ADMIN
- [ ] CRUD de fornecedores funcional
- [ ] API `/api/por-categoria/` retorna JSON
- [ ] API `/api/criar-rapido` aceita POST
- [ ] Dropdown no lançamento mensal carrega fornecedores
- [ ] Filtro por categoria funciona
- [ ] Botão [+] cria fornecedor
- [ ] AJAX recarrega dropdown após criar
- [ ] Lançamento salva com fornecedor correto

### Testes de Integração

- [ ] Criar fornecedor "Teste A" na categoria "ADVOGADO"
- [ ] Criar fornecedor "Teste B" na categoria "CONTADOR"
- [ ] Abrir lançamento mensal
- [ ] Verificar que "Teste A" aparece apenas em ADVOGADO
- [ ] Verificar que "Teste B" aparece apenas em CONTADOR
- [ ] Criar fornecedor inline
- [ ] Verificar que novo fornecedor aparece no dropdown
- [ ] Salvar lançamento
- [ ] Verificar no banco que fornecedor foi salvo corretamente

---

## 📞 Suporte

### Problemas Comuns

**1. Dropdown vazio:**
- Verificar se há fornecedores cadastrados na categoria
- Verificar console do navegador (F12) para erros AJAX
- Verificar se API retorna JSON correto

**2. Botão [+] não funciona:**
- Verificar console para erros JavaScript
- Verificar se API `/api/criar-rapido` está acessível
- Verificar permissões (apenas ADMIN)

**3. Fornecedor não aparece:**
- Verificar se está na categoria correta
- Verificar se está ativo (ativo = 1)
- Recarregar a página

### Logs

```bash
# Logs da aplicação
tail -f /var/log/nh-transportes/app.log

# Logs do navegador
# Abrir DevTools (F12) → Console
```

---

## 🎉 Conclusão

Sistema de Fornecedores de Despesas implementado com sucesso!

**Principais conquistas:**
- ✅ Cadastro completo de fornecedores
- ✅ Filtro automático por categoria
- ✅ Criação inline sem sair da tela
- ✅ AJAX para UX fluida
- ✅ Segurança e validação
- ✅ Código modular e extensível

**Próximos passos:**
1. Executar migration em produção
2. Treinar usuários
3. Cadastrar fornecedores iniciais
4. Monitorar uso
5. Coletar feedback para melhorias

---

**Data:** 15/02/2026  
**Versão:** 1.0  
**Status:** Implementado e Documentado
