from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('rubricas', __name__, url_prefix='/rubricas')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM rubricas WHERE ativo = 1 ORDER BY ordem, nome")
    rubricas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('rubricas/lista.html', rubricas=rubricas)

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
            cursor.execute("""
                INSERT INTO rubricas (
                    nome, descricao, tipo, percentualouvalorfixo, ordem, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('nome'),
                request.form.get('descricao'),
                request.form.get('tipo'),
                request.form.get('percentualouvalorfixo', 'VALOR_FIXO'),
                request.form.get('ordem', 1),
                1
            ))
            conn.commit()
            flash('Rubrica cadastrada com sucesso!', 'success')
            return redirect(url_for('rubricas.lista'))

        return render_template('rubricas/novo.html')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar rubrica: {str(e)}', 'danger')
        return redirect(url_for('rubricas.lista'))
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
            cursor.execute("""
                UPDATE rubricas 
                SET nome=%s, descricao=%s, tipo=%s, percentualouvalorfixo=%s, ordem=%s
                WHERE id=%s
            """, (
                request.form.get('nome'),
                request.form.get('descricao'),
                request.form.get('tipo'),
                request.form.get('percentualouvalorfixo'),
                request.form.get('ordem'),
                id
            ))
            conn.commit()
            flash('Rubrica atualizada com sucesso!', 'success')
            return redirect(url_for('rubricas.lista'))

        cursor.execute("SELECT * FROM rubricas WHERE id = %s", (id,))
        rubrica = cursor.fetchone()
        return render_template('rubricas/editar.html', rubrica=rubrica)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar rubrica: {str(e)}', 'danger')
        return redirect(url_for('rubricas.lista'))
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
        cursor.execute("UPDATE rubricas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()
        flash('Rubrica desativada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar rubrica: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('rubricas.lista'))
