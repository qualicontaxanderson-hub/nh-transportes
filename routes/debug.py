from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('debug', __name__, url_prefix='/debug')

@bp.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    
    result = {}
    
    for table_tuple in tables:
        table_name = table_tuple[0]
        cursor.execute(f"DESCRIBE {table_name}")
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
