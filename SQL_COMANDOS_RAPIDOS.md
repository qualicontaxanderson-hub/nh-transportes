# 🔧 COMANDOS SQL - TROCO PIX (Execução Rápida)

## ⚡ RESUMO EXECUTIVO

**O que vai mudar:** Tabela `tipos_receita_caixa`  
**Quantos registros:** 2 (1 modificado + 1 novo)  
**Tempo de execução:** < 1 segundo  
**Risco:** 🟢 Baixo (não apaga nada)

---

## 📋 COMANDOS SQL PARA EXECUTAR

### 1️⃣ Primeiro Comando - RENOMEAR registro existente
```sql
UPDATE tipos_receita_caixa 
SET tipo = 'MANUAL', nome = 'TROCO PIX (MANUAL)'
WHERE nome = 'TROCO PIX' AND (tipo IS NULL OR tipo = 'MANUAL');
```

**O que faz:**
- Encontra o registro "TROCO PIX"
- Muda o nome para "TROCO PIX (MANUAL)"
- ✅ NÃO apaga nenhum dado

---

### 2️⃣ Segundo Comando - CRIAR novo registro
```sql
INSERT INTO tipos_receita_caixa (nome, tipo, ativo) 
SELECT 'TROCO PIX (AUTO)', 'AUTO', 1
WHERE NOT EXISTS (
    SELECT 1 FROM tipos_receita_caixa 
    WHERE nome = 'TROCO PIX (AUTO)' AND tipo = 'AUTO'
);
```

**O que faz:**
- Cria um novo registro "TROCO PIX (AUTO)"
- Define tipo como 'AUTO' (automático)
- ✅ Só insere se ainda não existir (seguro)

---

## ✅ VERIFICAR RESULTADO

### Antes de executar:
```sql
SELECT id, nome, tipo, ativo 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;
```

**Resultado esperado ANTES:**
```
+----+------------+--------+-------+
| id | nome       | tipo   | ativo |
+----+------------+--------+-------+
| 24 | TROCO PIX  | MANUAL |     1 |
+----+------------+--------+-------+
1 linha
```

---

### Depois de executar:
```sql
SELECT id, nome, tipo, ativo 
FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%'
ORDER BY id;
```

**Resultado esperado DEPOIS:**
```
+----+---------------------+--------+-------+
| id | nome                | tipo   | ativo |
+----+---------------------+--------+-------+
| 24 | TROCO PIX (MANUAL)  | MANUAL |     1 |
| 25 | TROCO PIX (AUTO)    | AUTO   |     1 |
+----+---------------------+--------+-------+
2 linhas
```

---

## 🎯 CHECKLIST RÁPIDO

Depois de executar, verificar:

- [ ] Comando UPDATE executou? (deve retornar "1 row affected")
- [ ] Comando INSERT executou? (deve retornar "1 row affected")
- [ ] Query de verificação retorna 2 linhas?
- [ ] Uma linha tem nome "TROCO PIX (MANUAL)" e tipo "MANUAL"?
- [ ] Uma linha tem nome "TROCO PIX (AUTO)" e tipo "AUTO"?

**Se todos os itens estiverem ✅, está correto!**

---

## 🚀 COMO EXECUTAR

### Via Terminal MySQL:
```bash
mysql -u usuario -p banco_dados < migrations/20260203_add_troco_pix_auto.sql
```

### Ou copiar/colar direto no MySQL:
```sql
-- Conectar ao banco primeiro
USE seu_banco_de_dados;

-- Depois executar os 2 comandos acima
```

---

## 🔄 REVERTER (se necessário)

```sql
-- Apagar o tipo AUTO
DELETE FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)';

-- Restaurar nome original
UPDATE tipos_receita_caixa SET nome = 'TROCO PIX' WHERE nome = 'TROCO PIX (MANUAL)';
```

---

## ⚠️ IMPORTANTE

✅ **SEGURO:** Não apaga dados  
✅ **RÁPIDO:** < 1 segundo  
✅ **REVERSÍVEL:** Pode desfazer  
⚠️ **RECOMENDADO:** Fazer backup antes (opcional)

---

**Pronto para executar!** ✅
