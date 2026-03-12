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
        SELECT f.*
        FROM funcionarios f
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
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                INSERT INTO funcionarios (
                    nome, id_cliente, tipo, cpf, telefone, email, 
                    cargo, data_admissao, salario_base, categoria, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('nome'),
                request.form.get('clienteid') or None,
                'FUNCIONARIO',
                request.form.get('cpf'),
                request.form.get('telefone'),
                request.form.get('email'),
                request.form.get('cargo'),
                request.form.get('data_admissao') or None,
                request.form.get('salario_base') or None,
                request.form.get('categoria'),
                1
            ))
            conn.commit()
            flash('Funcionário cadastrado com sucesso!', 'success')
            return redirect(url_for('funcionarios.lista'))

        # Get categories for dropdown
        cursor.execute("SELECT * FROM categoriasfuncionarios WHERE ativo = 1 ORDER BY nome")
        categorias = cursor.fetchall()
        # Only show clients that have products configured (cliente_produtos)
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social as nome 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        return render_template('funcionarios/novo.html', categorias=categorias, clientes=clientes)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar funcionário: {str(e)}', 'danger')
        return redirect(url_for('funcionarios.lista'))
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
                UPDATE funcionarios SET 
                    nome=%s, id_cliente=%s, categoria=%s, cpf=%s, telefone=%s, 
                    email=%s, cargo=%s, data_admissao=%s, salario_base=%s
                WHERE id=%s
            """, (
                request.form.get('nome'),
                request.form.get('clienteid') or None,
                request.form.get('categoria'),
                request.form.get('cpf'),
                request.form.get('telefone'),
                request.form.get('email'),
                request.form.get('cargo'),
                request.form.get('data_admissao') or None,
                request.form.get('salario_base') or None,
                id
            ))
            conn.commit()
            flash('Funcionário atualizado com sucesso!', 'success')
            return redirect(url_for('funcionarios.lista'))

        cursor.execute("SELECT * FROM funcionarios WHERE id = %s", (id,))
        funcionario = cursor.fetchone()
        cursor.execute("SELECT * FROM categoriasfuncionarios WHERE ativo = 1 ORDER BY nome")
        categorias = cursor.fetchall()
        # Only show clients that have products configured (cliente_produtos)
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social as nome 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        return render_template('funcionarios/editar.html', funcionario=funcionario, categorias=categorias, clientes=clientes)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar funcionário: {str(e)}', 'danger')
        return redirect(url_for('funcionarios.lista'))
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
        # Soft delete
        cursor.execute("UPDATE funcionarios SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()
        flash('Funcionário desativado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar funcionário: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('funcionarios.lista'))

@bp.route('/vincular-veiculo/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def vincular_veiculo(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                INSERT INTO funcionariomotoristaveiculos (
                    funcionarioid, veiculoid, datainicio, datafim, principal, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                id,
                request.form.get('veiculoid'),
                request.form.get('datainicio'),
                request.form.get('datafim') or None,
                1 if request.form.get('principal') == '1' else 0,
                1
            ))
            conn.commit()
            flash('Veículo vinculado com sucesso!', 'success')
            return redirect(url_for('funcionarios.editar', id=id))

        cursor.execute("SELECT * FROM funcionarios WHERE id = %s", (id,))
        funcionario = cursor.fetchone()
        cursor.execute("SELECT * FROM veiculos WHERE ativo = 1 ORDER BY caminhao")
        veiculos = cursor.fetchall()
        return render_template('funcionarios/vincular_veiculo.html', funcionario=funcionario, veiculos=veiculos)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao vincular veículo: {str(e)}', 'danger')
        return redirect(url_for('funcionarios.editar', id=id))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
