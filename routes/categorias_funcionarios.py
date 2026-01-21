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
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
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
        cursor.close()
        conn.close()
        flash('Categoria cadastrada com sucesso!', 'success')
        return redirect(url_for('categorias_funcionarios.lista'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('categorias_funcionarios/novo.html', clientes=clientes)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
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
        cursor.close()
        conn.close()
        flash('Categoria atualizada com sucesso!', 'success')
        return redirect(url_for('categorias_funcionarios.lista'))
    
    cursor.execute("SELECT * FROM categoriasfuncionarios WHERE id = %s", (id,))
    categoria = cursor.fetchone()
    cursor.execute("SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('categorias_funcionarios/editar.html', categoria=categoria, clientes=clientes)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE categoriasfuncionarios SET ativo = 0 WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Categoria desativada com sucesso!', 'success')
    return redirect(url_for('categorias_funcionarios.lista'))
