# Guia de Deploy - Fornecedores de Despesas

## 📋 Pré-requisitos

- ✅ Acesso ao banco de dados MySQL
- ✅ Permissões de ADMIN no sistema
- ✅ Acesso SSH ao servidor (se deploy manual)

---

## 🚀 Deploy Rápido (5 Passos)

### Passo 1: Backup do Banco

```bash
# Conectar ao servidor
ssh usuario@servidor

# Fazer backup
mysqldump -u root -p nh_transportes > backup_$(date +%Y%m%d_%H%M%S).sql

# Ou via cliente
mysqldump -h railway.app -u usuario -p database > backup.sql
```

### Passo 2: Executar Migration

```bash
# Opção 1: Via MySQL client
mysql -u usuario -p database_name < migrations/20260215_add_despesas_fornecedores.sql

# Opção 2: Via interface
# Copiar conteúdo do arquivo e executar no phpMyAdmin ou DBeaver
```

**Migration SQL:**
```sql
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
```

### Passo 3: Verificar Estrutura

```sql
-- Verificar tabela criada
DESCRIBE despesas_fornecedores;

-- Verificar foreign keys
SHOW CREATE TABLE despesas_fornecedores;

-- Verificar índices
SHOW INDEX FROM despesas_fornecedores;
```

**Resultado esperado:**
```
+-------------+--------------+------+-----+-------------------+
| Field       | Type         | Null | Key | Default           |
+-------------+--------------+------+-----+-------------------+
| id          | int(11)      | NO   | PRI | NULL              |
| nome        | varchar(200) | NO   |     | NULL              |
| categoria_id| int(11)      | NO   | MUL | NULL              |
| ativo       | tinyint(1)   | YES  | MUL | 1                 |
| criado_em   | timestamp    | YES  |     | CURRENT_TIMESTAMP |
+-------------+--------------+------+-----+-------------------+
```

### Passo 4: Deploy do Código

**Render.com (Automático):**
```bash
# Código já está no repositório
# Render detecta mudanças automaticamente
# Aguardar deploy (2-5 minutos)
```

**Deploy Manual:**
```bash
# Pull do código
cd /var/www/nh-transportes
git pull origin main

# Reiniciar aplicação
sudo systemctl restart nh-transportes

# Verificar logs
tail -f /var/log/nh-transportes/app.log
```

### Passo 5: Validação

**1. Verificar menu:**
- Login como ADMIN
- Menu → Cadastros
- Deve aparecer "Despesas Fornecedor"

**2. Testar CRUD:**
- Acessar /despesas/fornecedores/
- Criar fornecedor teste
- Editar fornecedor
- Verificar lista

**3. Testar lançamento mensal:**
- Acessar /lancamentos_despesas/mensal
- Verificar dropdowns de fornecedor
- Testar botão [+]
- Criar fornecedor inline

---

## 🧪 Testes Detalhados

### Teste 1: Estrutura do Banco

```sql
-- 1. Verificar tabela existe
SELECT COUNT(*) FROM information_schema.tables 
WHERE table_schema = 'nh_transportes' 
AND table_name = 'despesas_fornecedores';
-- Esperado: 1

-- 2. Verificar foreign key
SELECT 
    CONSTRAINT_NAME,
    COLUMN_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_NAME = 'despesas_fornecedores'
AND CONSTRAINT_NAME != 'PRIMARY';
-- Esperado: 1 linha com categoria_id -> categorias_despesas

-- 3. Verificar índices
SELECT 
    INDEX_NAME,
    COLUMN_NAME,
    NON_UNIQUE
FROM information_schema.STATISTICS
WHERE TABLE_NAME = 'despesas_fornecedores';
-- Esperado: 3 índices (PRI, categoria, ativo)
```

### Teste 2: CRUD de Fornecedores

**2.1. Criar fornecedor:**
```sql
INSERT INTO despesas_fornecedores (nome, categoria_id, ativo)
VALUES ('Teste Deploy', 1, 1);

SELECT * FROM despesas_fornecedores WHERE nome = 'Teste Deploy';
-- Esperado: 1 registro
```

**2.2. Listar com JOIN:**
```sql
SELECT 
    df.id,
    df.nome,
    c.nome as categoria,
    t.nome as titulo
FROM despesas_fornecedores df
INNER JOIN categorias_despesas c ON df.categoria_id = c.id
INNER JOIN titulos_despesas t ON c.titulo_id = t.id
WHERE df.nome = 'Teste Deploy';
-- Esperado: 1 registro com categoria e título
```

