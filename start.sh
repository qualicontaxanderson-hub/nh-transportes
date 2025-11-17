#!/bin/bash
# Script para limpar cache Python, executar migração e iniciar a aplicação
echo "Limpando cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true

echo "Cache limpo! Iniciando aplicação..."

echo "Executando migração de dados..."
python3 migrate_fretes.py 2>&1


gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
