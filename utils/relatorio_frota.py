# -*- coding: utf-8 -*-
"""Relatórios da aba Frota em PDF: a lista de placas e o extrato de uma placa.

Sem nada de Flask aqui de propósito: recebe listas de dicionários e devolve
bytes, então dá para gerar e conferir o arquivo fora do servidor.

São DUAS saídas do mesmo gerador porque as duas contam a mesma história em
alturas diferentes — a da frota diz quanto cada placa custou, a da placa diz
de onde aquele número saiu, abastecimento por abastecimento. Se um dia elas
discordarem, é bug: as duas leem as mesmas funções de `routes/prazo.py`.

As cores e o formato de dinheiro são importados de `relatorio_boletos` de
propósito, e não copiados: são os mesmos papéis saindo da mesma empresa, e
duas cópias da mesma constante acabam divergindo.
"""
from __future__ import annotations

import io
import os
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from utils.relatorio_boletos import (AZUL, FRACO, LINHA, LINHA_2, TINTA,
                                     TINTA_2, _moeda)

VERDE  = colors.HexColor('#17963C')
AMBAR  = colors.HexColor('#8a5a00')
CINZA  = colors.HexColor('#465565')
ALERTA = colors.HexColor('#a32d2d')

MARGEM = 14 * mm
TOPO   = 30 * mm
RODAPE = 12 * mm
UTIL   = A4[0] - 2 * MARGEM


def _num(v, casas=0):
    if v is None:
        return '—'
    try:
        return ('{:,.%df}' % casas).format(float(v)).replace(',', 'X') \
            .replace('.', ',').replace('X', '.')
    except (TypeError, ValueError):
        return '—'


def _data_br(d):
    if not d:
        return '—'
    if hasattr(d, 'strftime'):
        return d.strftime('%d/%m/%Y')
    return str(d)[:10]


def _escapar(t):
    return (str(t or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


class _Doc(BaseDocTemplate):
    """Cabeçalho e rodapé em toda página, com o total de páginas no fim.

    O total só se sabe depois de montar, então o documento é montado duas
    vezes — a primeira conta as páginas, a segunda escreve "página 2 de 5".
    """

    def __init__(self, buf, cab, **kw):
        BaseDocTemplate.__init__(self, buf, pagesize=A4,
                                 leftMargin=MARGEM, rightMargin=MARGEM,
                                 topMargin=TOPO, bottomMargin=RODAPE, **kw)
        self.cab = cab
        self.total_paginas = 0
        quadro = Frame(MARGEM, RODAPE, UTIL, A4[1] - TOPO - RODAPE, id='corpo',
                       leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='pg', frames=[quadro],
                                            onPage=self._moldura)])

    def _moldura(self, canv, doc):
        c = self.cab
        canv.saveState()
        y = A4[1] - MARGEM

        if c.get('logo') and os.path.exists(c['logo']):
            try:
                canv.drawImage(c['logo'], MARGEM, y - 15 * mm,
                               width=15 * mm, height=15 * mm,
                               preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        x = MARGEM + 18 * mm
        canv.setFillColor(TINTA)
        canv.setFont('Helvetica-Bold', 13)
        canv.drawString(x, y - 6 * mm, c.get('titulo', 'Frota'))
        canv.setFont('Helvetica', 7.6)
        canv.setFillColor(TINTA_2)
        canv.drawString(x, y - 10 * mm, c.get('sub', '')[:110])

        canv.setFont('Helvetica', 7)
        canv.setFillColor(FRACO)
        canv.drawRightString(A4[0] - MARGEM, y - 6 * mm, c.get('quando', ''))
        if c.get('usuario'):
            canv.drawRightString(A4[0] - MARGEM, y - 9.5 * mm,
                                 'por %s' % c['usuario'][:40])

        canv.setStrokeColor(LINHA)
        canv.setLineWidth(0.6)
        canv.line(MARGEM, y - 17 * mm, A4[0] - MARGEM, y - 17 * mm)

        canv.setFont('Helvetica', 6.8)
        canv.setFillColor(FRACO)
        total = self.total_paginas or doc.page
        canv.drawRightString(A4[0] - MARGEM, RODAPE - 5 * mm,
                             'página %d de %d' % (doc.page, total))
        canv.drawString(MARGEM, RODAPE - 5 * mm, c.get('rodape', ''))
        canv.restoreState()


def _cartoes(itens):
    """A fileira de números do topo, no mesmo desenho dos cards da tela."""
    largura = (UTIL - 3 * 3 * mm) / 4.0
    celulas = []
    for rotulo, cor, valor in itens:
        celulas.append(Table(
            [[Paragraph(rotulo.upper(), ParagraphStyle(
                'r', fontName='Helvetica-Bold', fontSize=6.2, textColor=FRACO,
                leading=8))],
             [Paragraph(valor, ParagraphStyle(
                 'v', fontName='Helvetica-Bold', fontSize=12.5, textColor=cor,
                 leading=15))]],
            colWidths=[largura - 6 * mm],
            style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0),
                              ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                              ('TOPPADDING', (0, 0), (-1, -1), 0),
                              ('BOTTOMPADDING', (0, 0), (-1, -1), 0)])))
    fora = Table([celulas], colWidths=[largura] * 4)
    fora.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0, colors.white),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f7f9fc')),
        ('LINEAFTER', (0, 0), (-2, -1), 0.6, LINHA),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
    ]))
    return fora


