# Deploy: Sistema de Lançamento de Despesas

## 🚀 Guia Rápido de Deploy

### 1. Executar Migration

**Opção A: Via MySQL Client**
```bash
mysql -h [host] -u [user] -p[password] [database] < migrations/20260214_add_lancamentos_despesas.sql
```

**Opção B: Via Script Python**
```bash
python run_migrations.py
```

**Opção C: Via MySQL Workbench/phpMyAdmin**
1. Abrir o arquivo `migrations/20260214_add_lancamentos_despesas.sql`
2. Executar o conteúdo no banco de dados

### 2. Verificar Criação da Tabela

```sql
-- Verificar se tabela foi criada
SHOW TABLES LIKE 'lancamentos_despesas';

-- Ver estrutura
DESCRIBE lancamentos_despesas;

-- Verificar foreign keys
SHOW CREATE TABLE lancamentos_despesas;
```

**Resultado Esperado:**
```
+-------------------------+
| Tables_in_railway       |
+-------------------------+
| lancamentos_despesas    |
+-------------------------+
```

### 3. Reiniciar Aplicação

```bash
# Se usando Gunicorn/Procfile
ps aux | grep gunicorn
kill -HUP [PID]

# Ou reiniciar completamente
systemctl restart nh-transportes

# No Render.com
# Vai reiniciar automaticamente após git push
```

### 4. Verificar Blueprint Registrado

```python
# No console Python ou Flask shell
from app import app
print([bp.name for bp in app.blueprints.values()])
# Deve incluir 'lancamentos_despesas'
```

Ou verificar logs:
```bash
grep "lancamentos_despesas" /var/log/flask.log
# Deve ver: "Blueprint 'lancamentos_despesas' registrado"
```

### 5. Testar Funcionalidade

#### Teste 1: Acessar Menu
1. Login como ADMIN
2. Ir em **Lançamentos** → **Despesas**
3. Deve carregar página de lista

#### Teste 2: Criar Lançamento
1. Clicar em "Novo Lançamento"
2. Preencher:
   - Data: Hoje
   - Título: DESPESAS OPERACIONAIS
   - Categoria: ADVOGADO
   - Valor: 1.500,00
3. Salvar
4. Deve retornar para lista com mensagem de sucesso

#### Teste 3: Filtros
1. Na página de lista
2. Aplicar filtro por data ou título
3. Verificar se filtra corretamente

#### Teste 4: Edição
1. Clicar em editar um lançamento
2. Modificar valor
3. Salvar
4. Verificar se atualizou

#### Teste 5: Exclusão
1. Clicar em excluir
2. Confirmar
3. Verificar se foi removido

### 6. Troubleshooting

#### Problema: Tabela não foi criada
```sql
-- Verificar se migration já foi executada
SELECT * FROM migrations WHERE filename LIKE '%lancamentos_despesas%';

-- Se não existe, executar manualmente
SOURCE migrations/20260214_add_lancamentos_despesas.sql;
```

#### Problema: Menu não aparece
- Verificar se usuário é ADMIN (não ADMINISTRADOR sem permissão)
- Limpar cache do navegador
- Verificar navbar.html foi atualizado

#### Problema: Erro 500 ao acessar
```bash
# Verificar logs
tail -f /var/log/flask.log

# Ou no Render.com
# Ir em Logs e procurar por erros
```

Possíveis causas:
- Blueprint não registrado (verificar app.py)
- Tabela não existe (verificar migration)
- Erro de importação (verificar sintaxe Python)

#### Problema: Seleção hierárquica não funciona
- Abrir console do navegador (F12)
- Ver se há erros JavaScript
- Verificar se APIs retornam dados:
  - `/lancamentos_despesas/api/categorias/1`
  - `/lancamentos_despesas/api/subcategorias/1`

#### Problema: Erro ao salvar valores
- Verificar formato brasileiro (1.500,00)
- Ver validação no backend
- Conferir tipo DECIMAL(10,2) no banco

### 7. Validação Completa

Execute estes comandos SQL para validar:

```sql
-- 1. Verificar estrutura
DESCRIBE lancamentos_despesas;

-- 2. Verificar foreign keys
SELECT 
    CONSTRAINT_NAME,
    COLUMN_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_NAME = 'lancamentos_despesas'
  AND REFERENCED_TABLE_NAME IS NOT NULL;

-- 3. Verificar índices
SHOW INDEX FROM lancamentos_despesas;

-- 4. Testar insert
INSERT INTO lancamentos_despesas 
(data, titulo_id, categoria_id, valor, fornecedor, observacao)
VALUES 
(CURDATE(), 1, 1, 1500.00, 'Teste', 'Lançamento de teste');

-- 5. Verificar insert
SELECT * FROM lancamentos_despesas ORDER BY id DESC LIMIT 1;

-- 6. Deletar teste
DELETE FROM lancamentos_despesas WHERE observacao = 'Lançamento de teste';
```

### 8. Performance

#### Verificar Índices
```sql
EXPLAIN SELECT ld.*, t.nome, c.nome 
FROM lancamentos_despesas ld
INNER JOIN titulos_despesas t ON ld.titulo_id = t.id
INNER JOIN categorias_despesas c ON ld.categoria_id = c.id
WHERE ld.data BETWEEN '2026-01-01' AND '2026-12-31';
```

Deve usar índices:
- `idx_lancamentos_despesas_data`
- `PRIMARY` nas outras tabelas

### 9. Backup Antes do Deploy

```bash
# Backup completo
mysqldump -h [host] -u [user] -p[password] [database] > backup_pre_despesas.sql

# Backup apenas das tabelas relacionadas
mysqldump -h [host] -u [user] -p[password] [database] \
  titulos_despesas categorias_despesas subcategorias_despesas \
  > backup_despesas_estrutura.sql
```

### 10. Rollback (Se Necessário)

Se algo der errado:

```sql
-- Remover tabela
DROP TABLE IF EXISTS lancamentos_despesas;

-- Remover do registro de migrations
DELETE FROM migrations WHERE filename = '20260214_add_lancamentos_despesas.sql';

-- Restaurar backup
mysql -h [host] -u [user] -p[password] [database] < backup_pre_despesas.sql
```

## ✅ Checklist Final

- [ ] Migration executada com sucesso
- [ ] Tabela `lancamentos_despesas` criada
- [ ] Foreign keys configuradas
- [ ] Índices criados
- [ ] Aplicação reiniciada
- [ ] Blueprint registrado
- [ ] Menu visível para ADMIN
- [ ] Criação de lançamento funciona
- [ ] Edição funciona
- [ ] Exclusão funciona
- [ ] Filtros funcionam
- [ ] Seleção hierárquica (AJAX) funciona
- [ ] Totalização aparece corretamente
- [ ] Validação de valores funciona
- [ ] Mensagens flash aparecem

## 📞 Contatos de Emergência

Se encontrar problemas críticos:
1. Reverter commit: `git revert 04b8868`
2. Restaurar backup
3. Notificar equipe
4. Documentar erro para correção

---

**Tempo Estimado de Deploy:** 10-15 minutos  
**Downtime Necessário:** Não (apenas restart)  
**Prioridade:** Média  
**Risco:** Baixo (não altera dados existentes)
