"""Financeiro > Extrato (pedido 04/11/2026).

Banco por banco, dia a dia: saldo inicial, cada entrada e saída (conciliado
ou pendente, com a classificação), saldo final e — quando o banco informou o
saldo daquele dia — a diferença. Origem: On-Line, OFX ou os dois (só escolhe
o que aparece; o saldo é sempre com tudo). Exporta PDF, Excel e o Excel
Contábil que já existia (/banco/exportar-contabil), com os mesmos filtros.

O saldo e a conta ficam em utils/extrato_saldos.py.
"""
import io
import logging
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, render_template, request, url_for
from flask_login import login_required

from utils.db import get_db_connection
from utils import extrato_saldos as es

logger = logging.getLogger(__name__)

bp = Blueprint('extrato_bancario', __name__, url_prefix='/banco/extrato')

ORIGENS = {'todos': 'On-Line + OFX', 'online': 'Só On-Line', 'ofx': 'Só OFX'}
MAX_DIAS = 400


def _data(txt, padrao):
    try:
        return datetime.strptime(str(txt)[:10], '%Y-%m-%d').date()
    except Exception:
        return padrao


def _filtros():
    hoje = date.today()
    fim = _data(request.args.get('fim'), hoje)
    ini = _data(request.args.get('ini'), fim - timedelta(days=6))
    if ini > fim:
        ini, fim = fim, ini
    if (fim - ini).days > MAX_DIAS:
        ini = fim - timedelta(days=MAX_DIAS)
    origem = request.args.get('origem') or 'todos'
    if origem not in ORIGENS:
        origem = 'todos'
    ids = []
    for v in request.args.getlist('conta'):
        try:
            ids.append(int(v))
        except Exception:
            pass
    return ini, fim, origem, ids


def _blocos():
    ini, fim, origem, ids = _filtros()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        todas = es.contas(cur)
        escolhidas = [c for c in todas if not ids or c['id'] in ids]
        blocos = [es.montar(cur, c, ini, fim, origem) for c in escolhidas]
    finally:
        cur.close()
        conn.close()
    return todas, blocos, ini, fim, origem, ids


def _contabil_url(bloco, ini, fim):
    return url_for('bank_import.exportar_contabil', account_id=bloco['conta']['id'],
                   data_ini=str(ini), data_fim=str(fim))


@bp.route('/')
@login_required
def index():
    todas, blocos, ini, fim, origem, ids = _blocos()
    # contas sem nada no período ficam recolhidas no fim
    blocos.sort(key=lambda b: (not b['dias'], b['conta']['apelido'] or ''))
    for b in blocos:
        b['contabil_url'] = _contabil_url(b, ini, fim)
    qs = request.query_string.decode('utf-8')
    return render_template('bank_import/extrato.html', contas=todas, blocos=blocos,
                           ini=ini, fim=fim, origem=origem, ids=ids, origens=ORIGENS,
                           qs=qs, hoje=date.today())


# ── Excel ───────────────────────────────────────────────────────────────────