def _tabela(cabecalho, linhas, larguras, alinhamentos, pinta=None):
    dados = [cabecalho] + linhas
    t = Table(dados, colWidths=larguras, repeatRows=1)
    est = [
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 6.6),
        ('TEXTCOLOR', (0, 0), (-1, 0), FRACO),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f2f5f8')),
        ('FONT', (0, 1), (-1, -1), 'Helvetica', 7.4),
        ('TEXTCOLOR', (0, 1), (-1, -1), TINTA),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, LINHA_2),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, LINHA),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.1 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.1 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 1.6 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1.6 * mm),
    ]
    for i, al in enumerate(alinhamentos):
        est.append(('ALIGN', (i, 0), (i, -1), al))
    est.extend(pinta or [])
    t.setStyle(TableStyle(est))
    return t


def _montar(corpo, cab):
    # duas passadas: a primeira só para saber quantas páginas dá
    buf = io.BytesIO()
    doc = _Doc(buf, cab)
    doc.build(list(corpo))
    paginas = doc.page

    buf = io.BytesIO()
    doc = _Doc(buf, cab)
    doc.total_paginas = paginas
    doc.build(list(corpo))
    return buf.getvalue()


_NOTA_KML = (
    'O km/L sai de leituras seguidas do mesmo veículo: (hodômetro de agora − '
    'hodômetro anterior) ÷ litros de agora. Intervalo que anda para trás ou '
    'pula mais de 5.000 km entre dois abastecimentos é erro de digitação e '
    'fica fora da média — mas o valor em reais continua contando. Por isso o '
    'primeiro abastecimento do período nunca tem km/L.'
)


def _pe(texto):
    return Paragraph(texto, ParagraphStyle(
        'pe', fontName='Helvetica', fontSize=6.8, textColor=FRACO, leading=9.5))


