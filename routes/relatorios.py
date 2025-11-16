from flask import Blueprint, render_template, request
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
@login_required
def index():
    # Receber filtros
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    mes = request.args.get('mes', '')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Construir cláusula WHERE para filtros
    where_clause = ""
    params = []
    
    if mes:
        where_clause = "WHERE MONTH(lf.data_frete) = %s AND YEAR(lf.data_frete) = YEAR(CURDATE())"
        params = [mes]
    elif data_inicio and data_fim:
        where_clause = "WHERE lf.data_frete BETWEEN %s AND %s"
        params = [data_inicio, data_fim]
    elif data_inicio:
        where_clause = "WHERE lf.data_frete >= %s"
        params = [data_inicio]
    elif data_fim:
        where_clause = "WHERE lf.data_frete <= %s"
        params = [data_fim]
    
    # Top 10 clientes por lucro
    query_clientes = f"""
        SELECT c.razao_social as cliente, 
               COUNT(lf.id) as fretes,
               COALESCE(SUM(lf.vlr_total_frete), 0) as total,
               COALESCE(SUM(lf.lucro), 0) as lucro
        FROM lancamento_frete lf
        LEFT JOIN clientes c ON lf.clientes_id = c.id
        {where_clause}
        GROUP BY c.id, c.razao_social
        HAVING lucro > 0
        ORDER BY lucro DESC
        LIMIT 10
    """
    cursor.execute(query_clientes, params)
    por_cliente = cursor.fetchall()
    
    # Comissões de motoristas
    query_motoristas = f"""
        SELECT m.nome as motorista,
               COUNT(lf.id) as fretes,
               COALESCE(SUM(lf.comissao_motorista), 0) as total_comissao
        FROM lancamento_frete lf
        LEFT JOIN motoristas m ON lf.motoristas_id = m.id
        {where_clause}
        GROUP BY m.id, m.nome
        HAVING total_comissao > 0
        ORDER BY total_comissao DESC
    """
    cursor.execute(query_motoristas, params)
    por_motorista = cursor.fetchall()
    
    # Situação financeira por status (da tabela forma_pagamento)
    query_situacao = f"""
        SELECT 
            fp.status as status,
            COUNT(lf.id) as quantidade,
            COALESCE(SUM(lf.vlr_total_frete), 0) as valor_total
        FROM lancamento_frete lf
        LEFT JOIN forma_pagamento fp ON lf.forma_pagamento_id = fp.id
        {where_clause}
        GROUP BY fp.status
        ORDER BY valor_total DESC
    """
    cursor.execute(query_situacao, params)
    por_situacao = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('relatorios/index.html', 
                         por_cliente=por_cliente,
                         por_motorista=por_motorista, 
                         por_situacao=por_situacao,
                         data_inicio=data_inicio,
                         data_fim=data_fim,
                         mes=mes)
