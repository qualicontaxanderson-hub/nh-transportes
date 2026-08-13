# 🧪 GUIA DE TESTES - Permissões SUPERVISOR

## ✅ Status: Migration Aplicada com Sucesso!

As tabelas `usuario_empresas` e `usuario_permissoes` foram criadas no banco de dados.  
**Banco de dados: OK** ✓

---

## 🎯 O Que Vamos Testar

### Funcionalidades Implementadas:
1. ✅ Criar usuário SUPERVISOR com múltiplas empresas
2. ✅ Editar usuário SUPERVISOR e gerenciar empresas
3. ✅ SUPERVISOR acessar 9 seções específicas:
   - **CADASTRO:** Formas Pagamento, Formas Recebimento, Cartões
   - **LANÇAMENTOS:** Quilometragem, Arla, Vendas Posto, Fechamento Caixa, Troco Pix, Troco Pix Pista
4. ✅ Filtro de empresas por "Config. Produtos Posto"
5. ✅ Validações (frontend e backend)

---

## 📋 TESTE 1: Verificar Tabelas no Banco de Dados

### SQL para Verificação:

```sql
-- Verificar se tabelas existem
SHOW TABLES LIKE 'usuario_%';

-- Deve mostrar:
-- usuario_empresas
-- usuario_permissoes

-- Verificar estrutura da tabela usuario_empresas
DESCRIBE usuario_empresas;

-- Verificar estrutura da tabela usuario_permissoes
DESCRIBE usuario_permissoes;
```

### ✅ Resultado Esperado:
- Tabela `usuario_empresas` com colunas: id, usuario_id, cliente_id, criado_em
- Tabela `usuario_permissoes` com colunas: id, usuario_id, secao, pode_criar, pode_editar, pode_excluir

---

## 📋 TESTE 2: Criar Usuário SUPERVISOR

### Passo a Passo:

1. **Abra o navegador** e acesse:
   ```
   https://app.postonovohorizonte.com.br/auth/login
   ```

2. **Faça login como ADMIN** com suas credenciais de administrador

3. **Navegue para Gerenciar Usuários:**
   - Clique no menu → "Gerenciar Usuários"
   - Ou acesse diretamente: `/auth/usuarios`

4. **Clique em "Novo Usuário"** ou acesse `/auth/usuarios/novo`

5. **Preencha o formulário:**
   ```
   Username:        supervisor.teste
   Nome Completo:   Supervisor de Teste
   Senha:           teste123
   Confirmar Senha: teste123
   ```

6. **Selecione o Nível:** `SUPERVISOR` (importante!)

7. **Observe:** Um campo "Empresas com Acesso" deve aparecer automaticamente

8. **Selecione 2 ou mais empresas:**
   - ☑ Empresa A
   - ☑ Empresa B
   - ☐ Empresa C

9. **Clique em "Criar Usuário"**

### ✅ Resultado Esperado:
- Mensagem de sucesso: "Usuário supervisor.teste criado com sucesso!"
- Redirecionamento para lista de usuários
- Usuário aparece na lista com nível "SUPERVISOR"

### ❌ Erros Possíveis:
- **"SUPERVISOR deve ter pelo menos uma empresa"** → Selecione pelo menos 1 empresa
- **"Este nome de usuário já existe"** → Use outro username

---

## 📋 TESTE 3: Verificar Empresas no Banco

### SQL para Verificação:

```sql
-- Verificar empresas associadas ao SUPERVISOR
SELECT 
    u.username,
    u.nivel,
    c.razao_social as empresa,
    ue.criado_em
FROM usuarios u
INNER JOIN usuario_empresas ue ON u.id = ue.usuario_id
INNER JOIN clientes c ON ue.cliente_id = c.id
WHERE u.username = 'supervisor.teste'
ORDER BY c.razao_social;
```

### ✅ Resultado Esperado:
- Deve mostrar 2 linhas (uma para cada empresa selecionada)
- Cada linha mostra: username, nivel, nome da empresa, data de criação

---

## 📋 TESTE 4: Login como SUPERVISOR

### Passo a Passo:

1. **Faça logout** da conta ADMIN

2. **Faça login como SUPERVISOR:**
   ```
   Username: supervisor.teste
   Senha:    teste123
   ```

3. **Observe o redirecionamento:**
   - SUPERVISOR deve ser redirecionado para `/troco_pix/pista` automaticamente

