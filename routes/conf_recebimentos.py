"""Relatório de Conferência de Recebimentos.

Exibe uma matriz pivot mensal com dois blocos:
  - RECEBIMENTO DE ALUGUEL  (formas_recebimento cujo nome contém essa frase)
  - CLIENTES À PRAZO        (formas_recebimento cujo nome contém 'CLIENTE' e 'PRAZO')

As linhas de cada bloco são as formas_recebimento individuais (e.g. SICREDI –
NH GTBA, FENIX, etc.).  As colunas são os meses do período selecionado mais
uma coluna ACUM (acumulado).

Fonte dos dados: bank_transactions (tipo='CREDIT', status≠'ignorado') com
forma_recebimento_id preenchida, agrupados por mês e forma.
"""
import unicodedata
from collections import defaultdict
from datetime import date

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_recebimentos', __name__, url_prefix='/relatorios')

_MES_LABELS = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']


def _ascii_upper(s):
    """Converte para maiúsculas e remove acentos para comparação robusta."""
    return (unicodedata.normalize('NFD', (s or '').upper())
            .encode('ascii', 'ignore').decode('ascii'))


def _default_period():
    hoje = date.today()
    return f'{hoje.year}-01-01', f'{hoje.year}-12-31'


def _months_in_range(data_inicio_str, data_fim_str):
    """Retorna lista de dicts {year, month, label, key} para cada mês do intervalo."""
    d_ini = date.fromisoformat(data_inicio_str)
    d_fim = date.fromisoformat(data_fim_str)
    months = []
    y, m = d_ini.year, d_ini.month
    while (y, m) <= (d_fim.year, d_fim.month):
        months.append({
            'year': y,
            'month': m,
            'label': _MES_LABELS[m - 1],
            'key': f'{y}{m:02d}',
        })
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _empresas_list(conn):
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT DISTINCT c.id,
                      COALESCE(c.nome_fantasia, c.razao_social) AS nome
               FROM clientes c
               INNER JOIN bank_accounts ba ON ba.cliente_id = c.id
               ORDER BY nome"""
        )
        rows = cursor.fetchall()
    except Exception:
        rows = []
    cursor.close()
    return rows


def _classify_forma(nome):
    """Retorna 'aluguel', 'cliente_a_prazo' ou None."""
    u = _ascii_upper(nome)
    if 'RECEBIMENTO DE ALUGUEL' in u:
        return 'aluguel'
    if 'CLIENTE' in u and 'PRAZO' in u:
        return 'cliente_a_prazo'
    return None


def _build_block(formas_dict, label):
    """Monta estrutura de bloco a partir do dicionário de formas."""
    rows_list = sorted(formas_dict.values(), key=lambda r: r['nome'])
    # Convert defaultdict to plain dict for clean template access
    for r in rows_list:
        r['by_month'] = dict(r['by_month'])
    total_by_month = defaultdict(float)
    total = 0.0
    for r in rows_list:
        for mk, v in r['by_month'].items():
            total_by_month[mk] += v
        total += r['total']
    return {
        'label': label,
        'rows': rows_list,
        'total_by_month': dict(total_by_month),
        'total': total,
    }


@bp.route('/conf_recebimentos', methods=['GET'])
@login_required
@admin_required
def conf_recebimentos():
    """Relatório de Conferência de Recebimentos — matriz mensal por forma."""
    args = request.args
    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]

    conn = get_db_connection()
    try:
        empresas = _empresas_list(conn)
        months   = _months_in_range(data_inicio, data_fim)

        # Empresa filter
        emp_clause = ''
        emp_params: list = []
        if empresa_ids:
            placeholders = ','.join(['%s'] * len(empresa_ids))
            emp_clause = f'AND ba.cliente_id IN ({placeholders})'
            emp_params = [int(e) for e in empresa_ids]

        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"""SELECT
                    YEAR(bt.data_transacao)  AS yr,
                    MONTH(bt.data_transacao) AS mo,
                    fr.id   AS forma_id,
                    fr.nome AS forma_nome,
                    SUM(bt.valor) AS total
                FROM bank_transactions bt
                JOIN bank_accounts ba ON ba.id = bt.account_id
                JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
                WHERE bt.tipo = 'CREDIT'
                  AND bt.status != 'ignorado'
                  AND bt.data_transacao BETWEEN %s AND %s
                  {emp_clause}
                GROUP BY yr, mo, fr.id, fr.nome
                ORDER BY fr.nome, yr, mo""",
            [data_inicio, data_fim] + emp_params,
        )
        rows = cursor.fetchall()
        cursor.close()

        # Accumulate per-forma data into two groups
        aluguel_formas: dict       = {}
        cliente_prazo_formas: dict = {}

        for row in rows:
            grupo = _classify_forma(row['forma_nome'])
            if grupo is None:
                continue
            fid   = row['forma_id']
            fname = row['forma_nome']
            mk    = f"{int(row['yr'])}{int(row['mo']):02d}"
            val   = float(row['total'] or 0)

            store = aluguel_formas if grupo == 'aluguel' else cliente_prazo_formas
            if fid not in store:
                store[fid] = {
                    'id':       fid,
                    'nome':     fname,
                    'by_month': defaultdict(float),
                    'total':    0.0,
                }
            store[fid]['by_month'][mk] += val
            store[fid]['total']        += val

        blocks = [
            _build_block(aluguel_formas,      'RECEBIMENTO DE ALUGUEL'),
            _build_block(cliente_prazo_formas, 'CLIENTES À PRAZO'),
        ]

        # Grand totals
        grand_by_month: dict = defaultdict(float)
        grand_total = 0.0
        for block in blocks:
            for mk, v in block['total_by_month'].items():
                grand_by_month[mk] += v
            grand_total += block['total']

        total_formas = sum(len(b['rows']) for b in blocks)

    finally:
        conn.close()

    return render_template(
        'relatorios/conf_recebimentos.html',
        empresas=empresas,
        months=months,
        blocks=blocks,
        grand_by_month=dict(grand_by_month),
        grand_total=grand_total,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        total_formas=total_formas,
    )
