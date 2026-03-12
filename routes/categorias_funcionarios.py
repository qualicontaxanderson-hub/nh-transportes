from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('categorias_funcionarios', __name__, url_prefix='/categorias-funcionarios')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categoriasfuncionarios WHERE ativo = 1 ORDER BY nome")
    categorias = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('categorias_funcionarios/lista.html', categorias=categorias)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                INSERT INTO categoriasfuncionarios (nome, descricao, clienteid, ativo)
                VALUES (%s, %s, %s, %s)
            """, (
                request.form.get('nome'),
                request.form.get('descricao'),
                request.form.get('clienteid') or None,
                1
            ))
            conn.commit()
            flash('Categoria cadastrada com sucesso!', 'success')
            return redirect(url_for('categorias_funcionarios.lista'))

        cursor.execute("SELECT id, razao_social as nome FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        return render_template('categorias_funcionarios/novo.html', clientes=clientes)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar categoria: {str(e)}', 'danger')
        return redirect(url_for('categorias_funcionarios.lista'))
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
                UPDATE categoriasfuncionarios 
                SET nome=%s, descricao=%s, clienteid=%s
                WHERE id=%s
            """, (
                request.form.get('nome'),
                request.form.get('descricao'),
                request.form.get('clienteid') or None,
                id
            ))
            conn.commit()
            flash('Categoria atualizada com sucesso!', 'success')
            return redirect(url_for('categorias_funcionarios.lista'))

        cursor.execute("SELECT * FROM categoriasfuncionarios WHERE id = %s", (id,))
        categoria = cursor.fetchone()
        cursor.execute("SELECT id, razao_social as nome FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        return render_template('categorias_funcionarios/editar.html', categoria=categoria, clientes=clientes)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar categoria: {str(e)}', 'danger')
        return redirect(url_for('categorias_funcionarios.lista'))
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
        cursor.execute("UPDATE categoriasfuncionarios SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()
        flash('Categoria desativada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar categoria: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('categorias_funcionarios.lista'))
