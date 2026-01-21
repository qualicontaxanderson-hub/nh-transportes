from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('receitas', __name__, url_prefix='/receitas')

# Constants
MAX_NOME_LENGTH = 200


def validate_receita_input(nome, cliente_id):
    """
    Validate receita input fields.
    
    Args:
        nome: Receita name
        cliente_id: Client ID
        
    Returns:
        tuple: (is_valid, list of error messages)
    """
    errors = []
    
    if not nome:
        errors.append('Nome é obrigatório e não pode conter apenas espaços em branco.')
    elif len(nome) > MAX_NOME_LENGTH:
        errors.append(f'Nome deve ter no máximo {MAX_NOME_LENGTH} caracteres.')
    
    if not cliente_id:
        errors.append('Cliente é obrigatório!')
    else:
        try:
            int(cliente_id)
        except (ValueError, TypeError):
            errors.append('Cliente inválido!')
    
    return len(errors) == 0, errors


@bp.route('/')
@login_required
def lista():
    """List all receitas"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.*, c.razao_social as cliente_nome
            FROM receitas r
            INNER JOIN clientes c ON r.cliente_id = c.id
            ORDER BY r.nome
        """)
        receitas = cursor.fetchall()
        return render_template('receitas/lista.html', receitas=receitas)
    except Exception as e:
        flash(f'Erro ao carregar receitas: {str(e)}', 'danger')
        return render_template('receitas/lista.html', receitas=[])
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create a new receita"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            # Normalize input values
            nome = (request.form.get('nome', '') or '').strip()
            cliente_id = request.form.get('cliente_id', '')
            ativo = request.form.get('ativo', '1')

            # Validate input
            is_valid, validation_errors = validate_receita_input(nome, cliente_id)
            
            if not is_valid:
                for message in validation_errors:
                    flash(message, 'danger')
                # Get clients for dropdown
                cursor.execute("""
                    SELECT DISTINCT c.* FROM clientes c
                    INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
                    WHERE cp.ativo = 1
                    ORDER BY c.razao_social
                """)
                clientes = cursor.fetchall()
                return render_template('receitas/novo.html', clientes=clientes, nome=nome, cliente_id=cliente_id, ativo=ativo)

            cursor.execute("""
                INSERT INTO receitas (nome, cliente_id, ativo)
                VALUES (%s, %s, %s)
            """, (nome, int(cliente_id), int(ativo)))
            conn.commit()
            flash('Receita cadastrada com sucesso!', 'success')
            return redirect(url_for('receitas.lista'))

        # GET request - load clients for dropdown
        cursor.execute("""
            SELECT DISTINCT c.* FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        return render_template('receitas/novo.html', clientes=clientes)
        
    except Exception as e:
        flash(f'Erro ao cadastrar receita: {str(e)}', 'danger')
        # Try to get clients for re-rendering form
        try:
            cursor.execute("""
                SELECT DISTINCT c.* FROM clientes c
                INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
                WHERE cp.ativo = 1
                ORDER BY c.razao_social
            """)
            clientes = cursor.fetchall()
            return render_template('receitas/novo.html', clientes=clientes)
        except:
            return redirect(url_for('receitas.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit an existing receita"""
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Normalize input values
            nome = (request.form.get('nome', '') or '').strip()
            cliente_id = request.form.get('cliente_id', '')
            ativo = request.form.get('ativo', '1')

            # Validate input
            is_valid, validation_errors = validate_receita_input(nome, cliente_id)
            
            if not is_valid:
                for message in validation_errors:
                    flash(message, 'danger')
                cursor.execute("SELECT * FROM receitas WHERE id = %s", (id,))
                receita = cursor.fetchone()
                cursor.execute("""
                    SELECT DISTINCT c.* FROM clientes c
                    INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
                    WHERE cp.ativo = 1
                    ORDER BY c.razao_social
                """)
                clientes = cursor.fetchall()
                return render_template('receitas/editar.html', receita=receita, clientes=clientes)

            cursor.execute("""
                UPDATE receitas 
                SET nome = %s,
                    cliente_id = %s,
                    ativo = %s
                WHERE id = %s
            """, (nome, int(cliente_id), int(ativo), id))
            conn.commit()
            flash('Receita atualizada com sucesso!', 'success')
            return redirect(url_for('receitas.lista'))

        cursor.execute("SELECT * FROM receitas WHERE id = %s", (id,))
        receita = cursor.fetchone()
        
        if not receita:
            flash('Receita não encontrada!', 'danger')
            return redirect(url_for('receitas.lista'))
        
        cursor.execute("""
            SELECT DISTINCT c.* FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        
        return render_template('receitas/editar.html', receita=receita, clientes=clientes)
    except Exception as e:
        flash(f'Erro ao atualizar receita: {str(e)}', 'danger')
        return redirect(url_for('receitas.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/bloquear/<int:id>', methods=['POST'])
@login_required
@admin_required
def bloquear(id):
    """Block/unblock a receita (toggle ativo status)"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get current status
        cursor.execute("SELECT ativo FROM receitas WHERE id = %s", (id,))
        receita = cursor.fetchone()
        
        if not receita:
            flash('Receita não encontrada!', 'danger')
            return redirect(url_for('receitas.lista'))
        
        # Toggle status
        novo_status = 0 if receita['ativo'] else 1
        cursor.execute("""
            UPDATE receitas 
            SET ativo = %s
            WHERE id = %s
        """, (novo_status, id))
        conn.commit()
        
        status_text = 'desbloqueada' if novo_status else 'bloqueada'
        flash(f'Receita {status_text} com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao alterar status da receita: {str(e)}', 'danger')
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    
    return redirect(url_for('receitas.lista'))
