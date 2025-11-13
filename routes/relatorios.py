from flask import Blueprint, render_template, request
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
@login_required
def index():
    return render_template('relatorios/index.html')
    
    cursor.close()
    conn.close()
    
    return render_template('relatorios/index.html', por_cliente=por_cliente,
                         por_motorista=por_motorista, por_situacao=por_situacao)
