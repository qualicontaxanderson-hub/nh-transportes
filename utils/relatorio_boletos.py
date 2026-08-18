# -*- coding: utf-8 -*-
"""Relatório de boletos de frete em PDF.

Sem nada de Flask aqui de propósito: recebe listas de dicionários e devolve
bytes, então dá para gerar e conferir o arquivo fora do servidor.

O desenho é o que foi aprovado: cabeçalho com a logo (sem o nome escrito),
quatro cartões de resumo, e uma faixa por situação com a soma no fim. Cada
linha traz, sob o cliente, a mesma frase que o EFI imprime na descrição do
boleto — Frete #id · data · produto · litros · origem → destino — mais o
preço por litro, que o boleto não traz.
"""
from __future__ import annotations

import io
import os
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

# ── Cores, as mesmas da prova ────────────────────────────────────────────
TINTA      = colors.HexColor('#161b22')
TINTA_2    = colors.HexColor('#3c4753')
FRACO      = colors.HexColor('#6c7784')
FRACO_2    = colors.HexColor('#5a6675')
LINHA      = colors.HexColor('#dfe4ea')
LINHA_2    = colors.HexColor('#f0f2f5')
AZUL       = colors.HexColor('#1D63A5')
VENC       = colors.HexColor('#a3262b')
VENC_BG    = colors.HexColor('#fbecec')
ABER       = colors.HexColor('#8a5a00')
ABER_BG    = colors.HexColor('#fdf3de')
PAGO       = colors.HexColor('#186c37')
PAGO_BG    = colors.HexColor('#e6f4ea')
CANC       = colors.HexColor('#4b5563')
CANC_BG    = colors.HexColor('#eceef1')

MARGEM     = 14 * mm
TOPO       = 30 * mm          # espaço do cabeçalho repetido
RODAPE     = 12 * mm

# largura útil: A4 (210mm) menos as duas margens
UTIL       = A4[0] - 2 * MARGEM
COLS       = [15 * mm, UTIL - 15 * mm - 23 * mm - 17 * mm - 26 * mm,
              23 * mm, 17 * mm, 26 * mm]

# ── Situações, na ordem em que saem no papel ─────────────────────────────
FAIXAS = [
    ('vencido',   'Vencidos',        VENC, VENC_BG, 'Atraso'),
    ('pendente',  'A vencer',        ABER, ABER_BG, 'Faltam'),
    ('pago',      'Pagos',           PAGO, PAGO_BG, 'Pago em'),
    ('quitado',   'Baixados na mão', PAGO, PAGO_BG, 'Pago em'),
    ('cancelado', 'Cancelados',      CANC, CANC_BG, ''),
]


