# Guia para Executar Migration Manualmente

## 🐛 Problema

A tabela `despesas_fornecedores` não existe no banco de dados de produção, causando erro 500 ao acessar `/despesas/fornecedores/`.

**Erro:**
```
mysql.connector.errors.ProgrammingError: 1146 (42S02): Table 'railway.despesas_fornecedores' doesn't exist
```

## ✅ Solução

Executar a migration `20260215_add_despesas_fornecedores.sql` no banco de dados de produção.

---

## 📋 Opção 1: Via Script Python (RECOMENDADO)

### Passo 1: Acessar Shell do Render

1. Acesse https://dashboard.render.com
2. Selecione o serviço `nh-transportes`
3. Clique na aba **Shell**
4. Execute:

```bash
cd /opt/render/project/src
python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql --force
```

### O que o script faz:

1. ✅ Lê o arquivo SQL
2. ✅ Conecta ao banco usando variáveis de ambiente
3. ✅ Executa os comandos SQL
4. ✅ Verifica se a tabela foi criada
5. ✅ Mostra estrutura da tabela

### Saída Esperada:

```
============================================================
🚀 EXECUTAR MIGRATION
============================================================
Arquivo: migrations/20260215_add_despesas_fornecedores.sql

📄 Lendo migration: migrations/20260215_add_despesas_fornecedores.sql
📊 SQL a ser executado (15 linhas não-vazias)
------------------------------------------------------------
🔌 Conectando ao banco de dados...
⚙️  Executando migration...
   Executando statement 1/2...
   Executando statement 2/2...
✅ Migration executada com sucesso!
✅ Tabela 'despesas_fornecedores' criada com sucesso!

📋 Estrutura da tabela:
   - id: int
   - nome: varchar(200)
   - categoria_id: int
   - ativo: tinyint(1)
   - criado_em: timestamp

============================================================
✅ MIGRATION CONCLUÍDA COM SUCESSO!
============================================================
```

---

## 📋 Opção 2: Via MySQL Client Direto

Se preferir executar o SQL manualmente:

### SQL Completo:

```sql
-- Migration: Criar tabela de Fornecedores de Despesas
-- Data: 2026-02-15
-- Descrição: Tabela para cadastrar fornecedores vinculados a categorias de despesas

CREATE TABLE IF NOT EXISTS despesas_fornecedores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(200) NOT NULL,
    categoria_id INT NOT NULL,
    ativo TINYINT(1) DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id),
    INDEX idx_despesas_fornecedores_categoria (categoria_id),
    INDEX idx_despesas_fornecedores_ativo (ativo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comentários
ALTER TABLE despesas_fornecedores 
COMMENT = 'Fornecedores de despesas vinculados a categorias específicas';
```

### Como Executar:

**Via Railway/Render Dashboard:**

1. Acesse o banco de dados na dashboard
2. Abra o MySQL client
3. Cole o SQL acima
4. Execute

**Via MySQL Client Local:**

```bash
# Pegue as credenciais do banco em Render Dashboard
mysql -h <host> -u <user> -p<password> <database> < migrations/20260215_add_despesas_fornecedores.sql
```

---

## 🔍 Verificação Pós-Execução

Após executar a migration, verifique se tudo está OK:

### 1. Verificar se a Tabela Existe

```sql
SHOW TABLES LIKE 'despesas_fornecedores';
```

**Resultado esperado:** 1 linha retornada

### 2. Verificar Estrutura da Tabela

```sql
DESCRIBE despesas_fornecedores;
```

**Resultado esperado:**
```
+---------------+--------------+------+-----+-------------------+
| Field         | Type         | Null | Key | Default           |
+---------------+--------------+------+-----+-------------------+
| id            | int          | NO   | PRI | NULL              |
| nome          | varchar(200) | NO   |     | NULL              |
| categoria_id  | int          | NO   | MUL | NULL              |
| ativo         | tinyint(1)   | YES  |     | 1                 |
| criado_em     | timestamp    | YES  |     | CURRENT_TIMESTAMP |
+---------------+--------------+------+-----+-------------------+
```

### 3. Verificar Foreign Keys

```sql
SELECT 
    CONSTRAINT_NAME,
    TABLE_NAME,
    COLUMN_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM
    INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE
    TABLE_NAME = 'despesas_fornecedores'
    AND REFERENCED_TABLE_NAME IS NOT NULL;
```

**Resultado esperado:** 1 foreign key para `categorias_despesas`

### 4. Verificar Índices

```sql
SHOW INDEX FROM despesas_fornecedores;
```

**Resultado esperado:** 3 índices (PRIMARY, categoria_id, ativo)

---

## ✅ Teste Final

Após executar a migration:

1. **Reinicie a aplicação** (se necessário, Render faz isso automaticamente)

2. **Acesse a URL:**
   ```
   https://nh-transportes.onrender.com/despesas/fornecedores/
   ```

3. **Resultado esperado:**
   - ✅ Página carrega sem erro 500
   - ✅ Mostra lista vazia de fornecedores
   - ✅ Botão "Cadastrar Fornecedor" visível

4. **Teste Criar um Fornecedor:**
   - Clique em "Cadastrar Fornecedor"
   - Preencha:
     - Nome: "Fornecedor Teste"
     - Categoria: Selecione qualquer categoria
   - Salve
   - Verifique se aparece na lista

---

## 🔄 Rollback (Se Necessário)

Se precisar reverter:

```sql
DROP TABLE IF EXISTS despesas_fornecedores;
```

**⚠️ CUIDADO:** Isso apaga todos os dados da tabela!

---

## 📞 Troubleshooting

### Erro: "Foreign key constraint fails"

**Causa:** Tabela `categorias_despesas` não existe

**Solução:** Execute primeiro as migrations anteriores:
```bash
python run_single_migration.py migrations/20260212_add_titulos_despesas.sql --force
python run_single_migration.py migrations/20260212_seed_despesas.sql --force
python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql --force
```

### Erro: "Access denied"

**Causa:** Usuário não tem permissões

**Solução:** Use o usuário master/admin do banco de dados

### Erro: "Table already exists"

**Causa:** Migration já foi executada

**Solução:** Nada a fazer! A tabela já existe. Verifique se a aplicação está funcionando.

---

## 📊 Logs de Sucesso

Após executar com sucesso, você verá nos logs do Render:

```
✅ Migration executada com sucesso!
✅ Tabela 'despesas_fornecedores' criada com sucesso!
```

E o erro 500 não aparecerá mais:
```
# ANTES
mysql.connector.errors.ProgrammingError: Table 'railway.despesas_fornecedores' doesn't exist

# DEPOIS
✅ Página carrega normalmente
```

---

## 📝 Checklist Final

- [ ] Migration executada sem erros
- [ ] Tabela `despesas_fornecedores` existe
- [ ] Foreign key para `categorias_despesas` criada
- [ ] Índices criados (3 índices)
- [ ] URL `/despesas/fornecedores/` carrega sem erro
- [ ] Possível criar novo fornecedor
- [ ] Fornecedor aparece na lista

---

## 🎉 Conclusão

Após seguir este guia, o sistema de Fornecedores de Despesas estará totalmente funcional!

**Qualquer dúvida:**
- Consulte os logs do Render
- Verifique a estrutura do banco
- Execute os comandos de verificação acima
