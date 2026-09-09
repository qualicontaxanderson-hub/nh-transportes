# -*- coding: utf-8 -*-
"""Contraste dos textos das telas do Troco PIX, medido — não olhado.

"Ficou muito claro os texto." Cinza-claro em fonte de 0,66rem some no celular
ao sol, e é justamente onde estão as coisas pequenas que importam: a chave
PIX, a data, o rótulo do valor, os selos.

Aqui cada par cor/fundo declarado no CSS das duas telas é medido pela fórmula
de contraste do WCAG. O piso é 4.5:1, que é o mínimo para texto normal — o
mesmo que a W3C exige.

Não abre o app nem o banco: lê os arquivos.

    python prova_contraste_pix.py
"""
import io
import re
import sys

PISO = 4.5
ARQUIVOS = ('templates/troco_pix/listar.html',
            'templates/troco_pix/clientes.html')

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def rgb(cor):
    c = cor.strip().lstrip('#')
    if len(c) == 3:
        c = ''.join(x * 2 for x in c)
    if len(c) != 6:
        return None
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def luminancia(cor):
    def canal(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = cor
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(frente, fundo):
    a, b = luminancia(frente), luminancia(fundo)
    claro, escuro = max(a, b), min(a, b)
    return (claro + 0.05) / (escuro + 0.05)


for arq in ARQUIVOS:
    css = io.open(arq, encoding='utf-8').read()
    # as variáveis da tela (--muted, --blue, ...)
    vars_ = dict(re.findall(r'(--[a-z-]+):\s*(#[0-9a-fA-F]{3,6})', css))

    def cor_de(txt):
        txt = txt.strip()
        m = re.match(r'var\((--[a-z-]+)\)', txt)
        if m:
            txt = vars_.get(m.group(1), '')
        return rgb(txt) if txt.startswith('#') else None

    regras = re.findall(r'(#tp[xc][^{}]*)\{([^}]*)\}', css)
    medidos = 0
    print('\n%s' % arq)
    for seletor, corpo in regras:
        m_cor = re.search(r'(?<!-)color:\s*([^;]+);', corpo)
        if not m_cor:
            continue
        frente = cor_de(m_cor.group(1))
        if not frente:
            continue
        m_fundo = re.search(r'background:\s*([^;]+);', corpo)
        alvo = m_fundo.group(1).strip() if m_fundo else ''
        if alvo.startswith('linear-gradient') or alvo.startswith('rgba'):
            continue                      # gradiente/transparência: não dá para medir aqui
        fundo = cor_de(alvo) if alvo else (255, 255, 255)
        if not fundo:
            continue
        r = contraste(frente, fundo)
        medidos += 1
        nome = ' '.join(seletor.split())
        prova('%s — %.1f:1' % (nome, r), r >= PISO,
              'abaixo de %.1f:1 (texto some no sol)' % PISO)
    prova('%s: houve o que medir' % arq.split('/')[-1], medidos >= 8,
          'só %d pares medidos' % medidos)

# O cinza dos textos secundários é o que estava claro demais: fica explícito
# aqui para nunca mais voltar sem alguém perceber.
for arq in ARQUIVOS:
    css = io.open(arq, encoding='utf-8').read()
    m = re.search(r'--muted:\s*(#[0-9a-fA-F]{6})', css)
    r = contraste(rgb(m.group(1)), (255, 255, 255)) if m else 0
    prova('o cinza dos textos secundários de %s tem %.1f:1'
          % (arq.split('/')[-1], r), r >= 7.0,
          'o piso aqui é 7:1 (AAA), porque esses textos são de 0,66rem')

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S)' % len(falhas)))
sys.exit(1 if falhas else 0)
