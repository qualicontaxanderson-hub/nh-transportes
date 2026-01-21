from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('cartoes', __name__, url_prefix='/cartoes')


@bp.route('/')
@login_required
def lista():
    """List all card brands"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM bandeiras_cartao ORDER BY tipo, nome")
        cartoes = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('cartoes/lista.html', cartoes=cartoes)
    except Exception as e:
        flash(f'Erro ao carregar cartões: {str(e)}', 'danger')
        return render_template('cartoes/lista.html', cartoes=[])


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create a new card brand"""
    if request.method == 'POST':
        nome = request.form.get('nome')
        tipo = request.form.get('tipo')
        ativo = request.form.get('ativo', '1')

        if not nome or not tipo:
            flash('Nome e tipo são obrigatórios!', 'danger')
            return render_template('cartoes/novo.html')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bandeiras_cartao (nome, tipo, ativo)
                VALUES (%s, %s, %s)
            """, (nome, tipo, int(ativo)))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Cartão cadastrado com sucesso!', 'success')
            return redirect(url_for('cartoes.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar cartão: {str(e)}', 'danger')

    return render_template('cartoes/novo.html')


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit an existing card brand"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nome = request.form.get('nome')
        tipo = request.form.get('tipo')
        ativo = request.form.get('ativo', '1')

        if not nome or not tipo:
            flash('Nome e tipo são obrigatórios!', 'danger')
            cursor.execute("SELECT * FROM bandeiras_cartao WHERE id = %s", (id,))
            cartao = cursor.fetchone()
            cursor.close()
            conn.close()
            return render_template('cartoes/editar.html', cartao=cartao)

        try:
            cursor.execute("""
                UPDATE bandeiras_cartao 
                SET nome = %s,
                    tipo = %s,
                    ativo = %s
                WHERE id = %s
            """, (nome, tipo, int(ativo), id))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Cartão atualizado com sucesso!', 'success')
            return redirect(url_for('cartoes.lista'))
        except Exception as e:
            flash(f'Erro ao atualizar cartão: {str(e)}', 'danger')

    cursor.execute("SELECT * FROM bandeiras_cartao WHERE id = %s", (id,))
    cartao = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not cartao:
        flash('Cartão não encontrado!', 'danger')
        return redirect(url_for('cartoes.lista'))
    
    return render_template('cartoes/editar.html', cartao=cartao)


@bp.route('/bloquear/<int:id>', methods=['POST'])
@login_required
@admin_required
def bloquear(id):
    """Block/unblock a card brand (toggle ativo status)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get current status
        cursor.execute("SELECT ativo FROM bandeiras_cartao WHERE id = %s", (id,))
        cartao = cursor.fetchone()
        
        if not cartao:
            flash('Cartão não encontrado!', 'danger')
            return redirect(url_for('cartoes.lista'))
        
        # Toggle status
        novo_status = 0 if cartao['ativo'] else 1
        cursor.execute("""
            UPDATE bandeiras_cartao 
            SET ativo = %s
            WHERE id = %s
        """, (novo_status, id))
        conn.commit()
        cursor.close()
        conn.close()
        
        status_text = 'desbloqueado' if novo_status else 'bloqueado'
        flash(f'Cartão {status_text} com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao alterar status do cartão: {str(e)}', 'danger')
    
    return redirect(url_for('cartoes.lista'))
