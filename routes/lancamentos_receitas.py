from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime
from decimal import Decimal

bp = Blueprint('lancamentos_receitas', __name__, url_prefix='/lancamentos_receitas')


def validate_lancamento_input(data, receita_id, valor):
    """
    Validate lancamento input fields.
    
    Args:
        data: Date string
        receita_id: Receita ID
        valor: Value
        
    Returns:
        tuple: (is_valid, list of error messages)
    """
    errors = []
    
    if not data:
        errors.append('Data é obrigatória!')
    else:
        try:
            datetime.strptime(data, '%Y-%m-%d')
        except ValueError:
            errors.append('Data inválida!')
    
    if not receita_id:
        errors.append('Receita é obrigatória!')
    else:
        try:
            int(receita_id)
        except (ValueError, TypeError):
            errors.append('Receita inválida!')
    
    if not valor:
        errors.append('Valor é obrigatório!')
    else:
        try:
            val = Decimal(str(valor).replace(',', '.'))
            if val <= 0:
                errors.append('Valor deve ser maior que zero!')
        except:
            errors.append('Valor inválido!')
    
    return len(errors) == 0, errors


@bp.route('/')
@login_required
def lista():
    """List all lancamentos"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT lr.*, r.nome as receita_nome, c.razao_social as cliente_nome
            FROM lancamentos_receitas lr
            INNER JOIN receitas r ON lr.receita_id = r.id
            INNER JOIN clientes c ON r.cliente_id = c.id
            ORDER BY lr.data DESC, lr.id DESC
        """)
        lancamentos = cursor.fetchall()
        return render_template('lancamentos_receitas/lista.html', lancamentos=lancamentos)
    except Exception as e:
        flash(f'Erro ao carregar lançamentos: {str(e)}', 'danger')
        return render_template('lancamentos_receitas/lista.html', lancamentos=[])
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create a new lancamento"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            # Get input values
            data = request.form.get('data', '')
            receita_id = request.form.get('receita_id', '')
            valor = request.form.get('valor', '')
            observacao = request.form.get('observacao', '').strip()

            # Validate input
            is_valid, validation_errors = validate_lancamento_input(data, receita_id, valor)
            
            if not is_valid:
                for message in validation_errors:
                    flash(message, 'danger')
                # Get receitas for dropdown
                cursor.execute("""
                    SELECT r.*, c.razao_social as cliente_nome
                    FROM receitas r
                    INNER JOIN clientes c ON r.cliente_id = c.id
                    WHERE r.ativo = 1
                    ORDER BY r.nome
                """)
                receitas = cursor.fetchall()
                return render_template('lancamentos_receitas/novo.html', receitas=receitas, 
                                     data=data, receita_id=receita_id, valor=valor, observacao=observacao)

            # Convert value to decimal
            valor_decimal = Decimal(str(valor).replace(',', '.'))
            
            cursor.execute("""
                INSERT INTO lancamentos_receitas (data, receita_id, valor, observacao)
                VALUES (%s, %s, %s, %s)
            """, (data, int(receita_id), float(valor_decimal), observacao if observacao else None))
            conn.commit()
            flash('Lançamento cadastrado com sucesso!', 'success')
            return redirect(url_for('lancamentos_receitas.lista'))

        # GET request - load receitas for dropdown
        cursor.execute("""
            SELECT r.*, c.razao_social as cliente_nome
            FROM receitas r
            INNER JOIN clientes c ON r.cliente_id = c.id
            WHERE r.ativo = 1
            ORDER BY r.nome
        """)
        receitas = cursor.fetchall()
        
        # Default to today's date
        hoje = datetime.now().strftime('%Y-%m-%d')
        return render_template('lancamentos_receitas/novo.html', receitas=receitas, data=hoje)
        
    except Exception as e:
        flash(f'Erro ao cadastrar lançamento: {str(e)}', 'danger')
        # Try to get receitas for re-rendering form
        try:
            cursor.execute("""
                SELECT r.*, c.razao_social as cliente_nome
                FROM receitas r
                INNER JOIN clientes c ON r.cliente_id = c.id
                WHERE r.ativo = 1
                ORDER BY r.nome
            """)
            receitas = cursor.fetchall()
            return render_template('lancamentos_receitas/novo.html', receitas=receitas)
        except:
            return redirect(url_for('lancamentos_receitas.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit an existing lancamento"""
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Get input values
            data = request.form.get('data', '')
            receita_id = request.form.get('receita_id', '')
            valor = request.form.get('valor', '')
            observacao = request.form.get('observacao', '').strip()

            # Validate input
            is_valid, validation_errors = validate_lancamento_input(data, receita_id, valor)
            
            if not is_valid:
                for message in validation_errors:
                    flash(message, 'danger')
                cursor.execute("SELECT * FROM lancamentos_receitas WHERE id = %s", (id,))
                lancamento = cursor.fetchone()
                cursor.execute("""
                    SELECT r.*, c.razao_social as cliente_nome
                    FROM receitas r
                    INNER JOIN clientes c ON r.cliente_id = c.id
                    WHERE r.ativo = 1
                    ORDER BY r.nome
                """)
                receitas = cursor.fetchall()
                return render_template('lancamentos_receitas/editar.html', lancamento=lancamento, receitas=receitas)

            # Convert value to decimal
            valor_decimal = Decimal(str(valor).replace(',', '.'))
            
            cursor.execute("""
                UPDATE lancamentos_receitas 
                SET data = %s,
                    receita_id = %s,
                    valor = %s,
                    observacao = %s
                WHERE id = %s
            """, (data, int(receita_id), float(valor_decimal), observacao if observacao else None, id))
            conn.commit()
            flash('Lançamento atualizado com sucesso!', 'success')
            return redirect(url_for('lancamentos_receitas.lista'))

        cursor.execute("SELECT * FROM lancamentos_receitas WHERE id = %s", (id,))
        lancamento = cursor.fetchone()
        
        if not lancamento:
            flash('Lançamento não encontrado!', 'danger')
            return redirect(url_for('lancamentos_receitas.lista'))
        
        cursor.execute("""
            SELECT r.*, c.razao_social as cliente_nome
            FROM receitas r
            INNER JOIN clientes c ON r.cliente_id = c.id
            WHERE r.ativo = 1
            ORDER BY r.nome
        """)
        receitas = cursor.fetchall()
        
        return render_template('lancamentos_receitas/editar.html', lancamento=lancamento, receitas=receitas)
    except Exception as e:
        flash(f'Erro ao atualizar lançamento: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_receitas.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    """Delete a lancamento"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM lancamentos_receitas WHERE id = %s", (id,))
        conn.commit()
        
        flash('Lançamento excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir lançamento: {str(e)}', 'danger')
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    
    return redirect(url_for('lancamentos_receitas.lista'))
