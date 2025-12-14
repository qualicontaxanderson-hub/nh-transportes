# iOS Icons - NH Transportes

## 📁 Estrutura Atual

```
ios/
└── Assets.xcaAssets/
    └── AppIcon.appiconset (Contents.json apenas)
```

## ⚠️ Status

**Configuração:** ✅ Completa  
**Ícones PNG:** ❌ Não gerados ainda  

## 🚀 Como Gerar os Ícones

Execute o script de geração a partir da raiz do projeto:

```bash
# Da raiz do projeto
./scripts/generate_and_zip_icons.sh static/logo-nh.png \
  --background "#ffffff" --pad 8 --radius 0
```

## 📦 Ícones Que Serão Criados

Após executar o script, esta pasta conterá 18 arquivos PNG:

- **iPhone:** 8 ícones (20@2x, 20@3x, 29@2x, 29@3x, 40@2x, 40@3x, 60@2x, 60@3x)
- **iPad:** 9 ícones (20@1x, 20@2x-ipad, 29@1x, 29@2x-ipad, 40@1x, 40@2x-ipad, 76@1x, 76@2x, 83.5@2x)
- **Marketing:** 1 ícone (1024x1024)

## 📚 Documentação Completa

Para mais detalhes, consulte:
- `../IOS_ICON_ANALYSIS.md` - Análise técnica completa
- `../IOS_ICON_CHECKLIST.md` - Checklist rápido

## 🔧 Pré-requisitos

Antes de executar o script:

1. ImageMagick instalado: `sudo apt-get install imagemagick`
2. Script com permissão de execução: `chmod +x scripts/generate_and_zip_icons.sh`

## ✨ Resultado Final

Após a geração:
```
ios/
└── Assets.xcassets/
    └── AppIcon.appiconset/
        ├── Contents.json
        ├── Icon-20@1x.png
        ├── Icon-20@2x.png
        ├── Icon-20@3x.png
        ├── ... (15 mais)
        └── Icon-1024.png
```

E na raiz do projeto:
```
appicon_bundle.zip (pronto para usar no Xcode)
```
