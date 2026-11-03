# -*- coding: utf-8 -*-
"""Comissão Motorista em PDF (pedido 03/11/2026: "não consigo trabalhar").

Mesmo desenho dos PDFs da Frota (cabeçalho, cartões, tabela), reaproveitado
de utils/relatorio_frota. Recebe o mesmo dicionário que a tela recebe de
routes/relatorios._comissao_dados — tela e papel não podem discordar.
"""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from utils.relatorio_boletos import AZUL, FRACO, LINHA, TINTA, _moeda
from utils.relatorio_frota import (UTIL, VERDE, _Doc, _cartoes, _data_br, _escapar,
                                   _montar, _num, _tabela)

_CINZA_CLARO = colors.HexColor('#9aa5b1')


def _cab_motorista(g):
    estilo_n = ParagraphStyle('n', fontName='Helvetica-Bold', fontSize=9.5,
                              textColor=colors.white, leading=12)
    estilo_s = ParagraphStyle('s', fontName='Helvetica', fontSize=6.8,
                              textColor=colors.white, leading=9)
    estilo_v = ParagraphStyle('v', fontName='Helvetica-Bold', fontSize=10.5,
                              textColor=colors.white, leading=13, alignment=2)
    t = Table([[
        [Paragraph(_escapar(g['nome']), estilo_n),
         Paragraph('%d fretes · %s L transportados · %s L comissionados'
                   % (g['fretes'], _num(g['litros']), _num(g['litros_com'])), estilo_s)],
        Paragraph('Comissão<br/>%s' % _moeda(g['comissao']), estilo_v),
    ]], colWidths=[UTIL - 45 * mm - 1, 45 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), AZUL),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
    ]))
    return t


def gerar(dados, de, ate, filtro='', usuario='', logo=None, quando=None):
    """Duas passadas (a 1ª conta as páginas), cada uma com o corpo montado de
    novo: tabela que quebra de página não pode ser reaproveitada entre builds."""
    quando = quando or datetime.now().strftime('%d/%m/%Y %H:%M')
    cab = {
        'titulo': 'Comissão Motorista',
        'sub': '%s a %s · %s' % (_data_br(de), _data_br(ate), filtro or 'Todos os motoristas'),
        'quando': quando, 'usuario': usuario, 'logo': logo,
        'rodape': 'NH Transportes · comissão dos motoristas por frete',
    }
    buf = io.BytesIO()
    doc = _Doc(buf, cab)
    doc.build(_corpo(dados))
    paginas = doc.page
    buf = io.BytesIO()
    doc = _Doc(buf, cab)
    doc.total_paginas = paginas
    doc.build(_corpo(dados))
    return buf.getvalue()


def _corpo(dados):
    corpo = [_cartoes([
        ('Fretes', TINTA, str(dados['total_fretes'])),
        ('Litros', TINTA, _num(dados['total_quantidade'])),
        ('Valor frete', TINTA, _moeda(dados['total_valor_frete'])),
        ('Comissão', VERDE, _moeda(dados['total_comissao_motorista'])),
    ]), Spacer(1, 5 * mm)]

    larg = [16 * mm, 30 * mm, 0, 22 * mm, 26 * mm, 26 * mm]
    larg[2] = UTIL - sum(larg)
    for g in dados['grupos']:
        linhas, pinta = [], []
        for i, f in enumerate(g['itens'], start=1):
            linhas.append([
                _data_br(f['data_frete'])[:5], f['produto_nome'] or '—',
                (f['cliente_curto'] or '—')[:48], _num(f['quantidade']) + ' L',
                _moeda(f['valor_total_frete']) if f['valor_total_frete'] else '—',
                _moeda(f['comissao_motorista']) if f['comissao_motorista'] else 'sem comissão',
            ])
            if not f['comissao_motorista']:
                pinta.append(('TEXTCOLOR', (0, i), (-1, i), _CINZA_CLARO))
            else:
                pinta.append(('FONT', (5, i), (5, i), 'Helvetica-Bold', 7.4))
        linhas.append(['SUBTOTAL', '', '', _num(g['litros']) + ' L',
                       _moeda(g['valor_frete']), _moeda(g['comissao'])])
        pinta += [('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 7.6),
                  ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f4fa')),
                  ('LINEABOVE', (0, -1), (-1, -1), 0.8, LINHA)]
        tab = _tabela(['DATA', 'PRODUTO', 'CLIENTE', 'LITROS', 'FRETE', 'COMISSÃO'],
                      linhas, larg, ['LEFT', 'LEFT', 'LEFT', 'RIGHT', 'RIGHT', 'RIGHT'], pinta)
        corpo.append(KeepTogether([_cab_motorista(g), tab]) if len(linhas) < 25
                     else _cab_motorista(g))
        if len(linhas) >= 25:
            corpo.append(tab)
        corpo.append(Spacer(1, 5 * mm))

    # resumo por motorista
    res = [[g['nome'], str(g['fretes']), _num(g['litros']), _num(g['litros_com']),
            _moeda(g['comissao'])] for g in dados['grupos']]
    res.append(['TOTAL', str(dados['total_fretes']), _num(dados['total_quantidade']),
                _num(sum(g['litros_com'] for g in dados['grupos'])),
                _moeda(dados['total_comissao_motorista'])])
    lr = [0, 18 * mm, 30 * mm, 30 * mm, 30 * mm]
    lr[0] = UTIL - sum(lr)
    corpo.append(KeepTogether([
        Paragraph('Resumo por motorista', ParagraphStyle(
            't', fontName='Helvetica-Bold', fontSize=9.5, textColor=TINTA,
            leading=12, spaceAfter=2 * mm)),
        _tabela(['MOTORISTA', 'FRETES', 'TRANSPORTADO (L)', 'COMISSIONADO (L)', 'COMISSÃO'],
                res, lr, ['LEFT', 'CENTER', 'RIGHT', 'RIGHT', 'RIGHT'],
                [('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 7.6),
                 ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f2f5f8')),
                 ('LINEABOVE', (0, -1), (-1, -1), 0.8, LINHA)]),
    ]))

    return corpo
