# 📋 Níveis de Acesso do Sistema NH Transportes

## 🎯 Níveis Disponíveis

### 1. ADMIN - Administrador (🔴)
- Acesso total ao sistema
- Pode gerenciar todos os usuários
- Acessa todos os postos
- Sem restrições

### 2. GERENTE - Gerente de Operações (🟡)
- Gestão de múltiplos postos (acesso a todos ou posto específico opcional)
- Pode gerenciar usuários PISTA e SUPERVISOR (criar, editar, desativar)
- Edita transações sem limite de tempo
- Pode excluir transações
- Não pode criar/editar usuários ADMIN ou GERENTE

### 3. SUPERVISOR - Supervisor de Posto (🔵)
- Supervisão de posto(s) específico(s)
- Edita transações sem limite de tempo
- Visualiza apenas dados dos postos associados
- Não pode gerenciar usuários
- Não pode excluir transações
- Requer posto associado obrigatoriamente

**Acesso a Módulos de Cadastro:**
- ✅ Cartões
- ✅ Formas Pagamento Caixa
- ✅ Formas Recebimento Caixa
- ✅ Lubrificantes (produtos)

**Acesso a Módulos de Lançamentos:**
- ✅ Quilometragem
- ✅ ARLA
- ✅ Lubrificantes
- ✅ Vendas Posto
- ✅ Fechamento de Caixa
- ✅ Troco PIX
- ✅ Troco PIX Pista

### 4. PISTA - Operador (⚪)
- Operação básica de posto
- Edita transações apenas até 15 minutos após criação
- Visualiza apenas dados do seu posto específico
- Cria transações apenas para a data atual
- Não pode gerenciar usuários
- Não pode excluir transações
- Requer posto associado obrigatoriamente

## 📊 Comparativo Detalhado

| Permissão | ADMIN | GERENTE | SUPERVISOR | PISTA |
|-----------|-------|---------|------------|-------|
| **Gerenciar Usuários** | ✅ Todos | ⚠️ PISTA e SUPERVISOR | ❌ Não | ❌ Não |
| **Ver Todos Postos** | ✅ Sim | ✅ Sim | ❌ Apenas associados | ❌ Apenas o seu |
| **Editar Transações** | ✅ Sem limite | ✅ Sem limite | ✅ Sem limite | ⏱️ Até 15 minutos |
| **Excluir Transações** | ✅ Sim | ✅ Sim | ❌ Não | ❌ Não |
| **Posto Associado** | ➖ Não necessário | 🔄 Opcional | ✅ Obrigatório | ✅ Obrigatório |
| **Criar Transações** | ✅ Qualquer data | ✅ Qualquer data | ✅ Qualquer data | 📅 Apenas data atual |

## 🔑 Principais Diferenças

### GERENTE vs SUPERVISOR
- **GERENTE** pode gerenciar usuários (criar/editar PISTA e SUPERVISOR), **SUPERVISOR** não pode
- **GERENTE** pode excluir transações, **SUPERVISOR** não pode
- **GERENTE** tem acesso a todos os postos (mesmo sem associação), **SUPERVISOR** só vê postos associados
- Ambos editam transações sem limite de tempo

### SUPERVISOR vs PISTA
- **SUPERVISOR** edita sem limite de tempo, **PISTA** tem 15 minutos
- **SUPERVISOR** pode criar transações com qualquer data, **PISTA** só data atual
- Ambos precisam de posto associado obrigatoriamente
- Ambos não podem gerenciar usuários nem excluir transações

## 🔧 Como Usar

1. Dashboard → Gerenciar Usuários → Criar
2. Selecione o nível desejado
3. Configure posto se necessário