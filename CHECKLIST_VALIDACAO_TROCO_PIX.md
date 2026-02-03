# 🧪 CHECKLIST DE VALIDAÇÃO - Sistema TROCO PIX

Este documento contém a lista de verificação para validar que o sistema TROCO PIX está funcionando corretamente após as alterações.

---

## 📋 PRÉ-REQUISITOS

### 1. Migration Executada
```bash
# Conectar ao banco de dados
mysql -u usuario -p nome_banco

# Executar migration
source /path/to/migrations/20260203_add_troco_pix_auto.sql;

# Verificar resultado
SELECT id, nome, tipo, ativo FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

**Resultado Esperado:**
```
+----+---------------------+--------+-------+
| id | nome                | tipo   | ativo |
+----+---------------------+--------+-------+
| 24 | TROCO PIX (MANUAL)  | MANUAL |     1 |
| 25 | TROCO PIX (AUTO)    | AUTO   |     1 |
+----+---------------------+--------+-------+
```

- [ ] Migration executada com sucesso
- [ ] Dois registros criados em tipos_receita_caixa
- [ ] Nomes corretos: "TROCO PIX (AUTO)" e "TROCO PIX (MANUAL)"
- [ ] Tipos corretos: AUTO e MANUAL

---

## 🔧 TESTES FUNCIONAIS

### 2. Teste Básico: Criar Troco PIX

**Usuário:** Frentista (PISTA ou SUPERVISOR)  
**Caminho:** Menu → Lançamentos → Troco PIX Pista

**Passos:**
1. Fazer login como usuário PISTA
2. Acessar "Troco PIX Pista"
3. Clicar em "Novo Troco PIX"
4. Preencher formulário:
   - Data: Automática (hoje)
   - Cliente: Automático (posto do usuário)
   - **VENDA:**
     - Abastecimento: 2.000,00
     - Arla: 0,00
     - Produtos: 20,00
     - TOTAL: 2.020,00 (automático)
   - **CHEQUE:**
     - Tipo: À Vista
     - Valor: 3.000,00
   - **TROCO:**
     - Espécie: 80,00
     - PIX: 900,00
     - Crédito: 0,00
     - TOTAL: 980,00 (automático)
   - Cliente PIX: Selecionar ou criar
   - Frentista: Selecionar da lista
5. Clicar em "Salvar"

**Verificações:**
- [ ] Formulário carrega corretamente
- [ ] Campos automáticos calculam valores (totais)
- [ ] Data e cliente pré-preenchidos para PISTA
- [ ] Lista de frentistas carrega
- [ ] Lista de clientes PIX carrega
- [ ] Opção "SEM PIX" aparece no topo
- [ ] Salva com sucesso
- [ ] Gera número sequencial (ex: PIX-03-02-2026-N1)
- [ ] Redireciona para visualização
- [ ] Mensagem de sucesso exibida

---

### 3. Teste: Visualização e WhatsApp

**Continuando do teste anterior:**

1. Na tela de visualização, verificar cards:
   - Informações Gerais
   - Venda
   - Cheque
   - Troco
   - Destinatário PIX
   - Resumo Financeiro

2. Verificar cálculo:
   - Diferença = Cheque - Venda = 3.000 - 2.020 = 980
   - Deve conferir com Troco Total = 980
   - Alerta verde: "Valores conferem!"

3. Clicar em "Copiar para WhatsApp"

**Verificações:**
- [ ] Cards exibem informações corretas
- [ ] Valores formatados em R$ X.XXX,XX
- [ ] Cálculo de diferença correto
- [ ] Alerta de conferência apropriado (verde = OK, vermelho = erro)
- [ ] Botão WhatsApp copia mensagem
- [ ] Mensagem formatada com emojis
- [ ] Estrutura organizada (VENDA → CHEQUE → TROCO)
- [ ] Dados do destinatário PIX incluídos
- [ ] Nome do frentista incluído

**Formato esperado da mensagem:**
```
💰 *TROCO PIX* 💰
━━━━━━━━━━━━━━━━━━━━
📅 *Data:* 03/02/2026

