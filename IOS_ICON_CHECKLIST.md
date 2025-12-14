# ✅ Checklist: Ícones iOS - O Que Falta

## Status Rápido

### ✅ O Que Você JÁ TEM
- [x] Arquivo de configuração iOS (Contents.json)
- [x] Script completo de geração de ícones
- [x] Logo fonte (logo-nh.png - 527x595px)

### ❌ O Que FALTA Fazer

- [ ] **1. Instalar ImageMagick**
  ```bash
  sudo apt-get update && sudo apt-get install imagemagick
  ```
  
- [ ] **2. Tornar o script executável**
  ```bash
  chmod +x scripts/generate_and_zip_icons.sh
  ```
  
- [ ] **3. Gerar os 18 ícones iOS**
  ```bash
  ./scripts/generate_and_zip_icons.sh static/logo-nh.png --background "#ffffff" --pad 8 --radius 0
  ```

---

## Arquivos Que Serão Criados

Após executar o script, você terá:

### 📁 ios/Assets.xcaAssets/AppIcon.appiconset/
- [ ] Icon-20@1x.png (20x20)
- [ ] Icon-20@2x.png (40x40)
- [ ] Icon-20@3x.png (60x60)
- [ ] Icon-29@1x.png (29x29)
- [ ] Icon-29@2x.png (58x58)
- [ ] Icon-29@3x.png (87x87)
- [ ] Icon-40@1x.png (40x40)
- [ ] Icon-40@2x.png (80x80)
- [ ] Icon-40@3x.png (120x120)
- [ ] Icon-60@2x.png (120x120)
- [ ] Icon-60@3x.png (180x180)
- [ ] Icon-76@1x.png (76x76)
- [ ] Icon-76@2x.png (152x152)
- [ ] Icon-83.5@2x.png (167x167)
- [ ] Icon-1024.png (1024x1024)
- [ ] Icon-20@2x-ipad.png (40x40)
- [ ] Icon-29@2x-ipad.png (58x58)
- [ ] Icon-40@2x-ipad.png (80x80)

### 📦 Na raiz do projeto
- [ ] appicon_bundle.zip (ZIP pronto para usar)

---

## Comandos Rápidos (Copy/Paste)

```bash
# Passo 1: Instalar ImageMagick
sudo apt-get update && sudo apt-get install imagemagick

# Passo 2: Ir para o diretório do projeto
cd /home/runner/work/nh-transportes/nh-transportes

# Passo 3: Tornar executável
chmod +x scripts/generate_and_zip_icons.sh

# Passo 4: Gerar ícones
./scripts/generate_and_zip_icons.sh static/logo-nh.png --background "#ffffff" --pad 8 --radius 0

# Passo 5: Verificar resultado
ls -lh ios/Assets.xcaAssets/AppIcon.appiconset/*.png
ls -lh appicon_bundle.zip
```

---

## Opções de Personalização

Se quiser customizar os ícones:

### Fundo Transparente
```bash
./scripts/generate_and_zip_icons.sh static/logo-nh.png --background "transparent" --pad 8 --radius 0
```

### Com Cantos Arredondados
```bash
./scripts/generate_and_zip_icons.sh static/logo-nh.png --background "#ffffff" --pad 8 --radius 20
```

### Sem Padding
```bash
./scripts/generate_and_zip_icons.sh static/logo-nh.png --background "#ffffff" --pad 0 --radius 0
```

### Fundo Colorido
```bash
./scripts/generate_and_zip_icons.sh static/logo-nh.png --background "#007AFF" --pad 12 --radius 15
```

---

## 🎯 Resumo Ultra-Rápido

**Você está a 3 comandos de ter todos os ícones iOS prontos!**

1. Instale ImageMagick
2. Torne o script executável
3. Execute o script

**Tempo estimado:** 2-5 minutos ⚡

---

## Verificação Final

Depois de executar, você deve ter:
- ✅ 18 arquivos PNG em `ios/Assets.xcaAssets/AppIcon.appiconset/`
- ✅ 1 arquivo ZIP em `appicon_bundle.zip`
- ✅ Projeto pronto para usar ícones iOS no Xcode!
