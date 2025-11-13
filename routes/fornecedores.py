from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('fornecedores', __name__, url_prefix='/fornecedores')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM fornecedores ORDER BY nome")
    fornecedores = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('fornecedores/lista.html', fornecedores=fornecedores)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO fornecedores (nome, cnpj, telefone, email, observacoes)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            request.form.get('nome'),
            request.form.get('cnpj'),
            request.form.get('telefone'),
            request.form.get('email'),
            request.form.get('observacoes')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Fornecedor cadastrado com sucesso!', 'success')
        return redirect(url_for('fornecedores.lista'))
    return render_template('fornecedores/novo.html')
