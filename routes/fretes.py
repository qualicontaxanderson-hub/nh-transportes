from flask import Blueprint, render_template
from flask_login import login_required

from utils.db import get_db_connection

bp = Blueprint('fretes', __name__, url_prefix='/fretes')


@bp.route('/', methods=['GET'])
@login_required
def lista():
    """
    Lista simples de fretes — usada pelo menu (endpoint 'fretes.lista').
    Ajuste a query/colunas conforme sua tabela e template.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT f.id,
                   f.data_frete,
                   f.status,
                   f.valor_total_frete,
                   f.lucro,
                   c.razao_social AS cliente,
                   fo.razao_social AS fornecedor,
                   m.nome AS motorista,
                   v.caminhao AS veiculo
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            ORDER BY f.data_frete DESC, f.id DESC
            LIMIT 200
        """)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('fretes/lista.html', fretes=fretes)
