from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('origens_destinos', __name__, url_prefix='/origens_destinos')

def get_db():
    """Usa a conexão centralizada com credenciais seguras"""
    return get_db_connection()

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
    nome = request.form.get('nome', '').strip().upper()
    estado = request.form.get('estado', '').strip().upper()

    if not nome or not estado:
        flash('Nome e Estado são obrigatórios!', 'danger')
        return redirect(url_for('origens_destinos.lista_origens'))

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO origens (nome, estado) VALUES (%s, %s)", (nome, estado))
        conn.commit()
        flash('Origem cadastrada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar origem: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_origens'))

@bp.route('/origens/editar/<int:id>', methods=['POST'])
@login_required
def editar_origem(id):
    conn = None
    cursor = None
    try:
        nome = request.form.get('nome', '').strip().upper()
        estado = request.form.get('estado', '').strip().upper()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE origens SET nome = %s, estado = %s WHERE id = %s", (nome, estado, id))
        conn.commit()
        flash('Origem atualizada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao atualizar origem: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_origens'))

@bp.route('/origens/excluir/<int:id>')
@login_required
def excluir_origem(id):
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM origens WHERE id = %s", (id,))
        conn.commit()
        flash('Origem excluída com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir origem: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

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
    nome = request.form.get('nome', '').strip().upper()
    estado = request.form.get('estado', '').strip().upper()

    if not nome or not estado:
        flash('Nome e Estado são obrigatórios!', 'danger')
        return redirect(url_for('origens_destinos.lista_destinos'))

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO destinos (nome, estado) VALUES (%s, %s)", (nome, estado))
        conn.commit()
        flash('Destino cadastrado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar destino: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_destinos'))

@bp.route('/destinos/editar/<int:id>', methods=['POST'])
@login_required
def editar_destino(id):
    conn = None
    cursor = None
    try:
        nome = request.form.get('nome', '').strip().upper()
        estado = request.form.get('estado', '').strip().upper()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE destinos SET nome = %s, estado = %s WHERE id = %s", (nome, estado, id))
        conn.commit()
        flash('Destino atualizado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao atualizar destino: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_destinos'))

@bp.route('/destinos/excluir/<int:id>')
@login_required
def excluir_destino(id):
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM destinos WHERE id = %s", (id,))
        conn.commit()
        flash('Destino excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir destino: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_destinos'))
