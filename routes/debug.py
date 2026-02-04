from flask import Blueprint, render_template, jsonify, current_app
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('debug', __name__, url_prefix='/debug')

@bp.route('/')
@login_required
def index():
    # SEGURANÇA: Rota de debug só disponível em modo desenvolvimento
    if not current_app.debug:
        return jsonify({"error": "Debug route is only available in development mode"}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    
    result = {}
    
    # Lista branca de tabelas permitidas (segurança adicional)
    allowed_tables = set()
    
    for table_tuple in tables:
        table_name = table_tuple[0]
        
        # Validação: apenas nomes de tabelas alfanuméricos e underscore
        if not table_name.replace('_', '').isalnum():
            continue
            
        # Se houver lista branca configurada, verificar
        if allowed_tables and table_name not in allowed_tables:
            continue
            
        # Usar identifier quoting para prevenir SQL injection
        cursor.execute(f"DESCRIBE `{table_name}`")
        columns = cursor.fetchall()
        
        result[table_name] = [
            {
                'field': col[0],
                'type': col[1],
                'null': col[2],
                'key': col[3],
                'default': col[4],
                'extra': col[5]
            }
            for col in columns
        ]
    
    cursor.close()
    conn.close()
    
    return jsonify(result)
