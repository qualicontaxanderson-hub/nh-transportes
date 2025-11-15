from flask import Blueprint, render_template, request
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Top 10 clientes por lucro
    cursor.execute("""
        SELECT c.razao_social as cliente, 
               COUNT(lf.id) as fretes,
               SUM(lf.vlr_total_frete) as total,
               SUM(lf.lucro) as lucro
        FROM lancamento_frete lf
        JOIN clientes c ON lf.cliente_id = c.id
        GROUP BY c.id, c.razao_social
        ORDER BY lucro DESC
        LIMIT 10
    """)
    por_cliente = cursor.fetchall()
    
    # Comissões de motoristas
    cursor.execute("""
        SELECT m.nome as motorista,
               COUNT(lf.id) as fretes,
               SUM(lf.vlr_adiantamento) as total_comissao
        FROM lancamento_frete lf
        JOIN motoristas m ON lf.motorista_id = m.id
        GROUP BY m.id, m.nome
        ORDER BY total_comissao DESC
    """)
    por_motorista = cursor.fetchall()
    
    # Situação financeira
    cursor.execute("""
        SELECT 
            'Total' as status,
            COUNT(*) as quantidade,
            SUM(vlr_total_frete) as valor_total
        FROM lancamento_frete
    """)
    por_situacao = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('relatorios/index.html', 
                         por_cliente=por_cliente,
                         por_motorista=por_motorista, 
                         por_situacao=por_situacao)
