from flask import Blueprint, render_template, request
from utils.db import get_db_connection

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Exemplo de consulta apenas na tabela fretes
    cursor.execute("SELECT * FROM fretes")
    relatorio = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('relatorios/index.html', relatorio=relatorio)
