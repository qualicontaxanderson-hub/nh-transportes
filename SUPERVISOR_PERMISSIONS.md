# Implementação de Permissões SUPERVISOR

## Resumo das Mudanças

Este documento descreve as mudanças implementadas para dar aos usuários **SUPERVISOR** acesso pleno a seções específicas do sistema e permitir a seleção de múltiplas empresas.

## 📋 Requisitos Implementados

### Acesso às Seguintes Seções:

**CADASTRO:**
- ✅ Formas de Pagamento Caixa (`/caixa/*`)
- ✅ Formas Recebimento Caixa (`/tipos_receita_caixa/*`)
- ✅ Cartões (`/cartoes/*`)

**LANÇAMENTOS:**
- ✅ Quilometragem (`/quilometragem/*`)
- ✅ Arla (`/arla/*`)
- ✅ Vendas Posto (`/posto/*`)
- ✅ Fechamento de Caixa (`/lancamentos_caixa/fechamento*`)
- ✅ Troco Pix (`/troco_pix/*`)
- ✅ Troco Pix Pista (`/troco_pix/pista`)

### Seleção de Empresas:
- ✅ SUPERVISOR pode ter múltiplas empresas associadas
- ✅ Empresas disponíveis são filtradas por "Config. Produtos Posto" (clientes com produtos de posto configurados)

## 🗄️ Mudanças no Banco de Dados

### Nova Tabela: `usuario_empresas`
Relacionamento muitos-para-muitos entre usuários e empresas/clientes.

```sql
CREATE TABLE usuario_empresas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    cliente_id INT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_company (usuario_id, cliente_id)
);
```

### Nova Tabela: `usuario_permissoes`
Para controle granular de permissões futuras.

```sql
CREATE TABLE usuario_permissoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    secao VARCHAR(100) NOT NULL,
    pode_criar BOOLEAN DEFAULT TRUE,
    pode_editar BOOLEAN DEFAULT TRUE,
    pode_excluir BOOLEAN DEFAULT FALSE,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_section (usuario_id, secao)
);
```

### Como Aplicar a Migration:

```bash
# Via MySQL CLI
mysql -h <host> -u <user> -p <database> < migrations/20260204_add_supervisor_permissions.sql

# Via Python script
python scripts/run_migration.py migrations/20260204_add_supervisor_permissions.sql
```

## 🔧 Mudanças no Código

### 1. Modelo Usuario (`models/usuario.py`)

Novos métodos adicionados:

```python
@staticmethod
def get_empresas_usuario(user_id):
    """Retorna lista de empresas associadas ao usuário SUPERVISOR"""
    
@staticmethod
def set_empresas_usuario(user_id, empresa_ids):
    """Define as empresas associadas ao usuário SUPERVISOR"""
    
@staticmethod
def get_clientes_produtos_posto():
    """Retorna clientes que têm produtos de posto configurados"""
```

### 2. Decorators (`utils/decorators.py`)

Novo decorator adicionado:

```python
@supervisor_or_admin_required
def minha_rota():
    """Rota acessível para SUPERVISOR e ADMIN"""
    pass
```

### 3. Rotas de Autenticação (`routes/auth.py`)

**Criar Usuário:**
- Suporta seleção de múltiplas empresas para SUPERVISOR
- Validação: SUPERVISOR deve ter pelo menos uma empresa

**Editar Usuário:**
- Gerencia empresas associadas ao SUPERVISOR
- Mostra empresas já selecionadas
- Permite adicionar/remover empresas

### 4. Templates HTML

**`templates/auth/usuarios/novo.html`:**
- Campo multiselect para empresas (SUPERVISOR)
- Campo único de posto (PISTA)
- JavaScript para mostrar/ocultar campos baseado no nível

**`templates/auth/usuarios/editar.html`:**
- Mostra empresas selecionadas com checkboxes
- Mantém seleção ao editar
- Validação de pelo menos uma empresa para SUPERVISOR

