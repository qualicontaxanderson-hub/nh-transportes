--- a/nh-transportes/start.sh
+++ b/nh-transportes/start.sh
@@
-#!/bin/bash
-# Script para limpar cache Python e iniciar a aplicação
-
-echo "Limpando cache Python..."
-find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
-find . -type f -name "*.pyc" -delete 2>/dev/null || true
-find . -type f -name "*.pyo" -delete 2>/dev/null || true
-
-echo "Cache limpo! Iniciando aplicação..."
-
-gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120
+#!/bin/bash
+# Script para limpar cache Python, recriar o P12 a partir do secret e iniciar a aplicação
+
+set -e
+
+echo "Limpando cache Python..."
+find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
+find . -type f -name "*.pyc" -delete 2>/dev/null || true
+find . -type f -name "*.pyo" -delete 2>/dev/null || true
+
+echo "Cache limpo!"
+
+# --- recria certificado P12 a partir do secret EFI_CERT_B64 (se existir) ---
+if [ -n "$EFI_CERT_B64" ] || [ -n "$EFI_CERT_B64_1" ] || [ -n "$EFI_CERT_B64_2" ]; then
+  echo "Decodificando EFI_CERT_B64 para /opt/render/project/src/producao-855343-fretes.p12"
+  mkdir -p /opt/render/project/src
+  # junta possíveis partes automaticamente (compatível com EFI_CERT_B64_1 + EFI_CERT_B64_2)
+  combined="${EFI_CERT_B64}${EFI_CERT_B64_1}${EFI_CERT_B64_2}"
+  # remove possíveis quebras de linha e decodifica
+  printf "%s" "$combined" | tr -d '\r\n' | base64 -d > /opt/render/project/src/producao-855343-fretes.p12
+  chmod 600 /opt/render/project/src/producao-855343-fretes.p12
+else
+  echo "Variável EFI_CERT_B64 não encontrada — pulando criação do P12"
+fi
+# ----------------------------------------------------------------------
+
+echo "Iniciando aplicação..."
+gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120
