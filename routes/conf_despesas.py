"""
Relatório de Conferência de Despesas.

Cruza lançamentos de despesas (lancamentos_despesas) por empresa,
título, categoria e subcategoria, exibindo totais em cada nível e
um total geral — ideal para conferir gastos por período e empresa.

Rota:
  GET /relatorios/conf_despesas
"""
from collections import defaultdict
from datetime import date, datetime

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_despesas', __name__, url_prefix='/relatorios')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _default_period():
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


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


def _categorias_list(conn, titulo_id=None):
    cur = conn.cursor(dictionary=True)
    if titulo_id:
        cur.execute(
            """SELECT id, nome FROM categorias_despesas
                WHERE ativo = 1 AND titulo_id = %s ORDER BY ordem, nome""",
            (titulo_id,),
        )
    else:
        cur.execute(
            "SELECT id, nome FROM categorias_despesas WHERE ativo = 1 ORDER BY ordem, nome"
        )
    result = cur.fetchall()
    cur.close()
    return result


def _fetch_lancamentos(conn, data_inicio, data_fim, empresa_ids, titulo_ids, categoria_ids):
    """Retorna lançamentos de despesas filtrados com todos os metadados."""
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

    if categoria_ids:
        ph = ','.join(['%s'] * len(categoria_ids))
        where.append(f"ld.categoria_id IN ({ph})")
        params.extend(categoria_ids)

    sql = f"""
        SELECT
            ld.id,
            ld.data,
            ld.valor,
            ld.fornecedor,
            ld.observacao,
            ld.cliente_id                                       AS empresa_id,
            COALESCE(cl.nome_fantasia, cl.razao_social, '—')    AS empresa_nome,
            ld.titulo_id,
            t.nome                                              AS titulo_nome,
            ld.categoria_id,
            c.nome                                              AS categoria_nome,
            ld.subcategoria_id,
            s.nome                                              AS subcategoria_nome
        FROM lancamentos_despesas ld
        INNER JOIN titulos_despesas    t  ON t.id  = ld.titulo_id
        INNER JOIN categorias_despesas c  ON c.id  = ld.categoria_id
        LEFT  JOIN subcategorias_despesas s ON s.id = ld.subcategoria_id
        LEFT  JOIN clientes            cl ON cl.id = ld.cliente_id
        WHERE {' AND '.join(where)}
        ORDER BY empresa_nome, t.ordem, t.nome, c.ordem, c.nome,
                 COALESCE(s.ordem, 9999), COALESCE(s.nome, ''), ld.data, ld.id
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_report(lancamentos):
    """
    Organiza os lançamentos em uma estrutura hierárquica:

        empresas (list) →
          titulo_grupos (list) →
            categoria_grupos (list) →
              subcategoria_grupos (list) →
                linhas (list)

    Também calcula totais em cada nível.
    """
    # index: empresa_id → titulo_id → categoria_id → subcategoria_key → linhas
    tree = {}  # empresa_id → dict
    empresa_meta = {}
    titulo_meta = {}
    categoria_meta = {}
    subcat_meta = {}

    for row in lancamentos:
        emp_id  = row['empresa_id']  or 0
        tit_id  = row['titulo_id']
        cat_id  = row['categoria_id']
        sub_id  = row['subcategoria_id']  # may be None
        sub_key = sub_id if sub_id else '__none__'

        empresa_meta[emp_id] = row['empresa_nome']
        titulo_meta[tit_id]  = row['titulo_nome']
        categoria_meta[cat_id] = row['categoria_nome']
        if sub_id:
            subcat_meta[sub_id] = row['subcategoria_nome']

        if emp_id not in tree:
            tree[emp_id] = {}
        if tit_id not in tree[emp_id]:
            tree[emp_id][tit_id] = {}
        if cat_id not in tree[emp_id][tit_id]:
            tree[emp_id][tit_id][cat_id] = {}
        if sub_key not in tree[emp_id][tit_id][cat_id]:
            tree[emp_id][tit_id][cat_id][sub_key] = []

        tree[emp_id][tit_id][cat_id][sub_key].append({
            'id': row['id'],
            'data': row['data'].strftime('%d/%m/%Y') if isinstance(row['data'], (date, datetime)) else str(row['data']),
            'valor': float(row['valor'] or 0),
            'fornecedor': row['fornecedor'] or '',
            'observacao': row['observacao'] or '',
            'subcategoria_nome': row['subcategoria_nome'] or '',
        })

    # Build ordered output
    result_empresas = []

    for emp_id in sorted(tree.keys(), key=lambda x: empresa_meta.get(x, '')):
        emp_total = 0.0
        titulo_groups = []

        for tit_id in sorted(tree[emp_id].keys(), key=lambda x: titulo_meta.get(x, '')):
            tit_total = 0.0
            cat_groups = []

            for cat_id in sorted(tree[emp_id][tit_id].keys(), key=lambda x: categoria_meta.get(x, '')):
                cat_total = 0.0
                sub_groups = []
                has_subcats = False

                for sub_key in sorted(
                    tree[emp_id][tit_id][cat_id].keys(),
                    key=lambda x: subcat_meta.get(x, '') if x != '__none__' else '',
                ):
                    linhas = tree[emp_id][tit_id][cat_id][sub_key]
                    sub_total = sum(l['valor'] for l in linhas)
                    cat_total += sub_total
                    sub_nome = subcat_meta.get(sub_key, '') if sub_key != '__none__' else ''
                    if sub_nome:
                        has_subcats = True
                    sub_groups.append({
                        'subcategoria_id': sub_key if sub_key != '__none__' else None,
                        'subcategoria_nome': sub_nome,
                        'linhas': linhas,
                        'total': sub_total,
                    })

                tit_total += cat_total
                cat_groups.append({
                    'categoria_id': cat_id,
                    'categoria_nome': categoria_meta[cat_id],
                    'subcategoria_groups': sub_groups,
                    'has_subcats': has_subcats,
                    'total': cat_total,
                })

            emp_total += tit_total
            titulo_groups.append({
                'titulo_id': tit_id,
                'titulo_nome': titulo_meta[tit_id],
                'categoria_groups': cat_groups,
                'total': tit_total,
            })

        result_empresas.append({
            'empresa_id': emp_id,
            'empresa_nome': empresa_meta[emp_id],
            'titulo_groups': titulo_groups,
            'total': emp_total,
        })

    return result_empresas


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

    empresa_ids   = [e for e in args.getlist('empresa_ids[]')   if e]
    titulo_ids    = [t for t in args.getlist('titulo_ids[]')    if t]
    categoria_ids = [c for c in args.getlist('categoria_ids[]') if c]
    agrupar       = args.get('agrupar', 'empresa')  # 'empresa' | 'titulo' | 'flat'

    conn = get_db_connection()
    try:
        empresas   = _empresas_list(conn)
        titulos    = _titulos_list(conn)
        categorias = _categorias_list(conn)

        empresas_data = []
        grand_total   = 0.0
        total_lancamentos = 0

        if data_inicio and data_fim:
            lancamentos = _fetch_lancamentos(
                conn, data_inicio, data_fim,
                empresa_ids, titulo_ids, categoria_ids,
            )
            total_lancamentos = len(lancamentos)
            empresas_data = _build_report(lancamentos)
            grand_total = sum(e['total'] for e in empresas_data)
    finally:
        conn.close()

    # Per-titulo grand totals (for titulo-grouped view)
    titulo_totals = {}
    for emp in empresas_data:
        for tg in emp['titulo_groups']:
            titulo_totals[tg['titulo_id']] = (
                titulo_totals.get(tg['titulo_id'], 0.0) + tg['total']
            )

    return render_template(
        'relatorios/conf_despesas.html',
        empresas=empresas,
        titulos=titulos,
        categorias=categorias,
        empresas_data=empresas_data,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        titulo_ids=titulo_ids,
        categoria_ids=categoria_ids,
        agrupar=agrupar,
        grand_total=grand_total,
        total_lancamentos=total_lancamentos,
        titulo_totals=titulo_totals,
    )
