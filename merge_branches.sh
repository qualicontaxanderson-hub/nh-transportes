#!/bin/bash
# Script de ajuda para fazer merge dos branches
# Uso: bash merge_branches.sh [opcao]

echo "🚀 Script de Merge - NH Transportes"
echo "===================================="
echo ""

# Cores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Verificar se está no diretório correto
if [ ! -d ".git" ]; then
    echo -e "${RED}❌ Erro: Execute este script na raiz do repositório Git${NC}"
    exit 1
fi

# Mostrar opções se nenhum argumento for passado
if [ $# -eq 0 ]; then
    echo "Escolha uma opção:"
    echo ""
    echo "  1) Merge dos dois branches ao mesmo tempo (RECOMENDADO)"
    echo "  2) Merge sequencial (bug fix primeiro, depois permissões)"
    echo "  3) Apenas mostrar status atual"
    echo "  4) Sair"
    echo ""
    read -p "Digite o número da opção: " opcao
else
    opcao=$1
fi

echo ""

case $opcao in
    1)
        echo -e "${YELLOW}📦 Opção 1: Merge simultâneo${NC}"
        echo "Fazendo merge dos dois branches ao mesmo tempo..."
        echo ""
        
        # Ir para main
        echo "1️⃣ Indo para branch main..."
        git checkout main
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Erro ao trocar para branch main${NC}"
            exit 1
        fi
        
        # Atualizar
        echo "2️⃣ Atualizando repositório..."
        git fetch origin
        git pull origin main
        
        # Merge 1
        echo "3️⃣ Fazendo merge do bug fix (fix-troco-pix-auto-error)..."
        git merge origin/copilot/fix-troco-pix-auto-error -m "Merge: Correção bug TROCO PIX AUTO"
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Conflito detectado no primeiro merge!${NC}"
            echo "Resolva os conflitos e execute: git merge --continue"
            exit 1
        fi
        
        # Merge 2
        echo "4️⃣ Fazendo merge das permissões (define-access-levels-manager-supervisor)..."
        git merge origin/copilot/define-access-levels-manager-supervisor -m "Merge: Permissões SUPERVISOR"
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Conflito detectado no segundo merge!${NC}"
            echo "Resolva os conflitos e execute: git merge --continue"
            exit 1
        fi
        
        # Push
        echo "5️⃣ Enviando para o servidor..."
        git push origin main
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Erro ao fazer push${NC}"
            exit 1
        fi
        
        echo ""
        echo -e "${GREEN}✅ Sucesso! Ambos os branches foram mesclados!${NC}"
        echo ""
        echo "📋 Próximos passos:"
        echo "  - Teste o TROCO PIX AUTO"
        echo "  - Teste as permissões SUPERVISOR"
        echo "  - Faça deploy se necessário"
        ;;
        
    2)
        echo -e "${YELLOW}📦 Opção 2: Merge sequencial${NC}"
        echo "Fazendo merge um de cada vez..."
        echo ""
        
        # Ir para main
        echo "1️⃣ Indo para branch main..."
        git checkout main
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Erro ao trocar para branch main${NC}"
            exit 1
        fi
        
        # Atualizar
        echo "2️⃣ Atualizando repositório..."
        git fetch origin
        git pull origin main
        
        # Merge 1
        echo "3️⃣ Fazendo merge do bug fix (fix-troco-pix-auto-error)..."
        git merge origin/copilot/fix-troco-pix-auto-error -m "Merge: Correção bug TROCO PIX AUTO"
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Conflito detectado!${NC}"
            echo "Resolva os conflitos e execute: git merge --continue"
            exit 1
        fi
        
        # Push 1
        echo "4️⃣ Enviando primeiro merge..."
        git push origin main
        
        echo ""
        echo -e "${GREEN}✅ Primeiro merge concluído!${NC}"
        echo ""
        read -p "Testar antes de continuar? (s/N): " testar
        
        if [[ $testar =~ ^[Ss]$ ]]; then
            echo "👍 Teste o sistema agora. Quando estiver pronto, execute:"
            echo "   bash $0 2-continuar"
            exit 0
        fi
        
        # Merge 2
        echo "5️⃣ Fazendo merge das permissões (define-access-levels-manager-supervisor)..."
        git fetch origin
        git pull origin main
        git merge origin/copilot/define-access-levels-manager-supervisor -m "Merge: Permissões SUPERVISOR"
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Conflito detectado!${NC}"
            echo "Resolva os conflitos e execute: git merge --continue"
            exit 1
        fi
        
        # Push 2
        echo "6️⃣ Enviando segundo merge..."
        git push origin main
        
        echo ""
        echo -e "${GREEN}✅ Sucesso! Ambos os branches foram mesclados!${NC}"
        ;;
        
    "2-continuar")
        echo -e "${YELLOW}📦 Continuando merge sequencial...${NC}"
        
        git checkout main
        git fetch origin
        git pull origin main
        
        echo "Fazendo merge das permissões..."
        git merge origin/copilot/define-access-levels-manager-supervisor -m "Merge: Permissões SUPERVISOR"
        if [ $? -ne 0 ]; then
            echo -e "${RED}❌ Conflito detectado!${NC}"
            exit 1
        fi
        
        git push origin main
        echo -e "${GREEN}✅ Merge completo!${NC}"
        ;;
        
    3)
        echo -e "${YELLOW}📊 Status atual${NC}"
        echo ""
        
        echo "Branch atual:"
        git branch --show-current
        echo ""
        
        echo "Status do repositório:"
        git status
        echo ""
        
        echo "Branches disponíveis:"
        git branch -a | grep -E "fix-troco|define-access"
        echo ""
        
        echo "Últimos commits:"
        git log --oneline -5
        ;;
        
    4)
        echo "👋 Saindo..."
        exit 0
        ;;
        
    *)
        echo -e "${RED}❌ Opção inválida${NC}"
        echo "Use: bash $0 [1|2|3|4]"
        exit 1
        ;;
esac

echo ""
echo "✨ Script concluído!"
