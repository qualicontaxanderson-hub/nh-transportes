from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('funcionarios', __name__, url_prefix='/funcionarios')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.*, c.nome as categoria_nome
        FROM funcionarios f
        LEFT JOIN categorias_funcionarios c ON f.categoria_id = c.id
        WHERE f.ativo = 1
        ORDER BY f.nome
    """)
    funcionarios = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('funcionarios/lista.html', funcionarios=funcionarios)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO funcionarios (
                nome, cliente_id, categoria_id, cpf, telefone, email, 
                cargo, data_admissao, salario_base, ativo
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('nome'),
            request.form.get('cliente_id') or None,
            request.form.get('categoria_id') or None,
            request.form.get('cpf'),
            request.form.get('telefone'),
            request.form.get('email'),
            request.form.get('cargo'),
            request.form.get('data_admissao') or None,
            request.form.get('salario_base') or None,
            1
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Funcionário cadastrado com sucesso!', 'success')
        return redirect(url_for('funcionarios.lista'))
    
    # Get categories for dropdown
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categorias_funcionarios WHERE ativo = 1 ORDER BY nome")
    categorias = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('funcionarios/novo.html', categorias=categorias, clientes=clientes)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE funcionarios SET 
                nome=%s, cliente_id=%s, categoria_id=%s, cpf=%s, telefone=%s, 
                email=%s, cargo=%s, data_admissao=%s, salario_base=%s
            WHERE id=%s
        """, (
            request.form.get('nome'),
            request.form.get('cliente_id') or None,
            request.form.get('categoria_id') or None,
            request.form.get('cpf'),
            request.form.get('telefone'),
            request.form.get('email'),
            request.form.get('cargo'),
            request.form.get('data_admissao') or None,
            request.form.get('salario_base') or None,
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Funcionário atualizado com sucesso!', 'success')
        return redirect(url_for('funcionarios.lista'))
    
    cursor.execute("SELECT * FROM funcionarios WHERE id = %s", (id,))
    funcionario = cursor.fetchone()
    cursor.execute("SELECT * FROM categorias_funcionarios WHERE ativo = 1 ORDER BY nome")
    categorias = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('funcionarios/editar.html', funcionario=funcionario, categorias=categorias, clientes=clientes)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Soft delete
    cursor.execute("UPDATE funcionarios SET ativo = 0 WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Funcionário desativado com sucesso!', 'success')
    return redirect(url_for('funcionarios.lista'))

@bp.route('/vincular-veiculo/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def vincular_veiculo(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            INSERT INTO funcionariomotoristaveiculos (
                funcionario_id, veiculo_id, data_inicio, data_fim, principal, ativo
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            id,
            request.form.get('veiculo_id'),
            request.form.get('data_inicio'),
            request.form.get('data_fim') or None,
            1 if request.form.get('principal') == '1' else 0,
            1
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Veículo vinculado com sucesso!', 'success')
        return redirect(url_for('funcionarios.editar', id=id))
    
    cursor.execute("SELECT * FROM funcionarios WHERE id = %s", (id,))
    funcionario = cursor.fetchone()
    cursor.execute("SELECT * FROM veiculos WHERE ativo = 1 ORDER BY caminhao")
    veiculos = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('funcionarios/vincular_veiculo.html', funcionario=funcionario, veiculos=veiculos)
