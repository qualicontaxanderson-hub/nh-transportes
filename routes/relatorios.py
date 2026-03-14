from flask import Blueprint, render_template, request, redirect, url_for, Response
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime, date
import calendar
import csv
import io
import logging

from routes.auth import admin_required

logger = logging.getLogger(__name__)

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


def _ensure_date_defaults_on_params(params):
    """
    Garante que params (dict) tenha data_inicio/data_fim preenchidos.
    Usa 1º dia do mês até hoje como padrão.
    """
    hoje = date.today()
    primeiro_dia = hoje.replace(day=1)
    data_inicio_default = primeiro_dia.strftime('%Y-%m-%d')
    data_fim_default = hoje.strftime('%Y-%m-%d')
    if not params.get('data_inicio'):
        params['data_inicio'] = data_inicio_default
    if not params.get('data_fim'):
        params['data_fim'] = data_fim_default
    return params


@bp.route('/', methods=['GET'])
@login_required
def index():
    # Redireciona para um relatório padrão (Comissão CTE)
    return redirect(url_for('relatorios.fretes_comissao_cte'))


@bp.route('/fretes_comissao_cte', methods=['GET'])
@login_required
def fretes_comissao_cte():
    # usar dict para poder injetar defaults se necessário
    params = dict(request.args)
    params = _ensure_date_defaults_on_params(params)

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
            ORDER BY cliente_nome ASC, f.data_frete DESC
        """
        cursor.execute(q_det, args)
        fretes = cursor.fetchall()

        # Resumo por caminhão
        q_caminhoes = f"""
            SELECT
              COALESCE(v.caminhao, '(sem caminhão)') AS caminhao_nome,
              COALESCE(v.placa, '') AS placa,
              COUNT(f.id) AS qtd_fretes,
              COALESCE(SUM(f.valor_cte), 0) AS valor_cte_total,
              COALESCE(SUM(f.comissao_cte), 0) AS comissao_total,
              COALESCE(SUM(f.valor_total_frete), 0) AS valor_frete_total
            FROM fretes f
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            WHERE 1=1 {where_sql}
            GROUP BY f.veiculos_id, v.caminhao, v.placa
            ORDER BY COALESCE(SUM(f.valor_cte), 0) DESC
        """
        cursor.execute(q_caminhoes, args)
        resumo_caminhoes = cursor.fetchall()
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
        resumo_caminhoes=resumo_caminhoes,
        fretes=fretes
    )


@bp.route('/fretes_comissao_motorista', methods=['GET'])
@login_required
def fretes_comissao_motorista():
    params = dict(request.args)
    params = _ensure_date_defaults_on_params(params)

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
              COALESCE(SUM(CASE WHEN COALESCE(f.comissao_motorista,0) > 0
                THEN COALESCE(f.quantidade_manual, q.valor, 0) ELSE 0 END),0) AS quantidade_comissionada,
              COALESCE(SUM(f.comissao_motorista),0) AS comissao_total
            FROM fretes f
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            GROUP BY m.id
            ORDER BY motorista_nome ASC
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
            ORDER BY motorista_nome ASC, f.data_frete DESC
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
    params = dict(request.args)
    params = _ensure_date_defaults_on_params(params)

    where_sql, args = _build_filters(params)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        q_totals = f"""
            SELECT
              COALESCE(SUM(f.valor_total_frete),0) AS total_valor_frete,
              COALESCE(SUM(f.comissao_cte),0) AS total_comissao_cte,
              COALESCE(SUM(f.comissao_motorista),0) AS total_comissao_motorista,
              COALESCE(SUM(f.lucro),0) AS total_lucro,
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS total_quantidade
            FROM fretes f
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
        """
        cursor.execute(q_totals, args)
        totals = cursor.fetchone() or {}
        total_valor_frete = totals.get('total_valor_frete', 0)
        total_comissao_cte = totals.get('total_comissao_cte', 0)
        total_comissao_motorista = totals.get('total_comissao_motorista', 0)
        total_lucro = totals.get('total_lucro', 0)
        total_quantidade = totals.get('total_quantidade', 0)

        q_resumo = f"""
            SELECT
              COALESCE(c.razao_social, c.nome_fantasia, '') AS cliente_nome,
              COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS quantidade_total,
              COALESCE(SUM(f.valor_total_frete),0) AS valor_frete_total,
              COALESCE(SUM(f.comissao_cte),0) AS comissao_cte_total,
              COALESCE(SUM(f.comissao_motorista),0) AS comissao_motorista_total,
              COALESCE(SUM(f.lucro),0) AS lucro_total
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_sql}
            GROUP BY c.id, c.razao_social, c.nome_fantasia
            ORDER BY cliente_nome ASC
        """
        cursor.execute(q_resumo, args)
        resumo_clientes = cursor.fetchall()

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
            ORDER BY cliente_nome ASC, f.data_frete DESC
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
        total_quantidade=total_quantidade,
        resumo_clientes=resumo_clientes,
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
            pass

        # --- Construir resumo_por_produto_geral respeitando apenas o período (ignora filtros cliente/fornecedor/produto)
        di_raw = params.get('data_inicio')
        df_raw = params.get('data_fim')
        resumo_args = []
        where_period = ""
        if di_raw and df_raw:
            di = _parse_date_safe(di_raw)
            df = _parse_date_safe(df_raw)
            if di and df:
                where_period = " AND f.data_frete BETWEEN %s AND %s"
                resumo_args.extend([di, df])

        q_geral = f"""
            SELECT p.id AS produto_id, p.nome AS produto_nome,
                   COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)),0) AS quantidade_total
            FROM fretes f
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            WHERE 1=1 {where_period}
            GROUP BY p.id
            ORDER BY quantidade_total DESC
            LIMIT 500
        """
        cursor.execute(q_geral, resumo_args)
        resumo_por_produto_geral = cursor.fetchall()
        # --- fim resumo_por_produto_geral

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


# ---------------------------------------------------------------------------
# Relatório: Lucro Postos (FIFO)
# ---------------------------------------------------------------------------

def _calcular_fifo_relatorio(camadas_iniciais, compras, vendas):
    """
    Calcula FIFO para um produto. Reutiliza a mesma lógica das rotas admin.
    Retorna (resultado_dict, camadas_finais_list).
    """
    from decimal import Decimal
    from collections import defaultdict

    layers = [{'qtde': Decimal(str(c['qtde'])), 'custo': Decimal(str(c['custo']))}
              for c in camadas_iniciais if float(c.get('qtde', 0)) > 0]

    qtde_entrada = Decimal('0')
    custo_entrada = Decimal('0')
    qtde_saida = Decimal('0')
    receita = Decimal('0')
    cogs = Decimal('0')

    comp_by_date = defaultdict(list)
    for c in sorted(compras, key=lambda x: x['data']):
        comp_by_date[c['data']].append(c)
    vend_by_date = defaultdict(list)
    for v in sorted(vendas, key=lambda x: x['data']):
        vend_by_date[v['data']].append(v)

    all_dates = sorted(set(list(comp_by_date.keys()) + list(vend_by_date.keys())))

    for data in all_dates:
        for comp in comp_by_date.get(data, []):
            qtde = Decimal(str(comp['qtde']))
            custo = Decimal(str(comp['custo']))
            if qtde > 0:
                layers.append({'qtde': qtde, 'custo': custo})
                qtde_entrada += qtde
                custo_entrada += qtde * custo

        for vend in vend_by_date.get(data, []):
            qtde_vender = Decimal(str(vend['qtde']))
            valor = Decimal(str(vend['valor_total']))
            if qtde_vender <= 0:
                continue
            qtde_saida += qtde_vender
            receita += valor
            restante = qtde_vender
            while restante > Decimal('0.001') and layers:
                layer = layers[0]
                if layer['qtde'] <= restante + Decimal('0.001'):
                    cogs += layer['qtde'] * layer['custo']
                    restante -= layer['qtde']
                    layers.pop(0)
                else:
                    cogs += restante * layer['custo']
                    layer['qtde'] -= restante
                    restante = Decimal('0')

    estoque_final_qtde = sum(l['qtde'] for l in layers)
    estoque_final_valor = sum(l['qtde'] * l['custo'] for l in layers)

    resultado = {
        'qtde_entrada': float(qtde_entrada),
        'custo_entrada_total': float(custo_entrada),
        'custo_entrada_unit': float(custo_entrada / qtde_entrada) if qtde_entrada > 0 else 0.0,
        'qtde_saida': float(qtde_saida),
        'receita_saida': float(receita),
        'preco_medio_saida': float(receita / qtde_saida) if qtde_saida > 0 else 0.0,
        'cogs': float(cogs),
        'lucro': float(receita - cogs),
        'estoque_final_qtde': float(estoque_final_qtde),
        'estoque_final_valor': float(estoque_final_valor),
        'estoque_final_custo_unit': float(estoque_final_valor / estoque_final_qtde) if estoque_final_qtde > 0 else 0.0,
    }
    return resultado, layers


def _obter_camadas_base_relatorio(cur, cliente_id, produto_id, ano, mes):
    """Obtém camadas base para o relatório FIFO (snapshot anterior ou abertura)."""
    if mes == 1:
        ano_ant, mes_ant = ano - 1, 12
    else:
        ano_ant, mes_ant = ano, mes - 1
    ano_mes_ant = f'{ano_ant:04d}-{mes_ant:02d}'

    cur.execute("""
        SELECT fc.id, fc.versao_atual
        FROM fifo_competencia fc
        WHERE fc.cliente_id = %s AND fc.ano_mes = %s AND fc.status = 'FECHADO'
        LIMIT 1
    """, (cliente_id, ano_mes_ant))
    comp_ant = cur.fetchone()

    if comp_ant:
        cur.execute("""
            SELECT quantidade_restante AS qtde, custo_unitario AS custo
            FROM fifo_snapshot_lotes
            WHERE competencia_id = %s
              AND produto_id = %s
              AND versao = %s
              AND substituido = 0
              AND quantidade_restante > 0
            ORDER BY lote_ordem
        """, (comp_ant['id'], produto_id, comp_ant['versao_atual']))
        lotes = cur.fetchall()
        if lotes:
            return [{'qtde': float(l['qtde']), 'custo': float(l['custo'])} for l in lotes]

    cur.execute("""
        SELECT quantidade AS qtde, custo_unitario AS custo
        FROM fifo_abertura
        WHERE cliente_id = %s AND produto_id = %s
    """, (cliente_id, produto_id))
    ab = cur.fetchone()
    if ab and float(ab['qtde']) > 0:
        return [{'qtde': float(ab['qtde']), 'custo': float(ab['custo'])}]
    return []


def _calcular_resultado_cliente(cur, cliente_id, ano_mes, data_inicio, data_fim, produto_ids_filtro=None):
    """
    Retorna resultados por produto para um cliente num mês.
    Se mês FECHADO: usa fifo_resumo_mensal.
    Se ABERTO: calcula on-the-fly.
    """
    ano, mes = int(ano_mes[:4]), int(ano_mes[5:7])

    # Verificar status da competência
    cur.execute("""
        SELECT id, status, versao_atual
        FROM fifo_competencia
        WHERE cliente_id = %s AND ano_mes = %s
        LIMIT 1
    """, (cliente_id, ano_mes))
    comp = cur.fetchone()
    fechado = comp and comp['status'] == 'FECHADO'

    # Produtos do cliente (posto)
    q_produtos = """
        SELECT DISTINCT p.id, p.nome
        FROM produto p
        INNER JOIN cliente_produtos cp ON cp.produto_id = p.id
        WHERE cp.cliente_id = %s AND cp.ativo = 1
        ORDER BY p.nome
    """
    cur.execute(q_produtos, (cliente_id,))
    produtos = cur.fetchall()
    if produto_ids_filtro:
        produtos = [p for p in produtos if p['id'] in produto_ids_filtro]

    resultados = {}

    if fechado:
        # Usar resumo salvo
        cur.execute("""
            SELECT r.produto_id, r.qtde_entrada, r.custo_entrada_total,
                   r.qtde_saida, r.receita_saida_total, r.cogs_fifo,
                   r.lucro_bruto, r.estoque_final_qtde, r.estoque_final_valor
            FROM fifo_resumo_mensal r
            WHERE r.competencia_id = %s AND r.versao = %s AND r.substituido = 0
        """, (comp['id'], comp['versao_atual']))
        rows = cur.fetchall()
        for row in rows:
            pid = row['produto_id']
            if produto_ids_filtro and pid not in produto_ids_filtro:
                continue
            qtde_entrada = float(row['qtde_entrada'] or 0)
            qtde_saida = float(row['qtde_saida'] or 0)
            receita = float(row['receita_saida_total'] or 0)
            cogs = float(row['cogs_fifo'] or 0)
            estoque_qtde = float(row['estoque_final_qtde'] or 0)
            estoque_valor = float(row['estoque_final_valor'] or 0)
            resultados[pid] = {
                'qtde_entrada': qtde_entrada,
                'custo_entrada_total': float(row['custo_entrada_total'] or 0),
                'custo_entrada_unit': float(row['custo_entrada_total'] or 0) / qtde_entrada if qtde_entrada else 0.0,
                'qtde_saida': qtde_saida,
                'receita_saida': receita,
                'preco_medio_saida': receita / qtde_saida if qtde_saida else 0.0,
                'cogs': cogs,
                'lucro': float(row['lucro_bruto'] or 0),
                'estoque_final_qtde': estoque_qtde,
                'estoque_final_valor': estoque_valor,
                'estoque_final_custo_unit': estoque_valor / estoque_qtde if estoque_qtde else 0.0,
                'status': 'FECHADO',
            }
    else:
        # Calcular on-the-fly
        for prod in produtos:
            pid = prod['id']
            camadas_base = _obter_camadas_base_relatorio(cur, cliente_id, pid, ano, mes)

            cur.execute("""
                SELECT f.data_frete AS data,
                       COALESCE(f.quantidade_manual, q.valor, 0) AS qtde,
                       COALESCE(f.preco_produto_unitario, 0) AS custo
                FROM fretes f
                LEFT JOIN quantidades q ON f.quantidade_id = q.id
                WHERE f.clientes_id = %s
                  AND f.produto_id = %s
                  AND f.data_frete BETWEEN %s AND %s
                  AND COALESCE(f.quantidade_manual, q.valor, 0) > 0
                ORDER BY f.data_frete
            """, (cliente_id, pid, data_inicio, data_fim))
            compras = cur.fetchall()

            cur.execute("""
                SELECT data_movimento AS data,
                       SUM(COALESCE(quantidade_litros, 0)) AS qtde,
                       SUM(COALESCE(valor_total, 0)) AS valor_total
                FROM vendas_posto
                WHERE cliente_id = %s
                  AND produto_id = %s
                  AND data_movimento BETWEEN %s AND %s
                GROUP BY data_movimento
                ORDER BY data_movimento
            """, (cliente_id, pid, data_inicio, data_fim))
            vendas = cur.fetchall()

            resultado, _ = _calcular_fifo_relatorio(camadas_base, compras, vendas)
            resultado['status'] = 'ABERTO'
            resultados[pid] = resultado

    # Mapear nome dos produtos
    prod_map = {p['id']: p['nome'] for p in produtos}
    resultados_com_nome = {}
    for pid, res in resultados.items():
        res['produto_nome'] = prod_map.get(pid, f'Produto {pid}')
        resultados_com_nome[pid] = res

    return resultados_com_nome, fechado


@bp.route('/lucro_postos', methods=['GET'])
@admin_required
def lucro_postos():
    hoje = date.today()
    ano_mes_default = hoje.strftime('%Y-%m')
    ano_mes = request.args.get('ano_mes', ano_mes_default).strip()
    try:
        ano = int(ano_mes[:4])
        mes = int(ano_mes[5:7])
    except (ValueError, IndexError):
        ano_mes = ano_mes_default
        ano = hoje.year
        mes = hoje.month

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia)

    cliente_ids = request.args.getlist('cliente_ids[]')
    cliente_ids = [int(c) for c in cliente_ids if c.isdigit()]
    produto_ids = request.args.getlist('produto_ids[]')
    produto_ids = [int(p) for p in produto_ids if p.isdigit()]

    # Lista de clientes disponíveis (com produtos posto)
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT DISTINCT c.id, c.razao_social, c.nome_fantasia
            FROM clientes c
            INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes_disponiveis = cur.fetchall()

        cur.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos_disponiveis = cur.fetchall()

        # Se não selecionar clientes, usar todos
        ids_para_calcular = cliente_ids if cliente_ids else [c['id'] for c in clientes_disponiveis]
        prod_filtro = set(produto_ids) if produto_ids else None

        resultados_por_cliente = {}
        for cid in ids_para_calcular:
            res, fechado = _calcular_resultado_cliente(
                cur, cid, ano_mes, data_inicio, data_fim, prod_filtro
            )
            if res:
                # Nome do cliente
                c_info = next((c for c in clientes_disponiveis if c['id'] == cid), None)
                nome_cliente = (c_info['nome_fantasia'] or c_info['razao_social']) if c_info else f'Cliente {cid}'
                resultados_por_cliente[cid] = {
                    'nome': nome_cliente,
                    'produtos': res,
                    'fechado': fechado,
                }
    finally:
        cur.close()
        conn.close()

    # Consolidado todos os produtos
    consolidado = {}
    for cid, dados in resultados_por_cliente.items():
        for pid, res in dados['produtos'].items():
            if pid not in consolidado:
                consolidado[pid] = {
                    'produto_nome': res['produto_nome'],
                    'qtde_entrada': 0.0, 'custo_entrada_total': 0.0,
                    'qtde_saida': 0.0, 'receita_saida': 0.0,
                    'cogs': 0.0, 'lucro': 0.0,
                    'estoque_final_qtde': 0.0, 'estoque_final_valor': 0.0,
                }
            for campo in ('qtde_entrada', 'custo_entrada_total', 'qtde_saida',
                          'receita_saida', 'cogs', 'lucro',
                          'estoque_final_qtde', 'estoque_final_valor'):
                consolidado[pid][campo] += res.get(campo, 0.0)

    for pid, c in consolidado.items():
        c['custo_entrada_unit'] = c['custo_entrada_total'] / c['qtde_entrada'] if c['qtde_entrada'] else 0.0
        c['preco_medio_saida'] = c['receita_saida'] / c['qtde_saida'] if c['qtde_saida'] else 0.0
        c['estoque_final_custo_unit'] = c['estoque_final_valor'] / c['estoque_final_qtde'] if c['estoque_final_qtde'] else 0.0

    exportar = request.args.get('exportar')
    if exportar == 'csv':
        return _exportar_csv(resultados_por_cliente, consolidado, ano_mes)

    return render_template(
        'relatorios/lucro_postos.html',
        ano_mes=ano_mes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        clientes_disponiveis=clientes_disponiveis,
        produtos_disponiveis=produtos_disponiveis,
        cliente_ids=cliente_ids,
        produto_ids=produto_ids,
        resultados_por_cliente=resultados_por_cliente,
        consolidado=consolidado,
    )


def _exportar_csv(resultados_por_cliente, consolidado, ano_mes):
    """Gera exportação CSV do relatório Lucro Postos."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    cabecalho = [
        'Cliente', 'Produto', 'Status',
        'Entrada Qtde (L)', 'Entrada VlUnit (R$)', 'Entrada Total (R$)',
        'Saída Qtde (L)', 'Saída VlUnit Médio (R$)', 'Saída Total (R$)',
        'Estoque Final (L)', 'Estoque VlUnit (R$)', 'Estoque Valor (R$)',
        'Receita Bruta (R$)', 'COGS FIFO (R$)', 'Lucro (R$)',
    ]
    writer.writerow(cabecalho)

    def fmt(v):
        return f'{float(v):.4f}'.replace('.', ',')

    for cid, dados in resultados_por_cliente.items():
        for pid, res in sorted(dados['produtos'].items(), key=lambda x: x[1]['produto_nome']):
            writer.writerow([
                dados['nome'],
                res['produto_nome'],
                'FECHADO' if dados['fechado'] else 'ABERTO',
                fmt(res['qtde_entrada']),
                fmt(res['custo_entrada_unit']),
                fmt(res['custo_entrada_total']),
                fmt(res['qtde_saida']),
                fmt(res['preco_medio_saida']),
                fmt(res['receita_saida']),
                fmt(res['estoque_final_qtde']),
                fmt(res['estoque_final_custo_unit']),
                fmt(res['estoque_final_valor']),
                fmt(res['receita_saida']),
                fmt(res['cogs']),
                fmt(res['lucro']),
            ])

    # Linha em branco + consolidado
    writer.writerow([])
    writer.writerow(['CONSOLIDADO TODOS CLIENTES', '', '', '', '', '', '', '', '', '', '', '', '', '', ''])
    for pid, res in sorted(consolidado.items(), key=lambda x: x[1]['produto_nome']):
        writer.writerow([
            'TODOS',
            res['produto_nome'],
            '',
            fmt(res['qtde_entrada']),
            fmt(res['custo_entrada_unit']),
            fmt(res['custo_entrada_total']),
            fmt(res['qtde_saida']),
            fmt(res['preco_medio_saida']),
            fmt(res['receita_saida']),
            fmt(res['estoque_final_qtde']),
            fmt(res['estoque_final_custo_unit']),
            fmt(res['estoque_final_valor']),
            fmt(res['receita_saida']),
            fmt(res['cogs']),
            fmt(res['lucro']),
        ])

    output.seek(0)
    filename = f'lucro_postos_{ano_mes}.csv'
    return Response(
        '\ufeff' + output.getvalue(),  # BOM para Excel
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )
