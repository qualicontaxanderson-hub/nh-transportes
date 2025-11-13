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
    cursor.execute("SELECT * FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('motoristas/lista.html', motoristas=motoristas)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO motoristas (nome, cpf, cnh, telefone, observacoes)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            request.form.get('nome'),
            request.form.get('cpf'),
            request.form.get('cnh'),
            request.form.get('telefone'),
            request.form.get('observacoes')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Motorista cadastrado com sucesso!', 'success')
        return redirect(url_for('motoristas.lista'))
    return render_template('motoristas/novo.html')
