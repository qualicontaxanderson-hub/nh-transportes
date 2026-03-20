"""
Relatório de Conferência de Depósitos.

Exibe os depósitos registrados no Fechamento de Caixa (Depósitos em Espécie,
Cheques À Vista e Cheques A Prazo) com data da venda, valor, data de depósito
e acumulado, agrupados por tipo.

Rota:
  GET  /relatorios/conf_depositos  – relatório
"""
from datetime import date, datetime

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_depositos', __name__, url_prefix='/relatorios')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _default_period():
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _get_clientes(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT DISTINCT c.id,
               COALESCE(c.nome_fantasia, c.razao_social) AS nome
          FROM clientes c
          INNER JOIN lancamentos_caixa lc ON lc.cliente_id = c.id
         ORDER BY nome
        """
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _fmt_date(d):
    """Formata date/str para DD/MM/YYYY."""
    if d is None:
        return ''
    if isinstance(d, str):
        try:
            d = datetime.strptime(d, '%Y-%m-%d').date()
        except Exception:
            return d
    try:
        return d.strftime('%d/%m/%Y')
    except Exception:
        return str(d)


_TIPO_LABELS = {
    'DEPOSITO_ESPECIE':      'Depósitos em Espécie',
    'DEPOSITO_CHEQUE_VISTA': 'Cheques À Vista',
    'DEPOSITO_CHEQUE_PRAZO': 'Cheques A Prazo',
}

_TIPOS_ORDER = ['DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO']


def _fetch_depositos(conn, data_inicio, data_fim, cliente_ids):
    cur = conn.cursor(dictionary=True)
    params = [data_inicio, data_fim]

    cliente_filter = ''
    if cliente_ids:
        ph = ','.join(['%s'] * len(cliente_ids))
        cliente_filter = f'AND lc.cliente_id IN ({ph})'
        params.extend(cliente_ids)

    cur.execute(
        f"""
        SELECT lc.data         AS data_venda,
               lc.cliente_id,
               COALESCE(c.nome_fantasia, c.razao_social) AS cliente_nome,
               fp.tipo         AS deposito_tipo,
               lcc.valor,
               lcc.data_deposito,
               lcc.descricao
          FROM lancamentos_caixa_comprovacao lcc
          JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
          JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
          LEFT JOIN clientes c ON c.id = lc.cliente_id
         WHERE fp.tipo IN ('DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
           AND lc.data BETWEEN %s AND %s
           AND lcc.valor > 0
           {cliente_filter}
         ORDER BY fp.tipo, lc.data, lcc.id
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_report(rows):
    """
    Agrupa as linhas por tipo de depósito e calcula o acumulado.
    Retorna lista de seções: [{tipo, label, linhas, total}]
    """
    from collections import defaultdict

    by_tipo = defaultdict(list)
    for row in rows:
        by_tipo[row['deposito_tipo']].append(row)

    sections = []
    for tipo in _TIPOS_ORDER:
        linhas = by_tipo.get(tipo, [])
        if not linhas:
            continue
        acumulado = 0.0
        linhas_fmt = []
        for r in linhas:
            valor = float(r['valor'])
            acumulado += valor
            linhas_fmt.append({
                'data_venda':    _fmt_date(r['data_venda']),
                'cliente_nome':  r.get('cliente_nome') or '',
                'valor':         valor,
                'data_deposito': _fmt_date(r['data_deposito']),
                'descricao':     r.get('descricao') or '',
                'acumulado':     acumulado,
            })
        sections.append({
            'tipo':   tipo,
            'label':  _TIPO_LABELS[tipo],
            'linhas': linhas_fmt,
            'total':  acumulado,
        })
    return sections


# ──────────────────────────────────────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_depositos', methods=['GET'])
@login_required
@admin_required
def conf_depositos():
    args = request.args

    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim', '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    cliente_ids = [c for c in args.getlist('cliente_ids[]') if c]

    conn = get_db_connection()
    try:
        clientes = _get_clientes(conn)
        rows = _fetch_depositos(conn, data_inicio, data_fim, cliente_ids)
        sections = _build_report(rows)
    finally:
        conn.close()

    return render_template(
        'relatorios/conf_depositos.html',
        clientes=clientes,
        sections=sections,
        data_inicio=data_inicio,
        data_fim=data_fim,
        cliente_ids=cliente_ids,
    )
