# 🚨 CORREÇÃO RÁPIDA - Erro 500 em /despesas/fornecedores/

## O Problema

```
❌ ERRO: Table 'railway.despesas_fornecedores' doesn't exist
```

## A Solução (5 minutos)

### Opção A: Script Automático no Render Shell ⭐ RECOMENDADO

1. **Acesse:** https://dashboard.render.com
2. **Abra:** Shell do serviço `nh-transportes`
3. **Cole e execute:**

```bash
cd /opt/render/project/src
python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql --force
```

4. **Aguarde:** ~10 segundos
5. **Verifique:** ✅ "MIGRATION CONCLUÍDA COM SUCESSO!"
6. **Teste:** https://nh-transportes.onrender.com/despesas/fornecedores/

---

### Opção B: SQL Direto no MySQL

Se preferir executar o SQL manualmente via MySQL client:

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

ALTER TABLE despesas_fornecedores 
COMMENT = 'Fornecedores de despesas vinculados a categorias específicas';
```

---

## ✅ Verificação

Após executar:

```sql
-- Verificar se a tabela existe
SHOW TABLES LIKE 'despesas_fornecedores';

-- Ver estrutura
DESCRIBE despesas_fornecedores;
```

**Resultado esperado:** Tabela criada com 5 colunas (id, nome, categoria_id, ativo, criado_em)

---

## 🎯 Teste Final

1. Acesse: https://nh-transportes.onrender.com/despesas/fornecedores/
2. ✅ Deve carregar sem erro 500
3. ✅ Deve mostrar lista vazia
4. ✅ Botão "Cadastrar Fornecedor" deve estar visível

---

## 📚 Documentação Completa

Para mais detalhes, consulte:
- `MANUAL_MIGRATION_GUIDE.md` - Guia completo com troubleshooting
- `DEPLOY_FORNECEDORES_DESPESAS.md` - Documentação do sistema

---

## 🆘 Problemas?

**Se o erro persistir:**

1. Verifique se a migration foi executada com sucesso
2. Reinicie a aplicação no Render (se necessário)
3. Verifique os logs: `Erro ao conectar` ou `Foreign key constraint`
4. Consulte `MANUAL_MIGRATION_GUIDE.md` seção Troubleshooting

**Erro "Foreign key constraint"?**

Execute as migrations anteriores primeiro:
```bash
python run_single_migration.py migrations/20260212_add_titulos_despesas.sql --force
python run_single_migration.py migrations/20260212_seed_despesas.sql --force
python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql --force
```

---

**Tempo estimado:** 5 minutos  
**Complexidade:** Baixa  
**Impacto:** Alto (resolve erro 500)
