# 🚀 INSTRUÇÕES: Deploy e Limpeza de Dados

## ⚠️ ATENÇÃO

Este documento contém instruções CRÍTICAS para resolver o problema de comissões incorretas na página de detalhes.

**Problema Atual:**
- ✅ Código está correto nesta branch
- ❌ Código não está em produção ainda
- ❌ Dados ruins no banco de dados

**Solução:** Deploy + Limpeza de Dados

---

## 📋 PASSO A PASSO (15 MINUTOS)

### 1️⃣ MERGE E DEPLOY (5 minutos)

```bash
# 1. Ir para branch main
git checkout main

# 2. Fazer merge da branch com correções
git merge copilot/fix-merge-issue-39

# 3. Push para GitHub
git push origin main

# 4. Aguardar Railway fazer deploy automático (~5 min)
# Acompanhar em: https://railway.app/
```

**✅ Verificar deploy completo antes de prosseguir!**

---

### 2️⃣ LIMPAR DADOS DO BANCO (5 minutos)

Escolha uma das opções:

#### Opção A: Via Script SQL (Recomendado)

**Pré-requisitos:** Acesso ao banco MySQL

```bash
# 1. Acessar servidor de banco de dados
ssh usuario@servidor-db

# 2. Executar script de limpeza
mysql -h localhost -u nh_user -p nh_transportes < migrations/20260207_limpar_comissoes_frentistas.sql

# 3. Verificar resultado
# O script mostrará:
# - Quantos registros foram encontrados
# - Quais funcionários foram afetados
# - Quantos foram deletados
# - Validação final
```

#### Opção B: Via Rota Administrativa

**Pré-requisitos:** Estar logado como admin no sistema

**Método 1 - Via DevTools do Navegador:**

1. Acessar: `https://app.postonovohorizonte.com.br/lancamentos-funcionarios/`
2. Fazer login como admin
3. Abrir DevTools (F12)
4. Ir para Console
5. Executar:

```javascript
fetch('/lancamentos-funcionarios/admin/limpar-comissoes-frentistas', {
  method: 'POST',
  credentials: 'include'
})
.then(response => response.json())
.then(data => {
  console.log('Resultado:', data);
  alert(`Limpeza concluída! ${data.registros_deletados} registros deletados.`);
});
```

**Método 2 - Via curl:**

```bash
# 1. Obter cookie de sessão (após fazer login)
# Inspecionar Network tab no DevTools para pegar cookie

# 2. Executar curl
curl -X POST https://app.postonovohorizonte.com.br/lancamentos-funcionarios/admin/limpar-comissoes-frentistas \
  -H "Cookie: session=SEU_COOKIE_AQUI" \
  -H "Content-Type: application/json"
```

**Resposta Esperada:**
```json
{
  "success": true,
  "message": "Limpeza concluída com sucesso!",
  "registros_esperados": 3,
  "registros_deletados": 3
}
```

---

### 3️⃣ VALIDAR RESULTADO (5 minutos)

#### Via Interface Web:

1. **Acessar página de detalhes:**
   ```
   https://app.postonovohorizonte.com.br/lancamentos-funcionarios/detalhe/01-2026/1
   ```

2. **Verificar:**
   - ✅ **João** (frentista) → SEM comissão
   - ✅ **Roberta** (frentista) → SEM comissão  
   - ✅ **Rodrigo** (frentista) → SEM comissão
   - ✅ **Marcos** (motorista) → COM comissão (R$ 2.110,00)
   - ✅ **Valmir** (motorista) → COM comissão (R$ 1.400,00)

3. **Verificar total:**
   - Total de funcionários: 9
   - Comissões totais: R$ 3.510,00

#### Via Banco de Dados:

```sql
-- Ver funcionários com comissões (devem ser apenas motoristas)
SELECT DISTINCT
    COALESCE(f.nome, m.nome) as nome,
    CASE 
        WHEN m.id IS NOT NULL THEN 'Motorista'
        ELSE 'Funcionário'
    END as tipo,
    l.valor
FROM lancamentosfuncionarios_v2 l
LEFT JOIN funcionarios f ON l.funcionarioid = f.id
LEFT JOIN motoristas m ON l.funcionarioid = m.id
WHERE l.rubricaid IN (
    SELECT id FROM rubricas 
    WHERE nome IN ('Comissão', 'Comissão / Aj. Custo')
)
AND l.mes = '01/2026'
AND l.clienteid = 1;
```

