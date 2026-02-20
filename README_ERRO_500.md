# 🚨 AÇÃO NECESSÁRIA: Erro 500 em /despesas/fornecedores/

## Status: ⚠️ AGUARDANDO EXECUÇÃO DA MIGRATION

---

## 📋 O Que Aconteceu

A funcionalidade de **Fornecedores de Despesas** foi implementada e está no código, mas a **tabela do banco de dados não foi criada** em produção.

**Resultado:** Erro 500 ao acessar `/despesas/fornecedores/`

---

## ✅ O Que Fazer (2 opções simples)

### Opção 1: Script Automático (Recomendado) ⭐

**No Shell do Render:**

```bash
cd /opt/render/project/src
python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql --force
```

**Tempo:** 30 segundos  
**Resultado:** Tabela criada automaticamente

---

### Opção 2: SQL Direto (Alternativo)

**No MySQL Client:**

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

**Tempo:** 15 segundos  
**Resultado:** Tabela criada manualmente

---

## 🎯 Verificação Rápida

Após executar, teste:

```
https://nh-transportes.onrender.com/despesas/fornecedores/
```

**Esperado:**
- ✅ Status 200 (não 500)
- ✅ Página carrega normalmente
- ✅ Botão "Cadastrar Fornecedor" visível

---

## 📚 Documentação Disponível

**Para resolver agora (2 min):**
- `QUICK_FIX_DESPESAS_FORNECEDORES.md`

**Para entender tudo (15 min):**
- `SOLUCAO_ERRO_500_FORNECEDORES.md`

**Ferramenta:**
- `run_single_migration.py`

---

## 🆘 Precisa de Ajuda?

Consulte: `SOLUCAO_ERRO_500_FORNECEDORES.md` (troubleshooting completo)

---

**⏰ Tempo estimado:** 2-5 minutos  
**🎯 Impacto:** Resolve erro 500 completamente  
**📊 Risco:** Mínimo (usa IF NOT EXISTS)
