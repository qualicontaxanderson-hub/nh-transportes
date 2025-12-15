#!/bin/bash
# Script para limpar cache Python e iniciar a aplicação

echo "Limpando cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true

echo "Cache limpo! Iniciando aplicação..."

# --- recria certificado P12 a partir do secret EFI_CERT_B64 (se existir) ---
# destino pode ser sobrescrito pela variável EFI_CERT_PATH
destination="${EFI_CERT_PATH:-/opt/render/project/src/producao-855343-fretes.p12}"

if [ -n "${EFI_CERT_B64:-}" ] || [ -n "${EFI_CERT_B64_1:-}" ] || [ -n "${EFI_CERT_B64_2:-}" ]; then
  echo "Tentando decodificar EFI_CERT_B64 para ${destination}"
  mkdir -p "$(dirname "$destination")"

  # junta possíveis partes (se você tiver dividido o secret)
  combined="${EFI_CERT_B64}${EFI_CERT_B64_1}${EFI_CERT_B64_2}"

  # remove quebras de linha/carr. retorno e tenta decodificar (compatível com base64 -d ou --decode)
  if printf "%s" "$combined" | tr -d '\r\n' | base64 -d > "$destination" 2>/dev/null || \
     printf "%s" "$combined" | tr -d '\r\n' | base64 --decode > "$destination" 2>/dev/null; then
    chmod 600 "$destination"
    echo "Arquivo P12 criado em ${destination}"
  else
    echo "Falha ao decodificar EFI_CERT_B64 — o conteúdo pode estar corrompido ou inválido"
    # não interrompe a execução; segue para iniciar a aplicação
  fi
fi
# ----------------------------------------------------------------------

gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120