**2.3. Atualizar:**
```sql
UPDATE despesas_fornecedores 
SET nome = 'Teste Deploy Atualizado'
WHERE nome = 'Teste Deploy';

SELECT * FROM despesas_fornecedores WHERE nome LIKE 'Teste Deploy%';
-- Esperado: nome atualizado
```

**2.4. Desativar:**
```sql
UPDATE despesas_fornecedores 
SET ativo = 0
WHERE nome LIKE 'Teste Deploy%';

SELECT * FROM despesas_fornecedores WHERE nome LIKE 'Teste Deploy%';
-- Esperado: ativo = 0
```

**2.5. Limpar teste:**
```sql
DELETE FROM despesas_fornecedores WHERE nome LIKE 'Teste Deploy%';
```

### Teste 3: APIs

**3.1. API listar por categoria:**
```bash
# Com curl
curl https://nh-transportes.onrender.com/despesas/fornecedores/api/por-categoria/1

# Esperado:
# [{"id": 1, "nome": "Fornecedor 1"}, {"id": 2, "nome": "Fornecedor 2"}]
```

**3.2. API criar rápido:**
```bash
# Com curl
curl -X POST https://nh-transportes.onrender.com/despesas/fornecedores/api/criar-rapido \
  -H "Content-Type: application/json" \
  -d '{"nome": "Teste API", "categoria_id": 1}'

# Esperado:
# {"success": true, "id": 123, "nome": "Teste API", "message": "..."}
```

### Teste 4: Interface Web

**Checklist manual:**

- [ ] Login como ADMIN
- [ ] Menu Cadastros → "Despesas Fornecedor" visível
- [ ] Acessar /despesas/fornecedores/
- [ ] Página lista carrega sem erros
- [ ] Clicar "Cadastrar Fornecedor"
- [ ] Formulário carrega com categorias
- [ ] Criar fornecedor teste
- [ ] Fornecedor aparece na lista
- [ ] Clicar "Editar" no fornecedor
- [ ] Formulário editar carrega com dados
- [ ] Alterar nome e salvar
- [ ] Mudança reflete na lista
- [ ] Clicar "Desativar"
- [ ] Confirmar desativação
- [ ] Fornecedor some da lista

### Teste 5: Lançamento Mensal

**Checklist manual:**

- [ ] Acessar /lancamentos_despesas/mensal
- [ ] Página carrega sem erros JavaScript (F12)
- [ ] Selecionar empresa e mês
- [ ] Verificar campo "Fornecedor" é dropdown (não input)
- [ ] Verificar botão [+] ao lado de cada dropdown
- [ ] Abrir dropdown de uma categoria
- [ ] Verificar se mostra apenas fornecedores daquela categoria
- [ ] Clicar botão [+]
- [ ] Digitar nome no prompt
- [ ] Confirmar
- [ ] Verificar que fornecedor foi criado (mensagem de sucesso)
- [ ] Verificar que dropdown recarregou automaticamente
- [ ] Novo fornecedor aparece na lista
- [ ] Selecionar fornecedor e preencher valor
- [ ] Salvar lançamento
- [ ] Verificar que foi salvo com sucesso

---

## 🔍 Troubleshooting

### Problema 1: Tabela não foi criada

**Sintoma:**
```
Table 'nh_transportes.despesas_fornecedores' doesn't exist
```

**Solução:**
```sql
-- Verificar se migration foi executada
SHOW TABLES LIKE 'despesas_fornecedores';

-- Se não existe, executar migration manualmente
CREATE TABLE despesas_fornecedores (...);
```

### Problema 2: Foreign key error

**Sintoma:**
```
Cannot add foreign key constraint
```

**Causas possíveis:**
- Tabela `categorias_despesas` não existe
- Campo `id` em `categorias_despesas` não é INT
- Engines diferentes (InnoDB vs MyISAM)

**Solução:**
```sql
-- 1. Verificar tabela pai existe
SHOW TABLES LIKE 'categorias_despesas';

-- 2. Verificar estrutura
DESCRIBE categorias_despesas;

-- 3. Verificar engine
SHOW TABLE STATUS WHERE Name = 'categorias_despesas';
-- Deve ser InnoDB

-- 4. Se necessário, alterar engine
ALTER TABLE categorias_despesas ENGINE=InnoDB;
```

### Problema 3: Menu não aparece

**Sintoma:**
- "Despesas Fornecedor" não aparece no menu

