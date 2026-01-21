# Instruções de Deploy - Controle de Descargas

## Passo a Passo para Aplicar em Produção

### 1. Backup do Banco de Dados (IMPORTANTE!)

Antes de aplicar qualquer migração, faça backup:

```bash
mysqldump -h centerbeam.proxy.rlwy.net -P 56026 -u root -p railway > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 2. Aplicar Migração

**Opção A: Via Interface Web (phpMyAdmin, etc)**
1. Acesse o gerenciador do banco de dados
2. Selecione o banco `railway`
3. Vá em "SQL" ou "Importar"
4. Cole ou importe o conteúdo de `migrations/20260121_add_descargas_tables.sql`
5. Execute

**Opção B: Via linha de comando**
```bash
mysql -h centerbeam.proxy.rlwy.net -P 56026 -u root -p railway < migrations/20260121_add_descargas_tables.sql
```

**Opção C: Via script Python (requer acesso ao servidor)**
```bash
python3 scripts/apply_migration.py 20260121_add_descargas_tables.sql
```

### 3. Verificar Tabelas Criadas

Execute no banco:
```sql
SHOW TABLES LIKE '%descarga%';
```

Resultado esperado:
```
+---------------------------+
| Tables_in_railway         |
+---------------------------+
| descarga_etapas           |
| descargas                 |
+---------------------------+
```

### 4. Verificar Estrutura das Tabelas

```sql
DESCRIBE descargas;
DESCRIBE descarga_etapas;
```

### 5. Restart da Aplicação

Se necessário, reinicie a aplicação para garantir que os novos modelos sejam carregados:

```bash
# No Render.com ou servidor
# A aplicação geralmente reinicia automaticamente após o push
# Se necessário, force o restart manualmente via dashboard
```

### 6. Teste Inicial

1. Faça login na aplicação
2. Verifique se o menu "Descargas" aparece em **Lançamentos**
3. Tente acessar `/descargas/`
4. Crie uma descarga de teste a partir de um frete existente

### 7. Monitoramento

Após o deploy, monitore:
- Logs de erro da aplicação
- Queries lentas no banco
- Uso de espaço (novas tabelas)

## Rollback (Se Necessário)

Se algo der errado, execute:

```sql
DROP TABLE IF EXISTS descarga_etapas;
DROP TABLE IF EXISTS descargas;
```

E restaure o backup:
```bash
mysql -h centerbeam.proxy.rlwy.net -P 56026 -u root -p railway < backup_XXXXX.sql
```

## Problemas Comuns

### Erro: Table already exists
Se as tabelas já existirem, você pode:
1. Verificar se é uma instalação antiga
2. Remover as tabelas antigas (CUIDADO!)
3. Alterar o script para `CREATE TABLE IF NOT EXISTS`

### Erro: Foreign key constraint fails
Verifique se a tabela `fretes` existe:
```sql
SHOW TABLES LIKE 'fretes';
```

### Erro: Connection refused
- Verifique as credenciais em `config.py`
- Verifique se o host está acessível
- Verifique firewall/security groups

## Contatos

- Desenvolvedor: [GitHub copilot]
- Data: 2026-01-21