def gerar_frota(frota, de, ate, filtro='', usuario='', logo=None, quando=None):
    """Uma linha por placa. `frota` é a saída de routes.prazo._frota."""
    quando = quando or datetime.now().strftime('%d/%m/%Y %H:%M')
    valor = sum(p['valor'] for p in frota)
    litros = sum(p['litros'] for p in frota)
    km = sum(p['km_rodado'] for p in frota)

    corpo = [_cartoes([
        ('Custo no período', CINZA, 'R$ ' + _moeda(valor)),
        ('Litros', AZUL, _num(litros)),
        ('Km medidos', VERDE, _num(km)),
        ('Placas', AMBAR, str(len(frota))),
    ]), Spacer(1, 4 * mm)]

    if not frota:
        corpo.append(_pe('Nenhum abastecimento a prazo com placa nesse período '
                         'para o filtro escolhido.'))
        return _montar(corpo, {'titulo': 'Frota — combustível por placa',
                               'sub': '%s · %s a %s' % (filtro, _data_br(de),
                                                        _data_br(ate)),
                               'quando': quando, 'usuario': usuario,
                               'logo': logo, 'rodape': ''})

    est_emp = ParagraphStyle('e', fontName='Helvetica', fontSize=6.4,
                             textColor=FRACO, leading=8)
    est_pl = ParagraphStyle('p', fontName='Helvetica-Bold', fontSize=7.6,
                            textColor=TINTA, leading=9.5)
    linhas = []
    for p in frota:
        linhas.append([
            Paragraph('%s<br/><font size="6.2" color="#6c7784">%s</font>'
                      % (_escapar(p['placa']),
                         _escapar((p['cliente'] or '')[:38])), est_pl),
            str(p['abastecimentos']),
            _num(p['litros']),
            _moeda(p['valor']),
            _num(p['km_rodado']),
            _num(p['km_litro'], 2) if p['km_litro'] else '—',
            _moeda(p['custo_km']) if p['custo_km'] else '—',
            '%s%%' % _num(p['pct'], 1),
        ])
    linhas.append(['TOTAL', str(sum(p['abastecimentos'] for p in frota)),
                   _num(litros), _moeda(valor), _num(km), '', '', '100,0%'])

    # As larguras somam UTIL na unha, e a ULTIMA e o que sobra. Na primeira
    # versao sobravam 10 mm para "% DO CUSTO" e o cabecalho saiu por cima do
    # vizinho ("R$%/K DMO CUSTO" no papel). Somar a mao antes de mudar.
    larg = [52 * mm, 13 * mm, 19 * mm, 24 * mm, 19 * mm, 15 * mm, 16 * mm,
            UTIL - (52 + 13 + 19 + 24 + 19 + 15 + 16) * mm]
    corpo.append(_tabela(
        ['PLACA / EMPRESA', 'ABAST.', 'LITROS', 'VALOR', 'KM', 'KM/L',
         'R$/KM', '% CUSTO'],
        linhas, larg,
        ['LEFT', 'CENTER', 'RIGHT', 'RIGHT', 'RIGHT', 'RIGHT', 'RIGHT', 'RIGHT'],
        [('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 7.6),
         ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f2f5f8')),
         ('LINEABOVE', (0, -1), (-1, -1), 0.8, LINHA)]))
    corpo.append(Spacer(1, 3 * mm))
    corpo.append(_pe(_NOTA_KML))

    return _montar(corpo, {
        'titulo': 'Frota — combustível por placa',
        'sub': '%s · %s a %s' % (filtro, _data_br(de), _data_br(ate)),
        'quando': quando, 'usuario': usuario, 'logo': logo,
        'rodape': 'Grupo NH · abastecimento a prazo com placa',
    })


def gerar_placa(placa, resumo, linhas, de, ate, usuario='', logo=None,
                quando=None):
    """Uma placa, abastecimento por abastecimento."""
    quando = quando or datetime.now().strftime('%d/%m/%Y %H:%M')
    resumo = resumo or {}
    valor = sum(l['valor'] for l in linhas)
    litros = sum(l['litros'] for l in linhas)
    rodou = sum(l['rodou'] or 0 for l in linhas)
    descartadas = sum(1 for l in linhas if l['descartada'])

    corpo = [_cartoes([
        ('Abastecimentos', CINZA, str(len(linhas))),
        ('Litros', AZUL, _num(litros)),
        ('Valor', AMBAR, 'R$ ' + _moeda(valor)),
        ('Km/L do período', VERDE,
         _num(resumo.get('km_litro'), 2) if resumo.get('km_litro') else '—'),
    ]), Spacer(1, 4 * mm)]

    if not linhas:
        corpo.append(_pe('Nenhum abastecimento a prazo desta placa no período.'))
        return _montar(corpo, {'titulo': 'Placa %s' % placa,
                               'sub': '%s a %s' % (_data_br(de), _data_br(ate)),
                               'quando': quando, 'usuario': usuario,
                               'logo': logo, 'rodape': ''})

    corpo_linhas = []
    pinta = []
    for i, l in enumerate(linhas, start=1):
        corpo_linhas.append([
            _data_br(l['dia']),
            str(l['numero'] or '—'),
            _num(l['litros'], 1),
            _moeda(l['preco']) if l['preco'] else '—',
            _moeda(l['valor']),
            _num(l['km']) if l['km'] else '—',
            _num(l['rodou']) if l['rodou'] else ('descartada'
                                                 if l['descartada'] else '—'),
            _num(l['km_litro'], 2) if l['km_litro'] else '—',
        ])
        if l['descartada']:
            pinta.append(('TEXTCOLOR', (6, i), (6, i), ALERTA))
            pinta.append(('BACKGROUND', (0, i), (-1, i),
                          colors.HexColor('#fffaf2')))
    corpo_linhas.append(['TOTAL', '', _num(litros, 1), '', _moeda(valor), '',
                         _num(rodou), _num(resumo.get('km_litro'), 2)
                         if resumo.get('km_litro') else ''])
    pinta.extend([
        ('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 7.6),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f2f5f8')),
        ('LINEABOVE', (0, -1), (-1, -1), 0.8, LINHA),
    ])

    larg = [22 * mm, 20 * mm, 20 * mm, 20 * mm, 28 * mm, 26 * mm, 24 * mm,
            UTIL - 22 * mm - 20 * mm - 20 * mm - 20 * mm - 28 * mm - 26 * mm - 24 * mm]
    corpo.append(_tabela(
        ['DATA', 'NOTA', 'LITROS', 'R$/L', 'VALOR', 'HODÔMETRO', 'RODOU',
         'KM/L'],
        corpo_linhas, larg,
        ['LEFT', 'LEFT', 'RIGHT', 'RIGHT', 'RIGHT', 'RIGHT', 'RIGHT', 'RIGHT'],
        pinta))
    corpo.append(Spacer(1, 3 * mm))
    if descartadas:
        corpo.append(_pe(
            '<font color="#a32d2d"><b>%d leitura(s) descartada(s)</b></font> — '
            'o hodômetro andou para trás ou pulou mais de 5.000 km. O valor '
            'em reais dessas notas continua somando; só o km/L delas é que '
            'não entra.' % descartadas))
        corpo.append(Spacer(1, 1.5 * mm))
    corpo.append(_pe(_NOTA_KML))

    sub = '%s a %s' % (_data_br(de), _data_br(ate))
    if resumo.get('cliente'):
        sub = '%s · %s' % (resumo['cliente'], sub)
    return _montar(corpo, {
        'titulo': 'Placa %s' % placa,
        'sub': sub, 'quando': quando, 'usuario': usuario, 'logo': logo,
        'rodape': 'Grupo NH · abastecimento a prazo com placa',
    })
