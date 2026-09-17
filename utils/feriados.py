# -*- coding: utf-8 -*-
"""Os feriados NACIONAIS do Brasil, calculados — não cadastrados.

Quem depende deles é a conta de dia útil: o cartão vendido hoje cai na conta
em N dias úteis, e um feriado no meio empurra a data. Errar o feriado é errar
o dia do dinheiro.

POR QUE CALCULAR, E NÃO CADASTRAR
  Cadastrar exige lembrar todo ano, e um ano esquecido não dá erro — dá uma
  diferença silenciosa no relatório de cartões. Calculado, 2027 já nasce
  certo. E ninguém apaga por engano: esta lista não tem botão de excluir.

SÓ OS NACIONAIS, DE PROPÓSITO
  Feriado municipal e estadual NÃO entram, decisão do Anderson (17/09/2026):
  a praça do posto pode parar, mas quem processa o cartão e credita na conta
  costuma estar em outro estado, onde o dia foi útil — então o dinheiro anda.
  Quem quiser marcar um feriado local ainda pode, no cadastro manual da tela:
  esta lista não substitui aquele, soma-se a ele.

O QUE ENTRA (Lei 662/1949, Lei 10.607/2002, Lei 9.093/1995 e
Lei 14.759/2023):
    01/01  Confraternização Universal
    21/04  Tiradentes
    01/05  Dia do Trabalho
    07/09  Independência
    12/10  Nossa Senhora Aparecida
    02/11  Finados
    15/11  Proclamação da República
    20/11  Consciência Negra   (nacional desde 2024)
    25/12  Natal
    Sexta-feira Santa          (móvel: Páscoa − 2 dias)

O QUE NÃO ENTRA: Carnaval e Corpus Christi. Eles NÃO são feriado nacional --
são ponto facultativo. Mas o banco não opera neles, e para a conta de dia útil
é o banco que importa; por isso eles continuam valendo pelo cadastro manual da
tela, que é onde já estavam.
"""
from datetime import date, timedelta

# Os de data fixa: (mes, dia) -> nome.
_FIXOS = [
    ((1, 1), 'Confraternização Universal'),
    ((4, 21), 'Tiradentes'),
    ((5, 1), 'Dia do Trabalho'),
    ((9, 7), 'Independência'),
    ((10, 12), 'Nossa Senhora Aparecida'),
    ((11, 2), 'Finados'),
    ((11, 15), 'Proclamação da República'),
    ((11, 20), 'Consciência Negra'),
    ((12, 25), 'Natal'),
]

# A Consciencia Negra so virou feriado NACIONAL com a Lei 14.759, de 21/12/2023
# -- antes disso era feriado apenas em alguns estados e municipios. Em 2023 e
# antes, portanto, ela nao entra: dizer que entrava mudaria a conta de dia util
# de um ano que ja fechou.
_ANO_CONSCIENCIA_NEGRA = 2024


def pascoa(ano):
    """Domingo de Páscoa do ano (algoritmo de Meeus/Butcher, calendário
    gregoriano). É daqui que sai a Sexta-feira Santa."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lb = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * lb) // 433
    mes = (h + lb - 7 * m + 90) // 25
    dia = (h + lb - 7 * m + 33 * mes + 19) % 32
    return date(ano, mes, dia)


def nacionais(ano):
    """{date: nome} com os feriados nacionais daquele ano."""
    saida = {}
    for (mes, dia), nome in _FIXOS:
        if nome == 'Consciência Negra' and ano < _ANO_CONSCIENCIA_NEGRA:
            continue
        saida[date(ano, mes, dia)] = nome
    saida[pascoa(ano) - timedelta(days=2)] = 'Sexta-feira Santa'
    return saida


def nacionais_periodo(ano_ini, ano_fim):
    """{date: nome} de vários anos de uma vez, inclusive nas pontas."""
    if ano_fim < ano_ini:
        ano_ini, ano_fim = ano_fim, ano_ini
    saida = {}
    for ano in range(ano_ini, ano_fim + 1):
        saida.update(nacionais(ano))
    return saida


def set_iso(ano_ini, ano_fim):
    """As mesmas datas como {'AAAA-MM-DD'} — o formato que a conta de dia útil
    usa (conf_cartoes._next_business_day e bank_import comparam ISO)."""
    return {d.isoformat() for d in nacionais_periodo(ano_ini, ano_fim)}
