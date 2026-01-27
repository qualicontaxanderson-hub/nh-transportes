from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime
from decimal import Decimal
import json

bp = Blueprint('lancamentos_caixa', __name__, url_prefix='/lancamentos_caixa')


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
    
    # Check if there's a comma (Brazilian decimal separator)
    if ',' in value_str:
        # Remove pontos (separador de milhares)
        value_str = value_str.replace('.', '')
        # Substitui vírgula por ponto (separador decimal)
        value_str = value_str.replace(',', '.')
    # If no comma but has dots, assume it's already in English format
    
    return Decimal(value_str)


@bp.route('/')
@login_required
def lista():
    """List all cash closure entries"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Default to current month if no filters provided
        from datetime import date
        hoje = date.today()
        primeiro_dia_mes = hoje.replace(day=1)
        data_inicio_default = primeiro_dia_mes.strftime('%Y-%m-%d')
        data_fim_default = hoje.strftime('%Y-%m-%d')
        
        # Get filters from query string
        filtros = {
            'data_inicio': request.args.get('data_inicio', data_inicio_default),
            'data_fim': request.args.get('data_fim', data_fim_default),
            'cliente_id': request.args.get('cliente_id', '')
        }
        
        # Check if table exists first and determine schema
        has_new_schema = False
        try:
            cursor.execute("DESCRIBE lancamentos_caixa")
            describe_results = cursor.fetchall()
            # With dictionary=True, DESCRIBE returns dicts with 'Field' key
            columns = [col['Field'] for col in describe_results]
            
            # Determine if this is the new schema
            has_new_schema = 'usuario_id' in columns and 'data' in columns and 'total_receitas' in columns
            
        except Exception as table_error:
            # Table doesn't exist at all
            if "doesn't exist" in str(table_error) or "1146" in str(table_error):
                return render_template('lancamentos_caixa/lista.html', 
                                     lancamentos=[],
                                     filtros=filtros,
                                     clientes=[],
                                     resumo={},
                                     has_new_schema=False,
                                     table_exists=False)
            else:
                raise  # Re-raise if it's a different error
        
        # Build query based on available columns with filters
        if has_new_schema:
            # Build filter conditions
            where_conditions = []
            params = []
            
            if filtros['data_inicio']:
                where_conditions.append("lc.data >= %s")
                params.append(filtros['data_inicio'])
            if filtros['data_fim']:
                where_conditions.append("lc.data <= %s")
                params.append(filtros['data_fim'])
            if filtros['cliente_id']:
                where_conditions.append("lc.cliente_id = %s")
                params.append(int(filtros['cliente_id']))
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # New schema with usuario_id and data
            cursor.execute(f"""
                SELECT lc.*, u.username as usuario_nome, c.razao_social as cliente_nome
                FROM lancamentos_caixa lc
                LEFT JOIN usuarios u ON lc.usuario_id = u.id
                LEFT JOIN clientes c ON lc.cliente_id = c.id
                {where_clause}
                ORDER BY lc.data DESC, lc.id DESC
            """, tuple(params))
        elif 'data_movimento' in columns:
            # Existing schema with data_movimento
            cursor.execute("""
                SELECT lc.*
                FROM lancamentos_caixa lc
                ORDER BY lc.data_movimento DESC, lc.id DESC
                LIMIT 100
            """)
        else:
            # Fallback - just get recent records
            cursor.execute("""
                SELECT * FROM lancamentos_caixa
                ORDER BY id DESC
                LIMIT 100
            """)
        
        lancamentos = cursor.fetchall()
        
        # Calculate summary
        resumo = {
            'total_receitas': Decimal('0'),
            'total_comprovacao': Decimal('0'),
            'total_diferenca': Decimal('0')
        }
        
        if has_new_schema and lancamentos:
            for lanc in lancamentos:
                if lanc.get('total_receitas') is not None:
                    resumo['total_receitas'] += Decimal(str(lanc['total_receitas']))
                if lanc.get('total_comprovacao') is not None:
                    resumo['total_comprovacao'] += Decimal(str(lanc['total_comprovacao']))
                if lanc.get('diferenca') is not None:
                    resumo['total_diferenca'] += Decimal(str(lanc['diferenca']))
        
        # Get clients for filter
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        
        return render_template('lancamentos_caixa/lista.html', 
                             lancamentos=lancamentos,
                             filtros=filtros,
                             clientes=clientes,
                             resumo=resumo,
                             has_new_schema=has_new_schema,
                             table_exists=True)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in lancamentos_caixa lista: {error_details}")  # Log to console
        # Don't show the error message to user if table doesn't exist - that's expected
        if "doesn't exist" not in str(e) and "1146" not in str(e):
            flash(f'Erro ao carregar lançamentos de caixa: {str(e)}', 'danger')
        return render_template('lancamentos_caixa/lista.html', 
                             lancamentos=[],
                             filtros={'data_inicio': '', 'data_fim': '', 'cliente_id': ''},
                             clientes=[],
                             resumo={},
                             has_new_schema=False,
                             table_exists=False)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/api/vendas_dia', methods=['GET'])
@login_required
def get_vendas_dia():
    """API endpoint to get sales totals for a specific date and client"""
    conn = None
    cursor = None
    
    try:
        cliente_id = request.args.get('cliente_id')
        data = request.args.get('data')
        
        if not cliente_id or not data:
            return jsonify({'error': 'cliente_id e data são obrigatórios'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        result = {
            'vendas_posto': 0,
            'arla': 0,
            'lubrificantes': 0
        }
        
        # Get Vendas Posto total
        cursor.execute("""
            SELECT COALESCE(SUM(valor_total), 0) as total
            FROM vendas_posto
            WHERE cliente_id = %s AND data_movimento = %s
        """, (cliente_id, data))
        vendas_posto = cursor.fetchone()
        if vendas_posto:
            result['vendas_posto'] = float(vendas_posto['total'])
        
        # Get ARLA total (quantidade_vendida * preco_venda_aplicado)
        cursor.execute("""
            SELECT COALESCE(SUM(quantidade_vendida * preco_venda_aplicado), 0) as total
            FROM arla_lancamentos
            WHERE cliente_id = %s AND data = %s
        """, (cliente_id, data))
        arla = cursor.fetchone()
        if arla:
            result['arla'] = float(arla['total'])
        
        # Get Lubrificantes total (check if lubrificantes_lancamentos exists)
        try:
            cursor.execute("""
                SELECT COALESCE(SUM(valor_total), 0) as total
                FROM lubrificantes_lancamentos
                WHERE clienteid = %s AND data = %s
            """, (cliente_id, data))
            lubr = cursor.fetchone()
            if lubr:
                result['lubrificantes'] = float(lubr['total'])
        except:
            # Table doesn't exist or has different structure, leave as 0
            pass
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create a new cash closure entry"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Check which columns exist in the table
        cursor.execute("DESCRIBE lancamentos_caixa")
        describe_results = cursor.fetchall()
        columns = [col['Field'] for col in describe_results]
        has_new_schema = 'usuario_id' in columns and 'data' in columns and 'total_receitas' in columns
        
        if not has_new_schema:
            flash('Esta funcionalidade requer a execução da migration SQL. O schema atual do banco não é compatível com o sistema de Fechamento de Caixa.', 'warning')
            return redirect(url_for('lancamentos_caixa.lista'))
        
        if request.method == 'POST':
            # Get main data
            data = request.form.get('data', '')
            cliente_id = request.form.get('cliente_id', '')
            observacao = request.form.get('observacao', '').strip()
            
            # Get receitas (left side) - JSON encoded
            receitas_json = request.form.get('receitas', '[]')
            receitas = json.loads(receitas_json)
            
            # Get comprovacoes (right side) - JSON encoded
            comprovacoes_json = request.form.get('comprovacoes', '[]')
            comprovacoes = json.loads(comprovacoes_json)
            
            # Validate
            if not data:
                flash('Data é obrigatória!', 'danger')
                raise ValueError('Data não fornecida')
            
            if not cliente_id:
                flash('Cliente é obrigatório!', 'danger')
                raise ValueError('Cliente não fornecido')
            
            # Calculate totals: Diferença = Total Comprovação - Total Receitas
            total_receitas = sum(parse_brazilian_currency(r.get('valor', 0)) for r in receitas)
            total_comprovacao = sum(parse_brazilian_currency(c.get('valor', 0)) for c in comprovacoes)
            diferenca = total_comprovacao - total_receitas
            
            # Insert lancamento_caixa
            cursor.execute("""
                INSERT INTO lancamentos_caixa 
                (data, cliente_id, usuario_id, observacao, total_receitas, total_comprovacao, diferenca, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'ABERTO')
            """, (data, int(cliente_id), current_user.id, observacao if observacao else None, 
                  float(total_receitas), float(total_comprovacao), float(diferenca)))
            
            lancamento_id = cursor.lastrowid
            
            # Insert receitas
            for receita in receitas:
                if receita.get('tipo') and receita.get('valor'):
                    cursor.execute("""
                        INSERT INTO lancamentos_caixa_receitas 
                        (lancamento_caixa_id, tipo, descricao, valor)
                        VALUES (%s, %s, %s, %s)
                    """, (lancamento_id, receita['tipo'], 
                          receita.get('descricao', ''), 
                          float(parse_brazilian_currency(receita['valor']))))
            
            # Insert comprovacoes
            for comprovacao in comprovacoes:
                if comprovacao.get('forma_pagamento_id') and comprovacao.get('valor'):
                    forma_id = comprovacao['forma_pagamento_id']
                    cartao_id = comprovacao.get('bandeira_cartao_id')
                    
                    cursor.execute("""
                        INSERT INTO lancamentos_caixa_comprovacao 
                        (lancamento_caixa_id, forma_pagamento_id, bandeira_cartao_id, descricao, valor)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (lancamento_id, 
                          int(forma_id) if forma_id and forma_id != '' else None,
                          int(cartao_id) if cartao_id and cartao_id != '' else None,
                          comprovacao.get('descricao', ''),
                          float(parse_brazilian_currency(comprovacao['valor']))))
            
            conn.commit()
            flash('Lançamento de caixa cadastrado com sucesso!', 'success')
            return redirect(url_for('lancamentos_caixa.lista'))

        # GET request - load data for dropdown
        # Get clients with "Produtos Posto" configured
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        
        # Get payment methods
        cursor.execute("SELECT * FROM formas_pagamento_caixa WHERE ativo = 1 ORDER BY nome")
        formas_pagamento = cursor.fetchall()
        
        # Get card brands
        cursor.execute("SELECT * FROM bandeiras_cartao WHERE ativo = 1 ORDER BY nome")
        cartoes = cursor.fetchall()
        
        # Get receipt types from database
        cursor.execute("SELECT * FROM tipos_receita_caixa WHERE ativo = 1 ORDER BY nome")
        tipos_receita = cursor.fetchall()
        
        # Get last closure date to suggest next date
        cursor.execute("""
            SELECT MAX(data) as ultima_data 
            FROM lancamentos_caixa
        """)
        ultima_data_row = cursor.fetchone()
        
        # Suggest next date
        if ultima_data_row and ultima_data_row['ultima_data']:
            from datetime import timedelta
            ultima_data = ultima_data_row['ultima_data']
            proxima_data = (ultima_data + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            # Default to today's date
            proxima_data = datetime.now().strftime('%Y-%m-%d')
        
        return render_template('lancamentos_caixa/novo.html', 
                             clientes=clientes,
                             formas_pagamento=formas_pagamento,
                             cartoes=cartoes,
                             tipos_receita=tipos_receita,
                             data=proxima_data)
        
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar lançamento de caixa: {str(e)}', 'danger')
        # Try to get data for re-rendering form
        try:
            cursor.execute("""
                SELECT DISTINCT c.id, c.razao_social 
                FROM clientes c
                INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
                WHERE cp.ativo = 1
                ORDER BY c.razao_social
            """)
            clientes = cursor.fetchall()
            cursor.execute("SELECT * FROM formas_pagamento_caixa WHERE ativo = 1 ORDER BY nome")
            formas_pagamento = cursor.fetchall()
            cursor.execute("SELECT * FROM bandeiras_cartao WHERE ativo = 1 ORDER BY nome")
            cartoes = cursor.fetchall()
            cursor.execute("SELECT * FROM tipos_receita_caixa WHERE ativo = 1 ORDER BY nome")
            tipos_receita = cursor.fetchall()
            return render_template('lancamentos_caixa/novo.html', 
                                 clientes=clientes,
                                 formas_pagamento=formas_pagamento,
                                 cartoes=cartoes,
                                 tipos_receita=tipos_receita)
        except:
            return redirect(url_for('lancamentos_caixa.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/visualizar/<int:id>')
@login_required
def visualizar(id):
    """View a cash closure entry"""
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Check which columns exist in the table
        cursor.execute("DESCRIBE lancamentos_caixa")
        describe_results = cursor.fetchall()
        columns = [col['Field'] for col in describe_results]
        has_new_schema = 'usuario_id' in columns and 'data' in columns and 'total_receitas' in columns

        # Get lancamento
        if has_new_schema:
            cursor.execute("""
                SELECT lc.*, u.username as usuario_nome
                FROM lancamentos_caixa lc
                LEFT JOIN usuarios u ON lc.usuario_id = u.id
                WHERE lc.id = %s
            """, (id,))
        else:
            cursor.execute("""
                SELECT * FROM lancamentos_caixa
                WHERE id = %s
            """, (id,))
        
        lancamento = cursor.fetchone()
        
        if not lancamento:
            flash('Lançamento de caixa não encontrado!', 'danger')
            return redirect(url_for('lancamentos_caixa.lista'))
        
        if not has_new_schema:
            flash('Esta funcionalidade de visualização requer a execução da migration SQL. O schema atual não é compatível.', 'warning')
            return redirect(url_for('lancamentos_caixa.lista'))
        
        # Get receitas
        cursor.execute("""
            SELECT * FROM lancamentos_caixa_receitas
            WHERE lancamento_caixa_id = %s
            ORDER BY id
        """, (id,))
        receitas = cursor.fetchall()
        
        # tipo already contains the friendly name from database
        for receita in receitas:
            receita['tipo_nome'] = receita['tipo']
        
        # Get comprovacoes
        cursor.execute("""
            SELECT lcc.*, fpc.nome as forma_pagamento_nome, bc.nome as cartao_nome
            FROM lancamentos_caixa_comprovacao lcc
            LEFT JOIN formas_pagamento_caixa fpc ON lcc.forma_pagamento_id = fpc.id
            LEFT JOIN bandeiras_cartao bc ON lcc.bandeira_cartao_id = bc.id
            WHERE lcc.lancamento_caixa_id = %s
            ORDER BY lcc.id
        """, (id,))
        comprovacoes = cursor.fetchall()
        
        return render_template('lancamentos_caixa/visualizar.html', 
                             lancamento=lancamento, 
                             receitas=receitas,
                             comprovacoes=comprovacoes)
    except Exception as e:
        flash(f'Erro ao visualizar lançamento: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_caixa.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    """Delete a cash closure entry"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete comprovacoes
        cursor.execute("DELETE FROM lancamentos_caixa_comprovacao WHERE lancamento_caixa_id = %s", (id,))
        
        # Delete receitas
        cursor.execute("DELETE FROM lancamentos_caixa_receitas WHERE lancamento_caixa_id = %s", (id,))
        
        # Delete lancamento
        cursor.execute("DELETE FROM lancamentos_caixa WHERE id = %s", (id,))
        
        conn.commit()
        flash('Lançamento de caixa excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir lançamento: {str(e)}', 'danger')
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    
    return redirect(url_for('lancamentos_caixa.lista'))


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit a cash closure entry"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Check which columns exist in the table
        cursor.execute("DESCRIBE lancamentos_caixa")
        describe_results = cursor.fetchall()
        columns = [col['Field'] for col in describe_results]
        has_new_schema = 'usuario_id' in columns and 'data' in columns and 'total_receitas' in columns
        
        if not has_new_schema:
            flash('Esta funcionalidade requer a execução da migration SQL. O schema atual do banco não é compatível com o sistema de Fechamento de Caixa.', 'warning')
            return redirect(url_for('lancamentos_caixa.lista'))
        
        if request.method == 'POST':
            # Get main data
            data = request.form.get('data', '')
            cliente_id = request.form.get('cliente_id', '')
            observacao = request.form.get('observacao', '').strip()
            
            # Get receitas (left side) - JSON encoded
            receitas_json = request.form.get('receitas', '[]')
            receitas = json.loads(receitas_json)
            
            # Get comprovacoes (right side) - JSON encoded
            comprovacoes_json = request.form.get('comprovacoes', '[]')
            comprovacoes = json.loads(comprovacoes_json)
            
            # Validate
            if not data:
                flash('Data é obrigatória!', 'danger')
                raise ValueError('Data não fornecida')
            
            if not cliente_id:
                flash('Cliente é obrigatório!', 'danger')
                raise ValueError('Cliente não fornecido')
            
            # Calculate totals: Diferença = Total Comprovação - Total Receitas
            total_receitas = sum(parse_brazilian_currency(r.get('valor', 0)) for r in receitas)
            total_comprovacao = sum(parse_brazilian_currency(c.get('valor', 0)) for c in comprovacoes)
            diferenca = total_comprovacao - total_receitas
            
            # Update lancamento_caixa
            cursor.execute("""
                UPDATE lancamentos_caixa 
                SET data = %s, cliente_id = %s, observacao = %s, 
                    total_receitas = %s, total_comprovacao = %s, diferenca = %s
                WHERE id = %s
            """, (data, int(cliente_id), observacao if observacao else None, 
                  float(total_receitas), float(total_comprovacao), float(diferenca), id))
            
            # Delete old receitas and comprovacoes
            cursor.execute("DELETE FROM lancamentos_caixa_receitas WHERE lancamento_caixa_id = %s", (id,))
            cursor.execute("DELETE FROM lancamentos_caixa_comprovacao WHERE lancamento_caixa_id = %s", (id,))
            
            # Insert new receitas
            for receita in receitas:
                if receita.get('tipo') and receita.get('valor'):
                    cursor.execute("""
                        INSERT INTO lancamentos_caixa_receitas 
                        (lancamento_caixa_id, tipo, descricao, valor)
                        VALUES (%s, %s, %s, %s)
                    """, (id, receita['tipo'], 
                          receita.get('descricao', ''), 
                          float(parse_brazilian_currency(receita['valor']))))
            
            # Insert new comprovacoes
            for comprovacao in comprovacoes:
                if comprovacao.get('forma_pagamento_id') and comprovacao.get('valor'):
                    forma_id = comprovacao['forma_pagamento_id']
                    cartao_id = comprovacao.get('bandeira_cartao_id')
                    
                    cursor.execute("""
                        INSERT INTO lancamentos_caixa_comprovacao 
                        (lancamento_caixa_id, forma_pagamento_id, bandeira_cartao_id, descricao, valor)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (id, 
                          int(forma_id) if forma_id and forma_id != '' else None,
                          int(cartao_id) if cartao_id and cartao_id != '' else None,
                          comprovacao.get('descricao', ''),
                          float(parse_brazilian_currency(comprovacao['valor']))))
            
            conn.commit()
            flash('Lançamento de caixa atualizado com sucesso!', 'success')
            return redirect(url_for('lancamentos_caixa.lista'))
        
        # GET request - load existing data
        # Get lancamento
        cursor.execute("""
            SELECT lc.*, c.razao_social as cliente_nome
            FROM lancamentos_caixa lc
            LEFT JOIN clientes c ON lc.cliente_id = c.id
            WHERE lc.id = %s
        """, (id,))
        lancamento = cursor.fetchone()
        
        if not lancamento:
            flash('Lançamento de caixa não encontrado!', 'danger')
            return redirect(url_for('lancamentos_caixa.lista'))
        
        # Get receitas
        cursor.execute("""
            SELECT * FROM lancamentos_caixa_receitas
            WHERE lancamento_caixa_id = %s
            ORDER BY id
        """, (id,))
        receitas = cursor.fetchall()
        
        # Get comprovacoes
        cursor.execute("""
            SELECT lcc.*, fp.nome as forma_pagamento_nome, bc.nome as cartao_nome
            FROM lancamentos_caixa_comprovacao lcc
            LEFT JOIN formas_pagamento_caixa fp ON lcc.forma_pagamento_id = fp.id
            LEFT JOIN bandeiras_cartao bc ON lcc.bandeira_cartao_id = bc.id
            WHERE lcc.lancamento_caixa_id = %s
            ORDER BY lcc.id
        """, (id,))
        comprovacoes = cursor.fetchall()
        
        # Get active clients
        cursor.execute("""
            SELECT c.id, c.razao_social
            FROM clientes c
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        
        # Get payment methods
        cursor.execute("""
            SELECT id, nome, tipo
            FROM formas_pagamento_caixa
            WHERE ativo = 1
            ORDER BY nome
        """)
        formas_pagamento = cursor.fetchall()
        
        # Get card brands
        cursor.execute("""
            SELECT id, nome, tipo
            FROM bandeiras_cartao
            WHERE ativo = 1
            ORDER BY nome
        """)
        bandeiras_cartao = cursor.fetchall()
        
        # Get receipt types
        cursor.execute("""
            SELECT id, nome, tipo
            FROM tipos_receita_caixa
            WHERE ativo = 1
            ORDER BY nome
        """)
        tipos_receita = cursor.fetchall()
        
        # Convert cursor results to plain Python dicts/lists immediately
        # This avoids any special MySQL connector types that can't be serialized
        def convert_to_plain_python(obj):
            """Convert MySQL cursor results to plain Python types"""
            if obj is None:
                return ''
            elif isinstance(obj, Decimal):
                return float(obj)
            elif isinstance(obj, dict):
                # Force conversion to plain dict and clean each value
                result = {}
                for key, value in obj.items():
                    result[str(key)] = convert_to_plain_python(value)
                return result
            elif isinstance(obj, (list, tuple)):
                # Force conversion to plain list and clean each item
                return [convert_to_plain_python(item) for item in obj]
            elif isinstance(obj, (str, int, float, bool)):
                return obj
            elif isinstance(obj, bytes):
                return obj.decode('utf-8', errors='replace')
            else:
                # For ANY other type, convert to string or return empty
                try:
                    str_val = str(obj)
                    # If it's empty or "None" string, return empty string
                    return '' if str_val in ('None', '', 'null') else str_val
                except:
                    return ''
        
        # Convert ALL cursor results immediately to plain Python types
        lancamento_clean = convert_to_plain_python(lancamento)
        receitas_clean = convert_to_plain_python(receitas)
        comprovacoes_clean = convert_to_plain_python(comprovacoes)
        clientes_clean = convert_to_plain_python(clientes)
        formas_pagamento_clean = convert_to_plain_python(formas_pagamento)
        bandeiras_cartao_clean = convert_to_plain_python(bandeiras_cartao)
        tipos_receita_clean = convert_to_plain_python(tipos_receita)
        
        return render_template('lancamentos_caixa/novo.html',
                             edit_mode=True,
                             lancamento=lancamento_clean,
                             receitas=receitas_clean,
                             comprovacoes=comprovacoes_clean,
                             clientes=clientes_clean,
                             formas_pagamento=formas_pagamento_clean,
                             bandeiras_cartao=bandeiras_cartao_clean,
                             tipos_receita=tipos_receita_clean)
        
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar lançamento de caixa: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_caixa.lista'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
