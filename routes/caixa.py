from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required, supervisor_or_admin_required
from utils.text_utils import normalize_text_field

bp = Blueprint('caixa', __name__, url_prefix='/caixa')

# Constants for payment method types
VALID_TIPOS = {
    'DEPOSITO_ESPECIE': 'Depósito em Espécie',
    'DEPOSITO_CHEQUE_VISTA': 'Depósito em Cheque à Vista',
    'DEPOSITO_CHEQUE_PRAZO': 'Depósito em Cheque à Prazo',
    'PIX': 'Recebimento via PIX',
    'PRAZO': 'Prazo',
    'CARTAO': 'Cartões',
    'RETIRADA_PAGAMENTO': 'Retiradas para Pagamento'
}
MAX_NOME_LENGTH = 100


def validate_forma_pagamento_input(nome, tipo):
    """
    Validate payment method input fields.
    
    Args:
        nome: Payment method name
        tipo: Payment method type
        
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
        errors.append('Tipo inválido! Selecione uma opção válida.')
    
    return len(errors) == 0, errors


@bp.route('/')
@login_required
def lista():
    """List all payment methods for cash closure"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM formas_pagamento_caixa ORDER BY nome")
        formas_pagamento = cursor.fetchall()
        
        # Add tipo field if it doesn't exist (for compatibility)
        for forma in formas_pagamento:
            if 'tipo' not in forma or forma['tipo'] is None:
                forma['tipo'] = ''
                forma['tipo_nome'] = ''
            else:
                forma['tipo_nome'] = VALID_TIPOS.get(forma['tipo'], forma['tipo'])
        
        return render_template('caixa/lista.html', formas_pagamento=formas_pagamento, tipos=VALID_TIPOS)
    except Exception as e:
        flash(f'Erro ao carregar formas de pagamento: {str(e)}', 'danger')
        return render_template('caixa/lista.html', formas_pagamento=[], tipos=VALID_TIPOS)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@supervisor_or_admin_required
def novo():
    """Create a new payment method"""
    if request.method == 'POST':
        # Normalize input values
        nome = normalize_text_field(request.form.get('nome', ''))
        tipo = request.form.get('tipo', '')
        ativo = request.form.get('ativo', '1')

        # Basic validation for nome only (tipo might not exist in schema)
        if not nome:
            flash('Nome é obrigatório e não pode conter apenas espaços em branco.', 'danger')
            return render_template('caixa/novo.html', nome=nome, tipo=tipo, ativo=ativo, tipos=VALID_TIPOS)
        
        if len(nome) > MAX_NOME_LENGTH:
            flash(f'Nome deve ter no máximo {MAX_NOME_LENGTH} caracteres.', 'danger')
            return render_template('caixa/novo.html', nome=nome, tipo=tipo, ativo=ativo, tipos=VALID_TIPOS)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if tipo column exists in the table
            cursor.execute("DESCRIBE formas_pagamento_caixa")
            columns = [col[0] for col in cursor.fetchall()]
            has_tipo = 'tipo' in columns
            
            if has_tipo and tipo:
                # Insert with tipo if column exists and tipo is provided
                cursor.execute("""
                    INSERT INTO formas_pagamento_caixa (nome, tipo, ativo)
                    VALUES (%s, %s, %s)
                """, (nome, tipo, int(ativo)))
            else:
                # Insert without tipo if column doesn't exist
                cursor.execute("""
                    INSERT INTO formas_pagamento_caixa (nome, ativo)
                    VALUES (%s, %s)
                """, (nome, int(ativo)))
            
            conn.commit()
            flash('Forma de pagamento cadastrada com sucesso!', 'success')
            return redirect(url_for('caixa.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar forma de pagamento: {str(e)}', 'danger')
            return render_template('caixa/novo.html', nome=nome, tipo=tipo, ativo=ativo, tipos=VALID_TIPOS)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return render_template('caixa/novo.html', tipos=VALID_TIPOS)


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@supervisor_or_admin_required
def editar(id):
    """Edit an existing payment method"""
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Normalize input values
            nome = normalize_text_field(request.form.get('nome', ''))
            tipo = request.form.get('tipo', '')
            ativo = request.form.get('ativo', '1')

            # Basic validation for nome only
            if not nome:
                flash('Nome é obrigatório e não pode conter apenas espaços em branco.', 'danger')
                cursor.execute("SELECT * FROM formas_pagamento_caixa WHERE id = %s", (id,))
                forma_pagamento = cursor.fetchone()
                return render_template('caixa/editar.html', forma_pagamento=forma_pagamento, tipos=VALID_TIPOS)
            
            if len(nome) > MAX_NOME_LENGTH:
                flash(f'Nome deve ter no máximo {MAX_NOME_LENGTH} caracteres.', 'danger')
                cursor.execute("SELECT * FROM formas_pagamento_caixa WHERE id = %s", (id,))
                forma_pagamento = cursor.fetchone()
                return render_template('caixa/editar.html', forma_pagamento=forma_pagamento, tipos=VALID_TIPOS)

            # Check if tipo column exists in the table
            cursor.execute("DESCRIBE formas_pagamento_caixa")
            columns = [col[0] for col in cursor.fetchall()]
            has_tipo = 'tipo' in columns
            
            if has_tipo and tipo:
                # Update with tipo if column exists and tipo is provided
                cursor.execute("""
                    UPDATE formas_pagamento_caixa 
                    SET nome = %s,
                        tipo = %s,
                        ativo = %s
                    WHERE id = %s
                """, (nome, tipo, int(ativo), id))
            else:
                # Update without tipo if column doesn't exist
                cursor.execute("""
                    UPDATE formas_pagamento_caixa 
                    SET nome = %s,
                        ativo = %s
                    WHERE id = %s
                """, (nome, int(ativo), id))
            
            conn.commit()
            flash('Forma de pagamento atualizada com sucesso!', 'success')
            return redirect(url_for('caixa.lista'))

        cursor.execute("SELECT * FROM formas_pagamento_caixa WHERE id = %s", (id,))
        forma_pagamento = cursor.fetchone()
        
        if not forma_pagamento:
            flash('Forma de pagamento não encontrada!', 'danger')
            return redirect(url_for('caixa.lista'))
        
        # Add tipo field if it doesn't exist (for compatibility)
        if 'tipo' not in forma_pagamento:
            forma_pagamento['tipo'] = ''
        
        return render_template('caixa/editar.html', forma_pagamento=forma_pagamento, tipos=VALID_TIPOS)
    except Exception as e:
        flash(f'Erro ao atualizar forma de pagamento: {str(e)}', 'danger')
        return redirect(url_for('caixa.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/bloquear/<int:id>', methods=['POST'])
@login_required
@supervisor_or_admin_required
def bloquear(id):
    """Block/unblock a payment method (toggle ativo status)"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get current status
        cursor.execute("SELECT ativo FROM formas_pagamento_caixa WHERE id = %s", (id,))
        forma_pagamento = cursor.fetchone()
        
        if not forma_pagamento:
            flash('Forma de pagamento não encontrada!', 'danger')
            return redirect(url_for('caixa.lista'))
        
        # Toggle status
        novo_status = 0 if forma_pagamento['ativo'] else 1
        cursor.execute("""
            UPDATE formas_pagamento_caixa 
            SET ativo = %s
            WHERE id = %s
        """, (novo_status, id))
        conn.commit()
        
        status_text = 'desbloqueada' if novo_status else 'bloqueada'
        flash(f'Forma de pagamento {status_text} com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao alterar status da forma de pagamento: {str(e)}', 'danger')
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    
    return redirect(url_for('caixa.lista'))