def _moeda(v, com_cifrao=False):
    """1234.5 -> '1.234,50'. Mesma regra do formatar_moeda do app."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return '-'
    inteiro = int(abs(n))
    cent = int(round((abs(n) - inteiro) * 100))
    if cent == 100:                      # 1.999 arredonda pra 2,00
        inteiro, cent = inteiro + 1, 0
    txt = f'{inteiro:,}'.replace(',', '.') + f',{cent:02d}'
    return ('-' if n < 0 else '') + ('R$ ' if com_cifrao else '') + txt


def _litros(v):
    try:
        return f'{float(v):,.0f}'.replace(',', '.')
    except (TypeError, ValueError):
        return None


def _preco_litro(b):
    """O campo gravado; se estiver vazio, o total dividido pelos litros."""
    try:
        p = float(b.get('preco_por_litro') or 0)
        if p > 0:
            return p
    except (TypeError, ValueError):
        pass
    try:
        tot = float(b.get('valor_total_frete') or 0)
        qtd = float(b.get('quantidade') or 0)
        if tot > 0 and qtd > 0:
            return tot / qtd
    except (TypeError, ValueError):
        pass
    return None


def _data_br(d):
    if not d:
        return '-'
    if hasattr(d, 'strftime'):
        return d.strftime('%d/%m/%Y')
    try:
        return datetime.strptime(str(d)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return str(d)[:10]


def _dias(d, hoje):
    """Dias entre hoje e a data. Positivo = já passou."""
    if not d:
        return None
    if not hasattr(d, 'toordinal'):
        try:
            d = datetime.strptime(str(d)[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    if isinstance(d, datetime):
        d = d.date()
    return (hoje - d).days


def _escapar(t):
    return (str(t or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def _frase_frete(b):
    """A mesma frase do boleto do EFI, mais o preço por litro."""
    if not b.get('frete_id'):
        return None
    partes = ['<b>Frete %s</b>' % _escapar(b['frete_id'])]
    if b.get('data_frete'):
        partes.append(_data_br(b['data_frete']))

    produto = (b.get('produto') or '').strip()
    litros = _litros(b.get('quantidade'))
    ppl = _preco_litro(b)
    if produto or litros:
        pedaco = _escapar(produto)
        if litros:
            pedaco = (pedaco + ' ' if pedaco else '') + litros + ' L'
        if ppl:
            pedaco += ' a <b>R$ %s/L</b>' % _moeda(round(ppl, 4)).replace(
                ',00', ',%02d' % int(round((ppl - int(ppl)) * 100)))
        partes.append(pedaco)

    if b.get('origem') and b.get('destino'):
        partes.append('%s &rarr; %s' % (_escapar(b['origem']),
                                        _escapar(b['destino'])))
    return ' &middot; '.join(partes)


def _preco_litro_txt(ppl):
    """R$ 0,12/L — com dois decimais, ou quatro quando é fração miúda."""
    if ppl is None:
        return ''
    if abs(ppl * 100 - round(ppl * 100)) < 1e-6:
        return 'R$ %s/L' % _moeda(ppl)
    return ('R$ %s/L' % ('%.4f' % ppl).replace('.', ','))


# ── Estilos de parágrafo ─────────────────────────────────────────────────
def _estilos():
    base = ParagraphStyle('base', fontName='Helvetica', fontSize=8.2,
                          leading=10, textColor=TINTA)
    return {
        'cli': ParagraphStyle('cli', parent=base, fontName='Helvetica-Bold'),
        'det': ParagraphStyle('det', parent=base, fontSize=7, leading=8.6,
                              textColor=FRACO_2, spaceBefore=1),
        'cel': base,
        'num': ParagraphStyle('num', parent=base, alignment=TA_RIGHT),
    }


class _Doc(BaseDocTemplate):
    """Cabeçalho e rodapé em toda página, e o total de páginas no rodapé.

    O total só se sabe no fim, então o documento é montado duas vezes: a
    primeira conta as páginas, a segunda escreve "página 2 de 5".
    """

    def __init__(self, buf, cabecalho, **kw):
        BaseDocTemplate.__init__(self, buf, pagesize=A4,
                                 leftMargin=MARGEM, rightMargin=MARGEM,
                                 topMargin=TOPO, bottomMargin=RODAPE, **kw)
        self.cabecalho = cabecalho
        self.total_paginas = 0
        quadro = Frame(MARGEM, RODAPE, UTIL,
                       A4[1] - TOPO - RODAPE, id='corpo',
                       leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='pg', frames=[quadro],
                                            onPage=self._moldura)])

    def _moldura(self, canv, doc):
        c = self.cabecalho
        canv.saveState()
        y_topo = A4[1] - MARGEM

        # logo
        if c.get('logo') and os.path.exists(c['logo']):
            try:
                canv.drawImage(c['logo'], MARGEM, y_topo - 15 * mm,
                               width=15 * mm, height=15 * mm,
                               preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        x = MARGEM + 18 * mm
        canv.setFillColor(TINTA)
        canv.setFont('Helvetica-Bold', 13)
        canv.drawString(x, y_topo - 6 * mm, 'Boletos de Frete')
        canv.setFont('Helvetica', 7.6)
        canv.setFillColor(TINTA_2)
        canv.drawString(x, y_topo - 10 * mm, c.get('filtro', '')[:110])

        # o que fica à direita
        canv.setFont('Helvetica', 7)
        canv.setFillColor(FRACO)
        dir_x = A4[0] - MARGEM
        canv.drawRightString(dir_x, y_topo - 4 * mm,
                             'emitido em %s' % c.get('quando', ''))
        if c.get('usuario'):
            canv.drawRightString(dir_x, y_topo - 7.2 * mm,
                                 'por %s' % c['usuario'])
        total = self.total_paginas or '?'
        canv.drawRightString(dir_x, y_topo - 10.4 * mm,
                             'página %d de %s' % (doc.page, total))

        canv.setStrokeColor(TINTA)
        canv.setLineWidth(1.2)
        canv.line(MARGEM, y_topo - 17 * mm, dir_x, y_topo - 17 * mm)

        # rodapé
        canv.setStrokeColor(LINHA)
        canv.setLineWidth(.5)
        canv.line(MARGEM, RODAPE - 2 * mm, dir_x, RODAPE - 2 * mm)
        canv.setFont('Helvetica', 6.5)
        canv.setFillColor(FRACO)
        canv.drawString(MARGEM, RODAPE - 5.5 * mm,
                        'Relatório gerado pelo sistema')
        canv.drawRightString(dir_x, RODAPE - 5.5 * mm,
                             '%s — página %d de %s'
                             % (c.get('quando', ''), doc.page, total))
        canv.restoreState()


def _cartoes(resumo):
    """Os quatro quadros de resumo do topo."""
    est = _estilos()
    rot = ParagraphStyle('rot', parent=est['cel'], fontSize=6.2, leading=7.6,
                         fontName='Helvetica-Bold', textColor=FRACO)
    val = ParagraphStyle('val', parent=est['cel'], fontSize=10.5, leading=12.5,
                         fontName='Helvetica-Bold', textColor=TINTA)
    qtd = ParagraphStyle('qtd', parent=est['cel'], fontSize=6.6, leading=8,
                         textColor=FRACO)

    celulas, cores = [], []
    for rotulo, cor, dados in resumo:
        if dados is None:
            corpo = [Paragraph(rotulo.upper(), rot),
                     Paragraph('—', val),
                     Paragraph('fora do filtro', qtd)]
        else:
            n, v = dados
            corpo = [Paragraph(rotulo.upper(), rot),
                     Paragraph(_moeda(v, True), val),
                     Paragraph('%d boleto%s' % (n, '' if n == 1 else 's'), qtd)]
        celulas.append(Table([[c] for c in corpo],
                             colWidths=[UTIL / 4 - 3 * mm],
                             style=TableStyle([
                                 ('LEFTPADDING', (0, 0), (-1, -1), 4),
                                 ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                                 ('TOPPADDING', (0, 0), (-1, -1), 0),
                                 ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                             ])))
        cores.append(cor)

    est_ext = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
               ('TOPPADDING', (0, 0), (-1, -1), 4),
               ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
               ('LEFTPADDING', (0, 0), (-1, -1), 5),
               ('RIGHTPADDING', (0, 0), (-1, -1), 3),
               ('BOX', (0, 0), (-1, -1), .4, LINHA),
               ('INNERGRID', (0, 0), (-1, -1), .4, LINHA)]
    for i, cor in enumerate(cores):
        est_ext.append(('LINEBEFORE', (i, 0), (i, 0), 2.2, cor))
    return Table([celulas], colWidths=[UTIL / 4] * 4,
                 style=TableStyle(est_ext))


def _faixa(rotulo, cor, fundo, n, total):
    t = Table([[Paragraph('<b>%s</b>' % rotulo.upper(),
                          ParagraphStyle('f', fontName='Helvetica-Bold',
                                         fontSize=7.4, textColor=cor)),
                Paragraph('%d boleto%s &middot; %s'
                          % (n, '' if n == 1 else 's', _moeda(total, True)),
                          ParagraphStyle('fv', fontName='Helvetica-Bold',
                                         fontSize=7.8, textColor=cor,
                                         alignment=TA_RIGHT))]],
               colWidths=[UTIL * .5, UTIL * .5])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), fundo),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _tabela(itens, rot_prazo, hoje, est):
    """Uma tabela por CLIENTE: o nome em cima, os boletos dele embaixo.

    Antes era uma lista corrida ordenada por vencimento, com o nome do cliente
    repetido em toda linha. Quem cobra trabalha por cliente — liga uma vez e
    resolve tudo dele —, entao o papel passa a ser organizado assim.
    """
    cab = ParagraphStyle('cab', fontName='Helvetica-Bold', fontSize=6.2,
                         leading=8, textColor=FRACO)
    cab_d = ParagraphStyle('cabd', parent=cab, alignment=TA_RIGHT)
    nome_cli = ParagraphStyle('nomecli', fontName='Helvetica-Bold', fontSize=9,
                              leading=11, textColor=TINTA)
    tot_cli = ParagraphStyle('totcli', fontName='Helvetica-Bold', fontSize=8.6,
                             leading=11, textColor=TINTA_2, alignment=TA_RIGHT)

    # agrupa mantendo, dentro de cada cliente, a ordem que veio (vencimento)
    grupos = {}
    for b in itens:
        grupos.setdefault(b.get('cliente') or '—', []).append(b)

    # o maior devedor primeiro: e por onde a cobranca comeca
    ordem = sorted(grupos.items(),
                   key=lambda kv: -sum(float(x.get('valor') or 0) for x in kv[1]))

    blocos = []
    soma_faixa = 0.0
    for nome, linhas_cli in ordem:
        sub = sum(float(b.get('valor') or 0) for b in linhas_cli)
        soma_faixa += sub

        blocos.append(Table(
            [[Paragraph(_escapar(nome), nome_cli),
              Paragraph('%d boleto%s &middot; %s'
                        % (len(linhas_cli), '' if len(linhas_cli) == 1 else 's',
                           _moeda(sub, True)), tot_cli)]],
            colWidths=[UTIL * .62, UTIL * .38],
            style=TableStyle([
                ('LINEBELOW', (0, 0), (-1, -1), .6, LINHA),
                ('TOPPADDING', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ])))

        corpo = [[Paragraph('BOLETO', cab), Paragraph('FRETE', cab),
                  Paragraph('VENCIMENTO', cab),
                  Paragraph((rot_prazo or '').upper(), cab_d),
                  Paragraph('VALOR', cab_d)]]
        for b in linhas_cli:
            frase = _frase_frete(b) or 'sem frete vinculado'
            d = _dias(b.get('data_vencimento'), hoje)
            if b.get('display_status') in ('pago', 'quitado'):
                prazo, cor = (_data_br(b.get('data_pagamento'))
                              if b.get('data_pagamento') else '—'), TINTA
            elif d is None:
                prazo, cor = '—', FRACO
            elif d > 0:
                prazo, cor = '%d d' % d, VENC
            elif d == 0:
                prazo, cor = 'hoje', ABER
            else:
                prazo, cor = '%d d' % (-d), TINTA
            corpo.append([
                Paragraph('#%s' % _escapar(b.get('id')), est['cel']),
                Paragraph(frase, est['det']),
                Paragraph(_data_br(b.get('data_vencimento')), est['cel']),
                Paragraph('<font color="#%s">%s</font>'
                          % (cor.hexval()[2:], prazo), est['num']),
                Paragraph(_moeda(b.get('valor')), est['num']),
            ])

        t = Table(corpo, colWidths=COLS)
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, 1), (-1, -2), .4, LINHA_2),
        ]))
        # o nome e a primeira linha do cliente nao se separam na quebra
        blocos.append(KeepTogether([blocos.pop(), t]))

    total = Table([[Paragraph('<b>Soma</b>', est['cel']), '', '', '',
                    Paragraph('<b>%s</b>' % _moeda(soma_faixa), est['num'])]],
                  colWidths=COLS,
                  style=TableStyle([
                      ('LINEABOVE', (0, 0), (-1, 0), .9, TINTA),
                      ('TOPPADDING', (0, 0), (-1, -1), 4),
                      ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                      ('LEFTPADDING', (0, 0), (-1, -1), 4),
                      ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                      ('SPAN', (0, 0), (3, 0)),
                  ]))
    blocos.append(total)
    return blocos, soma_faixa


def gerar(boletos, filtro='', usuario='', logo=None, quando=None):
    """Devolve os bytes do PDF.

    boletos: lista de dicionários com id, cliente, valor, data_vencimento,
    display_status e, quando houver frete: frete_id, data_frete, produto,
    quantidade, preco_por_litro, valor_total_frete, origem, destino.
    """
    hoje = date.today()
    quando = quando or datetime.now().strftime('%d/%m/%Y %H:%M')
    est = _estilos()

    por_faixa = {}
    for b in boletos:
        por_faixa.setdefault(b.get('display_status') or 'pendente', []).append(b)

    def somar(chaves):
        itens = [b for k in chaves for b in por_faixa.get(k, [])]
        if not itens:
            return None
        return len(itens), sum(float(b.get('valor') or 0) for b in itens)

    abertos = somar(['vencido', 'pendente'])
    resumo = [
        ('Vencido', VENC, somar(['vencido'])),
        ('A vencer', ABER, somar(['pendente'])),
        ('Pago', PAGO, somar(['pago', 'quitado'])),
        ('Total em aberto', AZUL, abertos),
    ]

    corpo = [_cartoes(resumo), Spacer(1, 3 * mm)]
    for chave, rotulo, cor, fundo, rot_prazo in FAIXAS:
        itens = por_faixa.get(chave)
        if not itens:
            continue
        blocos, soma = _tabela(itens, rot_prazo, hoje, est)
        corpo.append(_faixa(rotulo, cor, fundo, len(itens), soma))
        corpo.extend(blocos)
        corpo.append(Spacer(1, 4 * mm))

    if len(corpo) == 2:
        corpo.append(Paragraph(
            'Nenhum boleto corresponde ao filtro escolhido.',
            ParagraphStyle('v', fontName='Helvetica', fontSize=9,
                           textColor=FRACO)))

    cab = {'filtro': filtro, 'usuario': usuario, 'logo': logo, 'quando': quando}

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


# ── O mesmo relatório em texto, para o WhatsApp ─────────────────────────
_EMOJI_FAIXA = {'vencido': '🔴', 'pendente': '🟡',
                'pago': '🟢', 'quitado': '🟢', 'cancelado': '⚪'}
_RISCO = '━' * 20


def _prazo_frase(b, hoje):
    """"Venceu 30/05/2026 · há 80 dias" / "Vence hoje, 18/08/2026"."""
    d = _dias(b.get('data_vencimento'), hoje)
    data = _data_br(b.get('data_vencimento'))
    if b.get('display_status') in ('pago', 'quitado'):
        return 'Pago' + (' em ' + _data_br(b['data_pagamento'])
                         if b.get('data_pagamento') else '')
    if d is None:
        return 'Sem data de vencimento'
    if d > 0:
        return 'Venceu %s · há %d dia%s' % (data, d, '' if d == 1 else 's')
    if d == 0:
        return 'Vence hoje, %s' % data
    return 'Vence %s · em %d dia%s' % (data, -d, '' if -d == 1 else 's')


def _frase_frete_texto(b):
    """A mesma frase do PDF, sem as marcas de negrito do HTML."""
    frase = _frase_frete(b)
    if not frase:
        return None
    return (frase.replace('<b>', '').replace('</b>', '')
            .replace('&middot;', '·').replace('&rarr;', '→')
            .replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>'))


def texto_whatsapp(boletos, quem='Diversos', hoje=None, fecho=None):
    """O relatório em texto, no formato que o WhatsApp entende (*negrito*).

    Uma empresa só: o nome vai no cabeçalho. Várias: cada faixa se divide por
    empresa, como no PDF.
    """
    hoje = hoje or date.today()
    linhas = ['📄 *CONTAS A RECEBER*', '🏢 %s' % quem,
              '📅 Emitido em %s' % hoje.strftime('%d/%m/%Y'), _RISCO]

    por_faixa = {}
    for b in boletos:
        por_faixa.setdefault(b.get('display_status') or 'pendente', []).append(b)

    total, n_total = 0.0, 0
    for chave, rotulo, _c, _f, _p in FAIXAS:
        itens = por_faixa.get(chave)
        if not itens:
            continue
        soma = sum(float(b.get('valor') or 0) for b in itens)
        total += soma
        n_total += len(itens)
        linhas.append('')
        linhas.append('%s *%s — %d boleto%s · %s*'
                      % (_EMOJI_FAIXA.get(chave, '•'), rotulo.upper(),
                         len(itens), '' if len(itens) == 1 else 's',
                         _moeda(soma, True)))

        # com mais de uma empresa, separa por empresa dentro da faixa
        grupos = {}
        for b in itens:
            grupos.setdefault(b.get('cliente') or '—', []).append(b)
        varias = len(grupos) > 1
        ordem = sorted(grupos.items(),
                       key=lambda kv: -sum(float(x.get('valor') or 0)
                                           for x in kv[1]))
        for nome, doGrupo in ordem:
            if varias:
                sub = sum(float(b.get('valor') or 0) for b in doGrupo)
                linhas.append('')
                linhas.append('🏢 *%s* — %d · %s'
                              % (nome, len(doGrupo), _moeda(sub, True)))
            for b in doGrupo:
                linhas.append('')
                linhas.append('• *#%s* — %s' % (b.get('id'),
                                                _moeda(b.get('valor'), True)))
                linhas.append('   %s' % _prazo_frase(b, hoje))
                frete = _frase_frete_texto(b)
                if frete:
                    partes = frete.split(' · ')
                    linhas.append('   %s' % ' · '.join(partes[:-1])
                                  if len(partes) > 1 else '   %s' % frete)
                    if len(partes) > 1:
                        linhas.append('   %s' % partes[-1])
                else:
                    linhas.append('   Sem frete vinculado')

    if not n_total:
        linhas.append('')
        linhas.append('Nenhum boleto nesta seleção.')
    else:
        linhas.append('')
        linhas.append(_RISCO)
        linhas.append('💰 *TOTAL EM ABERTO: %s*' % _moeda(total, True))
        linhas.append('   %d boleto%s' % (n_total, '' if n_total == 1 else 's'))

    if fecho:
        linhas.append('')
        linhas.append(fecho)
    return '\n'.join(linhas)
