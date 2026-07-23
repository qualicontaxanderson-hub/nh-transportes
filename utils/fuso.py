# -*- coding: utf-8 -*-
"""Fuso horário de Brasília para filtros de data.

O container roda em UTC, mas dh_emissao das vendas é gravado em horário de
BRASÍLIA. Usar date.today() (= data UTC) faz o "hoje" virar depois das 21h BRT:
as vendas das 21h–23h59 caem no dia anterior e os cards do dia zeram. O mesmo
vale para a virada de mês — dia 31 às 21h BRT já é dia 1 em UTC.

Módulo PURO de propósito: sem Flask, sem banco. Assim o teste
(scripts/test_fuso_dashboard.py) importa exatamente o código que roda em
produção, sem subir a aplicação.

pytz e não zoneinfo: zoneinfo lê /usr/share/zoneinfo do SO, que costuma vir
vazio em container slim; pytz já está no requirements e traz a tabela dentro.
"""
from datetime import date, datetime, timedelta

import pytz

BRASILIA = pytz.timezone('America/Sao_Paulo')


def hoje_brasilia():
    """Data de HOJE em Brasília, independente do fuso do servidor."""
    return datetime.now(BRASILIA).date()


def janelas_dia_mes(hoje):
    """Janelas SQL semiabertas [ini, fim) do dia e do mês de `hoje`.

    `hoje` tem que ser a data de Brasília (ver hoje_brasilia), porque é nesse
    fuso que dh_emissao está gravado.

    Retorna (ini_dia, fim_dia, ini_mes, fim_mes) como strings 'Y-m-d H:M:S'.
    """
    prox_mes = (date(hoje.year + 1, 1, 1) if hoje.month == 12
                else date(hoje.year, hoje.month + 1, 1))
    return (hoje.strftime('%Y-%m-%d 00:00:00'),
            (hoje + timedelta(days=1)).strftime('%Y-%m-%d 00:00:00'),
            hoje.replace(day=1).strftime('%Y-%m-%d 00:00:00'),
            prox_mes.strftime('%Y-%m-%d 00:00:00'))
