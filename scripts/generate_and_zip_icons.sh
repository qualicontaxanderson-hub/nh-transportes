#!/usr/bin/env bash
# Gera ícones iOS (AppIcon.appiconset) usando ImageMagick e empacota em appicon_bundle.zip
# Uso:
#   chmod +x scripts/generate_and_zip_icons.sh
#   ./scripts/generate_and_zip_icons.sh assets/icon.png --background "#ffffff" --pad 8 --radius 0
#
# Parâmetros:
#   1) caminho para a imagem fonte (ex.: assets/icon.png)
#   --background COLOR    cor de fundo (ex.: "#ffffff") ou "transparent" (default "#ffffff")
#   --pad N               padding interno em pixels (default 8)
#   --radius N            raio de cantos arredondados em px (default 0)

set -euo pipefail

if ! command -v convert >/dev/null 2>&1; then
  echo "ImageMagick (convert) não encontrado. Instale antes de prosseguir."
  exit 1
fi

INPUT="${1:-}"
if [ -z "$INPUT" ] || [ ! -f "$INPUT" ]; then
  echo "Uso: $0 assets/icon.png [--background COLOR] [--pad N] [--radius N]"
  exit 1
fi

# defaults
BG="#ffffff"
PAD=8
RADIUS=0

shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --background) BG="$2"; shift 2;;
    --pad) PAD="$2"; shift 2;;
    --radius) RADIUS="$2"; shift 2;;
    *) echo "Opção inválida: $1"; exit 1;;
  esac
done

OUT_DIR="ios/Assets.xcassets/AppIcon.appiconset"
mkdir -p "$OUT_DIR"

declare -A SIZES=(
  ["Icon-20@1x.png"]=20
  ["Icon-20@2x.png"]=40
  ["Icon-20@3x.png"]=60
  ["Icon-29@1x.png"]=29
  ["Icon-29@2x.png"]=58
  ["Icon-29@3x.png"]=87
  ["Icon-40@1x.png"]=40
  ["Icon-40@2x.png"]=80
  ["Icon-40@3x.png"]=120
  ["Icon-60@2x.png"]=120
  ["Icon-60@3x.png"]=180
  ["Icon-76@1x.png"]=76
  ["Icon-76@2x.png"]=152
  ["Icon-83.5@2x.png"]=167
  ["Icon-1024.png"]=1024
  ["Icon-20@2x-ipad.png"]=40
  ["Icon-29@2x-ipad.png"]=58
  ["Icon-40@2x-ipad.png"]=80
)

echo "Gerando ícones em $OUT_DIR (background=$BG pad=${PAD}px radius=${RADIUS}px) a partir de $INPUT"

for name in "${!SIZES[@]}"; do
  size=${SIZES[$name]}
  inner=$((size - 2 * PAD))
  if [ "$inner" -le 0 ]; then
    echo "Padding ($PAD) muito grande para alvo $size. Ajuste o padding."
    exit 1
  fi
  tmp="$(mktemp --suffix=.png 2>/dev/null || mktemp).png"
  convert "$INPUT" -resize "${inner}x${inner}" "$tmp"
  extent_bg="none"
  if [ "$BG" != "transparent" ]; then extent_bg="$BG"; fi
  convert "$tmp" -background "$extent_bg" -gravity center -extent "${size}x${size}" "$OUT_DIR/$name"
  if [ "$RADIUS" -gt 0 ]; then
    mask="$(mktemp --suffix=.png 2>/dev/null || mktemp).png"
    convert -size "${size}x${size}" xc:none -fill white -draw "roundrectangle 0,0 $((size-1)),$((size-1)) $RADIUS,$RADIUS" "$mask"
    convert "$OUT_DIR/$name" "$mask" -alpha set -compose DstIn -composite "$OUT_DIR/$name"
    rm -f "$mask"
  fi
  rm -f "$tmp"
  echo "Criado: $OUT_DIR/$name"
done

# cria Contents.json caso não exista (Xcode espera esse arquivo)
CONTENTS="$OUT_DIR/Contents.json"
cat > "$CONTENTS" <<'JSON'
{
  "images": [
    { "idiom":"iphone","size":"20x20","scale":"2x","filename":"Icon-20@2x.png" },
    { "idiom":"iphone","size":"20x20","scale":"3x","filename":"Icon-20@3x.png" },
    { "idiom":"iphone","size":"29x29","scale":"2x","filename":"Icon-29@2x.png" },
    { "idiom":"iphone","size":"29x29","scale":"3x","filename":"Icon-29@3x.png" },
    { "idiom":"iphone","size":"40x40","scale":"2x","filename":"Icon-40@2x.png" },
    { "idiom":"iphone","size":"40x40","scale":"3x","filename":"Icon-40@3x.png" },
    { "idiom":"iphone","size":"60x60","scale":"2x","filename":"Icon-60@2x.png" },
    { "idiom":"iphone","size":"60x60","scale":"3x","filename":"Icon-60@3x.png" },
    { "idiom":"ipad","size":"20x20","scale":"1x","filename":"Icon-20@1x.png" },
    { "idiom":"ipad","size":"20x20","scale":"2x","filename":"Icon-20@2x-ipad.png" },
    { "idiom":"ipad","size":"29x29","scale":"1x","filename":"Icon-29@1x.png" },
    { "idiom":"ipad","size":"29x29","scale":"2x","filename":"Icon-29@2x-ipad.png" },
    { "idiom":"ipad","size":"40x40","scale":"1x","filename":"Icon-40@1x.png" },
    { "idiom":"ipad","size":"40x40","scale":"2x","filename":"Icon-40@2x-ipad.png" },
    { "idiom":"ipad","size":"76x76","scale":"1x","filename":"Icon-76@1x.png" },
    { "idiom":"ipad","size":"76x76","scale":"2x","filename":"Icon-76@2x.png" },
    { "idiom":"ipad","size":"83.5x83.5","scale":"2x","filename":"Icon-83.5@2x.png" },
    { "idiom":"ios-marketing","size":"1024x1024","scale":"1x","filename":"Icon-1024.png" }
  ],
  "info": { "version":1, "author":"xcode" }
}
JSON

echo "Contents.json criado/atualizado em $CONTENTS"

# cria zip para download fácil
ZIPNAME="appicon_bundle.zip"
rm -f "$ZIPNAME"
cd ios/Assets.xcassets || exit 1
zip -r "../../$ZIPNAME" AppIcon.appiconset >/dev/null
cd - >/dev/null
echo "ZIP criado: $ZIPNAME (contém AppIcon.appiconset). Baixe/compartilhe este arquivo."
