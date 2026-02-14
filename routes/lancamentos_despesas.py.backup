from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime
from decimal import Decimal

bp = Blueprint('lancamentos_despesas', __name__, url_prefix='/lancamentos_despesas')


def parse_brazilian_currency(value_str):
    """
    Convert Brazilian currency format to Decimal.
    Examples: '1.500,00' -> 1500.00, '150000' -> 1500.00
    
    Args:
        value_str: String value in Brazilian format
        
    Returns:
        Decimal: Parsed decimal value
    """
    if not value_str:
        return Decimal('0')
    
    # Remove espaços
    value_str = str(value_str).strip()
    
    # Remove o símbolo R$ se existir
    value_str = value_str.replace('R$', '').strip()
    
    # Remove pontos (separador de milhares)
    value_str = value_str.replace('.', '')
    
    # Substitui vírgula por ponto (separador decimal)
    value_str = value_str.replace(',', '.')
    
    return Decimal(value_str)


def validate_lancamento_input(data, titulo_id, categoria_id, valor):
    """
    Validate lancamento input fields.
    
    Args:
        data: Date string
        titulo_id: Titulo ID
        categoria_id: Categoria ID
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
    
    if not titulo_id:
        errors.append('Título é obrigatório!')
    else:
        try:
            int(titulo_id)
        except (ValueError, TypeError):
            errors.append('Título inválido!')
    
    if not categoria_id:
        errors.append('Categoria é obrigatória!')
    else:
        try:
            int(categoria_id)
        except (ValueError, TypeError):
            errors.append('Categoria inválida!')
    
    if not valor:
        errors.append('Valor é obrigatório!')
    else:
        try:
            val = parse_brazilian_currency(valor)
            if val <= 0:
                errors.append('Valor deve ser maior que zero!')
        except:
            errors.append('Valor inválido!')
    
    return len(errors) == 0, errors


@bp.route('/')
@login_required
@admin_required
def lista():
    """List all lancamentos de despesas"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get filter parameters
        data_inicio = request.args.get('data_inicio', '')
        data_fim = request.args.get('data_fim', '')
        titulo_id = request.args.get('titulo_id', '')
        categoria_id = request.args.get('categoria_id', '')
        
        # Base query
        query = """
            SELECT ld.*, 
                   t.nome as titulo_nome,
                   c.nome as categoria_nome,
                   s.nome as subcategoria_nome
            FROM lancamentos_despesas ld
            INNER JOIN titulos_despesas t ON ld.titulo_id = t.id
            INNER JOIN categorias_despesas c ON ld.categoria_id = c.id
            LEFT JOIN subcategorias_despesas s ON ld.subcategoria_id = s.id
            WHERE 1=1
        """
        params = []
        
        # Apply filters
        if data_inicio:
            query += " AND ld.data >= %s"
            params.append(data_inicio)
        
        if data_fim:
            query += " AND ld.data <= %s"
            params.append(data_fim)
        
        if titulo_id:
            query += " AND ld.titulo_id = %s"
            params.append(titulo_id)
        
        if categoria_id:
            query += " AND ld.categoria_id = %s"
            params.append(categoria_id)
        
        query += " ORDER BY ld.data DESC, ld.id DESC"
        
        cursor.execute(query, params)
        lancamentos = cursor.fetchall()
        
        # Calculate total
        total = sum(lanc['valor'] for lanc in lancamentos) if lancamentos else Decimal('0')
        
        # Get titulos for filter
        cursor.execute("""
            SELECT id, nome 
            FROM titulos_despesas 
            WHERE ativo = 1 
            ORDER BY ordem, nome
        """)
        titulos = cursor.fetchall()
        
        # Get categorias for filter (if titulo selected)
        categorias = []
        if titulo_id:
            cursor.execute("""
                SELECT id, nome 
                FROM categorias_despesas 
                WHERE titulo_id = %s AND ativo = 1 
                ORDER BY ordem, nome
            """, (titulo_id,))
            categorias = cursor.fetchall()
        
        return render_template('lancamentos_despesas/lista.html', 
                             lancamentos=lancamentos,
                             total=total,
                             titulos=titulos,
                             categorias=categorias,
                             filtros={
                                 'data_inicio': data_inicio,
                                 'data_fim': data_fim,
                                 'titulo_id': titulo_id,
                                 'categoria_id': categoria_id
                             })
    except Exception as e:
        flash(f'Erro ao listar lançamentos: {str(e)}', 'danger')
        return render_template('lancamentos_despesas/lista.html', 
                             lancamentos=[],
                             total=Decimal('0'),
                             titulos=[],
                             categorias=[],
                             filtros={})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create new lancamento"""
    conn = None
    cursor = None
    
    if request.method == 'POST':
        try:
            # Get form data
            data = request.form.get('data')
            titulo_id = request.form.get('titulo_id')
            categoria_id = request.form.get('categoria_id')
            subcategoria_id = request.form.get('subcategoria_id')
            valor = request.form.get('valor')
            fornecedor = request.form.get('fornecedor')
            observacao = request.form.get('observacao')
            
            # Validate
            is_valid, errors = validate_lancamento_input(data, titulo_id, categoria_id, valor)
            
            if not is_valid:
                for error in errors:
                    flash(error, 'danger')
                return redirect(url_for('lancamentos_despesas.novo'))
            
            # Parse valor
            valor_decimal = parse_brazilian_currency(valor)
            
            # Convert empty subcategoria to None
            subcategoria_id = int(subcategoria_id) if subcategoria_id and subcategoria_id.strip() else None
            
            # Insert
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO lancamentos_despesas 
                (data, titulo_id, categoria_id, subcategoria_id, valor, fornecedor, observacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (data, titulo_id, categoria_id, subcategoria_id, valor_decimal, fornecedor, observacao))
            
            conn.commit()
            
            flash('Lançamento criado com sucesso!', 'success')
            return redirect(url_for('lancamentos_despesas.lista'))
            
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao criar lançamento: {str(e)}', 'danger')
            return redirect(url_for('lancamentos_despesas.novo'))
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    # GET - Show form
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get titulos
        cursor.execute("""
            SELECT id, nome 
            FROM titulos_despesas 
            WHERE ativo = 1 
            ORDER BY ordem, nome
        """)
        titulos = cursor.fetchall()
        
        # Get today's date
        data_hoje = datetime.now().strftime('%Y-%m-%d')
        
        return render_template('lancamentos_despesas/novo.html', 
                             titulos=titulos,
                             data_hoje=data_hoje)
    except Exception as e:
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_despesas.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit lancamento"""
    conn = None
    cursor = None
    
    if request.method == 'POST':
        try:
            # Get form data
            data = request.form.get('data')
            titulo_id = request.form.get('titulo_id')
            categoria_id = request.form.get('categoria_id')
            subcategoria_id = request.form.get('subcategoria_id')
            valor = request.form.get('valor')
            fornecedor = request.form.get('fornecedor')
            observacao = request.form.get('observacao')
            
            # Validate
            is_valid, errors = validate_lancamento_input(data, titulo_id, categoria_id, valor)
            
            if not is_valid:
                for error in errors:
                    flash(error, 'danger')
                return redirect(url_for('lancamentos_despesas.editar', id=id))
            
            # Parse valor
            valor_decimal = parse_brazilian_currency(valor)
            
            # Convert empty subcategoria to None
            subcategoria_id = int(subcategoria_id) if subcategoria_id and subcategoria_id.strip() else None
            
            # Update
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE lancamentos_despesas 
                SET data = %s, 
                    titulo_id = %s, 
                    categoria_id = %s, 
                    subcategoria_id = %s, 
                    valor = %s, 
                    fornecedor = %s, 
                    observacao = %s
                WHERE id = %s
            """, (data, titulo_id, categoria_id, subcategoria_id, valor_decimal, fornecedor, observacao, id))
            
            conn.commit()
            
            flash('Lançamento atualizado com sucesso!', 'success')
            return redirect(url_for('lancamentos_despesas.lista'))
            
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao atualizar lançamento: {str(e)}', 'danger')
            return redirect(url_for('lancamentos_despesas.editar', id=id))
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    # GET - Show form
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get lancamento
        cursor.execute("""
            SELECT ld.*,
                   t.nome as titulo_nome,
                   c.nome as categoria_nome,
                   s.nome as subcategoria_nome
            FROM lancamentos_despesas ld
            INNER JOIN titulos_despesas t ON ld.titulo_id = t.id
            INNER JOIN categorias_despesas c ON ld.categoria_id = c.id
            LEFT JOIN subcategorias_despesas s ON ld.subcategoria_id = s.id
            WHERE ld.id = %s
        """, (id,))
        lancamento = cursor.fetchone()
        
        if not lancamento:
            flash('Lançamento não encontrado!', 'danger')
            return redirect(url_for('lancamentos_despesas.lista'))
        
        # Get titulos
        cursor.execute("""
            SELECT id, nome 
            FROM titulos_despesas 
            WHERE ativo = 1 
            ORDER BY ordem, nome
        """)
        titulos = cursor.fetchall()
        
        # Get categorias for selected titulo
        cursor.execute("""
            SELECT id, nome 
            FROM categorias_despesas 
            WHERE titulo_id = %s AND ativo = 1 
            ORDER BY ordem, nome
        """, (lancamento['titulo_id'],))
        categorias = cursor.fetchall()
        
        # Get subcategorias for selected categoria
        cursor.execute("""
            SELECT id, nome 
            FROM subcategorias_despesas 
            WHERE categoria_id = %s AND ativo = 1 
            ORDER BY ordem, nome
        """, (lancamento['categoria_id'],))
        subcategorias = cursor.fetchall()
        
        return render_template('lancamentos_despesas/editar.html', 
                             lancamento=lancamento,
                             titulos=titulos,
                             categorias=categorias,
                             subcategorias=subcategorias)
    except Exception as e:
        flash(f'Erro ao carregar lançamento: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_despesas.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    """Delete lancamento"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM lancamentos_despesas WHERE id = %s", (id,))
        conn.commit()
        
        flash('Lançamento excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir lançamento: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    return redirect(url_for('lancamentos_despesas.lista'))


# API endpoints for dynamic form loading

@bp.route('/api/categorias/<int:titulo_id>')
@login_required
@admin_required
def api_categorias(titulo_id):
    """Get categorias for a titulo (JSON)"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, nome 
            FROM categorias_despesas 
            WHERE titulo_id = %s AND ativo = 1 
            ORDER BY ordem, nome
        """, (titulo_id,))
        categorias = cursor.fetchall()
        
        return jsonify(categorias)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/api/subcategorias/<int:categoria_id>')
@login_required
@admin_required
def api_subcategorias(categoria_id):
    """Get subcategorias for a categoria (JSON)"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, nome 
            FROM subcategorias_despesas 
            WHERE categoria_id = %s AND ativo = 1 
            ORDER BY ordem, nome
        """, (categoria_id,))
        subcategorias = cursor.fetchall()
        
        return jsonify(subcategorias)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
