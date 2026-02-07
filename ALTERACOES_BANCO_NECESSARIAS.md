# 📋 Alterações Necessárias no Banco de Dados

## Pergunta: "preciso alterar alguma coisa no banco de dados?"

### Resposta: 🟡 **SIM - 1 Migration Precisa Ser Aplicada**

---

## 🎯 Migration Obrigatória

### Arquivo: `migrations/20260204_add_supervisor_permissions.sql`

**Criado em:** 2026-02-04  
**Propósito:** Adicionar suporte para permissões SUPERVISOR e múltiplas empresas

---

## 📊 Tabelas que Serão Criadas

### 1. Tabela `usuario_empresas`

**Propósito:** Relacionamento many-to-many entre usuários SUPERVISOR e empresas

**Estrutura:**
```sql
CREATE TABLE IF NOT EXISTS usuario_empresas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    cliente_id INT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_company (usuario_id, cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Índices:**
- `PRIMARY KEY` em `id`
- `UNIQUE KEY` em `(usuario_id, cliente_id)` - evita duplicatas
- `INDEX` em `usuario_id` - performance nas buscas por usuário
- `INDEX` em `cliente_id` - performance nas buscas por empresa

**Uso:**
- Armazena quais empresas cada SUPERVISOR pode acessar
- Exemplo: SUPERVISOR "MELKE" (id=5) acessa empresas 1, 3 e 7

**Dados de Exemplo:**
```sql
INSERT INTO usuario_empresas (usuario_id, cliente_id) VALUES (5, 1);
INSERT INTO usuario_empresas (usuario_id, cliente_id) VALUES (5, 3);
INSERT INTO usuario_empresas (usuario_id, cliente_id) VALUES (5, 7);
```

---

### 2. Tabela `usuario_permissoes`

**Propósito:** Permissões granulares por seção (uso futuro)

**Estrutura:**
```sql
CREATE TABLE IF NOT EXISTS usuario_permissoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    secao VARCHAR(100) NOT NULL,
    pode_criar BOOLEAN DEFAULT TRUE,
    pode_editar BOOLEAN DEFAULT TRUE,
    pode_excluir BOOLEAN DEFAULT FALSE,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_section (usuario_id, secao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Índices:**
- `PRIMARY KEY` em `id`
- `UNIQUE KEY` em `(usuario_id, secao)` - evita duplicatas

**Uso:**
- Permite controle fino sobre o que cada SUPERVISOR pode fazer
- Atualmente **não é utilizada** (reservada para uso futuro)
- Seções possíveis: `caixa`, `cartoes`, `quilometragem`, `arla`, etc.

**Dados de Exemplo (futuro):**
```sql
-- SUPERVISOR pode criar/editar caixa, mas não excluir
INSERT INTO usuario_permissoes (usuario_id, secao, pode_criar, pode_editar, pode_excluir) 
VALUES (5, 'caixa', TRUE, TRUE, FALSE);
```

---

## 🚨 Por Que Esta Migration é Necessária?

### Funcionalidades que DEPENDEM destas tabelas:

1. **Criar Usuário SUPERVISOR** (`/auth/usuarios/novo`)
   - Precisa salvar empresas em `usuario_empresas`
   - ❌ Sem a tabela = ERRO ao salvar

2. **Editar Usuário SUPERVISOR** (`/auth/usuarios/5/editar`)
   - Precisa ler/atualizar empresas de `usuario_empresas`
   - ❌ Sem a tabela = ERRO ao carregar/salvar

3. **Filtrar Dados por Empresa**
   - Código lê `usuario_empresas` para saber quais empresas o SUPERVISOR acessa
   - ❌ Sem a tabela = ERRO ao filtrar dados

### Código que USA estas tabelas:

**Arquivo:** `models/usuario.py`

```python
@staticmethod
def get_empresas_usuario(usuario_id):
    """Retorna lista de empresas do usuário SUPERVISOR"""
    cursor.execute("""
        SELECT cliente_id 
        FROM usuario_empresas 
        WHERE usuario_id = %s
    """, (usuario_id,))
    # ❌ ERRO se tabela não existir!

@staticmethod
def set_empresas_usuario(usuario_id, empresas_ids):
    """Define empresas do usuário SUPERVISOR"""
    cursor.execute("""
        DELETE FROM usuario_empresas 
        WHERE usuario_id = %s
    """, (usuario_id,))
    # ❌ ERRO se tabela não existir!
```

**Arquivo:** `routes/auth.py`

```python
# Ao criar/editar SUPERVISOR
if nivel == 'SUPERVISOR':
    empresas = request.form.getlist('empresas')
    Usuario.set_empresas_usuario(usuario_id, empresas)
    # ❌ ERRO se tabela não existir!
```

---

## 🔧 Como Aplicar a Migration

### Pré-requisitos:
- ✅ Acesso ao banco de dados de produção
- ✅ Permissões para criar tabelas
- ✅ Arquivo `migrations/20260204_add_supervisor_permissions.sql`

### Método 1: Linha de Comando (MySQL Client)

```bash
# Conectar ao banco
mysql -h <HOST> -u <USUARIO> -p <BANCO_DE_DADOS>

# No prompt do MySQL, executar:
source migrations/20260204_add_supervisor_permissions.sql;

# Ou em uma linha:
mysql -h <HOST> -u <USUARIO> -p <BANCO> < migrations/20260204_add_supervisor_permissions.sql
```

**Exemplo Railway:**
```bash
mysql -h containers-us-west-xxx.railway.app \
      -u root \
      -p \
      railway < migrations/20260204_add_supervisor_permissions.sql
```

---

### Método 2: Interface Web (Railway/Render)

**Railway:**
1. Acessar dashboard do projeto
2. Clicar no serviço do banco de dados
3. Aba "Data" → "Query"
4. Copiar conteúdo do arquivo `migrations/20260204_add_supervisor_permissions.sql`
5. Colar e executar

**Render:**
1. Acessar dashboard
2. Selecionar o banco de dados
3. Aba "Console"
4. Copiar conteúdo do arquivo `migrations/20260204_add_supervisor_permissions.sql`
5. Colar e executar

---

### Método 3: Script Python

Criar arquivo `aplicar_migration.py`:

```python
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

# Conectar ao banco
conn = mysql.connector.connect(
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME
)

cursor = conn.cursor()

# Ler migration
with open('migrations/20260204_add_supervisor_permissions.sql', 'r') as f:
    sql = f.read()

# Executar (dividir por comandos se necessário)
for statement in sql.split(';'):
    if statement.strip():
        cursor.execute(statement)

conn.commit()
print("✅ Migration aplicada com sucesso!")

cursor.close()
conn.close()
```

Executar:
```bash
python aplicar_migration.py
```

---

## ✅ Verificação Pós-Migration

### Teste 1: Verificar Tabelas Criadas

```sql
-- Listar tabelas
SHOW TABLES LIKE 'usuario_%';

-- Resultado esperado:
-- usuario_empresas
-- usuario_permissoes
```

### Teste 2: Verificar Estrutura

```sql
-- Ver estrutura de usuario_empresas
DESCRIBE usuario_empresas;

-- Resultado esperado:
-- id           | int         | NO  | PRI | NULL    | auto_increment
-- usuario_id   | int         | NO  | MUL | NULL    |
-- cliente_id   | int         | NO  | MUL | NULL    |
-- criado_em    | timestamp   | YES |     | CURRENT_TIMESTAMP

-- Ver estrutura de usuario_permissoes
DESCRIBE usuario_permissoes;

-- Resultado esperado:
-- id             | int         | NO  | PRI | NULL    | auto_increment
-- usuario_id     | int         | NO  | MUL | NULL    |
-- secao          | varchar(100)| NO  |     | NULL    |
-- pode_criar     | tinyint(1)  | YES |     | 1       |
-- pode_editar    | tinyint(1)  | YES |     | 1       |
-- pode_excluir   | tinyint(1)  | YES |     | 0       |
-- criado_em      | timestamp   | YES |     | CURRENT_TIMESTAMP
-- atualizado_em  | timestamp   | YES |     | CURRENT_TIMESTAMP
```

### Teste 3: Verificar Índices

```sql
-- Ver índices de usuario_empresas
SHOW INDEX FROM usuario_empresas;

-- Resultado esperado:
-- PRIMARY (id)
-- unique_user_company (usuario_id, cliente_id)
-- idx_usuario_empresas_usuario (usuario_id)
-- idx_usuario_empresas_cliente (cliente_id)
```

### Teste 4: Teste Funcional

```sql
-- Inserir teste
INSERT INTO usuario_empresas (usuario_id, cliente_id) VALUES (5, 1);

-- Verificar
SELECT * FROM usuario_empresas;

-- Limpar teste (opcional)
DELETE FROM usuario_empresas WHERE usuario_id = 5;
```

---

## 📦 Outras Mudanças (NÃO Requerem Alteração no Banco)

### ✅ Mudanças Apenas de Código

As seguintes mudanças foram feitas no código mas **NÃO** alteram o banco de dados:

#### 1. Filtro de 45 Dias
**Arquivos:** `routes/arla.py`, `routes/posto.py`, `routes/lubrificantes.py`
- Mudança de lógica de data (mês atual → últimos 45 dias)
- **Tabelas:** Usa tabelas existentes
- **Schema:** Sem alterações

#### 2. Card de Totais na Edição
**Arquivo:** `templates/posto/vendas_lancar.html`
- Mudança de interface (HTML + JavaScript)
- **Tabelas:** Não usa banco de dados
- **Schema:** Sem alterações

#### 3. Filtro de Empresas com Produtos
**Arquivo:** `models/usuario.py`
- Mudança na query SQL (INNER JOIN)
- **Tabelas:** Usa `clientes` e `cliente_produtos` (já existem)
- **Schema:** Sem alterações

#### 4. Permissões SUPERVISOR nas Rotas
**Arquivos:** `routes/*.py`, `utils/decorators.py`
- Mudança de decorators e verificações
- **Tabelas:** Usa `usuarios` (já existe)
- **Schema:** Sem alterações

#### 5. Menu SUPERVISOR Atualizado
**Arquivo:** `templates/includes/navbar.html`
- Mudança de interface (HTML)
- **Tabelas:** Não usa banco de dados
- **Schema:** Sem alterações

---

## 🎯 Tabela Resumo

| Mudança | Migration? | Tabelas Afetadas | Status |
|---------|-----------|------------------|--------|
| **Permissões SUPERVISOR** | ✅ **SIM** | `usuario_empresas` (nova), `usuario_permissoes` (nova) | 🟡 Pendente |
| Filtro de 45 dias | ❌ Não | Nenhuma (usa existentes) | ✅ OK |
| Card de totais | ❌ Não | Nenhuma | ✅ OK |
| Filtro de empresas | ❌ Não | `clientes`, `cliente_produtos` (existentes) | ✅ OK |
| Menu SUPERVISOR | ❌ Não | Nenhuma | ✅ OK |

---

## 🚀 Ordem de Deploy Recomendada

### Passo 1: Aplicar Migration ao Banco ✅
```bash
# PRODUÇÃO
mysql -h <host> -u <user> -p <db> < migrations/20260204_add_supervisor_permissions.sql
```

### Passo 2: Verificar Tabelas Criadas ✅
```sql
SHOW TABLES LIKE 'usuario_%';
-- Deve mostrar: usuario_empresas, usuario_permissoes
```

### Passo 3: Deploy do Código ✅
```bash
# Via git push para Render/Railway
git push origin main  # ou branch apropriada
```

### Passo 4: Teste Funcional ✅
1. Acessar `/auth/usuarios/novo`
2. Criar SUPERVISOR com múltiplas empresas
3. Verificar que salva sem erro
4. Editar SUPERVISOR
5. Verificar que empresas aparecem selecionadas

---

## ⚠️ IMPORTANTE - Avisos

### ❌ NÃO fazer deploy do código ANTES da migration

**Por quê?**
- Código tentará acessar tabelas que não existem
- Criar/editar SUPERVISOR causará erro 500
- Funcionalidade ficará quebrada

**Sintomas se fizer errado:**
```python
# Erro no log:
mysql.connector.errors.ProgrammingError: 1146 (42S02): 
Table 'railway.usuario_empresas' doesn't exist
```

### ✅ ORDEM CORRETA:

```
1. Aplicar migration ao banco
   ↓
2. Verificar que tabelas existem
   ↓
3. Deploy do código
   ↓
4. Testar funcionalidade
```

---

## 📞 Suporte

### Se der erro na migration:

**Erro: "Table already exists"**
- ✅ Isso é OK! A migration usa `CREATE TABLE IF NOT EXISTS`
- ✅ Significa que tabela já foi criada anteriormente
- ✅ Pode continuar com o deploy

**Erro: "Foreign key constraint fails"**
- ❌ Significa que tabela `usuarios` ou `clientes` não existe
- ❌ Verificar se banco de dados está correto
- ❌ Verificar se migrations anteriores foram aplicadas

**Erro: "Access denied"**
- ❌ Usuário do banco não tem permissão para CREATE TABLE
- ❌ Usar usuário com permissões de administrador
- ❌ Ou pedir ao DBA para aplicar a migration

---

## 📊 Resumo Final

### Pergunta Original:
> "preciso alterar alguma coisa no banco de dados?"

### Resposta:
✅ **SIM, aplicar 1 migration:**
- Arquivo: `migrations/20260204_add_supervisor_permissions.sql`
- Cria 2 tabelas: `usuario_empresas`, `usuario_permissoes`
- Obrigatória para funcionalidade SUPERVISOR funcionar

### Status:
🟡 **Migration criada, aguardando aplicação no banco de produção**

### Próximo Passo:
1. Aplicar migration ao banco de produção
2. Verificar tabelas criadas
3. Fazer deploy do código
4. Testar funcionalidade SUPERVISOR

---

**Data:** 2026-02-05  
**Branch:** `copilot/fix-merge-issue-39`  
**Migration:** `migrations/20260204_add_supervisor_permissions.sql`  
**Status:** 🟡 Pendente aplicação
