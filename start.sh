#!/bin/bash
# Script para limpar cache Python e iniciar a aplicação

echo "Limpando cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true

echo "Cache limpo! Iniciando aplicação..."

gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120