**Resultado Esperado:**
```
nome          | tipo      | valor
--------------+-----------+--------
MARCOS        | Motorista | 2110.00
VALMIR        | Motorista | 1400.00
```

---

## 🔧 Troubleshooting

### ❌ Problema: "Ainda aparecem comissões para frentistas"

**Causa:** Limpeza não foi executada.

**Solução:** Execute o Passo 2 novamente.

---

### ❌ Problema: "Motoristas não aparecem"

**Causa Possível 1:** Deploy não completou.

**Solução:** Aguardar mais tempo, verificar logs do Railway.

**Causa Possível 2:** Endpoint da API está errado.

**Solução:** Verificar logs do servidor:
```
Warning: Could not fetch commissions from API...
```

Se aparecer este warning, o código correto ainda não foi deployado.

---

### ❌ Problema: "Erro 401 na rota administrativa"

**Causa:** Não está autenticado como admin.

**Solução:**
1. Fazer logout
2. Fazer login como admin
3. Tentar novamente

---

### ❌ Problema: "Erro 404 na rota administrativa"

**Causa:** Deploy não foi feito ainda.

**Solução:** Completar o Passo 1 primeiro.

---

## 📊 O Que Foi Corrigido

### Correções de Código (Branch completa):

1. ✅ Erro 500 ao salvar (duplicação)
2. ✅ Botão Detalhe não funcionava
3. ✅ Faltava botão Editar
4. ✅ Erro 404 em URLs
5. ✅ Comissões erradas (edição)
6. ✅ Títulos inconsistentes
7. ✅ Nome do endpoint errado
8. ✅ Rastreamento de motoristas
9. ✅ Filtro de comissões
10. ✅ Ferramentas de limpeza

### Arquivos Modificados:

- `routes/lancamentos_funcionarios.py` (~265 linhas)
- `templates/lancamentos_funcionarios/novo.html` (~50 linhas)
- `templates/lancamentos_funcionarios/lista.html` (~10 linhas)
- `migrations/20260207_limpar_comissoes_frentistas.sql` (novo)

---

## 📞 Suporte

**Se algo der errado:**

1. **Verificar logs do Railway:**
   ```
   https://railway.app/ → Logs
   ```

2. **Verificar logs do MySQL:**
   ```bash
   mysql -h <host> -u <user> -p -e "SHOW PROCESSLIST;"
   ```

3. **Reverter se necessário:**
   ```bash
   git revert HEAD
   git push origin main
   ```

4. **Contatar equipe de desenvolvimento**

---

## ✅ Checklist de Execução

### Antes de Começar:
- [ ] Acesso ao Git configurado
- [ ] Acesso ao Railway configurado
- [ ] Acesso ao banco MySQL configurado
- [ ] Login admin no sistema disponível

### Durante Execução:
- [ ] Passo 1: Merge realizado
- [ ] Passo 1: Push realizado
- [ ] Passo 1: Deploy completo (verificado no Railway)
- [ ] Passo 2: Limpeza executada (SQL ou API)
- [ ] Passo 2: Resposta de sucesso recebida
- [ ] Passo 3: Página detalhe validada
- [ ] Passo 3: Dados no banco validados

### Após Conclusão:
- [ ] João SEM comissões ✅
- [ ] Roberta SEM comissões ✅
- [ ] Marcos COM comissões ✅
- [ ] Valmir COM comissões ✅
- [ ] Total correto ✅
- [ ] Problema resolvido ✅

---

## 📚 Documentação Relacionada

- `GUIA_LIMPEZA_DADOS_COMISSOES.md` - Guia técnico detalhado
- `RESUMO_EXECUTIVO_BRANCH.md` - Resumo de todas as correções
- `migrations/20260207_limpar_comissoes_frentistas.sql` - Script SQL

---

## 🎯 Resultado Final Esperado

**Página Detalhe:**
- 9 funcionários listados
- Apenas motoristas com comissões
- Frentistas sem comissões
- Total de comissões: R$ 3.510,00

**Banco de Dados:**
- 0 comissões para frentistas
- 2 comissões para motoristas (Marcos e Valmir)

**Sistema:**
- 100% funcional
- 100% consistente
- 0 erros nos logs

---

**Data:** 07/02/2026  
**Branch:** copilot/fix-merge-issue-39  
**Versão:** Final  
**Status:** ✅ PRONTO PARA EXECUÇÃO
