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

    Inclui:
      - lancamentos_caixa_receitas  (tipos normais de receita)
      - lancamentos_caixa_sobras_funcionarios  (sobras de caixa dos funcionários)
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f"AND lc.cliente_id IN ({ph_emp})" if ph_emp else ""
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    cur.execute(
        f"""SELECT data, tipo_nome, SUM(valor) AS valor
             FROM (
               -- Receitas normais
               SELECT lc.data,
                      COALESCE(tr.nome, lcr.tipo) AS tipo_nome,
                      lcr.valor
                 FROM lancamentos_caixa_receitas lcr
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcr.lancamento_caixa_id
                 LEFT  JOIN tipos_receita_caixa tr ON tr.nome = lcr.tipo
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
               UNION ALL
               -- Sobras de caixa por funcionário
               SELECT lc.data,
                      'SOBRAS DE CAIXA' AS tipo_nome,
                      s.valor
                 FROM lancamentos_caixa_sobras_funcionarios s
                 INNER JOIN lancamentos_caixa lc ON lc.id = s.lancamento_caixa_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
             ) sub
             GROUP BY data, tipo_nome
             ORDER BY tipo_nome, data""",
        params * 2,
    )
    rows = cur.fetchall()
    cur.close()
    return rows


# RETIRADA_PAGAMENTO descriptions treated as standalone rows (not collapsed under parent)
_FIXED_RETIRADA_CATEGORIES = (
    'DESCONTO CADASTROS',
    'DESCONTO GERAIS',
    'EMPRÉSTIMO FUNCIONÁRIOS',
    'RETIRADA ALUGUEL',
)