**Checklist:**
- [ ] Usuário é ADMIN? (não GERENTE)
- [ ] Navbar.html foi atualizado?
- [ ] Navegador cache limpo? (Ctrl+F5)
- [ ] App reiniciado?

**Solução:**
```bash
# Limpar cache do navegador
# Chrome: Ctrl+Shift+Del
# Firefox: Ctrl+Shift+Del

# Reiniciar app
sudo systemctl restart nh-transportes

# Verificar navbar.html
grep "Despesas Fornecedor" templates/includes/navbar.html
```

### Problema 4: Blueprint não registrado

**Sintoma:**
```
werkzeug.routing.BuildError: Could not build url for endpoint 'despesas_fornecedores.lista'
```

**Solução:**
```python
# Verificar logs da aplicação
tail -f /var/log/nh-transportes/app.log | grep despesas_fornecedores

# Deve aparecer:
# "Blueprint 'despesas_fornecedores' registrado a partir de routes.despesas_fornecedores"

# Se não aparece, verificar arquivo routes/despesas_fornecedores.py
# Deve ter: bp = Blueprint('despesas_fornecedores', ...)

# Reiniciar app
sudo systemctl restart nh-transportes
```

### Problema 5: Dropdown vazio

**Sintoma:**
- Dropdown de fornecedor não carrega opções

**Checklist:**
- [ ] Fornecedores cadastrados na categoria?
- [ ] API retorna dados? (testar no navegador)
- [ ] Console JavaScript tem erros? (F12)
- [ ] AJAX está funcionando?

**Solução:**
```bash
# 1. Verificar no banco
SELECT * FROM despesas_fornecedores 
WHERE categoria_id = 1 AND ativo = 1;

# 2. Testar API
curl https://nh-transportes.onrender.com/despesas/fornecedores/api/por-categoria/1

# 3. Verificar console do navegador (F12)
# Procurar por erros AJAX

# 4. Verificar JavaScript carregou
# Abrir DevTools → Sources → mensal.html
# Procurar por loadFornecedoresPorCategoria()
```

### Problema 6: Botão [+] não funciona

**Sintoma:**
- Clicar no [+] não abre prompt

**Checklist:**
- [ ] JavaScript carregou sem erros?
- [ ] Evento click registrado?
- [ ] API criar-rapido acessível?

**Solução:**
```javascript
// Abrir console do navegador (F12)
// Testar manualmente:

// 1. Verificar se função existe
console.log(typeof createFornecedor);
// Esperado: "function"

// 2. Testar criar
createFornecedor(1, "Teste Console");

// 3. Verificar response
// Deve mostrar mensagem de sucesso ou erro
```

---

## 📊 Validação Pós-Deploy

### Checklist Completo

**Banco de Dados:**
- [ ] Tabela `despesas_fornecedores` criada
- [ ] Foreign key funcionando
- [ ] Índices criados
- [ ] Charset UTF8MB4
- [ ] Collation unicode_ci

**Aplicação:**
- [ ] Blueprint registrado
- [ ] Rotas acessíveis
- [ ] APIs respondendo JSON
- [ ] Templates renderizando

**Interface:**
- [ ] Menu visível para ADMIN
- [ ] Lista de fornecedores carrega
- [ ] Formulário novo funciona
- [ ] Formulário editar funciona
- [ ] Desativar funciona
- [ ] Dropdown no mensal carrega
- [ ] Filtro por categoria OK
- [ ] Botão [+] cria fornecedor
- [ ] AJAX recarrega dropdown

**Segurança:**
- [ ] Apenas ADMIN acessa
- [ ] SQL parametrizado
- [ ] Validação de dados
- [ ] Soft delete (não delete físico)

**Performance:**
- [ ] Queries com índices
- [ ] AJAX rápido (< 500ms)
- [ ] Sem N+1 queries
- [ ] Páginas carregam rápido

---

## 🎓 Primeiros Passos Após Deploy

### 1. Cadastrar Fornecedores Iniciais

**Sugestão:** Cadastrar principais fornecedores de cada categoria

```
DESPESAS OPERACIONAIS:
├─ ADVOGADO
│  ├─ Silva & Associados Advogados
│  └─ Costa Advocacia
├─ CONTADOR
│  ├─ Contábil ABC
│  └─ Contador Silva
├─ ENGENHEIRO
│  └─ Engenharia XYZ
└─ MECÂNICO
   └─ Oficina Central

IMPOSTOS:
└─ (geralmente não tem fornecedores específicos)

FINANCEIRO:
├─ BOLETOS
│  └─ Banco Sicredi
└─ TARIFA BANCÁRIA
   ├─ Banco Santander
   └─ Banco Cora
```

