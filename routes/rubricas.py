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
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO rubricas (
                nome, descricao, tipo, percentual_ou_valor_fixo, ordem, ativo
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('nome'),
            request.form.get('descricao'),
            request.form.get('tipo'),
            request.form.get('percentual_ou_valor_fixo', 'VALOR_FIXO'),
            request.form.get('ordem', 1),
            1
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Rubrica cadastrada com sucesso!', 'success')
        return redirect(url_for('rubricas.lista'))
    
    return render_template('rubricas/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE rubricas 
            SET nome=%s, descricao=%s, tipo=%s, percentual_ou_valor_fixo=%s, ordem=%s
            WHERE id=%s
        """, (
            request.form.get('nome'),
            request.form.get('descricao'),
            request.form.get('tipo'),
            request.form.get('percentual_ou_valor_fixo'),
            request.form.get('ordem'),
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Rubrica atualizada com sucesso!', 'success')
        return redirect(url_for('rubricas.lista'))
    
    cursor.execute("SELECT * FROM rubricas WHERE id = %s", (id,))
    rubrica = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return render_template('rubricas/editar.html', rubrica=rubrica)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE rubricas SET ativo = 0 WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Rubrica desativada com sucesso!', 'success')
    return redirect(url_for('rubricas.lista'))