def _fetch_comprovacoes(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna linhas (data, forma_nome, parent_nome, valor) para comprovações.

    Estrutura hierárquica:
      • Cartões → parent "CARTÕES DÉBITO" / "CARTÕES CRÉDITO" + children por bandeira
      • _FIXED_RETIRADA_CATEGORIES → linhas autônomas (sem parent)
      • Outros itens RETIRADA_PAGAMENTO → parent "RETIRADAS PARA PAGAMENTO" + children
      • Demais formas de pagamento → linhas autônomas
      • Perdas e vales de funcionários → linhas autônomas
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f"AND lc.cliente_id IN ({ph_emp})" if ph_emp else ""
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    # Build SQL IN list for fixed categories (hardcoded strings, safe)
    fixed_in = ','.join(f"'{c}'" for c in _FIXED_RETIRADA_CATEGORIES)
    cur.execute(
        f"""SELECT data, forma_nome, parent_nome, SUM(valor) AS valor
             FROM (
               -- Formas de pagamento normais (não CARTAO, não RETIRADA_PAGAMENTO)
               SELECT lc.data,
                      COALESCE(fp.nome, bc.nome, 'OUTROS') AS forma_nome,
                      NULL AS parent_nome,
                      lcc.valor
                 FROM lancamentos_caixa_comprovacao lcc
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
                 LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
                 LEFT  JOIN bandeiras_cartao bc ON bc.id = lcc.bandeira_cartao_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
                   AND (fp.tipo IS NULL
                        OR fp.tipo NOT IN ('CARTAO','RETIRADA_PAGAMENTO'))

               UNION ALL
               -- Cartões: linha totalizadora pai (CARTÕES DÉBITO / CARTÕES CRÉDITO)
               SELECT lc.data,
                      CONCAT('CARTÕES ', COALESCE(bc.tipo,'')) AS forma_nome,
                      NULL AS parent_nome,
                      lcc.valor
                 FROM lancamentos_caixa_comprovacao lcc
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
                 LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
                 LEFT  JOIN bandeiras_cartao bc ON bc.id = lcc.bandeira_cartao_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
                   AND fp.tipo = 'CARTAO'

               UNION ALL
               -- Cartões: linhas filho por bandeira
               SELECT lc.data,
                      COALESCE(bc.nome,'Cartão s/ Bandeira') AS forma_nome,
                      CONCAT('CARTÕES ', COALESCE(bc.tipo,'')) AS parent_nome,
                      lcc.valor
                 FROM lancamentos_caixa_comprovacao lcc
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
                 LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
                 LEFT  JOIN bandeiras_cartao bc ON bc.id = lcc.bandeira_cartao_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
                   AND fp.tipo = 'CARTAO'

               UNION ALL
               -- Categorias fixas de RETIRADA_PAGAMENTO → linhas autônomas
               SELECT lc.data,
                      UPPER(TRIM(COALESCE(lcc.descricao,''))) AS forma_nome,
                      NULL AS parent_nome,
                      lcc.valor
                 FROM lancamentos_caixa_comprovacao lcc
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
                 LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
                   AND fp.tipo = 'RETIRADA_PAGAMENTO'
                   AND UPPER(TRIM(COALESCE(lcc.descricao,''))) IN ({fixed_in})

               UNION ALL
               -- Retiradas para Pagamento: linha pai totalizadora
               SELECT lc.data,
                      'RETIRADAS PARA PAGAMENTO' AS forma_nome,
                      NULL AS parent_nome,
                      lcc.valor
                 FROM lancamentos_caixa_comprovacao lcc
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
                 LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
                   AND fp.tipo = 'RETIRADA_PAGAMENTO'
                   AND UPPER(TRIM(COALESCE(lcc.descricao,''))) NOT IN ({fixed_in})

               UNION ALL
               -- Retiradas para Pagamento: linhas filho por descrição
               SELECT lc.data,
                      COALESCE(lcc.descricao,'Sem Descrição') AS forma_nome,
                      'RETIRADAS PARA PAGAMENTO' AS parent_nome,
                      lcc.valor
                 FROM lancamentos_caixa_comprovacao lcc
                 INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
                 LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
                   AND fp.tipo = 'RETIRADA_PAGAMENTO'
                   AND UPPER(TRIM(COALESCE(lcc.descricao,''))) NOT IN ({fixed_in})

               UNION ALL
               -- Perdas de caixa por funcionário
               SELECT lc.data,
                      'PERDAS DE CAIXA' AS forma_nome,
                      NULL AS parent_nome,
                      p.valor
                 FROM lancamentos_caixa_perdas_funcionarios p
                 INNER JOIN lancamentos_caixa lc ON lc.id = p.lancamento_caixa_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}

               UNION ALL
               -- Vales / quebras de caixa por funcionário
               SELECT lc.data,
                      'VALES FUNCIONÁRIOS' AS forma_nome,
                      NULL AS parent_nome,
                      v.valor
                 FROM lancamentos_caixa_vales_funcionarios v
                 INNER JOIN lancamentos_caixa lc ON lc.id = v.lancamento_caixa_id
                 WHERE lc.data BETWEEN %s AND %s
                   AND lc.status = 'FECHADO'
                   {emp_cond}
             ) sub
             GROUP BY data, forma_nome, parent_nome
             ORDER BY COALESCE(parent_nome, forma_nome), parent_nome IS NULL DESC,
                      forma_nome, data""",
        params * 8,
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


# Canonical sort order for receita categories.
_RECEITAS_ORDER = {
    'VENDAS POSTO':          '01',
    'ARLA':                  '02',
    'LUBRIFICANTES':         '03',
    'ANTECIPAÇÃO CLIENTE':   '03a',
    'RECEBIMENTOS':          '04',
    'ACRÉSCIMOS CADASTROS':  '05',
    'ACRÉSCIMOS GERAIS':     '06',
    'TROCO PIX':             '07',
    'TROCO PIX (AUTO)':      '08',
    'EMPRESTIMOS':           '09',
    'EMPRÉSTIMOS':           '09',
    'OUTROS':                '10',
    'SOBRAS DE CAIXA':       '11',
}


def _receitas_sort_key(nome):
    return _RECEITAS_ORDER.get(nome, '50_' + nome)


# Custom sort order for known comprovação categories.
# Lower number → appears earlier in the table.
_COMPROV_ORDER = {
    'PRAZO':                         '01',
    'DEPOSITO EM ESPECIE':           '02',
    'DEPÓSITO EM ESPÉCIE':           '02',
    'DEPOSITO EM CHEQUE A VISTA':    '03',
    'DEPÓSITO EM CHEQUE À VISTA':    '03',
    # Cheque à prazo — singular and plural, accented and unaccented
    'DEPOSITO EM CHEQUE A PRAZO':    '04',
    'DEPÓSITO EM CHEQUE À PRAZO':    '04',
    'DEPOSITOS EM CHEQUE A PRAZO':   '04',
    'DEPÓSITOS EM CHEQUE A PRAZO':   '04',
    'RECEBIMENTO VIA PIX':           '05',
    # Cartões — CONCAT('CARTÕES ', bc.tipo) produces 'CARTÕES CREDITO'/'CARTÕES DEBITO'
    'CARTÕES CREDITO':               '06',
    'CARTÕES CRÉDITO':               '06',
    'CARTÕES DEBITO':                '07',
    'CARTÕES DÉBITO':                '07',
    'DESCONTO CADASTROS':            '08',
    'DESCONTOS CADASTROS':           '08',
    'DESCONTO GERAIS':               '09',
    'DESCONTOS GERAIS':              '09',
    'VALES FUNCIONÁRIOS':            '10',
    'RETIRADA ALUGUEL':              '11',
    'EMPRÉSTIMO FUNCIONÁRIOS':       '12',
    'EMPRESTIMOS FUNCIONÁRIOS':      '12',
    'EMPRÉSTIMOS FUNCIONÁRIOS':      '12',
    'PERDAS DE CAIXA':               '13',
    'VENDA PROGRAMADA':              '13a',
    'RETIRADAS PARA PAGAMENTO':      '14',
}


def _comprov_sort_key(nome):
    """Return a sort key so known rows appear in canonical order."""
    return _COMPROV_ORDER.get(nome, '30_' + nome)


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
    for nome in sorted(rec_map.keys(), key=_receitas_sort_key):
        by_col = rec_map[nome]
        receitas_block.append({'nome': nome, 'by_col': by_col, 'total': sum(by_col.values())})

    # --- COMPROVAÇÕES with parent/child hierarchy ---
    # comprovacoes_rows have: data, forma_nome, parent_nome (None|str), valor
    row_data   = {}   # (forma_nome, parent_nome) → {col_key → float}
    children_of = {}  # parent_nome → set of child forma_nomes

    for r in comprovacoes_rows:
        nome   = r['forma_nome']
        parent = r.get('parent_nome')   # None means this row is a parent or normal row
        ck     = col_key_fn(r['data'])
        val    = float(r['valor'] or 0)
        key    = (nome, parent)
        if key not in row_data:
            row_data[key] = {}
        row_data[key][ck] = row_data[key].get(ck, 0.0) + val
        if parent:
            if parent not in children_of:
                children_of[parent] = set()
            children_of[parent].add(nome)

    # Separate top-level rows (parent_nome is None) and build comprov_block
    top_rows = [(nome, by_col)
                for (nome, parent), by_col in row_data.items()
                if parent is None]
    top_rows.sort(key=lambda t: _comprov_sort_key(t[0]))

    comprov_block = []
    grp_counter   = 0
    for nome, by_col in top_rows:
        total    = sum(by_col.values())
        is_parent = nome in children_of
        if is_parent:
            grp_counter += 1
            gid = f'grp{grp_counter}'
        else:
            gid = None
        comprov_block.append({
            'nome':       nome,
            'by_col':     by_col,
            'total':      total,
            'row_type':   'parent' if is_parent else 'normal',
            'group_id':   gid,
            'parent_nome': None,
        })
        if is_parent:
            child_nomes = sorted(children_of[nome])
            for cname in child_nomes:
                child_by_col = row_data.get((cname, nome), {})
                comprov_block.append({
                    'nome':        cname,
                    'by_col':      child_by_col,
                    'total':       sum(child_by_col.values()),
                    'row_type':    'child',
                    'group_id':    gid,
                    'parent_nome': nome,
                })

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
