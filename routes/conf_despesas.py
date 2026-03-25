"""
Relatório de Conferência de Despesas.

Exibe uma matriz pivot: blocos por Título de despesa,
linhas por Categoria, colunas pelos meses do período selecionado
(JAN–DEZ) + coluna ACUM (acumulado do período).

Multi-empresa: filtro empresa_ids[] restringe quais empresas
contribuem com dados; os valores são somados em uma única matriz.

Rota:
  GET /relatorios/conf_despesas
"""
from datetime import date, datetime

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_despesas', __name__, url_prefix='/relatorios')

_MES_LABELS = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _default_period():
    """Padrão: ano corrente completo (01/01 – 31/12)."""
    hoje = date.today()
    return f'{hoje.year}-01-01', f'{hoje.year}-12-31'


def _months_in_range(data_inicio_str, data_fim_str):
    """
    Retorna lista ordenada de dicts {year, month, label, key}
    para cada mês entre data_inicio e data_fim (inclusive).
    key = 'YYYYMM' string.
    """
    try:
        d_ini = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        d_fim = datetime.strptime(data_fim_str,    '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return []
    months = []
    y, m = d_ini.year, d_ini.month
    while (y, m) <= (d_fim.year, d_fim.month):
        months.append({
            'year':  y,
            'month': m,
            'label': _MES_LABELS[m - 1],
            'key':   f'{y}{m:02d}',
        })
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _empresas_list(conn):
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


def _titulos_list(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome"
    )
    result = cur.fetchall()
    cur.close()
    return result


def _fetch_lancamentos(conn, data_inicio, data_fim, empresa_ids, titulo_ids):
    """Retorna lançamentos de despesas filtrados com metadados de título e categoria."""
    where = ["ld.data BETWEEN %s AND %s"]
    params = [data_inicio, data_fim]

    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        where.append(f"ld.cliente_id IN ({ph})")
        params.extend(empresa_ids)

    if titulo_ids:
        ph = ','.join(['%s'] * len(titulo_ids))
        where.append(f"ld.titulo_id IN ({ph})")
        params.extend(titulo_ids)

    sql = f"""
        SELECT
            ld.id,
            ld.data,
            COALESCE(ld.valor, 0)                               AS valor,
            ld.titulo_id,
            COALESCE(t.ordem,  9999)                            AS titulo_ordem,
            t.nome                                              AS titulo_nome,
            ld.categoria_id,
            COALESCE(c.ordem,  9999)                            AS categoria_ordem,
            c.nome                                              AS categoria_nome
        FROM lancamentos_despesas ld
        INNER JOIN titulos_despesas    t ON t.id = ld.titulo_id
        INNER JOIN categorias_despesas c ON c.id = ld.categoria_id
        WHERE {' AND '.join(where)}
        ORDER BY titulo_ordem, t.nome, categoria_ordem, c.nome, ld.data
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_category_matrix(lancamentos, months):
    """
    Constrói a matriz pivot:

        bloco  = Título  (grupo de despesa, ex.: FUNCIONÁRIOS, CAMINHÃO)
        linha  = Categoria dentro do título
        coluna = mês  (chave YYYYMM)

    Retorna:
        blocks (list) – cada elemento:
          titulo_id, titulo_nome,
          rows (list):
            categoria_id, categoria_nome,
            by_month {key: float}, total (float)
          total_by_month {key: float}, total (float)

        grand_by_month {key: float}
        grand_total    float
    """
    month_keys = {m['key'] for m in months}

    # titulo_id → (nome, ordem)
    titulo_meta = {}
    # cat_id → (nome, titulo_id, ordem)
    cat_meta    = {}
    # titulo_id → cat_id → month_key → float
    tree        = {}

    for row in lancamentos:
        tit_id  = row['titulo_id']
        cat_id  = row['categoria_id']
        d       = row['data']
        if isinstance(d, str):
            try:
                d = datetime.strptime(d, '%Y-%m-%d').date()
            except ValueError:
                continue
        mk = f'{d.year}{d.month:02d}'
        if mk not in month_keys:
            continue

        titulo_meta.setdefault(tit_id, (row['titulo_nome'], row['titulo_ordem']))
        cat_meta.setdefault(cat_id,    (row['categoria_nome'], tit_id, row['categoria_ordem']))

        if tit_id not in tree:
            tree[tit_id] = {}
        if cat_id not in tree[tit_id]:
            tree[tit_id][cat_id] = {}
        tree[tit_id][cat_id][mk] = tree[tit_id][cat_id].get(mk, 0.0) + float(row['valor'])

    grand_by_month = {m['key']: 0.0 for m in months}
    grand_total    = 0.0
    blocks         = []

    for tit_id in sorted(tree, key=lambda x: (titulo_meta[x][1], titulo_meta[x][0])):
        block_by_month = {m['key']: 0.0 for m in months}
        rows = []

        for cat_id in sorted(
            tree[tit_id],
            key=lambda x: (cat_meta[x][2], cat_meta[x][0]),
        ):
            row_by_month = {}
            row_total    = 0.0
            for m in months:
                val = tree[tit_id][cat_id].get(m['key'], 0.0)
                row_by_month[m['key']]  = val
                row_total              += val
                block_by_month[m['key']] += val
            rows.append({
                'categoria_id':   cat_id,
                'categoria_nome': cat_meta[cat_id][0],
                'by_month':       row_by_month,
                'total':          row_total,
            })

        block_total = sum(block_by_month.values())
        for mk, v in block_by_month.items():
            grand_by_month[mk] = grand_by_month.get(mk, 0.0) + v
        grand_total += block_total

        blocks.append({
            'titulo_id':        tit_id,
            'titulo_nome':      titulo_meta[tit_id][0],
            'rows':             rows,
            'total_by_month':   block_by_month,
            'total':            block_total,
        })

    return blocks, grand_by_month, grand_total


# ──────────────────────────────────────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_despesas', methods=['GET'])
@login_required
@admin_required
def conf_despesas():
    args = request.args

    # ── Filters ──────────────────────────────────────────────────────────────
    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()

    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]
    titulo_ids  = [t for t in args.getlist('titulo_ids[]')  if t]

    conn = get_db_connection()
    try:
        empresas = _empresas_list(conn)
        titulos  = _titulos_list(conn)

        months            = []
        blocks            = []
        grand_by_month    = {}
        grand_total       = 0.0
        total_lancamentos = 0

        if data_inicio and data_fim:
            months = _months_in_range(data_inicio, data_fim)
            lancamentos = _fetch_lancamentos(
                conn, data_inicio, data_fim, empresa_ids, titulo_ids,
            )
            total_lancamentos = len(lancamentos)
            blocks, grand_by_month, grand_total = _build_category_matrix(
                lancamentos, months
            )
    finally:
        conn.close()

    return render_template(
        'relatorios/conf_despesas.html',
        empresas=empresas,
        titulos=titulos,
        months=months,
        blocks=blocks,
        grand_by_month=grand_by_month,
        grand_total=grand_total,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        titulo_ids=titulo_ids,
        total_lancamentos=total_lancamentos,
    )
