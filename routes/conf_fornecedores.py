"""
Relatório de Conferência de Fornecedores.

Cruza carregamentos (fretes) e pagamentos (bank_transactions DEBIT com
fornecedor_id) por fornecedor, mostrando saldo corrente (credor/devedor).

Rota:
  GET /relatorios/conf_fornecedores
"""
from collections import defaultdict
from datetime import date, datetime

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_fornecedores', __name__, url_prefix='/relatorios')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _default_period():
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _clientes_com_produtos(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT DISTINCT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome
             FROM clientes c
             INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome"""
    )
    result = cur.fetchall()
    cur.close()
    return result


def _fornecedores_list(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    result = cur.fetchall()
    cur.close()
    return result


def _fetch_carregamentos(conn, data_inicio, data_fim, cliente_ids, fornecedor_ids):
    """Retorna fretes filtrados como linhas de carregamento."""
    where = ["f.data_frete BETWEEN %s AND %s"]
    params = [data_inicio, data_fim]

    if cliente_ids:
        ph = ','.join(['%s'] * len(cliente_ids))
        where.append(f"f.clientes_id IN ({ph})")
        params.extend(cliente_ids)

    if fornecedor_ids:
        ph = ','.join(['%s'] * len(fornecedor_ids))
        where.append(f"f.fornecedores_id IN ({ph})")
        params.extend(fornecedor_ids)

    # Must be linked to a supplier
    where.append("f.fornecedores_id IS NOT NULL")

    sql = f"""
        SELECT
            f.id,
            f.data_frete                                    AS data_carregamento,
            NULL                                            AS data_pagto,
            COALESCE(f.quantidade_manual, f.quantidade_id, 0) AS quantidade,
            COALESCE(f.preco_produto_unitario, 0)           AS vlr_uni,
            COALESCE(f.total_nf_compra, 0)                  AS vlr_compra_total,
            0                                               AS valor_pago,
            f.fornecedores_id                               AS fornecedor_id,
            fo.razao_social                                 AS fornecedor_nome,
            'carregamento'                                  AS tipo,
            COALESCE(c.nome_fantasia, c.razao_social)       AS empresa_nome
        FROM fretes f
        JOIN fornecedores fo ON fo.id = f.fornecedores_id
        LEFT JOIN clientes c ON c.id = f.clientes_id
        WHERE {' AND '.join(where)}
        ORDER BY f.data_frete, f.id
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetch_pagamentos(conn, data_inicio, data_fim, cliente_ids, fornecedor_ids):
    """Retorna pagamentos bank_transactions DEBIT vinculados a fornecedor."""
    where = [
        "bt.tipo = 'DEBIT'",
        "bt.fornecedor_id IS NOT NULL",
        "bt.data_transacao BETWEEN %s AND %s",
    ]
    params = [data_inicio, data_fim]

    if fornecedor_ids:
        ph = ','.join(['%s'] * len(fornecedor_ids))
        where.append(f"bt.fornecedor_id IN ({ph})")
        params.extend(fornecedor_ids)

    if cliente_ids:
        ph = ','.join(['%s'] * len(cliente_ids))
        where.append(f"ba.cliente_id IN ({ph})")
        params.extend(cliente_ids)

    sql = f"""
        SELECT
            bt.id,
            NULL                                            AS data_carregamento,
            bt.data_transacao                               AS data_pagto,
            0                                               AS quantidade,
            0                                               AS vlr_uni,
            0                                               AS vlr_compra_total,
            bt.valor                                        AS valor_pago,
            bt.fornecedor_id                                AS fornecedor_id,
            fo.razao_social                                 AS fornecedor_nome,
            'pagamento'                                     AS tipo,
            COALESCE(c.nome_fantasia, c.razao_social)       AS empresa_nome
        FROM bank_transactions bt
        JOIN bank_accounts ba ON ba.id = bt.account_id
        JOIN fornecedores fo ON fo.id = bt.fornecedor_id
        LEFT JOIN clientes c ON c.id = ba.cliente_id
        WHERE {' AND '.join(where)}
        ORDER BY bt.data_transacao, bt.id
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_linhas(carregamentos, pagamentos):
    """
    Mescla pagamentos e carregamentos do mesmo fornecedor.

    Regra de ordenação:
      - Itens de datas diferentes seguem ordem cronológica.
      - Na mesma data: pagamento vem antes do carregamento.

    Calcula saldo corrente (positivo = credor — já pagou mas não retirou;
    negativo = devedor — retirou mas não pagou).
    """
    # Group all events by fornecedor_id
    by_forn = defaultdict(list)
    for row in pagamentos:
        by_forn[row['fornecedor_id']].append(row)
    for row in carregamentos:
        by_forn[row['fornecedor_id']].append(row)

    result = {}  # fornecedor_id -> {nome, linhas, totais}

    for forn_id, eventos in by_forn.items():
        # Sort: by effective date asc, then payments before loads, then id
        def _sort_key(e):
            d = e.get('data_pagto') or e.get('data_carregamento')
            if isinstance(d, str):
                try:
                    d = datetime.strptime(d, '%Y-%m-%d').date()
                except Exception:
                    d = date.min
            order = 0 if e['tipo'] == 'pagamento' else 1
            return (d or date.min, order, e['id'])

        eventos.sort(key=_sort_key)

        saldo = 0.0
        total_qtd = 0.0
        total_compra = 0.0
        total_pago = 0.0
        linhas = []

        for ev in eventos:
            qtd = float(ev.get('quantidade') or 0)
            vlr_uni = float(ev.get('vlr_uni') or 0)
            vlr_compra = float(ev.get('vlr_compra_total') or 0)
            valor_pago = float(ev.get('valor_pago') or 0)

            if ev['tipo'] == 'pagamento':
                saldo += valor_pago   # pagamento aumenta crédito a favor
                total_pago += valor_pago
            else:
                # carregamento: deduz do saldo (estamos retirando o que foi pago)
                saldo -= vlr_compra
                total_qtd += qtd
                total_compra += vlr_compra

            # Format dates
            def _fmt(d):
                if d is None:
                    return ''
                if isinstance(d, str):
                    try:
                        d = datetime.strptime(d, '%Y-%m-%d').date()
                    except Exception:
                        return str(d)
                return d.strftime('%d/%m/%Y')

            linhas.append({
                'tipo': ev['tipo'],
                'data_pagto': _fmt(ev.get('data_pagto')),
                'data_carregamento': _fmt(ev.get('data_carregamento')),
                'quantidade': qtd,
                'vlr_uni': vlr_uni,
                'vlr_compra_total': vlr_compra,
                'valor_pago': valor_pago,
                'saldo': saldo,
            })

        result[forn_id] = {
            'fornecedor_id': forn_id,
            'fornecedor_nome': eventos[0]['fornecedor_nome'],
            'linhas': linhas,
            'total_qtd': total_qtd,
            'total_compra': total_compra,
            'total_pago': total_pago,
            'saldo_final': saldo,
        }

    # Sort suppliers alphabetically
    return sorted(result.values(), key=lambda x: x['fornecedor_nome'] or '')


# ──────────────────────────────────────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_fornecedores', methods=['GET'])
@admin_required
def conf_fornecedores():
    args = request.args

    # ── Filters ──────────────────────────────────────────────────────────────
    data_inicio = args.get('data_inicio', '').strip()
    data_fim = args.get('data_fim', '').strip()

    # Apply default period (current month) on first load
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    cliente_ids = [c for c in args.getlist('cliente_ids[]') if c]
    fornecedor_ids = [f for f in args.getlist('fornecedor_ids[]') if f]
    # Whether to show all suppliers in one running list or separate tables
    agrupar = args.get('agrupar', '1')  # '1' = group by supplier (default), '0' = flat

    conn = get_db_connection()
    try:
        empresas = _clientes_com_produtos(conn)
        fornecedores = _fornecedores_list(conn)

        fornecedores_data = []

        # Only query if we have a valid date range
        if data_inicio and data_fim:
            carregamentos = _fetch_carregamentos(
                conn, data_inicio, data_fim, cliente_ids, fornecedor_ids
            )
            pagamentos = _fetch_pagamentos(
                conn, data_inicio, data_fim, cliente_ids, fornecedor_ids
            )
            fornecedores_data = _build_linhas(carregamentos, pagamentos)
    finally:
        conn.close()

    # Grand totals
    grand_total_qtd = sum(f['total_qtd'] for f in fornecedores_data)
    grand_total_compra = sum(f['total_compra'] for f in fornecedores_data)
    grand_total_pago = sum(f['total_pago'] for f in fornecedores_data)
    grand_saldo = sum(f['saldo_final'] for f in fornecedores_data)

    return render_template(
        'relatorios/conf_fornecedores.html',
        empresas=empresas,
        fornecedores=fornecedores,
        fornecedores_data=fornecedores_data,
        data_inicio=data_inicio,
        data_fim=data_fim,
        cliente_ids=cliente_ids,
        fornecedor_ids=fornecedor_ids,
        agrupar=agrupar,
        grand_total_qtd=grand_total_qtd,
        grand_total_compra=grand_total_compra,
        grand_total_pago=grand_total_pago,
        grand_saldo=grand_saldo,
    )