@bp.route('/excel')
@login_required
def excel():
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    _todas, blocos, ini, fim, origem, _ids = _blocos()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    azul = PatternFill('solid', fgColor='1D63A5')
    dia_f = PatternFill('solid', fgColor='EAF1F9')
    fim_f = PatternFill('solid', fgColor='F3F5F8')
    dif_f = PatternFill('solid', fgColor='FBE9E9')
    fina = Side(style='thin', color='D9E0E8')
    moeda = '#,##0.00;[Red]-#,##0.00'
    usados = set()
    for b in blocos:
        c = b['conta']
        nome = (c['apelido'] or c['banco_nome'] or 'Conta')[:28]
        for ch in '[]:*?/\\':
            nome = nome.replace(ch, ' ')
        while nome in usados:
            nome = nome[:26] + '_' + str(len(usados))
        usados.add(nome)
        ws = wb.create_sheet(nome)
        ws.append([f"Extrato — {c['apelido']}"])
        ws['A1'].font = Font(bold=True, size=14, color='0C4C86')
        ws.append([f"{c.get('empresa') or ''} · Ag {c.get('agencia') or '—'} · Conta {c.get('conta') or '—'}"])
        ws.append([f"Período {ini:%d/%m/%Y} a {fim:%d/%m/%Y} · {ORIGENS[origem]} · saldo: {b['base']}"])
        ws.append([])
        cab = ['Data', 'Descrição', 'Classificação', 'Situação', 'Origem', 'Entrada', 'Saída', 'Saldo']
        ws.append(cab)
        for i in range(1, len(cab) + 1):
            cel = ws.cell(row=ws.max_row, column=i)
            cel.fill = azul
            cel.font = Font(bold=True, color='FFFFFF')
            cel.alignment = Alignment(horizontal='center')
        for d in b['dias']:
            ws.append([d['data'], 'Saldo inicial', '', '', '', None, None, d['saldo_ini']])
            r = ws.max_row
            for i in range(1, 9):
                ws.cell(row=r, column=i).fill = dia_f
                ws.cell(row=r, column=i).font = Font(bold=True)
            corrido = d['saldo_ini']
            for l in d['linhas']:
                ent = l['valor'] if l['tipo'] == 'CREDIT' else None
                sai = l['valor'] if l['tipo'] == 'DEBIT' else None
                if corrido is not None and origem == 'todos':
                    corrido = round(corrido + (ent or 0) - (sai or 0), 2)
                orig = 'On-Line + OFX' if (l['online'] and l['ofx']) else ('On-Line' if l['online'] else 'OFX')
                ws.append([d['data'], l['descricao'] or '', l['classe'] or '',
                           {'conciliado': 'Conciliado', 'pendente': 'Pendente',
                            'ignorado': 'Ignorado'}.get(l['status'], l['status']),
                           orig, ent, sai, corrido if origem == 'todos' else None])
            ws.append([d['data'], 'Saldo final' + (' — dia conciliado' if d['conciliado'] else
                                                    ' — %d pendente(s)' % d['pendentes'] if d['pendentes'] else ''),
                       '', '', '', d['entradas'], d['saidas'], d['saldo_fim']])
            r = ws.max_row
            for i in range(1, 9):
                ws.cell(row=r, column=i).fill = fim_f
                ws.cell(row=r, column=i).font = Font(bold=True)
            if d['banco'] is not None:
                ws.append([d['data'], 'Saldo informado pelo banco (%s)' % ('OFX' if d['banco_origem'] == 'ofx' else 'On-Line'),
                           'DIFERENÇA %s' % ('{:,.2f}'.format(d['dif']).replace(',', 'X').replace('.', ',').replace('X', '.')) if d['dif'] else 'confere',
                           '', '', None, None, d['banco']])
                if d['dif']:
                    for i in range(1, 9):
                        ws.cell(row=ws.max_row, column=i).fill = dif_f
                        ws.cell(row=ws.max_row, column=i).font = Font(bold=True, color='A32D2D')
            ws.append([])
        ws.append(['', 'Total do período', '', '', '', b['tot']['entradas'], b['tot']['saidas'], b['saldo_final']])
        for i in range(1, 9):
            ws.cell(row=ws.max_row, column=i).font = Font(bold=True)
        for row in ws.iter_rows(min_row=6):
            row[0].number_format = 'DD/MM/YYYY'
            for cel in row[5:8]:
                cel.number_format = moeda
            for cel in row:
                if cel.value is not None:
                    cel.border = Border(bottom=fina)
        for col, w in zip('ABCDEFGH', (11, 52, 40, 12, 14, 14, 14, 15)):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = 'A6'
    if not blocos:
        wb.create_sheet('Extrato').append(['Nenhuma conta escolhida'])
    buf = io.BytesIO()
    wb.save(buf)
    nome = f"extrato_{ini:%d-%m-%Y}_a_{fim:%d-%m-%Y}.xlsx"
    return Response(buf.getvalue(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="{nome}"'})


# ── PDF ─────────────────────────────────────────────────────────────────────

@bp.route('/pdf')
@login_required
def pdf():
    from utils.extrato_pdf import gerar
    _todas, blocos, ini, fim, origem, _ids = _blocos()
    conteudo = gerar(blocos, ini, fim, ORIGENS[origem], origem == 'todos')
    nome = f"extrato_{ini:%d-%m-%Y}_a_{fim:%d-%m-%Y}.pdf"
    return Response(conteudo, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{nome}"'})
