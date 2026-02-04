# 📸 Guia Visual com "Screenshots" - GitHub Web

## 🎯 Como Fazer Merge no GitHub (Passo a Passo Visual)

---

## 🌐 PASSO 1: Abrir GitHub

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  GitHub                                    🔍 Search  [👤]  │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  📁 qualicontaxanderson-hub / nh-transportes              │
│                                                             │
│  [< > Code] [📊 Issues] [🔀 Pull requests] [⚙️ Settings]  │
│       ↑                         ↑                          │
│   Você está aqui           Vai clicar aqui                 │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
- Clique em **"Pull requests"** (terceira aba)

---

## 📝 PASSO 2: Nova Pull Request

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  Pull requests                                             │
│                                                             │
│  🔍 Search           Filters ▼    [ New pull request ]    │
│                                           ↑                 │
│                                     Clique aqui             │
│                                                             │
│  📋 Lista de PRs vazias ou existentes...                  │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
- Clique no botão verde **"New pull request"** (canto direito)

---

## 🔄 PASSO 3: Comparar Branches

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  Compare changes                                           │
│                                                             │
│  Choose two branches to see what's changed or to start    │
│  a new pull request.                                       │
│                                                             │
│  base: [main ▼]  ←  compare: [Choose branch... ▼]        │
│        ↑                            ↑                       │
│    Já está ok              Clique aqui e escolha           │
│                                                             │
│  [ Create pull request ]                                   │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
1. Deixe **base** como **main** (já está)
2. Clique no dropdown **"compare"**
3. Procure e selecione: `copilot/fix-troco-pix-auto-error`

---

## ✅ PASSO 4: Ver Comparação

**O que você vê depois de selecionar:**
```
┌────────────────────────────────────────────────────────────┐
│  Comparing changes                                         │
│                                                             │
│  base: main  ←  compare: copilot/fix-troco-pix-auto-error│
│                                                             │
│  ✅ Able to merge. These branches can be automatically    │
│     merged.                                                │
│                                                             │
│  [ Create pull request ]  ← Clique aqui                   │
│                                                             │
│  📁 Files changed (3)                                      │
│  └─ routes/troco_pix.py         +50 -20                   │
│  └─ templates/lancamentos_ca... +10 -5                    │
│  └─ CORRECAO_TROCO_PIX_AUTO...  +100 -0                  │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
- Clique no botão **"Create pull request"**

---

## ✍️ PASSO 5: Preencher Detalhes

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  Open a pull request                                       │
│                                                             │
│  Title: ┌────────────────────────────────────────────┐   │
│         │ [Digite aqui o título]                     │   │
│         └────────────────────────────────────────────┘   │
│                                                             │
│  Leave a comment:                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │ [Digite aqui a descrição - opcional]                 ││
│  │                                                       ││
│  └──────────────────────────────────────────────────────┘│
│                                                             │
│  [ Create pull request ]  ← Clique aqui                   │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
1. **Título:** Digite "Correção: Bug TROCO PIX AUTO"
2. **Descrição:** (opcional) "Corrige carregamento automático"
3. Clique em **"Create pull request"**

---

## 🎯 PASSO 6: Pull Request Criado

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  Correção: Bug TROCO PIX AUTO  #42                        │
│  Open     copilot-bot wants to merge 3 commits            │
│                                                             │
│  Corrige carregamento automático                          │
│                                                             │
│  ─────────────────────────────────────────                │
│                                                             │
│  📝 Conversation    📂 Commits    📄 Files changed        │
│                                                             │
│  ✅ This branch has no conflicts with the base branch     │
│                                                             │
│     [ Merge pull request ▼]  ← Clique aqui               │
│                                                             │
│  ⚠️ You can also open this in GitHub Desktop or view     │
│     command line instructions.                            │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
- Role para baixo até ver a caixa verde
- Clique em **"Merge pull request"**

---

## ✔️ PASSO 7: Confirmar Merge

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  ✅ This branch has no conflicts with the base branch     │
│                                                             │
│  Merge pull request #42 from copilot/fix-troco-pix...    │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐│
│  │ [Título da mensagem de merge]                        ││
│  └──────────────────────────────────────────────────────┘│
│                                                             │
│  [ Confirm merge ]  ← Clique aqui                         │
│  [  Cancel  ]                                              │
└────────────────────────────────────────────────────────────┘
```

