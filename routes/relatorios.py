from flask import Blueprint, render_template, request
from flask_login import login_required
from app import get_db  # use seu get_db do app.py
from datetime import datetime

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
@login_required
def index():
    # Receber filtros
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    mes = request.args.get('mes', '')
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Construir cláusula WHERE para filtros
    where_clause = ""
    params = []
    
    if mes:
        where_clause = "WHERE MONTH(f.data_frete) = %s AND YEAR(f.data_frete) = YEAR(CURDATE())"
        params = [mes]
    elif data_inicio and data_fim:
        where_clause = "WHERE f.data_frete BETWEEN %s AND %s"
        params = [data_inicio, data_fim]
    elif data_inicio:
        where_clause = "WHERE f.data_frete >= %s"
        params = [data_inicio]
    elif data_fim:
        where_clause = "WHERE f.data_frete <= %s"
        params = [data_fim]
    
    # Top 10 clientes por lucro
    query_clientes = f"""
        SELECT c.razao_social as cliente, 
               COUNT(f.id) as fretes,
               COALESCE(SUM(f.valor_total_frete), 0) as total,
               COALESCE(SUM(f.lucro), 0) as lucro
        FROM fretes f
        LEFT JOIN clientes c ON f.clientes_id = c.id
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
               COUNT(f.id) as fretes,
               COALESCE(SUM(f.comissao_motorista), 0) as total_comissao
        FROM fretes f
        LEFT JOIN motoristas m ON f.motoristas_id = m.id
        {where_clause}
        GROUP BY m.id, m.nome
        HAVING total_comissao > 0
        ORDER BY total_comissao DESC
    """
    cursor.execute(query_motoristas, params)
    por_motorista = cursor.fetchall()
    
    # Situação financeira por status
    query_situacao = f"""
        SELECT 
            f.status as status,
            COUNT(f.id) as quantidade,
            COALESCE(SUM(f.valor_total_frete), 0) as valor_total
        FROM fretes f
        {where_clause}
        GROUP BY f.status
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
