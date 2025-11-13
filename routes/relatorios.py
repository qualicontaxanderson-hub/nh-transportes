```python
from flask import Blueprint, render_template
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.razao_social, COUNT(*) as total_fretes,
               SUM(lf.vlr_total_frete) as total_faturado, SUM(lf.lucro) as total_lucro
        FROM lancamento_frete lf
        JOIN clientes c ON lf.cliente_id = c.id
        GROUP BY c.id ORDER BY total_faturado DESC LIMIT 10
    """)
    por_cliente = cursor.fetchall()
    
    cursor.execute("""
        SELECT m.nome, COUNT(*) as total_fretes, SUM(lf.comissao_motorista) as total_comissao
        FROM lancamento_frete lf
        JOIN motorista m ON lf.motorista_id = m.id
        GROUP BY m.id ORDER BY total_comissao DESC
    """)
    por_motorista = cursor.fetchall()
    
    cursor.execute("""
        SELECT fp.status, COUNT(*) as total, SUM(lf.vlr_total_frete) as valor_total
        FROM lancamento_frete lf
        JOIN forma_pagamento fp ON lf.situacao_financeira_id = fp.id
        GROUP BY fp.id
    """)
    por_situacao = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('relatorios/index.html', por_cliente=por_cliente,
                         por_motorista=por_motorista, por_situacao=por_situacao)
```