### 2. Treinar Usuários

**Tópicos:**
1. Como cadastrar fornecedor
2. Como usar dropdown no lançamento
3. Como criar fornecedor inline [+]
4. Filtro automático por categoria

**Tempo estimado:** 15 minutos

### 3. Migrar Dados Antigos (Opcional)

Se já existem lançamentos com fornecedores em texto livre:

```sql
-- 1. Ver fornecedores únicos nos lançamentos
SELECT DISTINCT fornecedor, categoria_id
FROM lancamentos_despesas
WHERE fornecedor IS NOT NULL AND fornecedor != ''
ORDER BY categoria_id, fornecedor;

-- 2. Inserir em despesas_fornecedores
-- (fazer manualmente ou via script para evitar duplicatas)

-- 3. Padronizar nomes nos lançamentos antigos
-- (opcional, pode deixar como está)
```

### 4. Monitorar Uso

**Queries úteis:**

```sql
-- Fornecedores mais cadastrados
SELECT COUNT(*) as total, categoria_id
FROM despesas_fornecedores
WHERE ativo = 1
GROUP BY categoria_id
ORDER BY total DESC;

-- Categorias sem fornecedores
SELECT c.id, c.nome, t.nome as titulo
FROM categorias_despesas c
INNER JOIN titulos_despesas t ON c.titulo_id = t.id
LEFT JOIN despesas_fornecedores df ON c.id = df.categoria_id AND df.ativo = 1
WHERE df.id IS NULL
ORDER BY t.nome, c.nome;
```

---

## 🔄 Rollback (Em Caso de Problema)

### Opção 1: Rollback Completo

```sql
-- 1. Remover foreign keys
ALTER TABLE despesas_fornecedores 
DROP FOREIGN KEY despesas_fornecedores_ibfk_1;

-- 2. Dropar tabela
DROP TABLE IF EXISTS despesas_fornecedores;

-- 3. Restaurar código anterior
git reset --hard HEAD~1
sudo systemctl restart nh-transportes
```

### Opção 2: Rollback Parcial

```sql
-- Apenas desabilitar tabela sem dropar
ALTER TABLE despesas_fornecedores RENAME TO despesas_fornecedores_old;

-- Código reverter para usar input texto
-- (requer commit reverso no git)
```

### Opção 3: Restaurar Backup

```bash
# Restaurar dump do backup
mysql -u usuario -p database_name < backup_20260215_120000.sql
```

---

## 📞 Suporte

### Logs Importantes

```bash
# Logs da aplicação
tail -f /var/log/nh-transportes/app.log

# Logs do MySQL
tail -f /var/log/mysql/error.log

# Logs do sistema
journalctl -u nh-transportes -f
```

### Comandos de Diagnóstico

```bash
# Verificar se app está rodando
sudo systemctl status nh-transportes

# Verificar conexão com banco
mysql -u usuario -p -e "SELECT 1"

# Verificar porta da aplicação
netstat -tulpn | grep :5000

# Verificar uso de memória
free -h
```

### Contato

- **Email:** suporte@gruponh.com.br
- **Slack:** #nh-transportes-dev
- **Documentação:** README.md

---

## ✅ Checklist Final

Antes de considerar deploy concluído:

**Pré-Deploy:**
- [ ] Código revisado
- [ ] Testes locais passaram
- [ ] Backup do banco realizado
- [ ] Usuários notificados

**Deploy:**
- [ ] Migration executada
- [ ] Código deployed
- [ ] App reiniciado
- [ ] Sem erros nos logs

**Pós-Deploy:**
- [ ] Testes funcionais OK
- [ ] Performance OK
- [ ] Segurança OK
- [ ] Usuários treinados

**Documentação:**
- [ ] Guia técnico criado
- [ ] Guia de usuário criado
- [ ] Changelog atualizado
- [ ] Wiki atualizada

---

## 🎉 Conclusão

Deploy do Sistema de Fornecedores de Despesas!

**Próximos Passos:**
1. ✅ Monitorar logs nas primeiras 24h
2. ✅ Coletar feedback dos usuários
3. ✅ Ajustar conforme necessário
4. ✅ Planejar melhorias futuras

**Data Deploy:** 15/02/2026  
**Versão:** 1.0  
**Status:** ✅ PRODUÇÃO
