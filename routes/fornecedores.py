from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('fornecedores', __name__, url_prefix='/fornecedores')

@bp.route('/')
@login_required
def lista():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('fornecedores/lista.html', fornecedores=fornecedores)
    except Exception as e:
        flash(f'Erro ao carregar fornecedores: {str(e)}', 'danger')
        return render_template('fornecedores/lista.html', fornecedores=[])

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO fornecedores (razao_social, nome_fantasia, cnpj, ie, 
                                      endereco, numero, complemento, bairro, 
                                      municipio, uf, nome_vendedor, telefone, email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia'),
            request.form.get('cnpj'),
            request.form.get('ie'),
            request.form.get('endereco'),
            request.form.get('numero'),
            request.form.get('complemento'),
            request.form.get('bairro'),
            request.form.get('municipio'),
            request.form.get('uf'),
            request.form.get('nome_vendedor'),
            request.form.get('telefone'),
            request.form.get('email')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Fornecedor cadastrado com sucesso!', 'success')
        return redirect(url_for('fornecedores.lista'))
    return render_template('fornecedores/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE fornecedores 
            SET razao_social=%s, nome_fantasia=%s, cnpj=%s, ie=%s,
                endereco=%s, numero=%s, complemento=%s, bairro=%s,
                municipio=%s, uf=%s, nome_vendedor=%s, telefone=%s, email=%s
            WHERE id=%s
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia'),
            request.form.get('cnpj'),
            request.form.get('ie'),
            request.form.get('endereco'),
            request.form.get('numero'),
            request.form.get('complemento'),
            request.form.get('bairro'),
            request.form.get('municipio'),
            request.form.get('uf'),
            request.form.get('nome_vendedor'),
            request.form.get('telefone'),
            request.form.get('email'),
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Fornecedor atualizado com sucesso!', 'success')
        return redirect(url_for('fornecedores.lista'))
    
    cursor.execute("SELECT * FROM fornecedores WHERE id = %s", (id,))
    fornecedor = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('fornecedores/editar.html', fornecedor=fornecedor)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fornecedores WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Fornecedor excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir fornecedor: {str(e)}', 'danger')
    return redirect(url_for('fornecedores.lista'))
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO fornecedores (razao_social, nome_fantasia, cnpj, ie, 
                                      endereco, numero, complemento, bairro, 
                                      municipio, uf, nome_vendedor, telefone, email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia'),
            request.form.get('cnpj'),
            request.form.get('ie'),
            request.form.get('endereco'),
            request.form.get('numero'),
            request.form.get('complemento'),
            request.form.get('bairro'),
            request.form.get('municipio'),
            request.form.get('uf'),
            request.form.get('nome_vendedor'),
            request.form.get('telefone'),
            request.form.get('email')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Fornecedor cadastrado com sucesso!', 'success')
        return redirect(url_for('fornecedores.lista'))
    return render_template('fornecedores/novo.html')
