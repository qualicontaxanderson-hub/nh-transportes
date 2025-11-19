from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('clientes', __name__, url_prefix='/clientes')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('clientes/lista.html', clientes=clientes)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Pegar valor dos checkboxes (se marcado = 1, se não = 0)
        paga_comissao = 1 if request.form.get('paga_comissao') == 'on' else 0
        cte_integral = 1 if request.form.get('cte_integral') == 'on' else 0
        
        cursor.execute("""
            INSERT INTO clientes (razao_social, nome_fantasia, cnpj, ie, contato,
                                 endereco, numero, complemento, bairro, municipio, uf, cep,
                                 telefone, email, paga_comissao, cte_integral)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia') or None,
            request.form.get('cnpj') or None,
            request.form.get('ie') or None,
            request.form.get('contato') or None,
            request.form.get('endereco') or None,
            request.form.get('numero') or None,
            request.form.get('complemento') or None,
            request.form.get('bairro') or None,
            request.form.get('municipio') or None,
            request.form.get('uf') or None,
            request.form.get('cep') or None,
            request.form.get('telefone') or None,
            request.form.get('email') or None,
            paga_comissao,
            cte_integral
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('clientes.lista'))
    return render_template('clientes/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Pegar valor dos checkboxes (se marcado = 1, se não = 0)
        paga_comissao = 1 if request.form.get('paga_comissao') == 'on' else 0
        cte_integral = 1 if request.form.get('cte_integral') == 'on' else 0
        
        cursor.execute("""
            UPDATE clientes SET razao_social=%s, nome_fantasia=%s, cnpj=%s, ie=%s, contato=%s,
                              endereco=%s, numero=%s, complemento=%s, bairro=%s, municipio=%s, uf=%s, cep=%s,
                              telefone=%s, email=%s, paga_comissao=%s, cte_integral=%s
            WHERE id=%s
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia') or None,
            request.form.get('cnpj') or None,
            request.form.get('ie') or None,
            request.form.get('contato') or None,
            request.form.get('endereco') or None,
            request.form.get('numero') or None,
            request.form.get('complemento') or None,
            request.form.get('bairro') or None,
            request.form.get('municipio') or None,
            request.form.get('uf') or None,
            request.form.get('cep') or None,
            request.form.get('telefone') or None,
            request.form.get('email') or None,
            paga_comissao,
            cte_integral,
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Cliente atualizado com sucesso!', 'success')
        return redirect(url_for('clientes.lista'))
    
    cursor.execute("SELECT * FROM clientes WHERE id = %s", (id,))
    cliente = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('clientes/editar.html', cliente=cliente)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir cliente: {str(e)}', 'danger')
    return redirect(url_for('clientes.lista'))
