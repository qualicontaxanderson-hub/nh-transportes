from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from config import Config
import mysql.connector

bp = Blueprint('produtos', __name__, url_prefix='/produtos')

def get_db():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=Config.DB_PORT
    )

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
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO produto (nome) VALUES (%s)",
                (nome,)
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash('Produto cadastrado com sucesso!', 'success')
            return redirect(url_for('produtos.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar produto: {str(e)}', 'danger')
    
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
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produto WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Produto excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir produto: {str(e)}', 'danger')
    return redirect(url_for('produtos.lista'))
