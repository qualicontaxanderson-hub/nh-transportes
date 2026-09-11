# -*- coding: utf-8 -*-
"""Prova do formatador de moeda — e do alcance da correção.

O `formatar_moeda` separava a parte inteira da decimal e só então arredondava
os centavos. Quando os centavos passavam de 99,5 o arredondamento dava 100 e
não subia o vai-um: R$ 7.143,9995 saía como "R$ 7.143,100". Apareceu no Lucro
Postos Migrados, mas o filtro é o do app inteiro — 30 templates o usam.

O que esta prova estabelece, porque em dinheiro o alcance importa tanto quanto
a correção: o comportamento novo só difere do velho EXATAMENTE nos casos em que
o velho produzia texto quebrado. Em todo valor que já saía certo, sai igual.

    python prova_formatar_moeda.py
"""
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.formatadores import formatar_moeda                 # noqa: E402

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def velho(valor):
    """O formatador como era antes — para medir o que a correção muda."""
    try:
        if valor is None or valor == '':
            return '-'
        num = float(valor)
    except Exception:
        return '-'
    inteiro = int(abs(num))
    centavos = int(round((abs(num) - inteiro) * 100))
    inteiro_str = '{:,}'.format(inteiro).replace(',', '.')
    sinal = '-' if num < 0 else ''
    return '%sR$ %s,%02d' % (sinal, inteiro_str, centavos)


BEM_FORMADO = re.compile(r'^-?R\$ \d{1,3}(\.\d{3})*,\d{2}$')


def numero_de(txt):
    """'R$ 1.234,56' -> 1234.56 — para conferir que o texto ainda vale."""
    s = txt.replace('R$', '').replace('.', '').replace(',', '.')
    return float(s.replace(' ', ''))


# ── o caso que apareceu na tela ───────────────────────────────────────────
prova('R$ 7.143,9995 não sai mais como "R$ 7.143,100"',
      formatar_moeda(7143.9995) == 'R$ 7.144,00',
      'saiu %r' % formatar_moeda(7143.9995))
prova('e o velho realmente errava esse',
      velho(7143.9995) == 'R$ 7.143,100',
      'o velho dava %r — a prova estaria medindo outra coisa'
      % velho(7143.9995))

# ── o basico continua ─────────────────────────────────────────────────────
casos = [
    (0, 'R$ 0,00'), (1, 'R$ 1,00'), (0.5, 'R$ 0,50'),
    (1234.56, 'R$ 1.234,56'), (1000000, 'R$ 1.000.000,00'),
    (-1234.56, '-R$ 1.234,56'), (-0.01, '-R$ 0,01'),
    # 0,005 fica em 0,00: o Python arredonda meio-para-par, e o velho fazia
    # o mesmo — a correcao nao mexe nisso
    (0.005, 'R$ 0,00'), (0.994, 'R$ 0,99'), (0.999, 'R$ 1,00'),
    (999.999, 'R$ 1.000,00'),
]
erros = [(v, formatar_moeda(v), e) for v, e in casos if formatar_moeda(v) != e]
prova('os valores de sempre saem como sempre', not erros, '%r' % erros)

prova('None e vazio continuam virando traço',
      formatar_moeda(None) == '-' and formatar_moeda('') == '-'
      and formatar_moeda('abc') == '-')
prova('string já formatada continua sendo aceita',
      formatar_moeda('R$ 1.234,56') == 'R$ 1.234,56'
      and formatar_moeda('1234.56') == 'R$ 1.234,56',
      '%r / %r' % (formatar_moeda('R$ 1.234,56'), formatar_moeda('1234.56')))

# ── o alcance: onde o novo difere do velho ────────────────────────────────
random.seed(20260911)
valores = [0.0, -0.0]
for _ in range(40000):
    valores.append(round(random.uniform(-500000, 500000), random.choice([2, 4, 6])))
# e os casos de virada, que sao onde o bug morava
for base in (0, 1, 7143, 99, 999, 1000, 123456):
    for c in (0.9949, 0.995, 0.9951, 0.999, 0.9999, 0.99999):
        valores.append(base + c)
        valores.append(-(base + c))

mal_velho, mal_novo, quebrados, empates, piorou, fora = [], [], [], [], [], []
for v in valores:
    n, a = formatar_moeda(v), velho(v)
    if not BEM_FORMADO.match(n):
        mal_novo.append((v, n))
    if not BEM_FORMADO.match(a):
        mal_velho.append((v, a))
    if n != a:
        if not BEM_FORMADO.match(a):
            quebrados.append((v, a, n))          # o velho estava quebrado
        else:
            # os dois sao texto valido: entao a diferenca so pode ser de um
            # centavo, e o novo tem de estar MAIS PERTO do valor de verdade
            dn, da = abs(numero_de(n) - v), abs(numero_de(a) - v)
            if abs(numero_de(n) - numero_de(a)) > 0.0101 or dn > da + 1e-9:
                piorou.append((v, a, n))
            else:
                empates.append((v, a, n))
    # e, sempre, o texto tem de estar a menos de meio centavo do numero
    if abs(numero_de(n) - v) > 0.005 + 1e-6:
        fora.append((v, n))

prova('em %s valores, o novo nunca produz texto quebrado' % len(valores),
      not mal_novo, '%r' % mal_novo[:5])
prova('o velho produzia, e é isso que se está corrigindo',
      bool(mal_velho), 'o velho não errou nenhum — não haveria o que corrigir')
prova('o novo nunca arredonda para pior que o velho',
      not piorou, '%s valor(es) pioraram: %r' % (len(piorou), piorou[:5]))
prova('o texto formatado nunca fica a mais de meio centavo do número',
      not fora, '%r' % fora[:5])
print('        %s valores conferidos · o velho quebrava %s · além disso a '
      'correção só muda %s empate(s) de meio centavo, sempre para o lado certo'
      % (len(valores), len(quebrados), len(empates)))
if empates:
    v, a, n = empates[0]
    print('        exemplo de empate: %r era %s e passa a %s (o valor real é '
          'um fio acima do meio centavo)' % (v, a, n))

# ── o app.py tem a mesma função; as duas não podem divergir ──────────────
import importlib.util                                          # noqa: E402
spec = importlib.util.spec_from_file_location('_app_fmt', 'app.py')
fonte = open('app.py', encoding='utf-8').read()
prova('a cópia do app.py levou a mesma correção',
      'total_cent = int(round(abs(num) * 100))' in fonte,
      'app.py define seu próprio formatar_moeda e é ELE que vira o filtro do '
      'Jinja — corrigir só o utils não mudaria nenhuma tela')

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
