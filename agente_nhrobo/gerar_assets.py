# -*- coding: utf-8 -*-
"""Gera os assets embutidos do agente a partir das imagens OFICIAIS do sistema
(as MESMAS do app), para a próxima versão não depender de ninguém
lembrar de onde saiu cada imagem:

  - nhrobo_logo.png : o logo do Grupo NH (static/logo-nh.png),
    redimensionado para caber no cabeçalho da janela (a mesma do app).
  - nhrobo_icon.png : a marca NH (static/icons/icon-512.png) em 256px, para o
    ícone da janela e da BANDEJA — o mesmo desenho do ícone do app.
  - nhrobo.ico      : a mesma marca em múltiplos tamanhos, para o ícone do
    EXECUTÁVEL (Nuitka --windows-icon-from-ico).

Rodar da raiz do repositório:  python agente_nhrobo/gerar_assets.py
"""
import os

from PIL import Image

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.join(RAIZ, "agente_nhrobo")
LOGO_SRC = os.path.join(RAIZ, "static", "logo-nh.png")
QMARK_SRC = os.path.join(RAIZ, "static", "icons", "icon-512.png")

ALTURA_LOGO = 44          # altura do logo no cabeçalho (px), como no Q-Robô


def main():
    # 1) logo do cabeçalho — preserva proporção, altura fixa.
    logo = Image.open(LOGO_SRC).convert("RGBA")
    larg = max(1, round(logo.width * ALTURA_LOGO / logo.height))
    logo.resize((larg, ALTURA_LOGO), Image.LANCZOS).save(
        os.path.join(AQUI, "nhrobo_logo.png"))
    print("nhrobo_logo.png:", larg, "x", ALTURA_LOGO)

    # 2) "Q" verde — 256px para janela/bandeja.
    q = Image.open(QMARK_SRC).convert("RGBA")
    q.resize((256, 256), Image.LANCZOS).save(os.path.join(AQUI, "nhrobo_icon.png"))
    print("nhrobo_icon.png: 256 x 256")

    # 3) .ico multi-tamanho para o executável.
    q.save(os.path.join(AQUI, "nhrobo.ico"),
           sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("nhrobo.ico: 16..256")


if __name__ == "__main__":
    main()
