# 🔐 Gestão de Permissões - Sistema NH Transportes

## 📋 Pergunta do Usuário

> "Ai eu preciso saber se será criado um local para eu administrar o que cada Nivel tem acesso ou se sempre que precisar incluir ou alterar um nivel eu acesso por aqui!"

## 💡 Resposta

Atualmente, as permissões dos níveis de acesso são **definidas diretamente no código** do sistema. Quando você precisa alterar as permissões de um nível, isso é feito através de modificações no código fonte, como foi feito nesta implementação.

### Como Funciona Atualmente

As permissões são controladas em **dois lugares principais**:

#### 1. **Menu de Navegação** (`templates/includes/navbar.html`)
- Define quais menus cada nível pode ver
- Usa condições Jinja2 para mostrar/ocultar itens baseado no nível do usuário
- Exemplo: `{% if nivel_usuario != 'SUPERVISOR' %}` oculta itens para SUPERVISOR

#### 2. **Decorators nas Rotas** (arquivos em `routes/`)
- Cada rota (função) tem decorators que controlam quem pode acessar
- `@login_required` - Requer login
- `@admin_required` - Apenas ADMIN
- `@nivel_required(['ADMIN', 'GERENTE', 'SUPERVISOR'])` - Lista de níveis permitidos

### Exemplo de Como Foi Implementado

```python
# Antes (apenas ADMIN):
@bp.route('/novo')
@login_required
@admin_required
def novo():
    ...

# Depois (ADMIN, GERENTE e SUPERVISOR):
@bp.route('/novo')
@login_required
@nivel_required(['ADMIN', 'GERENTE', 'SUPERVISOR'])
def novo():
    ...
```

## 🚀 Opções para o Futuro

### Opção 1: Continuar com Código (Atual)
**Vantagens:**
- ✅ Controle total e precisão
- ✅ Não requer desenvolvimento adicional
- ✅ Mudanças documentadas via Git
- ✅ Sem risco de configuração incorreta por usuário

**Desvantagens:**
- ❌ Requer conhecimento técnico
- ❌ Necessita acesso ao código
- ❌ Mudanças precisam de deploy

**Quando usar:**
- Mudanças pontuais e bem definidas
- Alterações que afetam a segurança do sistema
- Quando há um desenvolvedor disponível

### Opção 2: Interface de Administração (Futuro)
**Poderia ser desenvolvido um painel administrativo onde:**
- 📊 Visualizar todos os módulos do sistema
- ✏️ Configurar permissões por nível de acesso
- 💾 Salvar configurações no banco de dados
- 🔄 Aplicar mudanças em tempo real (sem deploy)

**Exemplo de Interface:**
```
┌─────────────────────────────────────────┐
│  Administração de Permissões            │
├─────────────────────────────────────────┤
│  Módulo: Cartões                        │
│  ☑ ADMIN    ☑ GERENTE    ☑ SUPERVISOR  │
│                                         │
│  Módulo: Formas Pagamento Caixa        │
│  ☑ ADMIN    ☑ GERENTE    ☑ SUPERVISOR  │
│                                         │
│  Módulo: Fechamento de Caixa           │
│  ☑ ADMIN    ☑ GERENTE    ☑ SUPERVISOR  │
│                                         │
│  [Salvar Configurações]                 │
└─────────────────────────────────────────┘
```

**Vantagens:**
- ✅ Não requer conhecimento técnico
- ✅ Mudanças rápidas e fáceis
- ✅ Interface visual e intuitiva
- ✅ Histórico de alterações

**Desvantagens:**
- ❌ Requer desenvolvimento adicional (tempo e custo)
- ❌ Possibilidade de configuração incorreta
- ❌ Necessita mais testes e validações
- ❌ Banco de dados mais complexo

## 📝 Recomendação Atual

Para a **situação atual**, recomendo:

1. **Continuar usando código** para definir permissões
2. **Documentar bem** as permissões de cada nível (como em `NIVEIS_ACESSO.md`)
3. **Fazer mudanças via GitHub/GitLab** como foi feito agora
4. **Avaliar futuro painel** se houver necessidade frequente de mudanças

## 🎯 Para Solicitar Mudanças de Permissões

Quando precisar alterar permissões:

1. **Abra um issue/ticket** descrevendo:
   - Qual nível precisa de mudança
   - Quais módulos adicionar/remover
   - Se deve poder visualizar, criar, editar ou excluir

2. **Forneça exemplos** como você fez:
   - "SUPERVISOR precisa acessar Cartões"
   - "Pode visualizar, alterar e cadastrar"

3. **Aguarde implementação** (geralmente rápida)

4. **Teste e valide** após deploy

## 📚 Documentação das Permissões Atuais

Consulte sempre o arquivo **`docs/NIVEIS_ACESSO.md`** para ver:
- Lista completa de permissões por nível
- Comparativo entre níveis
- Módulos que cada nível pode acessar

## ✅ Conclusão

**Para agora:** Continue solicitando mudanças de permissões via código (como foi feito nesta implementação).

**Para o futuro:** Se houver necessidade frequente de alterar permissões (mais de 1-2 vezes por mês), vale a pena considerar o desenvolvimento de uma interface administrativa.

---

**Implementado em:** 03/02/2026  
**Documentado por:** GitHub Copilot  
**Revisão:** Equipe NH Transportes
