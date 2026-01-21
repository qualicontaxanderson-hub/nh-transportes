from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('cartoes', __name__, url_prefix='/cartoes')


@bp.route('/')
@login_required
def lista():
    """List all card brands"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM bandeiras_cartao ORDER BY tipo, nome")
        cartoes = cursor.fetchall()
        return render_template('cartoes/lista.html', cartoes=cartoes)
    except Exception as e:
        flash(f'Erro ao carregar cartões: {str(e)}', 'danger')
        return render_template('cartoes/lista.html', cartoes=[])
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create a new card brand"""
    if request.method == 'POST':
        # Normalize input values
        nome = (request.form.get('nome', '') or '').strip()
        tipo = (request.form.get('tipo', '') or '').strip()
        ativo = request.form.get('ativo', '1')

        validation_errors = []

        if not nome:
            validation_errors.append('Nome é obrigatório e não pode conter apenas espaços em branco.')
        elif len(nome) > 50:
            validation_errors.append('Nome deve ter no máximo 50 caracteres.')

        valid_tipos = {'DEBITO', 'CREDITO'}
        if not tipo:
            validation_errors.append('Tipo é obrigatório!')
        elif tipo not in valid_tipos:
            validation_errors.append('Tipo inválido! Selecione DEBITO ou CREDITO.')

        if validation_errors:
            for message in validation_errors:
                flash(message, 'danger')
            return render_template('cartoes/novo.html', nome=nome, tipo=tipo, ativo=ativo)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bandeiras_cartao (nome, tipo, ativo)
                VALUES (%s, %s, %s)
            """, (nome, tipo, int(ativo)))
            conn.commit()
            flash('Cartão cadastrado com sucesso!', 'success')
            return redirect(url_for('cartoes.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar cartão: {str(e)}', 'danger')
            return render_template('cartoes/novo.html', nome=nome, tipo=tipo, ativo=ativo)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return render_template('cartoes/novo.html')


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit an existing card brand"""
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Normalize input values
            nome = (request.form.get('nome', '') or '').strip()
            tipo = (request.form.get('tipo', '') or '').strip()
            ativo = request.form.get('ativo', '1')

            validation_errors = []

            if not nome:
                validation_errors.append('Nome é obrigatório e não pode conter apenas espaços em branco.')
            elif len(nome) > 50:
                validation_errors.append('Nome deve ter no máximo 50 caracteres.')

            valid_tipos = {'DEBITO', 'CREDITO'}
            if not tipo:
                validation_errors.append('Tipo é obrigatório!')
            elif tipo not in valid_tipos:
                validation_errors.append('Tipo inválido! Selecione DEBITO ou CREDITO.')

            if validation_errors:
                for message in validation_errors:
                    flash(message, 'danger')
                cursor.execute("SELECT * FROM bandeiras_cartao WHERE id = %s", (id,))
                cartao = cursor.fetchone()
                return render_template('cartoes/editar.html', cartao=cartao)

            cursor.execute("""
                UPDATE bandeiras_cartao 
                SET nome = %s,
                    tipo = %s,
                    ativo = %s
                WHERE id = %s
            """, (nome, tipo, int(ativo), id))
            conn.commit()
            flash('Cartão atualizado com sucesso!', 'success')
            return redirect(url_for('cartoes.lista'))

        cursor.execute("SELECT * FROM bandeiras_cartao WHERE id = %s", (id,))
        cartao = cursor.fetchone()
        
        if not cartao:
            flash('Cartão não encontrado!', 'danger')
            return redirect(url_for('cartoes.lista'))
        
        return render_template('cartoes/editar.html', cartao=cartao)
    except Exception as e:
        flash(f'Erro ao atualizar cartão: {str(e)}', 'danger')
        return redirect(url_for('cartoes.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/bloquear/<int:id>', methods=['POST'])
@login_required
@admin_required
def bloquear(id):
    """Block/unblock a card brand (toggle ativo status)"""
    conn = None
    cursor = None
    
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
        
        status_text = 'desbloqueado' if novo_status else 'bloqueado'
        flash(f'Cartão {status_text} com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao alterar status do cartão: {str(e)}', 'danger')
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    
    return redirect(url_for('cartoes.lista'))
