from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime, date

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')


def _parse_date_safe(s):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return None


def _build_filters(params):
    """
    Construir WHERE dinâmico e lista de parâmetros (para usar em cursor.execute).
    Retorna (where_sql, args_list).
    """
    where = []
    args = []

    di = params.get('data_inicio')
    df = params.get('data_fim')
    if di and df:
        dstart = _parse_date_safe(di)
        dend = _parse_date_safe(df)
        if dstart and dend:
            where.append("f.data_frete BETWEEN %s AND %s")
            args.extend([dstart, dend])

    cliente_id = params.get('cliente_id')
    if cliente_id:
        where.append("f.clientes_id = %s")
        args.append(cliente_id)

    motorista_id = params.get('motorista_id')
    if motorista_id:
        where.append("f.motoristas_id = %s")
        args.append(motorista_id)

    produto_id = params.get('produto_id')
    if produto_id:
        where.append("f.produto_id = %s")
        args.append(produto_id)

    fornecedor_id = params.get('fornecedor_id')
    if fornecedor_id:
        where.append("f.fornecedores_id = %s")
        args.append(fornecedor_id)

    where_sql = (" AND " + " AND ".join(where)) if where else ""
    return where_sql, args


def _load_select_list(table_name):
    """
    Carrega lista para selects usados nos filtros.
    table_name: 'clientes' | 'motoristas' | 'produto' | 'fornecedores'
    Retorna lista de dicts (cada dict depende do select).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if table_name == 'clientes':
            cursor.execute("SELECT id, razao_social, nome_fantasia FROM clientes ORDER BY razao_social")
            return cursor.fetchall()
        if table_name == 'motoristas':
            cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
            return cursor.fetchall()
        if table_name == 'produto':
            cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
            return cursor.fetchall()
        if table_name == 'fornecedores':
            cursor.execute("SELECT id, razao_social, nome_fantasia FROM fornecedores ORDER BY razao_social")
            return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return []


@bp.route('/', methods=['GET'])
@login_required
def index():
    # Redireciona para um relatório padrão (Comissão CTE)
    return redirect(url_for('relatorios.fretes_comissao_cte'))


@bp.route('/fretes_comissao_cte', methods=['GET'])
@login_required
def fretes_comissao_cte():
    params = request.args
    where_sql, args = _build_filters(params)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Totais
        q_totals = f"""
            SELECT
              COALESCE(SUM(f.valor_cte), 0) AS total_valor_cte,
              COALESCE(SUM(f.comissao_cte), 0) AS total_comissao_cte,
              COALESCE(SUM(f.valor_total_frete), 0) AS total_valor_frete
            FROM fretes f
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_valor_cte = totals.get('total_valor_cte', 0)
        total_comissao_cte = totals.get('total_comissao_cte', 0)
        total_valor_frete = totals.get('total_valor_frete', 0)

        # Resumo por cliente
        q_resumo = f"""
            SELECT
              c.id AS cliente_id,
              COALESCE(c.nome_fantasia, c.razao_social) AS cliente_nome,
              COUNT(f.id) AS qtd_fretes,
              COALESCE(SUM(f.valor_cte),0) AS valor_cte_total,
              COALESCE(SUM(f.comissao_cte),0) AS comissao_total
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            WHERE 1=1 {where_sql}
            GROUP BY c.id
            ORDER BY valor_cte_total DESC
        """
        cursor.execute(q_resumo, args)
        resumo_clientes = cursor.fetchall()

        # Detalhe de fretes
        q_det = f"""
            SELECT f.data_frete, COALESCE(c.razao_social,'') AS cliente_nome,
                   COALESCE(p.nome,'') AS produto_nome,
                   COALESCE(m.nome,'') AS motorista_nome,
                   f.valor_cte, f.comissao_cte, f.valor_total_frete
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            WHERE 1=1 {where_sql}
            ORDER BY f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'relatorios/fretes_comissao_cte.html',
        data_inicio=params.get('data_inicio'),
        data_fim=params.get('data_fim'),
        cliente_id=int(params.get('cliente_id')) if params.get('cliente_id') else None,
        motorista_id=int(params.get('motorista_id')) if params.get('motorista_id') else None,
        produto_id=int(params.get('produto_id')) if params.get('produto_id') else None,
        clientes=_load_select_list('clientes'),
        motoristas=_load_select_list('motoristas'),
        produtos=_load_select_list('produto'),
        total_valor_cte=total_valor_cte,
        total_comissao_cte=total_comissao_cte,
        total_valor_frete=total_valor_frete,
        resumo_clientes=resumo_clientes,
        fretes=fretes
    )


@bp.route('/fretes_comissao_motorista', methods=['GET'])
@login_required
def fretes_comissao_motorista():
    params = request.args
    where_sql, args = _build_filters(params)

    # Para lidar com quantidades: usar COALESCE(f.quantidade_manual, q.valor)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q_totals = f"""
            SELECT
              COALESCE(SUM(f.comissao_motorista),0) AS total_comissao_motorista,
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS total_quantidade,
              COALESCE(SUM(f.valor_total_frete),0) AS total_valor_frete
            FROM fretes f
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_comissao_motorista = totals.get('total_comissao_motorista', 0)
        total_quantidade = totals.get('total_quantidade', 0)
        total_valor_frete = totals.get('total_valor_frete', 0)

        q_resumo = f"""
            SELECT
              m.id AS motorista_id,
              m.nome AS motorista_nome,
              COUNT(f.id) AS qtd_fretes,
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS quantidade_total,
              COALESCE(SUM(f.comissao_motorista),0) AS comissao_total
            FROM fretes f
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            GROUP BY m.id
            ORDER BY comissao_total DESC
        """
        cursor.execute(q_resumo, args)
        resumo_motoristas = cursor.fetchall()

        q_det = f"""
            SELECT f.data_frete,
                   COALESCE(c.razao_social,'') AS cliente_nome,
                   COALESCE(p.nome,'') AS produto_nome,
                   COALESCE(m.nome,'') AS motorista_nome,
                   COALESCE(f.quantidade_manual, q.valor, 0) AS quantidade,
                   f.valor_total_frete, f.comissao_motorista
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            ORDER BY f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'relatorios/fretes_comissao_motorista.html',
        data_inicio=params.get('data_inicio'),
        data_fim=params.get('data_fim'),
        cliente_id=int(params.get('cliente_id')) if params.get('cliente_id') else None,
        motorista_id=int(params.get('motorista_id')) if params.get('motorista_id') else None,
        produto_id=int(params.get('produto_id')) if params.get('produto_id') else None,
        clientes=_load_select_list('clientes'),
        motoristas=_load_select_list('motoristas'),
        produtos=_load_select_list('produto'),
        total_comissao_motorista=total_comissao_motorista,
        total_quantidade=total_quantidade,
        total_valor_frete=total_valor_frete,
        resumo_motoristas=resumo_motoristas,
        fretes=fretes
    )


@bp.route('/fretes_lucro', methods=['GET'])
@login_required
def fretes_lucro():
I'll produce the updated fretes_produtos function modified to use data defaults from request and include resumo_por_produto_geral. Need to finish file snippet. Provide only modified portion or full file? User likely wants modification inserted. Previously asked not to touch relatorios.py but now gave it; they want code changes. Provide full updated routes/relatorios.py file including data defaults and resumo_por_produto_geral. Must ensure imports include date; already earlier included. Continue from where left off. Provide complete file. We must ensure no syntax errors. Compose full file (we already had earlier constructed). Let's produce final file with fretes_produtos modified:

At top of fretes_produtos: params = request.args; compute hoje = date.today(); primeiro_dia = hoje.replace(day=1); data_inicio = params.get('data_inicio') or primeiro_dia.strftime...; data_fim = params.get('data_fim') or hoje.strftime(...); then create params2 = dict(params); params2['data_inicio']=data_inicio; params2['data_fim']=data_fim; where_sql,args=_build_filters(params2);

Later when building resumo_por_produto conditioned on cliente_id provided, keep same.

Also compute resumo_por_produto_geral if not cliente_id: run query grouping by produto.

Finally return render_template including data_inicio,data_fim,resumo_por_produto_geral.

Okay produce full file.
```python name=routes/relatorios.py url=https://github.com/qualicontaxanderson-hub/nh-transportes/blob/main/routes/relatorios.py
from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime, date

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')


def _parse_date_safe(s):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return None


def _build_filters(params):
    """
    Construir WHERE dinâmico e lista de parâmetros (para usar em cursor.execute).
    Retorna (where_sql, args_list).
    """
    where = []
    args = []

    di = params.get('data_inicio')
    df = params.get('data_fim')
    if di and df:
        dstart = _parse_date_safe(di)
        dend = _parse_date_safe(df)
        if dstart and dend:
            where.append("f.data_frete BETWEEN %s AND %s")
            args.extend([dstart, dend])

    cliente_id = params.get('cliente_id')
    if cliente_id:
        where.append("f.clientes_id = %s")
        args.append(cliente_id)

    motorista_id = params.get('motorista_id')
    if motorista_id:
        where.append("f.motoristas_id = %s")
        args.append(motorista_id)

    produto_id = params.get('produto_id')
    if produto_id:
        where.append("f.produto_id = %s")
        args.append(produto_id)

    fornecedor_id = params.get('fornecedor_id')
    if fornecedor_id:
        where.append("f.fornecedores_id = %s")
        args.append(fornecedor_id)

    where_sql = (" AND " + " AND ".join(where)) if where else ""
    return where_sql, args


def _load_select_list(table_name):
    """
    Carrega lista para selects usados nos filtros.
    table_name: 'clientes' | 'motoristas' | 'produto' | 'fornecedores'
    Retorna lista de dicts (cada dict depende do select).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if table_name == 'clientes':
            cursor.execute("SELECT id, razao_social, nome_fantasia FROM clientes ORDER BY razao_social")
            return cursor.fetchall()
        if table_name == 'motoristas':
            cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
            return cursor.fetchall()
        if table_name == 'produto':
            cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
            return cursor.fetchall()
        if table_name == 'fornecedores':
            cursor.execute("SELECT id, razao_social, nome_fantasia FROM fornecedores ORDER BY razao_social")
            return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return []