🏪 *VENDA*
├ Abastecimento: 2.000,00
├ Arla: —
├ Produtos: 20,00
└ *TOTAL:* 2.020,00

💵 *CHEQUE*
├ Tipo: À Vista
└ *Valor:* 3.000,00

💸 *TROCO*
├ Em Espécie: 80,00
├ Crédito Vda. Programada: —
└ *TOTAL:* 980,00

🔑 *TROCO PIX:* 900,00
━━━━━━━━━━━━━━━━━━━━
📱 Chave Pix: *CPF* - XXX.XXX.XXX-XX
👤 Cliente: *[Nome Cliente]*

⛽ Frentista: *[Nome Frentista]*
```

---

### 4. Teste: Integração com Fechamento de Caixa

**Usuário:** Admin ou Gerente  
**Caminho:** Menu → Lançamentos → Fechamento de Caixa → Novo

**Passos:**
1. Fazer login como ADMIN
2. Acessar "Fechamento de Caixa"
3. Clicar em "Novo Lançamento"
4. Selecionar:
   - Cliente: Mesmo do teste anterior
   - Data: Mesmo do teste anterior (hoje)
5. Aguardar carregamento automático

**Verificações:**
- [ ] Formulário carrega
- [ ] Após selecionar cliente + data, campos AUTO preenchem automaticamente
- [ ] Campo "VENDAS POSTO" carrega (se houver vendas)
- [ ] Campo "ARLA" carrega (se houver lançamentos)
- [ ] Campo "LUBRIFICANTES" carrega (se houver lançamentos)
- [ ] Campo "TROCO PIX (AUTO)" carrega com valor 900,00 ✨
- [ ] Campo é readonly (não editável)
- [ ] Badge "Auto" (azul) aparece ao lado
- [ ] Botão 📤 aparece ao lado do campo
- [ ] Clicar no botão 📤 abre `/troco_pix/` em nova aba
- [ ] Campo "TROCO PIX (MANUAL)" editável aparece abaixo
- [ ] Total Receitas inclui TROCO PIX (AUTO)

**Ordem esperada dos campos:**
```
Receitas e Entradas:
1. VENDAS POSTO          [Auto]
2. ARLA                  [Auto]
3. LUBRIFICANTES         [Auto]
4. TROCO PIX (AUTO)      [Auto] 📤  ← NOVO!
5. RECEBIMENTOS          [Manual]
6. ACRÉSCIMOS GERAIS     [Manual]
7. ACRÉSCIMOS CADASTROS  [Manual]
8. TROCO PIX (MANUAL)    [Manual]   ← NOVO!
9. EMPRESTIMOS           [Manual]
10. OUTROS               [Manual]
```

---

### 5. Teste: Edição (Restrição 15 minutos)

**Teste A: Edição permitida (dentro de 15 min)**

**Usuário:** Frentista (mesmo que criou)  
**Caminho:** Troco PIX Pista → Editar transação recém-criada

**Passos:**
1. Na lista de TROCO PIX Pista
2. Clicar em "Editar" na transação criada há menos de 15 min
3. Alterar valor do Troco PIX: 900 → 1000
4. Salvar

**Verificações:**
- [ ] Formulário de edição abre
- [ ] Valores carregam corretamente
- [ ] Permite editar
- [ ] Salva com sucesso
- [ ] Lançamento de caixa atualiza automaticamente
- [ ] Valor no Fechamento de Caixa reflete mudança (1000 em vez de 900)

**Teste B: Edição bloqueada (após 15 min)**

**Passos:**
1. Aguardar 16 minutos
2. Tentar editar a mesma transação

**Verificações:**
- [ ] Sistema bloqueia edição
- [ ] Mensagem: "Você só pode editar transações até 15 minutos após a criação"
- [ ] Redireciona para visualização

**Teste C: Edição por Admin (sem restrição)**

**Usuário:** Admin  
**Caminho:** Troco PIX → Editar qualquer transação

**Verificações:**
- [ ] Admin pode editar transação antiga (> 15 min)
- [ ] Sem mensagem de bloqueio
- [ ] Edição funciona normalmente

---

### 6. Teste: Exclusão

**Usuário:** Admin ou Gerente  
**Caminho:** Troco PIX → Excluir transação

**Passos:**
1. Na lista de TROCO PIX
2. Clicar em "Excluir" em uma transação
3. Confirmar exclusão

**Verificações:**
- [ ] Modal de confirmação aparece
- [ ] Ao confirmar, transação é excluída
- [ ] Lançamento de caixa vinculado também é excluído
- [ ] Valor some do Fechamento de Caixa
- [ ] Mensagem de sucesso exibida

**Teste de bloqueio:**
- [ ] Usuário PISTA NÃO vê botão de excluir
- [ ] Acesso direto à URL de exclusão é bloqueado para PISTA

---

### 7. Teste: Controle de Acesso

**Teste A: Visibilidade por Posto**

**Setup:** Criar 2 usuários PISTA para postos diferentes

**Usuário 1 (PISTA - Posto A):**
1. Criar TROCO PIX no Posto A

**Usuário 2 (PISTA - Posto B):**
1. Acessar TROCO PIX Pista
2. Verificar lista

**Verificações:**
- [ ] Usuário 2 NÃO vê transação do Posto A
- [ ] Cada usuário vê apenas transações do seu posto
- [ ] Filtro de cliente_id funciona corretamente

**Teste B: Acesso Admin**

**Usuário:** Admin

**Verificações:**
- [ ] Admin vê transações de TODOS os postos
- [ ] Pode filtrar por cliente específico
- [ ] Pode acessar todas as rotas (/troco_pix/ e /troco_pix/pista)

---

### 8. Teste: Numeração Sequencial

**Passos:**
1. Criar 3 transações TROCO PIX no mesmo dia
2. Verificar números gerados

**Verificações:**
- [ ] Primeira: PIX-DD-MM-YYYY-N1
- [ ] Segunda: PIX-DD-MM-YYYY-N2
- [ ] Terceira: PIX-DD-MM-YYYY-N3
- [ ] Formato correto (dia-mês-ano)
- [ ] Sequência incrementa corretamente
- [ ] Próximo dia reinicia em N1

---

### 9. Teste: Cliente PIX "SEM PIX"

**Passos:**
1. Criar transação TROCO PIX
2. Selecionar cliente "SEM PIX"
3. Preencher todos os campos
4. Salvar
5. Visualizar transação
6. Copiar WhatsApp

**Verificações:**
- [ ] Opção "SEM PIX" aparece no topo da lista
- [ ] Permite selecionar
- [ ] Salva corretamente
- [ ] Na visualização, mensagem não mostra dados de PIX
- [ ] Título da mensagem: "VENDA EM CHEQUE" (não "TROCO PIX")
- [ ] Seção de chave PIX omitida ou marcada como "—"

---

### 10. Teste: Múltiplas Transações no Mesmo Dia

**Passos:**
1. Criar 3 transações TROCO PIX no mesmo dia:
   - Transação 1: Troco PIX = 500
   - Transação 2: Troco PIX = 300
   - Transação 3: Troco PIX = 200
2. Acessar Fechamento de Caixa
3. Selecionar mesmo cliente e data

**Verificações:**
- [ ] Campo "TROCO PIX (AUTO)" mostra 1.000,00 (soma das 3)
- [ ] Ao salvar Fechamento de Caixa, valor correto é registrado
- [ ] Lançamento de caixa reflete total acumulado

---

## 🐛 TESTES DE VALIDAÇÃO

### 11. Teste: Campos Obrigatórios

**Passos:**
1. Tentar criar TROCO PIX sem preencher campos obrigatórios
2. Tentar salvar

**Verificações:**
- [ ] Sistema bloqueia salvamento
- [ ] Mensagem de erro: "Preencha todos os campos obrigatórios"
- [ ] Campos obrigatórios destacados

**Campos obrigatórios:**
- Cliente (posto)
- Data
- Cheque: Tipo
- Cheque: Valor
- Cliente PIX
- Frentista

### 12. Teste: Cheque A Prazo sem Data

**Passos:**
1. Criar TROCO PIX
2. Selecionar Cheque: A Prazo
3. NÃO preencher data de vencimento
4. Tentar salvar

**Verificações:**
- [ ] Sistema bloqueia
- [ ] Mensagem: "Para cheque A PRAZO, a data de vencimento é obrigatória"

### 13. Teste: Valores Inválidos

**Teste A: Valores não conferem**

**Passos:**
1. Criar TROCO PIX com:
   - Venda Total: 2.000,00
   - Cheque: 2.500,00
   - Troco Total: 1.000,00 (deveria ser 500)

**Verificações:**
- [ ] Sistema permite salvar (apenas alerta, não bloqueia)
- [ ] Na visualização, alerta vermelho: "Valores não conferem!"
- [ ] Diferença calculada: 500,00 ≠ 1.000,00

---

## 📊 TESTES DE INTEGRAÇÃO

### 14. Teste: Fluxo Completo End-to-End

**Cenário:** Dia completo de operação

**Manhã - Frentista:**
1. Login como PISTA
2. Criar 2 transações TROCO PIX
3. Editar uma delas (dentro de 15 min)
4. Tentar editar após 15 min (bloqueio)

**Tarde - Admin:**
5. Login como ADMIN
6. Acessar lista TROCO PIX
7. Ver ambas as transações
8. Criar Fechamento de Caixa para o dia
9. Verificar campo AUTO preenchido com soma
10. Adicionar valor MANUAL (ajuste)
11. Salvar Fechamento de Caixa

**Verificações:**
- [ ] Todas as transações PISTA criadas corretamente
- [ ] Restrição de edição funciona
- [ ] Admin vê tudo
- [ ] Fechamento de Caixa integra valores AUTO
- [ ] Valores MANUAL e AUTO salvos separadamente
- [ ] Totais calculados corretamente

---

## 🔐 TESTES DE SEGURANÇA

### 15. Teste: Acesso Direto a URLs

**Teste A: PISTA tentando acessar rota Admin**

**Usuário:** PISTA

**URLs para testar:**
```
/troco_pix/              (lista admin)
/troco_pix/clientes      (gestão clientes PIX)
```

**Verificações:**
- [ ] Acesso bloqueado ou redirecionado
- [ ] Mensagem de erro apropriada
- [ ] Não vê informações de outros postos

**Teste B: Manipulação de ID**

**Usuário:** PISTA (Posto A)

**Passos:**
1. Criar transação no Posto A (ex: ID 123)
2. Tentar editar transação de outro posto via URL: `/troco_pix/editar/456`

**Verificações:**
- [ ] Sistema bloqueia acesso
- [ ] Retorna erro ou redirecionamento
- [ ] Não permite edição cross-posto

---

## 📱 TESTES DE INTERFACE

### 16. Teste: Responsividade

**Dispositivos para testar:**
- Desktop (1920x1080)
- Tablet (768x1024)
- Mobile (375x667)

**Páginas:**
- Lista TROCO PIX
- Formulário novo
- Visualização
- Fechamento de Caixa

**Verificações:**
- [ ] Layout adapta para cada tamanho
- [ ] Botões acessíveis
- [ ] Formulários utilizáveis
- [ ] Tabelas scrolláveis em mobile
- [ ] Texto legível

### 17. Teste: Navegação

**Verificações:**
- [ ] Breadcrumbs corretos em todas as páginas
- [ ] Links do menu funcionam
- [ ] Botões "Voltar" retornam à página anterior
- [ ] Redirecionamentos após salvar corretos

---

## 🔧 TESTES TÉCNICOS

### 18. Teste: Console do Navegador

**Passos:**
1. Abrir DevTools (F12)
2. Navegar por todas as páginas TROCO PIX
3. Verificar aba Console

**Verificações:**
- [ ] Sem erros JavaScript
- [ ] Sem warnings críticos
- [ ] Requests AJAX bem-sucedidos (200 OK)
- [ ] Sem recursos 404 (imagens, scripts, etc.)

### 19. Teste: Performance

**Passos:**
1. Criar 50+ transações TROCO PIX
2. Acessar lista
3. Verificar tempo de carregamento

**Verificações:**
- [ ] Página carrega em < 3 segundos
- [ ] Scroll suave
- [ ] Filtros aplicam rapidamente
- [ ] Paginação funciona (se implementada)

### 20. Teste: Banco de Dados

**Queries para executar:**

```sql
-- Verificar transações criadas
SELECT COUNT(*) FROM troco_pix;