### ✅ Resultado Esperado:
- Login bem-sucedido
- Redirecionamento automático para Troco Pix Pista

---

## 📋 TESTE 5: Testar Acesso às Seções PERMITIDAS

### Seções que SUPERVISOR DEVE Acessar:

| Seção | URL | Teste |
|-------|-----|-------|
| **Formas Pagamento** | `/caixa` | ✓ Acessar |
| **Formas Pagamento - Novo** | `/caixa/novo` | ✓ Criar nova |
| **Formas Recebimento** | `/tipos_receita_caixa` | ✓ Acessar |
| **Formas Recebimento - Novo** | `/tipos_receita_caixa/novo` | ✓ Criar nova |
| **Cartões** | `/cartoes` | ✓ Acessar |
| **Cartões - Novo** | `/cartoes/novo` | ✓ Criar novo |
| **Quilometragem** | `/quilometragem` | ✓ Acessar |
| **Arla** | `/arla` | ✓ Acessar |
| **Vendas Posto** | `/posto` | ✓ Acessar |
| **Troco Pix** | `/troco_pix` | ✓ Acessar |
| **Troco Pix Pista** | `/troco_pix/pista` | ✓ Acessar |

### Como Testar:

1. **Acesse cada URL acima** enquanto logado como SUPERVISOR
2. **Verifique se a página carrega** sem erro 403
3. **Tente criar um novo registro** nas seções de CADASTRO

### ✅ Resultado Esperado:
- Todas as URLs acima devem ser acessíveis
- Nenhuma mensagem de "Acesso negado"
- Formulários de criação devem ser exibidos

---

## 📋 TESTE 6: Testar Acesso BLOQUEADO (Segurança)

### Seções que SUPERVISOR NÃO DEVE Acessar:

| Seção | URL | Resultado Esperado |
|-------|-----|-------------------|
| **Gerenciar Usuários** | `/auth/usuarios` | ❌ Bloqueado |
| **Criar Usuário** | `/auth/usuarios/novo` | ❌ Bloqueado |

### Como Testar:

1. **Tente acessar** `/auth/usuarios` enquanto logado como SUPERVISOR
2. **Observe a mensagem de erro**

### ✅ Resultado Esperado:
- Mensagem: "Acesso negado. Esta área é restrita a administradores."
- Redirecionamento para página inicial
- HTTP 403 (Forbidden)

---

## 📋 TESTE 7: Editar Usuário SUPERVISOR

### Passo a Passo:

1. **Faça login como ADMIN** novamente

2. **Vá para Gerenciar Usuários** → `/auth/usuarios`

3. **Clique em "Editar"** no usuário `supervisor.teste`

4. **Observe:**
   - Campo "Empresas com Acesso" deve estar visível
   - Empresas previamente selecionadas devem estar marcadas (☑)

5. **Adicione ou remova empresas:**
   - ☑ Empresa A (mantém)
   - ☐ Empresa B (desmarca)
   - ☑ Empresa C (adiciona)

6. **Clique em "Atualizar Usuário"**

### ✅ Resultado Esperado:
- Mensagem: "Usuário supervisor.teste atualizado com sucesso!"
- Mudanças salvas no banco de dados

### SQL para Verificar:
```sql
SELECT c.razao_social
FROM usuario_empresas ue
INNER JOIN clientes c ON ue.cliente_id = c.id
INNER JOIN usuarios u ON ue.usuario_id = u.id
WHERE u.username = 'supervisor.teste';
```

Deve mostrar: Empresa A e Empresa C (apenas)

---

## 📋 TESTE 8: Validação - SUPERVISOR sem Empresas

### Passo a Passo:

1. **Como ADMIN**, edite o usuário `supervisor.teste`

2. **Desmarque TODAS as empresas** (deixe todos desmarcados)

3. **Tente salvar**

### ✅ Resultado Esperado:
- **Validação JavaScript impede o envio:**
  - Alert: "SUPERVISOR deve ter pelo menos uma empresa selecionada!"
  - Formulário não é enviado

- **Se JavaScript estiver desabilitado, validação no backend:**
  - Mensagem: "Usuários SUPERVISOR devem ter pelo menos uma empresa associada."

---

## 📋 TESTE 9: Login como PISTA (Controle Negativo)

### Passo a Passo:

