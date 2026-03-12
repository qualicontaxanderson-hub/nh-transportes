from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('produtos', __name__, url_prefix='/produtos')

def get_db():
    """Usa a conexão centralizada com credenciais seguras"""
    return get_db_connection()

@bp.route('/')
@login_required
def lista():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM produto ORDER BY id DESC")
    produtos = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('produtos/lista.html', produtos=produtos)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        nome = request.form.get('nome')
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO produto (nome) VALUES (%s)",
                (nome,)
            )
            conn.commit()
            flash('Produto cadastrado com sucesso!', 'success')
            return redirect(url_for('produtos.lista'))
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao cadastrar produto: {str(e)}', 'danger')
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return render_template('produtos/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nome = request.form.get('nome')
        try:
            cursor.execute(
                "UPDATE produto SET nome=%s WHERE id=%s",
                (nome, id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash('Produto atualizado com sucesso!', 'success')
            return redirect(url_for('produtos.lista'))
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao atualizar produto: {str(e)}', 'danger')

    cursor.execute("SELECT * FROM produto WHERE id = %s", (id,))
    produto = cursor.fetchone()
    cursor.close()
    conn.close()

    if not produto:
        flash('Produto não encontrado!', 'danger')
        return redirect(url_for('produtos.lista'))

    return render_template('produtos/editar.html', produto=produto)

@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produto WHERE id = %s", (id,))
        conn.commit()
        flash('Produto excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir produto: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('produtos.lista'))
