from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime
from decimal import Decimal
import calendar
import logging

bp = Blueprint('emprestimos', __name__, url_prefix='/emprestimos')

def parse_brazilian_currency(value_str):
    """Parse Brazilian currency format to Decimal"""
    # Remove thousand separators (.) and replace decimal comma with dot
    cleaned = value_str.replace('.', '').replace(',', '.')
    return Decimal(cleaned)

def calcular_mes_parcela(mes_inicio, numero_parcela):
    """Calculate the month for a given installment number"""
    mes, ano = map(int, mes_inicio.split('/'))
    
    # Add months
    total_months = (ano * 12 + mes - 1) + (numero_parcela - 1)
    ano_resultado = total_months // 12
    mes_resultado = (total_months % 12) + 1
    
    return f"{mes_resultado:02d}/{ano_resultado}"

@bp.route('/')
@login_required
def lista():
    """List all loans"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get filter parameters
    funcionario_filtro = request.args.get('funcionario_id')
    status_filtro = request.args.get('status', 'ATIVO')
    
    # Build query
    query = """
        SELECT 
            e.*,
            f.nome as funcionario_nome,
            c.razao_social as cliente_nome
        FROM emprestimos e
        INNER JOIN funcionarios f ON e.funcionario_id = f.id
        LEFT JOIN clientes c ON e.cliente_id = c.id
        WHERE 1=1
    """
    params = []
    
    if funcionario_filtro:
        query += " AND e.funcionario_id = %s"
        params.append(funcionario_filtro)
    
    if status_filtro:
        query += " AND e.status = %s"
        params.append(status_filtro)
    
    query += " ORDER BY e.criado_em DESC"
    
    cursor.execute(query, params)
    emprestimos = cursor.fetchall()
    
    # Get all funcionarios for filter
    cursor.execute("""
        SELECT id, nome 
        FROM funcionarios 
        WHERE ativo = 1 
        ORDER BY nome
    """)
    funcionarios = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('emprestimos/lista.html',
                         emprestimos=emprestimos,
                         funcionarios=funcionarios,
                         status_filtro=status_filtro)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Create new loan"""
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            funcionario_id = request.form.get('funcionario_id')
            cliente_id = request.form.get('cliente_id')
            data_emprestimo = request.form.get('data_emprestimo')
            mes_inicio_desconto = request.form.get('mes_inicio_desconto')
            descricao = request.form.get('descricao')
            valor_total = parse_brazilian_currency(request.form.get('valor_total'))
            quantidade_parcelas = int(request.form.get('quantidade_parcelas'))
            
            # Calculate installment value
            valor_parcela = valor_total / quantidade_parcelas
            
            # Insert loan
            cursor.execute("""
                INSERT INTO emprestimos (
                    funcionario_id, cliente_id, data_emprestimo, mes_inicio_desconto,
                    descricao, valor_total, quantidade_parcelas, valor_parcela, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                funcionario_id, cliente_id, data_emprestimo, mes_inicio_desconto,
                descricao, valor_total, quantidade_parcelas, valor_parcela, 'ATIVO'
            ))
            
            emprestimo_id = cursor.lastrowid
            
            # Create installments
            for i in range(1, quantidade_parcelas + 1):
                mes_ref = calcular_mes_parcela(mes_inicio_desconto, i)
                cursor.execute("""
                    INSERT INTO emprestimos_parcelas (
                        emprestimo_id, numero_parcela, mes_referencia, valor, pago
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (emprestimo_id, i, mes_ref, valor_parcela, 0))
            
            conn.commit()
            flash('Empréstimo cadastrado com sucesso!', 'success')
            return redirect(url_for('emprestimos.lista'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao cadastrar empréstimo: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()
    
    # GET request - show form
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get funcionarios
    cursor.execute("""
        SELECT id, nome, clienteid
        FROM funcionarios 
        WHERE ativo = 1 
        ORDER BY nome
    """)
    funcionarios = cursor.fetchall()
    
    # Get clientes
    cursor.execute("""
        SELECT id, razao_social as nome 
        FROM clientes 
        ORDER BY razao_social
    """)
    clientes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Default values
    mes_atual = datetime.now()
    mes_inicio_default = f"{mes_atual.month:02d}/{mes_atual.year}"
    
    return render_template('emprestimos/novo.html',
                         funcionarios=funcionarios,
                         clientes=clientes,
                         mes_inicio_default=mes_inicio_default)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edit existing loan"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            status = request.form.get('status')
            descricao = request.form.get('descricao')
            
            cursor.execute("""
                UPDATE emprestimos 
                SET status = %s, descricao = %s, atualizado_em = NOW()
                WHERE id = %s
            """, (status, descricao, id))
            
            conn.commit()
            flash('Empréstimo atualizado com sucesso!', 'success')
            return redirect(url_for('emprestimos.lista'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar empréstimo: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()
    
    # GET request - show form
    cursor.execute("""
        SELECT 
            e.*,
            f.nome as funcionario_nome,
            c.razao_social as cliente_nome
        FROM emprestimos e
        INNER JOIN funcionarios f ON e.funcionario_id = f.id
        LEFT JOIN clientes c ON e.cliente_id = c.id
        WHERE e.id = %s
    """, (id,))
    emprestimo = cursor.fetchone()
    
    if not emprestimo:
        flash('Empréstimo não encontrado', 'danger')
        return redirect(url_for('emprestimos.lista'))
    
    # Get installments
    cursor.execute("""
        SELECT *
        FROM emprestimos_parcelas
        WHERE emprestimo_id = %s
        ORDER BY numero_parcela
    """, (id,))
    parcelas = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('emprestimos/editar.html',
                         emprestimo=emprestimo,
                         parcelas=parcelas)

@bp.route('/get-emprestimos-ativos/<int:funcionario_id>/<mes>')
@login_required
def get_emprestimos_ativos(funcionario_id, mes):
    """API endpoint to get active loans for an employee in a specific month"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get active loans with installments for this month
        cursor.execute("""
            SELECT 
                e.id,
                e.descricao,
                e.valor_total,
                e.quantidade_parcelas,
                p.numero_parcela,
                p.valor as valor_parcela,
                p.pago
            FROM emprestimos e
            INNER JOIN emprestimos_parcelas p ON e.id = p.emprestimo_id
            WHERE e.funcionario_id = %s 
                AND e.status = 'ATIVO'
                AND p.mes_referencia = %s
            ORDER BY e.criado_em
        """, (funcionario_id, mes))
        
        emprestimos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Convert Decimal to float for JSON serialization
        for emp in emprestimos:
            emp['valor_total'] = float(emp['valor_total'])
            emp['valor_parcela'] = float(emp['valor_parcela'])
        
        return jsonify(emprestimos)
        
    except Exception as e:
        logging.error(f"Error in get_emprestimos_ativos: {str(e)}")
        return jsonify([])

@bp.route('/deletar/<int:id>', methods=['POST'])
@login_required
@admin_required
def deletar(id):
    """Delete a loan"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if loan has any paid installments
        cursor.execute("""
            SELECT COUNT(*) as paid_count
            FROM emprestimos_parcelas
            WHERE emprestimo_id = %s AND pago = 1
        """, (id,))
        result = cursor.fetchone()
        
        if result[0] > 0:
            flash('Não é possível excluir empréstimo com parcelas já pagas. Altere o status para CANCELADO.', 'warning')
        else:
            cursor.execute("DELETE FROM emprestimos WHERE id = %s", (id,))
            conn.commit()
            flash('Empréstimo excluído com sucesso!', 'success')
            
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir empréstimo: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('emprestimos.lista'))