1. **Faça login como usuário PISTA** (se existir)

2. **Tente acessar:** `/caixa/novo`

### ✅ Resultado Esperado:
- **BLOQUEADO**: Mensagem de erro
- "Acesso negado. Esta área requer nível SUPERVISOR ou superior."
- Redirecionamento para página inicial

---

## 📋 TESTE 10: Mudar Nível de SUPERVISOR para PISTA

### Passo a Passo:

1. **Como ADMIN**, edite `supervisor.teste`

2. **Mude o Nível:** SUPERVISOR → PISTA

3. **Selecione UMA empresa** apenas (campo único para PISTA)

4. **Salve**

### ✅ Resultado Esperado:
- Usuário salvo como PISTA
- Empresas múltiplas são removidas da tabela `usuario_empresas`
- `cliente_id` é definido na tabela `usuarios` (campo único)

### SQL para Verificar:
```sql
-- Não deve ter registros em usuario_empresas
SELECT COUNT(*) FROM usuario_empresas ue
INNER JOIN usuarios u ON ue.usuario_id = u.id
WHERE u.username = 'supervisor.teste';
-- Resultado: 0

-- Deve ter cliente_id preenchido
SELECT username, nivel, cliente_id 
FROM usuarios 
WHERE username = 'supervisor.teste';
-- cliente_id deve ter um valor
```

---

## 🎓 CHECKLIST COMPLETO DE TESTES

Use esta lista para marcar cada teste realizado:

- [ ] ✅ TESTE 1: Verificar tabelas no banco
- [ ] ✅ TESTE 2: Criar usuário SUPERVISOR
- [ ] ✅ TESTE 3: Verificar empresas no banco
- [ ] ✅ TESTE 4: Login como SUPERVISOR
- [ ] ✅ TESTE 5: Acessar seções permitidas (9 seções)
- [ ] ✅ TESTE 6: Verificar acesso bloqueado (segurança)
- [ ] ✅ TESTE 7: Editar usuário SUPERVISOR
- [ ] ✅ TESTE 8: Validação - SUPERVISOR sem empresas
- [ ] ✅ TESTE 9: Login como PISTA (controle negativo)
- [ ] ✅ TESTE 10: Mudar nível de SUPERVISOR para PISTA

---

## 🐛 Problemas Comuns e Soluções

### Problema 1: "Tabela usuario_empresas não existe"
**Solução:** Execute a migration:
```bash
mysql ... < migrations/20260204_add_supervisor_permissions.sql
```

### Problema 2: Lista de empresas vazia
**Solução:** Verifique se existem produtos posto:
```sql
SELECT COUNT(*) FROM clientes_produtos WHERE ativo = 1;
```

### Problema 3: JavaScript não valida
**Solução:** Limpe o cache do navegador (Ctrl+Shift+R)

### Problema 4: Acesso negado mesmo sendo SUPERVISOR
**Solução:** Verifique o nível no banco:
```sql
SELECT username, nivel FROM usuarios WHERE username = 'supervisor.teste';
```
O nível deve ser exatamente: `SUPERVISOR` (maiúsculas)

---

## 📊 Relatório de Teste

Após completar todos os testes, preencha:

**Data do Teste:** ___/___/______  
**Testador:** _________________  
**Ambiente:** ☐ Desenvolvimento ☐ Produção  

**Resumo:**
- Testes Passaram: ___/10
- Testes Falharam: ___/10
- Bugs Encontrados: ___

**Observações:**
_________________________________________________
_________________________________________________
_________________________________________________

---

## 🎉 Conclusão

Se todos os 10 testes passaram, a implementação está **100% funcional** e pronta para uso em produção! 🚀

**Próximos Passos:**
1. ✅ Treinar equipe sobre novo nível SUPERVISOR
2. ✅ Criar usuários SUPERVISOR reais
3. ✅ Monitorar logs de acesso
4. ✅ Coletar feedback dos usuários

---

**Documentação Adicional:**
- `IMPLEMENTACAO_FINALIZADA.md` - Resumo completo
- `RESUMO_SUPERVISOR.md` - Guia rápido
- `SUPERVISOR_PERMISSIONS.md` - Detalhes técnicos
- `DIAGRAMA_SUPERVISOR.md` - Diagramas visuais

**Suporte:** Em caso de dúvidas, consulte a documentação ou abra uma issue no GitHub.