## 📝 Como Usar

### Criar Usuário SUPERVISOR

1. Acesse: `/auth/usuarios/novo`
2. Preencha os dados básicos
3. Selecione "SUPERVISOR" no nível de acesso
4. Selecione uma ou mais empresas na lista
5. Clique em "Criar Usuário"

### Editar Usuário SUPERVISOR

1. Acesse: `/auth/usuarios`
2. Clique em "Editar" no usuário desejado
3. Modifique as empresas selecionadas
4. Clique em "Atualizar Usuário"

## 🔐 Níveis de Acesso

| Nível       | Descrição                                          | Empresas                   |
|-------------|---------------------------------------------------|----------------------------|
| **ADMIN**   | Acesso total ao sistema                           | Todas (sem restrição)      |
| **GERENTE** | Gestão sem restrição de tempo                     | Todas ou específica (opcional) |
| **SUPERVISOR** | Supervisão com acesso pleno às seções listadas | Múltiplas (obrigatório)   |
| **PISTA**   | Operação básica com limite de 15 min para edição | Uma única (obrigatório)    |

## 🧪 Testes Necessários

### 1. Criação de Usuário SUPERVISOR
```
✓ Criar SUPERVISOR sem empresas deve falhar
✓ Criar SUPERVISOR com uma empresa deve funcionar
✓ Criar SUPERVISOR com múltiplas empresas deve funcionar
✓ Empresas devem ser salvas na tabela usuario_empresas
```

### 2. Edição de Usuário SUPERVISOR
```
✓ Editar e adicionar empresas deve funcionar
✓ Editar e remover empresas deve funcionar
✓ Remover todas empresas deve falhar
✓ Mudar de SUPERVISOR para outro nível deve limpar empresas
```

### 3. Acesso às Rotas
```
✓ SUPERVISOR deve acessar /caixa/novo
✓ SUPERVISOR deve acessar /cartoes/novo
✓ SUPERVISOR deve acessar /tipos_receita_caixa/novo
✓ SUPERVISOR deve acessar /quilometragem/*
✓ SUPERVISOR deve acessar /arla/*
✓ SUPERVISOR deve acessar /posto/*
✓ SUPERVISOR deve acessar /troco_pix/*
✓ PISTA NÃO deve acessar rotas protegidas por supervisor_or_admin_required
```

## 📊 Diagrama de Relacionamentos

```
usuarios
    ├── id
    ├── username
    ├── nivel (ADMIN/GERENTE/SUPERVISOR/PISTA)
    └── cliente_id (apenas PISTA)

usuario_empresas
    ├── usuario_id (FK → usuarios.id)
    └── cliente_id (FK → clientes.id)

clientes
    ├── id
    ├── razao_social
    └── (produtos posto via clientes_produtos)
```

## 🚨 Notas Importantes

1. **Compatibilidade**: PISTA continua usando `cliente_id` na tabela `usuarios`
2. **SUPERVISOR**: Usa `usuario_empresas` para múltiplas empresas
3. **GERENTE**: Pode ou não ter `cliente_id` (opcional)
4. **Filtro de Empresas**: Baseado em `clientes_produtos` (produtos posto)
5. **Fallback**: Se não houver produtos posto configurados, mostra todos os clientes

## 🔄 Rollback

Se necessário reverter as mudanças:

```sql
-- Remover tabelas
DROP TABLE IF EXISTS usuario_permissoes;
DROP TABLE IF EXISTS usuario_empresas;

-- Reverter mudanças nos decorators
-- Substituir @supervisor_or_admin_required por @admin_required
```

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique os logs do sistema
2. Confirme que a migration foi aplicada
3. Verifique permissões do banco de dados
4. Consulte a documentação do Flask-Login

---

**Data de Implementação**: 2026-02-04  
**Versão**: 1.0  
**Autor**: GitHub Copilot Coding Agent
