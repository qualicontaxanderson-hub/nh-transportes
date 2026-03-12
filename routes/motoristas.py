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
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'POST':
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
            flash('Motorista cadastrado com sucesso!', 'success')
            return redirect(url_for('motoristas.lista'))

        return render_template('motoristas/novo.html')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar motorista: {str(e)}', 'danger')
        return redirect(url_for('motoristas.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = None
    cursor = None
    try:
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
            flash('Motorista atualizado com sucesso!', 'success')
            return redirect(url_for('motoristas.lista'))

        cursor.execute("SELECT * FROM motoristas WHERE id = %s", (id,))
        motorista = cursor.fetchone()
        return render_template('motoristas/editar.html', motorista=motorista)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar motorista: {str(e)}', 'danger')
        return redirect(url_for('motoristas.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM motoristas WHERE id = %s", (id,))
        conn.commit()
        flash('Motorista excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir motorista: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('motoristas.lista'))
