"""
Relatório de Conferência de Fechamento de Caixa.

Cruza os lançamentos diários do fechamento de caixa (lancamentos_caixa,
lancamentos_caixa_receitas, lancamentos_caixa_comprovacao) e os apresenta
em dois formatos:

  conf_fechamento_mensal  – colunas = dias do mês selecionado
  conf_fechamento_anual   – colunas = meses do ano selecionado  (idêntico ao
                             layout do conf_despesas)

Rotas:
  GET /relatorios/conf_fechamento_mensal   – relatório mensal
  GET /relatorios/conf_fechamento_anual    – relatório anual
"""
from calendar import monthrange
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

_MONTHS_PT = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
              'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

bp = Blueprint('conf_fechamento', __name__, url_prefix='/relatorios')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _empresas_list(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT DISTINCT c.id, COALESCE(c.nome_fantasia, c.razao_social) AS nome
             FROM clientes c
             INNER JOIN lancamentos_caixa lc ON lc.cliente_id = c.id
            ORDER BY nome"""
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _default_month():
    """Retorna (ano, mes) do mês atual."""
    hoje = date.today()
    return hoje.year, hoje.month


def _default_year():
    return date.today().year


def _days_in_month(year, month):
    """Lista de dicts {'key': 'YYYYMMDD', 'label': 'DD', 'date': date} para o mês."""
    _, last = monthrange(year, month)
    days = []
    for d in range(1, last + 1):
        dt = date(year, month, d)
        days.append({'key': dt.isoformat(), 'label': str(d).zfill(2), 'date': dt})
    return days


def _months_in_year(year):
    """Lista de dicts {'key': 'YYYYMM', 'label': 'Jan'} para o ano."""
    months = []
    for m in range(1, 13):
        months.append({
            'key':   f'{year}{m:02d}',
            'label': _MONTHS_PT[m - 1],
        })
    return months


def _fetch_receitas(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna SUM(valor) agrupado por (tipo_nome, data) para receitas.
    Usa tipos_receita_caixa.nome quando disponível; caso contrário o campo
    tipo bruto de lancamentos_caixa_receitas.
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f"AND lc.cliente_id IN ({ph_emp})" if ph_emp else ""
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    cur.execute(
        f"""SELECT
               lc.data,
               COALESCE(tr.nome, lcr.tipo) AS tipo_nome,
               COALESCE(tr.id, 0)          AS tipo_id,
               SUM(lcr.valor)              AS valor
             FROM lancamentos_caixa_receitas lcr
             INNER JOIN lancamentos_caixa lc ON lc.id = lcr.lancamento_caixa_id
             LEFT  JOIN tipos_receita_caixa tr ON tr.nome = lcr.tipo OR tr.tipo = lcr.tipo
             WHERE lc.data BETWEEN %s AND %s
               AND lc.status = 'FECHADO'
               {emp_cond}
             GROUP BY lc.data, tipo_nome, tipo_id
             ORDER BY tipo_id, tipo_nome, lc.data""",
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetch_comprovacoes(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna SUM(valor) agrupado por (forma_nome, data) para comprovações.
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f"AND lc.cliente_id IN ({ph_emp})" if ph_emp else ""
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    cur.execute(
        f"""SELECT
               lc.data,
               COALESCE(fp.nome, bc.nome, 'OUTROS') AS forma_nome,
               COALESCE(fp.id, 0)                   AS forma_id,
               COALESCE(bc.id, 0)                   AS bandeira_id,
               SUM(lcc.valor)                        AS valor
             FROM lancamentos_caixa_comprovacao lcc
             INNER JOIN lancamentos_caixa lc      ON lc.id = lcc.lancamento_caixa_id
             LEFT  JOIN formas_pagamento_caixa fp  ON fp.id = lcc.forma_pagamento_id
             LEFT  JOIN bandeiras_cartao bc        ON bc.id = lcc.bandeira_cartao_id
             WHERE lc.data BETWEEN %s AND %s
               AND lc.status = 'FECHADO'
               {emp_cond}
             GROUP BY lc.data, forma_nome, forma_id, bandeira_id
             ORDER BY forma_id, bandeira_id, forma_nome, lc.data""",
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetch_totais(conn, data_inicio, data_fim, empresa_ids):
    """Totais de receitas, comprovações e diferença por data."""
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f"AND lc.cliente_id IN ({ph_emp})" if ph_emp else ""
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    cur.execute(
        f"""SELECT lc.data,
                   SUM(lc.total_receitas)    AS total_receitas,
                   SUM(lc.total_comprovacao) AS total_comprovacao,
                   SUM(lc.diferenca)         AS diferenca
             FROM lancamentos_caixa lc
             WHERE lc.data BETWEEN %s AND %s
               AND lc.status = 'FECHADO'
               {emp_cond}
             GROUP BY lc.data
             ORDER BY lc.data""",
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_matrix(receitas_rows, comprovacoes_rows, totais_rows, col_key_fn):
    """
    Constrói a matrix do relatório.

    col_key_fn(date) → string key usada para identificar a coluna
      (ex: data.isoformat() para mensal, f'{data.year}{data.month:02d}' para anual).

    Retorna:
      - receitas_block:      list of {nome, by_col, total}
      - comprov_block:       list of {nome, by_col, total}
      - total_receitas_col:  dict col_key→float
      - total_comprov_col:   dict col_key→float
      - diferenca_col:       dict col_key→float
      - grand_receitas:      float
      - grand_comprov:       float
      - grand_diferenca:     float
    """
    # --- RECEITAS ---
    rec_map = {}   # tipo_nome → {col_key → float}
    for r in receitas_rows:
        nome = r['tipo_nome']
        ck   = col_key_fn(r['data'])
        val  = float(r['valor'] or 0)
        if nome not in rec_map:
            rec_map[nome] = {}
        rec_map[nome][ck] = rec_map[nome].get(ck, 0.0) + val

    receitas_block = []
    for nome in sorted(rec_map.keys()):
        by_col = rec_map[nome]
        receitas_block.append({'nome': nome, 'by_col': by_col, 'total': sum(by_col.values())})

    # --- COMPROVAÇÕES ---
    comp_map = {}  # forma_nome → {col_key → float}
    for r in comprovacoes_rows:
        nome = r['forma_nome']
        ck   = col_key_fn(r['data'])
        val  = float(r['valor'] or 0)
        if nome not in comp_map:
            comp_map[nome] = {}
        comp_map[nome][ck] = comp_map[nome].get(ck, 0.0) + val

    comprov_block = []
    for nome in sorted(comp_map.keys()):
        by_col = comp_map[nome]
        comprov_block.append({'nome': nome, 'by_col': by_col, 'total': sum(by_col.values())})

    # --- TOTAIS por coluna ---
    total_receitas_col = {}
    total_comprov_col  = {}
    diferenca_col      = {}
    for r in totais_rows:
        ck  = col_key_fn(r['data'])
        total_receitas_col[ck] = total_receitas_col.get(ck, 0.0) + float(r['total_receitas'] or 0)
        total_comprov_col[ck]  = total_comprov_col.get(ck, 0.0)  + float(r['total_comprovacao'] or 0)
        diferenca_col[ck]      = diferenca_col.get(ck, 0.0)      + float(r['diferenca'] or 0)

    grand_receitas  = sum(total_receitas_col.values())
    grand_comprov   = sum(total_comprov_col.values())
    grand_diferenca = sum(diferenca_col.values())

    return (receitas_block, comprov_block,
            total_receitas_col, total_comprov_col, diferenca_col,
            grand_receitas, grand_comprov, grand_diferenca)


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_fechamento_mensal')
@login_required
@admin_required
def conf_fechamento_mensal():
    """Conferência mensal de fechamento de caixa — colunas = dias."""
    args = request.args

    # Filtros
    ano_default, mes_default = _default_month()
    try:
        ano = int(args.get('ano', ano_default))
    except (ValueError, TypeError):
        ano = ano_default
    try:
        mes = int(args.get('mes', mes_default))
        if not 1 <= mes <= 12:
            mes = mes_default
    except (ValueError, TypeError):
        mes = mes_default

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]

    _, last_day = monthrange(ano, mes)
    data_inicio = date(ano, mes, 1).isoformat()
    data_fim    = date(ano, mes, last_day).isoformat()

    conn = get_db_connection()
    try:
        empresas = _empresas_list(conn)
        days     = _days_in_month(ano, mes)

        receitas_block = []
        comprov_block  = []
        total_receitas_col = {}
        total_comprov_col  = {}
        diferenca_col      = {}
        grand_receitas = grand_comprov = grand_diferenca = 0.0

        receitas_rows    = _fetch_receitas(conn, data_inicio, data_fim, empresa_ids)
        comprovacoes_rows = _fetch_comprovacoes(conn, data_inicio, data_fim, empresa_ids)
        totais_rows       = _fetch_totais(conn, data_inicio, data_fim, empresa_ids)

        def day_key(d):
            return d.isoformat() if isinstance(d, date) else str(d)

        (receitas_block, comprov_block,
         total_receitas_col, total_comprov_col, diferenca_col,
         grand_receitas, grand_comprov, grand_diferenca) = _build_matrix(
            receitas_rows, comprovacoes_rows, totais_rows, day_key
        )
    finally:
        conn.close()

    anos_list = list(range(date.today().year - 3, date.today().year + 1))
    meses_list = [(i, _MONTHS_PT[i - 1]) for i in range(1, 13)]
    _MESES_NOME = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                   'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

    return render_template(
        'relatorios/conf_fechamento_mensal.html',
        empresas=empresas,
        empresa_ids_filter=empresa_ids,
        ano=ano,
        mes=mes,
        mes_nome=_MESES_NOME[mes - 1],
        days=days,
        receitas_block=receitas_block,
        comprov_block=comprov_block,
        total_receitas_col=total_receitas_col,
        total_comprov_col=total_comprov_col,
        diferenca_col=diferenca_col,
        grand_receitas=grand_receitas,
        grand_comprov=grand_comprov,
        grand_diferenca=grand_diferenca,
        anos_list=anos_list,
        meses_list=meses_list,
    )


@bp.route('/conf_fechamento_anual')
@login_required
@admin_required
def conf_fechamento_anual():
    """Conferência anual de fechamento de caixa — colunas = meses."""
    args = request.args

    ano_default = _default_year()
    try:
        ano = int(args.get('ano', ano_default))
    except (ValueError, TypeError):
        ano = ano_default

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]

    data_inicio = date(ano, 1, 1).isoformat()
    data_fim    = date(ano, 12, 31).isoformat()

    conn = get_db_connection()
    try:
        empresas = _empresas_list(conn)
        months   = _months_in_year(ano)

        receitas_rows     = _fetch_receitas(conn, data_inicio, data_fim, empresa_ids)
        comprovacoes_rows = _fetch_comprovacoes(conn, data_inicio, data_fim, empresa_ids)
        totais_rows       = _fetch_totais(conn, data_inicio, data_fim, empresa_ids)

        def month_key(d):
            if isinstance(d, date):
                return f'{d.year}{d.month:02d}'
            # fallback for string date
            try:
                dt = datetime.strptime(str(d), '%Y-%m-%d').date()
                return f'{dt.year}{dt.month:02d}'
            except Exception:
                return str(d)[:7].replace('-', '')

        (receitas_block, comprov_block,
         total_receitas_col, total_comprov_col, diferenca_col,
         grand_receitas, grand_comprov, grand_diferenca) = _build_matrix(
            receitas_rows, comprovacoes_rows, totais_rows, month_key
        )
    finally:
        conn.close()

    anos_list = list(range(date.today().year - 3, date.today().year + 1))

    return render_template(
        'relatorios/conf_fechamento_anual.html',
        empresas=empresas,
        empresa_ids_filter=empresa_ids,
        ano=ano,
        months=months,
        receitas_block=receitas_block,
        comprov_block=comprov_block,
        total_receitas_col=total_receitas_col,
        total_comprov_col=total_comprov_col,
        diferenca_col=diferenca_col,
        grand_receitas=grand_receitas,
        grand_comprov=grand_comprov,
        grand_diferenca=grand_diferenca,
        anos_list=anos_list,
    )
