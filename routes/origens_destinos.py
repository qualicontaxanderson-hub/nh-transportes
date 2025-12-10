from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from config import Config
import mysql.connector

bp = Blueprint('origens_destinos', __name__, url_prefix='/origens_destinos')

def get_db():
    """Retorna conexão com o banco de dados usando Config"""
    return mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=Config.DB_PORT
    )

# ==================== ROOT / INDEX ====================

@bp.route('/')
@login_required
def index():
    """Redireciona para a página de origens"""
    return redirect(url_for('origens_destinos.lista_origens'))

# ==================== ORIGENS ====================

@bp.route('/origens')
@login_required
def lista_origens():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('origens_destinos/lista_origens.html', origens=origens)

@bp.route('/origens/nova', methods=['POST'])
@login_required
def nova_origem():
    try:
        nome = request.form.get('nome').strip().upper()
        estado = request.form.get('estado').strip().upper()
        
        if not nome or not estado:
            flash('Nome e Estado são obrigatórios!', 'danger')
            return redirect(url_for('origens_destinos.lista_origens'))
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO origens (nome, estado) VALUES (%s, %s)", (nome, estado))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Origem cadastrada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao cadastrar origem: {str(e)}', 'danger')
    
    return redirect(url_for('origens_destinos.lista_origens'))

@bp.route('/origens/editar/<int:id>', methods=['POST'])
@login_required
def editar_origem(id):
    try:
        nome = request.form.get('nome').strip().upper()
        estado = request.form.get('estado').strip().upper()
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE origens SET nome = %s, estado = %s WHERE id = %s", (nome, estado, id))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Origem atualizada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao atualizar origem: {str(e)}', 'danger')
    
    return redirect(url_for('origens_destinos.lista_origens'))

@bp.route('/origens/excluir/<int:id>')
@login_required
def excluir_origem(id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM origens WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Origem excluída com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir origem: {str(e)}', 'danger')
    
    return redirect(url_for('origens_destinos.lista_origens'))

# ==================== DESTINOS ====================

@bp.route('/destinos')
@login_required
def lista_destinos():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('origens_destinos/lista_destinos.html', destinos=destinos)

@bp.route('/destinos/novo', methods=['POST'])
@login_required
def novo_destino():
    try:
        nome = request.form.get('nome').strip().upper()
        estado = request.form.get('estado').strip().upper()
        
        if not nome or not estado:
            flash('Nome e Estado são obrigatórios!', 'danger')
            return redirect(url_for('origens_destinos.lista_destinos'))
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO destinos (nome, estado) VALUES (%s, %s)", (nome, estado))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Destino cadastrado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao cadastrar destino: {str(e)}', 'danger')
    
    return redirect(url_for('origens_destinos.lista_destinos'))

@bp.route('/destinos/editar/<int:id>', methods=['POST'])
@login_required
def editar_destino(id):
    try:
        nome = request.form.get('nome').strip().upper()
        estado = request.form.get('estado').strip().upper()
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE destinos SET nome = %s, estado = %s WHERE id = %s", (nome, estado, id))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Destino atualizado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao atualizar destino: {str(e)}', 'danger')
    
    return redirect(url_for('origens_destinos.lista_destinos'))

@bp.route('/destinos/excluir/<int:id>')
@login_required
def excluir_destino(id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM destinos WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Destino excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir destino: {str(e)}', 'danger')
    
    return redirect(url_for('origens_destinos.lista_destinos'))
