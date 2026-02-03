from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required, nivel_required
from utils.text_utils import normalize_text_field

bp = Blueprint('cartoes', __name__, url_prefix='/cartoes')

# Constants
VALID_TIPOS = {'DEBITO', 'CREDITO'}
MAX_NOME_LENGTH = 50


def validate_card_input(nome, tipo):
    """
    Validate card brand input fields.
    
    Args:
        nome: Card brand name
        tipo: Card type (DEBITO or CREDITO)
        
    Returns:
        tuple: (is_valid, list of error messages)
    """
    errors = []
    
    if not nome:
        errors.append('Nome é obrigatório e não pode conter apenas espaços em branco.')
    elif len(nome) > MAX_NOME_LENGTH:
        errors.append(f'Nome deve ter no máximo {MAX_NOME_LENGTH} caracteres.')
    
    if not tipo:
        errors.append('Tipo é obrigatório!')
    elif tipo not in VALID_TIPOS:
        errors.append('Tipo inválido! Selecione DEBITO ou CREDITO.')
    
    return len(errors) == 0, errors


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
@nivel_required(['ADMIN', 'GERENTE', 'SUPERVISOR'])
def novo():
    """Create a new card brand"""
    if request.method == 'POST':
        # Normalize input values (já converte para maiúsculas)
        nome = normalize_text_field(request.form.get('nome', ''))
        tipo = normalize_text_field(request.form.get('tipo', ''))
        ativo = request.form.get('ativo', '1')

        # Validate input
        is_valid, validation_errors = validate_card_input(nome, tipo)
        
        if not is_valid:
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
@nivel_required(['ADMIN', 'GERENTE', 'SUPERVISOR'])
def editar(id):
    """Edit an existing card brand"""
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Normalize input values (já converte para maiúsculas)
            nome = normalize_text_field(request.form.get('nome', ''))
            tipo = normalize_text_field(request.form.get('tipo', ''))
            ativo = request.form.get('ativo', '1')

            # Validate input
            is_valid, validation_errors = validate_card_input(nome, tipo)
            
            if not is_valid:
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
@nivel_required(['ADMIN', 'GERENTE', 'SUPERVISOR'])
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