**O que fazer:**
- Clique no botão verde **"Confirm merge"**

---

## 🎉 PASSO 8: Merge Concluído!

**O que você vê:**
```
┌────────────────────────────────────────────────────────────┐
│  ✅ Pull request successfully merged and closed           │
│                                                             │
│  copilot/fix-troco-pix-auto-error is now merged into     │
│  main                                                      │
│                                                             │
│  [ Delete branch ]  ← Opcional: pode deletar              │
│                                                             │
│  🎊 Congrats! You've merged your first pull request!      │
└────────────────────────────────────────────────────────────┘
```

**Resultado:**
✅ **PRIMEIRO MERGE FEITO COM SUCESSO!**

---

## 🔁 REPETIR PARA O SEGUNDO BRANCH

Agora repita **TODOS os passos acima** (Passos 2-8) para:

**Branch:** `copilot/define-access-levels-manager-supervisor`

**Título:** "Feature: Permissões SUPERVISOR"

**Vai ser EXATAMENTE igual, só muda o nome do branch!**

---

## 📊 FLUXOGRAMA VISUAL

```
    🌐 Abrir GitHub
         ↓
    🔀 Pull requests (aba)
         ↓
    ➕ New pull request
         ↓
    🔄 Escolher branches
         ↓
    ✍️ Create pull request
         ↓
    📝 Preencher título
         ↓
    ✅ Create pull request
         ↓
    🎯 Merge pull request
         ↓
    ✔️ Confirm merge
         ↓
    🎉 FEITO!
         ↓
    🔁 Repetir para segundo branch
```

---

## 🎬 "CLIQUE AQUI" - Resumo dos Botões

### Na ordem que você vai clicar:

1. **"Pull requests"** (aba no topo)
2. **"New pull request"** (botão verde direita)
3. **Dropdown "compare"** (escolher branch)
4. **"Create pull request"** (botão verde)
5. **"Create pull request"** (botão verde de novo)
6. **"Merge pull request"** (botão verde)
7. **"Confirm merge"** (botão verde)

**Repetir 1-7 para o segundo branch!**

---

## 💡 TRUQUES VISUAIS

### Como Saber se É o Botão Certo?

✅ **Botões de ação principais são VERDES**  
✅ **Ficam em destaque (maiores)**  
✅ **Tem texto claro: "Merge", "Create", "Confirm"**

### Se Não Achar o Botão?

- Use **Ctrl+F** (ou Cmd+F no Mac)
- Procure por "merge" ou "pull request"
- Role a página para baixo

### Cores dos Botões:

- 🟢 **Verde** = Ação principal (clique!)
- ⚪ **Branco/Cinza** = Cancelar
- 🔴 **Vermelho** = Deletar (cuidado!)

---

## ✅ CHECKLIST VISUAL

Marque conforme faz:

### Primeiro PR (Bug Fix):
- [ ] Vi a página do GitHub
- [ ] Cliquei em "Pull requests"
- [ ] Cliquei em "New pull request"
- [ ] Vi os dois dropdowns (base e compare)
- [ ] Selecionei fix-troco-pix-auto-error
- [ ] Vi "✅ Able to merge"
- [ ] Cliquei em "Create pull request"
- [ ] Preenchi título e descrição
- [ ] Cliquei em "Create pull request" de novo
- [ ] Vi a página do PR criado
- [ ] Cliquei em "Merge pull request"
- [ ] Cliquei em "Confirm merge"
- [ ] Vi "✅ successfully merged"

### Segundo PR (Permissões):
- [ ] Repeti TODOS os passos acima
- [ ] Mas com o branch: define-access-levels-manager-supervisor
- [ ] ✅ Ambos merges concluídos!

---

## 🎯 VOCÊ CONSEGUE!

**É só seguir as "telas" acima!**  
**Cada "tela" mostra o que você vai ver!**  
**Cada seta (↑) mostra onde clicar!**

**Não tem erro! É só clicar nos botões VERDES! 🟢**

---

**Criado especialmente para quem prefere interface visual!** 🖱️✨