@bp.route('/', methods=['GET'])
@login_required
def index():
    # Redireciona para um relatório padrão (Comissão CTE)
    return redirect(url_for('relatorios.fretes_comissao_cte'))


@bp.route('/fretes_comissao_cte', methods=['GET'])
@login_required
def fretes_comissao_cte():
    params = request.args
    where_sql, args = _build_filters(params)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Totais
        q_totals = f"""
            SELECT
              COALESCE(SUM(f.valor_cte), 0) AS total_valor_cte,
              COALESCE(SUM(f.comissao_cte), 0) AS total_comissao_cte,
              COALESCE(SUM(f.valor_total_frete), 0) AS total_valor_frete
            FROM fretes f
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_valor_cte = totals.get('total_valor_cte', 0)
        total_comissao_cte = totals.get('total_comissao_cte', 0)
        total_valor_frete = totals.get('total_valor_frete', 0)

        # Resumo por cliente
        q_resumo = f"""
            SELECT
              c.id AS cliente_id,
              COALESCE(c.nome_fantasia, c.razao_social) AS cliente_nome,
              COUNT(f.id) AS qtd_fretes,
              COALESCE(SUM(f.valor_cte),0) AS valor_cte_total,
              COALESCE(SUM(f.comissao_cte),0) AS comissao_total
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            WHERE 1=1 {where_sql}
            GROUP BY c.id
            ORDER BY valor_cte_total DESC
        """
        cursor.execute(q_resumo, args)
        resumo_clientes = cursor.fetchall()

        # Detalhe de fretes
        q_det = f"""
            SELECT f.data_frete, COALESCE(c.razao_social,'') AS cliente_nome,
                   COALESCE(p.nome,'') AS produto_nome,
                   COALESCE(m.nome,'') AS motorista_nome,
                   f.valor_cte, f.comissao_cte, f.valor_total_frete
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            WHERE 1=1 {where_sql}
            ORDER BY f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'relatorios/fretes_comissao_cte.html',
        data_inicio=params.get('data_inicio'),
        data_fim=params.get('data_fim'),
        cliente_id=int(params.get('cliente_id')) if params.get('cliente_id') else None,
        motorista_id=int(params.get('motorista_id')) if params.get('motorista_id') else None,
        produto_id=int(params.get('produto_id')) if params.get('produto_id') else None,
        clientes=_load_select_list('clientes'),
        motoristas=_load_select_list('motoristas'),
        produtos=_load_select_list('produto'),
        total_valor_cte=total_valor_cte,
        total_comissao_cte=total_comissao_cte,
        total_valor_frete=total_valor_frete,
        resumo_clientes=resumo_clientes,
        fretes=fretes
    )


