from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('motoristas', __name__, url_prefix='/motoristas')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM motorista ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('motoristas/lista.html', motoristas=motoristas)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        nome = request.form.get('nome', '').upper()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO motorista (nome) VALUES (%s)", (nome,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Motorista cadastrado com sucesso!', 'success')
        return redirect(url_for('motoristas.lista'))
    return render_template('motoristas/novo.html')

@bp.route('/excluir/<int:id>')
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM motorista WHERE id = %s", (id,))
        conn.commit()
        flash('Motorista excluído!', 'success')
    except Exception as e:
        flash(f'Erro: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('motoristas.lista'))