-- Verificar numeração sequencial
SELECT numero_sequencial, data FROM troco_pix 
ORDER BY data DESC, numero_sequencial DESC 
LIMIT 10;

-- Verificar integração com lancamentos_caixa
SELECT tp.id, tp.numero_sequencial, lc.id as lancamento_id
FROM troco_pix tp
LEFT JOIN lancamentos_caixa lc ON tp.lancamento_caixa_id = lc.id
WHERE tp.lancamento_caixa_id IS NOT NULL;

-- Verificar tipos de receita
SELECT * FROM tipos_receita_caixa 
WHERE nome LIKE '%TROCO PIX%';
```

**Verificações:**
- [ ] Dados consistentes
- [ ] Referências de chaves estrangeiras corretas
- [ ] Campos calculados (totais) corretos
- [ ] Sem registros órfãos

---

## ✅ CRITÉRIOS DE ACEITAÇÃO

### Sistema considerado APROVADO se:

- [ ] **Todos** os testes de funcionalidade (1-13) passam
- [ ] **Maioria** dos testes de integração (14) passa
- [ ] **Todos** os testes de segurança (15) passam
- [ ] Sem erros críticos no console
- [ ] Performance aceitável (< 3s)
- [ ] Dados consistentes no banco

### Bugs Aceitáveis (não bloqueantes):
- Problemas cosméticos de CSS
- Mensagens de validação pouco específicas
- Performance em listas muito grandes (100+ registros)

### Bugs Inaceitáveis (bloqueantes):
- Perda de dados ao salvar
- Valores calculados incorretos
- Falhas de segurança (acesso cross-posto)
- Erros ao integrar com Fechamento de Caixa
- Crashes do sistema

---

## 📝 TEMPLATE DE REPORTE DE BUG

Ao encontrar problemas, documentar assim:

```
**BUG #X: [Título breve]**

**Severidade:** Crítica / Alta / Média / Baixa
**Tipo:** Funcional / Interface / Performance / Segurança

**Reprodução:**
1. Passo 1
2. Passo 2
3. Passo 3

**Resultado Esperado:**
[O que deveria acontecer]

**Resultado Atual:**
[O que acontece]

**Evidências:**
- Screenshot
- Console logs
- Query SQL (se aplicável)

**Ambiente:**
- Navegador: [Chrome/Firefox/Safari]
- Versão: [XX.X]
- Sistema: [Windows/Mac/Linux]
- Usuário: [Admin/PISTA]
```

---

## 🎉 CONCLUSÃO

Após completar todos os testes desta checklist:

✅ **APROVADO**: Sistema pronto para produção  
⚠️ **CONDICIONAL**: Corrigir bugs não-críticos antes do deploy  
❌ **REPROVADO**: Corrigir bugs críticos obrigatoriamente

---

**Data do Checklist:** 03/02/2026  
**Versão:** 1.0  
**Responsável pela Validação:** _______________  
**Status:** [ ] Aprovado [ ] Condicional [ ] Reprovado

---

**FIM DO CHECKLIST**