@bp.route('/fretes_comissao_motorista', methods=['GET'])
@login_required
def fretes_comissao_motorista():
    params = request.args
    where_sql, args = _build_filters(params)

    # Para lidar com quantidades: usar COALESCE(f.quantidade_manual, q.valor)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q_totals = f"""
            SELECT
              COALESCE(SUM(f.comissao_motorista),0) AS total_comissao_motorista,
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS total_quantidade,
              COALESCE(SUM(f.valor_total_frete),0) AS total_valor_frete
            FROM fretes f
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_comissao_motorista = totals.get('total_comissao_motorista', 0)
        total_quantidade = totals.get('total_quantidade', 0)
        total_valor_frete = totals.get('total_valor_frete', 0)

        q_resumo = f"""
            SELECT
              m.id AS motorista_id,
              m.nome AS motorista_nome,
              COUNT(f.id) AS qtd_fretes,
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS quantidade_total,
              COALESCE(SUM(f.comissao_motorista),0) AS comissao_total
            FROM fretes f
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            GROUP BY m.id
            ORDER BY comissao_total DESC
        """
        cursor.execute(q_resumo, args)
        resumo_motoristas = cursor.fetchall()

        q_det = f"""
            SELECT f.data_frete,
                   COALESCE(c.razao_social,'') AS cliente_nome,
                   COALESCE(p.nome,'') AS produto_nome,
                   COALESCE(m.nome,'') AS motorista_nome,
                   COALESCE(f.quantidade_manual, q.valor, 0) AS quantidade,
                   f.valor_total_frete, f.comissao_motorista
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            ORDER BY f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'relatorios/fretes_comissao_motorista.html',
        data_inicio=params.get('data_inicio'),
        data_fim=params.get('data_fim'),
        cliente_id=int(params.get('cliente_id')) if params.get('cliente_id') else None,
        motorista_id=int(params.get('motorista_id')) if params.get('motorista_id') else None,
        produto_id=int(params.get('produto_id')) if params.get('produto_id') else None,
        clientes=_load_select_list('clientes'),
        motoristas=_load_select_list('motoristas'),
        produtos=_load_select_list('produto'),
        total_comissao_motorista=total_comissao_motorista,
        total_quantidade=total_quantidade,
        total_valor_frete=total_valor_frete,
        resumo_motoristas=resumo_motoristas,
        fretes=fretes
    )


@bp.route('/fretes_lucro', methods=['GET'])
@login_required
def fretes_lucro():
    params = request.args
    where_sql, args = _build_filters(params)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q_totals = f"""
            SELECT
              COALESCE(SUM(f.valor_total_frete),0) AS total_valor_frete,
              COALESCE(SUM(f.comissao_cte),0) AS total_comissao_cte,
              COALESCE(SUM(f.comissao_motorista),0) AS total_comissao_motorista,
              COALESCE(SUM(f.lucro),0) AS total_lucro
            FROM fretes f
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_valor_frete = totals.get('total_valor_frete', 0)
        total_comissao_cte = totals.get('total_comissao_cte', 0)
        total_comissao_motorista = totals.get('total_comissao_motorista', 0)
        total_lucro = totals.get('total_lucro', 0)

        q_det = f"""
            SELECT f.data_frete,
                   COALESCE(c.razao_social,'') AS cliente_nome,
                   COALESCE(p.nome,'') AS produto_nome,
                   COALESCE(m.nome,'') AS motorista_nome,
                   COALESCE(f.quantidade_manual, q.valor, 0) AS quantidade,
                   f.valor_total_frete, f.comissao_cte, f.comissao_motorista, f.lucro
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            ORDER BY f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'relatorios/fretes_lucro.html',
        data_inicio=params.get('data_inicio'),
        data_fim=params.get('data_fim'),
        cliente_id=int(params.get('cliente_id')) if params.get('cliente_id') else None,
        motorista_id=int(params.get('motorista_id')) if params.get('motorista_id') else None,
        produto_id=int(params.get('produto_id')) if params.get('produto_id') else None,
        clientes=_load_select_list('clientes'),
        motoristas=_load_select_list('motoristas'),
        produtos=_load_select_list('produto'),
        total_valor_frete=total_valor_frete,
        total_comissao_cte=total_comissao_cte,
        total_comissao_motorista=total_comissao_motorista,
        total_lucro=total_lucro,
        fretes=fretes
    )


@bp.route('/fretes_produtos', methods=['GET'])
@login_required
def fretes_produtos():
    # Defaults: se data_inicio/data_fim não vierem no request, usar primeiro dia do mês até hoje
    hoje = date.today()
    primeiro_dia = hoje.replace(day=1)
    data_inicio_default = primeiro_dia.strftime('%Y-%m-%d')
    data_fim_default = hoje.strftime('%Y-%m-%d')

    # criar params com defaults para construir filtros corretamente
    params = dict(request.args)
    if not params.get('data_inicio'):
        params['data_inicio'] = data_inicio_default
    if not params.get('data_fim'):
        params['data_fim'] = data_fim_default

    where_sql, args = _build_filters(params)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q_totals = f"""
            SELECT
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS total_quantidade,
              COALESCE(SUM(f.total_nf_compra),0) AS total_nf,
              COUNT(DISTINCT f.produto_id) AS qtd_produtos_diferentes
            FROM fretes f
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_quantidade = totals.get('total_quantidade', 0)
        total_nf = totals.get('total_nf', 0)
        qtd_produtos_diferentes = totals.get('qtd_produtos_diferentes', 0)

        q_det = f"""
            SELECT f.data_frete, COALESCE(c.razao_social,'') AS cliente_nome,
                   COALESCE(fo.razao_social,'') AS fornecedor_nome,
                   COALESCE(p.nome,'') AS produto_nome,
                   COALESCE(f.quantidade_manual, q.valor, 0) AS quantidade,
                   f.preco_produto_unitario, f.total_nf_compra
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            ORDER BY f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()

        resumo_por_produto = []
        resumo_por_produto_geral = []
        cliente_id = request.args.get('cliente_id')
        if cliente_id:
            q_resumo = f"""
                SELECT p.id AS produto_id, p.nome AS produto_nome,
                       COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS quantidade_total,
                       COALESCE(SUM(f.total_nf_compra),0) AS valor_nf_total
                FROM fretes f
                LEFT JOIN produto p ON f.produto_id = p.id
                LEFT JOIN quantidades q ON f.quantidade_id = q.id
                WHERE f.clientes_id = %s
                {('AND f.data_frete BETWEEN %s AND %s' if params.get('data_inicio') and params.get('data_fim') else '')}
                GROUP BY p.id
                ORDER BY quantidade_total DESC
            """
            resumo_args = [cliente_id]
            if params.get('data_inicio') and params.get('data_fim'):
                di = _parse_date_safe(params.get('data_inicio'))
                df = _parse_date_safe(params.get('data_fim'))
                if di and df:
                    resumo_args.extend([di, df])
            cursor.execute(q_resumo, resumo_args)
            resumo_por_produto = cursor.fetchall()
        else:
            # quando não há cliente selecionado, construir um resumo geral por produto
            q_geral = f"""
                SELECT p.id AS produto_id, p.nome AS produto_nome,
                       COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS quantidade_total
                FROM fretes f
                LEFT JOIN produto p ON f.produto_id = p.id
                LEFT JOIN quantidades q ON f.quantidade_id = q.id
                WHERE 1=1 {where_sql}
                GROUP BY p.id
                ORDER BY quantidade_total DESC
                LIMIT 200
            """
            cursor.execute(q_geral, args)
            resumo_por_produto_geral = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'relatorios/fretes_produtos.html',
        # garantir que template receba data_inicio/data_fim mesmo quando não vierem no request
        data_inicio=request.args.get('data_inicio') or data_inicio_default,
        data_fim=request.args.get('data_fim') or data_fim_default,
        cliente_id=int(request.args.get('cliente_id')) if request.args.get('cliente_id') else None,
        fornecedor_id=int(request.args.get('fornecedor_id')) if request.args.get('fornecedor_id') else None,
        produto_id=int(request.args.get('produto_id')) if request.args.get('produto_id') else None,
        clientes=_load_select_list('clientes'),
        fornecedores=_load_select_list('fornecedores'),
        produtos=_load_select_list('produto'),
        total_quantidade=total_quantidade,
        total_nf=total_nf,
        qtd_produtos_diferentes=qtd_produtos_diferentes,
        fretes=fretes,
        resumo_por_produto=resumo_por_produto,
        resumo_por_produto_geral=resumo_por_produto_geral
    )
