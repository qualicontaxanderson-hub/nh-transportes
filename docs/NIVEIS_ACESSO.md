# 📋 Níveis de Acesso do Sistema NH Transportes

## 🎯 Níveis Disponíveis

### 1. ADMIN - Administrador (🔴)
- Acesso total ao sistema
- Pode gerenciar todos os usuários
- Acessa todos os postos
- Sem restrições

### 2. GERENTE - Gerente de Operações (🟡)
- Gestão de múltiplos postos
- Pode gerenciar PISTA e SUPERVISOR
- Edita sem limite de tempo
- Não pode excluir transações

### 3. SUPERVISOR - Supervisor de Posto (🔵)
- Supervisão de posto(s) específico(s)
- Edita sem limite de tempo
- Não gerencia usuários
- Precisa de posto associado

### 4. PISTA - Operador (🔵 claro)
- Operação básica
- Edita apenas 15 minutos
- Um posto específico
- Acesso limitado

## 📊 Comparativo

| Permissão | ADMIN | GERENTE | SUPERVISOR | PISTA |
|-----------|-------|---------|------------|-------|
| Criar Usuários | ✅ | Limitado | ❌ | ❌ |
| Ver Todos Postos | ✅ | ✅ | ❌ | ❌ |
| Editar Sem Limite | ✅ | ✅ | ✅ | ❌ |
| Excluir | ✅ | ❌ | ❌ | ❌ |

## 🔧 Como Usar

1. Dashboard → Gerenciar Usuários → Criar
2. Selecione o nível desejado
3. Configure posto se necessário

