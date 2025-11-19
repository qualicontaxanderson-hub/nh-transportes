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
        
        # Verifica se o checkbox foi marcado (paga_comissao)
        paga_comissao = 1 if request.form.get('paga_comissao') == '1' else 0
        
        cursor.execute("""
            INSERT INTO motoristas (nome, cpf, cnh, telefone, observacoes, paga_comissao)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('nome'),
            request.form.get('cpf'),
            request.form.get('cnh'),
            request.form.get('telefone'),
            request.form.get('observacoes'),
            paga_comissao
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Motorista cadastrado com sucesso!', 'success')
        return redirect(url_for('motoristas.lista'))
    return render_template('motoristas/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Verifica se o checkbox foi marcado (paga_comissao)
        paga_comissao = 1 if request.form.get('paga_comissao') == '1' else 0
        
        cursor.execute("""
            UPDATE motoristas SET nome=%s, cpf=%s, cnh=%s, telefone=%s, observacoes=%s, paga_comissao=%s
            WHERE id=%s
        """, (
            request.form.get('nome'),
            request.form.get('cpf'),
            request.form.get('cnh'),
            request.form.get('telefone'),
            request.form.get('observacoes'),
            paga_comissao,
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Motorista atualizado com sucesso!', 'success')
        return redirect(url_for('motoristas.lista'))
    
    cursor.execute("SELECT * FROM motoristas WHERE id = %s", (id,))
    motorista = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('motoristas/editar.html', motorista=motorista)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM motoristas WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Motorista excluído com sucesso!', 'success')
    return redirect(url_for('motoristas.lista'))
