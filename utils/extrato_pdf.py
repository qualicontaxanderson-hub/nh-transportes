# -*- coding: utf-8 -*-
"""Extrato bancário em PDF (pedido 04/11/2026).

Recebe os blocos de utils.extrato_saldos.montar e devolve bytes. Mesmo
cabeçalho/rodapé do relatório de boletos (logo, emitido em, página x de y).
Um banco por vez; em cada dia: faixa com o saldo inicial, os lançamentos e
a linha do saldo final — com o saldo do banco e a diferença quando houver.
"""
from __future__ import annotations

import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from utils.relatorio_boletos import (AZUL, FRACO, FRACO_2, LINHA, LINHA_2, PAGO,
                                     PAGO_BG, TINTA, TINTA_2, VENC, VENC_BG,
                                     ABER, ABER_BG, _escapar, _moeda)

MARGEM = 12 * mm
TOPO = 27 * mm
RODAPE = 12 * mm
UTIL = A4[0] - 2 * MARGEM
COLS = [0, 20 * mm, 22 * mm, 22 * mm, 24 * mm]
COLS[0] = UTIL - sum(COLS)
DIA_BG = colors.HexColor('#eaf1f9')
FIM_BG = colors.HexColor('#f3f5f8')


class _Doc(BaseDocTemplate):
    def __init__(self, buf, cab, **kw):
        BaseDocTemplate.__init__(self, buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM,
                                 topMargin=TOPO, bottomMargin=RODAPE, **kw)
        self.cab = cab
        self.total_paginas = 0
        quadro = Frame(MARGEM, RODAPE, UTIL, A4[1] - TOPO - RODAPE, id='corpo',
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='pg', frames=[quadro], onPage=self._moldura)])

    def _moldura(self, canv, doc):
        c = self.cab
        canv.saveState()
        y = A4[1] - MARGEM
        if c.get('logo') and os.path.exists(c['logo']):
            try:
                canv.drawImage(c['logo'], MARGEM, y - 13 * mm, width=13 * mm, height=13 * mm,
                               preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        x = MARGEM + 16 * mm
        canv.setFillColor(TINTA)
        canv.setFont('Helvetica-Bold', 13)
        canv.drawString(x, y - 5.5 * mm, 'Extrato bancário')
        canv.setFont('Helvetica', 7.6)
        canv.setFillColor(TINTA_2)
        canv.drawString(x, y - 9.5 * mm, c.get('filtro', '')[:120])
        dx = A4[0] - MARGEM
        canv.setFont('Helvetica', 7)
        canv.setFillColor(FRACO)
        total = self.total_paginas or '?'
        canv.drawRightString(dx, y - 4 * mm, 'emitido em %s' % c.get('quando', ''))
        canv.drawRightString(dx, y - 7.4 * mm, 'página %d de %s' % (doc.page, total))
        canv.setStrokeColor(TINTA)
        canv.setLineWidth(1.2)
        canv.line(MARGEM, y - 15 * mm, dx, y - 15 * mm)
        canv.setStrokeColor(LINHA)
        canv.setLineWidth(.5)
        canv.line(MARGEM, RODAPE - 2 * mm, dx, RODAPE - 2 * mm)
        canv.setFont('Helvetica', 6.5)
        canv.drawString(MARGEM, RODAPE - 5.5 * mm, 'Saldo do dia conferido com o saldo que o próprio banco informou (OFX / On-Line)')
        canv.drawRightString(dx, RODAPE - 5.5 * mm, 'página %d de %s' % (doc.page, total))
        canv.restoreState()


def _br(d):
    return d.strftime('%d/%m/%Y') if d else ''


def _sem(d):
    return ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'][d.weekday()]


def gerar(blocos, ini, fim, rotulo_origem, mostra_corrido=True, logo=None, quando=None):
    quando = quando or datetime.now().strftime('%d/%m/%Y %H:%M')
    if logo is None:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'logo-nh.png')
        logo = p if os.path.exists(p) else None
    base = ParagraphStyle('b', fontName='Helvetica', fontSize=7.6, leading=9.2, textColor=TINTA)
    est = {
        'cel': base,
        'det': ParagraphStyle('d', parent=base, fontSize=6.6, leading=8, textColor=FRACO_2),
        'num': ParagraphStyle('n', parent=base, alignment=TA_RIGHT),
        'cab': ParagraphStyle('c', parent=base, fontName='Helvetica-Bold', fontSize=6.8, textColor=colors.white),
        'cabd': ParagraphStyle('cd', parent=base, fontName='Helvetica-Bold', fontSize=6.8,
                               textColor=colors.white, alignment=TA_RIGHT),
        'tit': ParagraphStyle('t', parent=base, fontName='Helvetica-Bold', fontSize=11.5, leading=14,
                              textColor=AZUL),
        'sub': ParagraphStyle('s', parent=base, fontSize=7.4, textColor=TINTA_2),
        'bold': ParagraphStyle('bo', parent=base, fontName='Helvetica-Bold'),
        'boldd': ParagraphStyle('bod', parent=base, fontName='Helvetica-Bold', alignment=TA_RIGHT),
    }
    # a historia e montada de novo em cada passada: o reportlab marca na
    # tabela que ela foi adiada (_postponed) e, reaproveitada na segunda
    # passada, a mesma tabela dava LayoutError "too large on page 1"
    def _historia():
        corpo = []
        for n, b in enumerate(blocos):
            c = b['conta']
            if n and corpo:
                corpo.append(PageBreak())
            t = b['tot']
            corpo.append(Paragraph(_escapar(c['apelido'] or c['banco_nome']), est['tit']))
            corpo.append(Paragraph('%s · Ag %s · Conta %s · saldo de partida: %s%s' % (
                _escapar(c.get('empresa') or ''), _escapar(c.get('agencia') or '—'), _escapar(c.get('conta') or '—'),
                _escapar(b['base']),
                (' · %d espelho(s) de transferência fora (não existem no banco)' % b['espelhos']) if b['espelhos'] else ''),
                est['sub']))
            corpo.append(Spacer(1, 2 * mm))
            resumo = Table([[
                Paragraph('SALDO INICIAL<br/><b>%s</b>' % (_moeda(b['saldo_inicial'], True) if b['saldo_inicial'] is not None else '—'), est['cel']),
                Paragraph('ENTRADAS<br/><b><font color="#186c37">%s</font></b>' % _moeda(t['entradas'], True), est['cel']),
                Paragraph('SAÍDAS<br/><b><font color="#a3262b">%s</font></b>' % _moeda(t['saidas'], True), est['cel']),
                Paragraph('SALDO FINAL<br/><b>%s</b>' % (_moeda(b['saldo_final'], True) if b['saldo_final'] is not None else '—'), est['cel']),
                Paragraph('PENDENTES / DIFERENÇAS<br/><b>%d / %d</b>' % (t['pendentes'], t['divergencias']), est['cel']),
            ]], colWidths=[UTIL / 5] * 5)
            resumo.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), .6, LINHA), ('INNERGRID', (0, 0), (-1, -1), .6, LINHA),
                                        ('BACKGROUND', (0, 0), (-1, -1), LINHA_2),
                                        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
            corpo.append(resumo)
            corpo.append(Spacer(1, 3 * mm))
            if not b['dias']:
                corpo.append(Paragraph('Sem movimento no período.', est['det']))
                continue
            for d in b['dias']:
                linhas = [[Paragraph('<b>%s %s</b> — saldo inicial' % (_sem(d['data']), _br(d['data'])), est['bold']),
                           '', '', '',
                           Paragraph('<b>%s</b>' % (_moeda(d['saldo_ini']) if d['saldo_ini'] is not None else '—'), est['boldd'])]]
                corrido = d['saldo_ini']
                for l in d['linhas']:
                    ent = l['tipo'] == 'CREDIT'
                    if corrido is not None and mostra_corrido:
                        corrido += l['valor'] if ent else -l['valor']
                    sit = {'conciliado': '<font color="#186c37">conciliado</font>',
                           'pendente': '<font color="#8a5a00">pendente</font>',
                           'ignorado': '<font color="#6c7784">ignorado</font>'}.get(l['status'], l['status'])
                    desc = _escapar(l['descricao'] or '')
                    if l['classe']:
                        desc += '<br/><font size="6.4" color="#5a6675">%s</font>' % _escapar(l['classe'])
                    linhas.append([
                        Paragraph(desc, est['cel']),
                        Paragraph(sit, est['det']),
                        Paragraph('<font color="#186c37">%s</font>' % _moeda(l['valor']) if ent else '', est['num']),
                        Paragraph('<font color="#a3262b">%s</font>' % _moeda(l['valor']) if not ent else '', est['num']),
                        Paragraph(_moeda(corrido) if (mostra_corrido and corrido is not None) else '', est['num']),
                    ])
                selo = ('<font color="#186c37">dia conciliado</font>' if d['conciliado'] else
                        ('<font color="#8a5a00">%d pendente(s)</font>' % d['pendentes']) if d['pendentes'] else '')
                linhas.append([Paragraph('<b>Saldo final</b> %s' % selo, est['bold']), '',
                               Paragraph('<b>%s</b>' % _moeda(d['entradas']), est['num']),
                               Paragraph('<b>%s</b>' % _moeda(d['saidas']), est['num']),
                               Paragraph('<b>%s</b>' % (_moeda(d['saldo_fim']) if d['saldo_fim'] is not None else '—'), est['boldd'])])
                n_fim = len(linhas) - 1
                n_dif = None
                if d['banco'] is not None:
                    if d['dif']:
                        linhas.append([Paragraph('<font color="#a3262b"><b>Banco informou %s — DIFERENÇA %s</b> (falta ou sobra lançamento neste dia)</font>'
                                                 % (_moeda(d['banco'], True), _moeda(d['dif'], True)), est['cel']), '', '', '', ''])
                        n_dif = len(linhas) - 1
                    else:
                        linhas.append([Paragraph('<font color="#186c37">confere com o saldo do banco (%s)</font>'
                                                 % ('OFX' if d['banco_origem'] == 'ofx' else 'On-Line'), est['det']), '', '', '', ''])
                tb = Table(linhas, colWidths=COLS)
                st = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
                      ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                      ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                      ('BACKGROUND', (0, 0), (-1, 0), DIA_BG), ('SPAN', (0, 0), (3, 0)),
                      ('BACKGROUND', (0, n_fim), (-1, n_fim), FIM_BG), ('SPAN', (0, n_fim), (1, n_fim)),
                      ('LINEBELOW', (0, 1), (-1, n_fim - 1), .3, LINHA)]
                if len(linhas) > n_fim + 1:
                    st.append(('SPAN', (0, n_fim + 1), (-1, n_fim + 1)))
                if n_dif is not None:
                    st.append(('BACKGROUND', (0, n_dif), (-1, n_dif), VENC_BG))
                tb.setStyle(TableStyle(st))
                # espaço depois da tabela pelo spaceAfter: um Spacer solto no pé
                # da página dava LayoutError no reportlab
                tb.spaceAfter = 2.2 * mm
                corpo.append(KeepTogether([tb]) if len(linhas) <= 25 else tb)

        if not corpo:
            corpo.append(Paragraph('Nenhuma conta escolhida.', est['cel']))
        return corpo
    cab = {'logo': logo, 'quando': quando,
           'filtro': 'Período %s a %s · %s · %d conta(s)' % (_br(ini), _br(fim), rotulo_origem, len(blocos))}
    buf = io.BytesIO()
    doc = _Doc(buf, cab)
    doc.build(_historia())
    paginas = doc.page
    buf = io.BytesIO()
    doc = _Doc(buf, cab)
    doc.total_paginas = paginas
    doc.build(_historia())
    return buf.getvalue()
