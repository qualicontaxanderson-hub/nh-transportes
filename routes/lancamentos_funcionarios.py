from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime, timedelta
import calendar

bp = Blueprint('lancamentos_funcionarios', __name__, url_prefix='/lancamentos-funcionarios')

def get_previous_month():
    """Get previous month in MMM/YYYY format"""
    today = datetime.now()
    first_day = today.replace(day=1)
    last_month = first_day - timedelta(days=1)
    month_abbr = calendar.month_abbr[last_month.month].upper()
    return f"{month_abbr}/{last_month.year}"

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get unique months for filtering
    cursor.execute("""
        SELECT DISTINCT mes 
        FROM lancamentos_funcionarios_v2 
        ORDER BY mes DESC
    """)
    meses = cursor.fetchall()
    
    # Get filter parameters
    mes_filtro = request.args.get('mes')
    cliente_filtro = request.args.get('cliente_id')
    
    # Build query
    query = """
        SELECT 
            l.mes,
            l.cliente_id,
            c.nome as cliente_nome,
            COUNT(DISTINCT l.funcionario_id) as total_funcionarios,
            SUM(l.valor) as total_valor,
            l.status_lancamento
        FROM lancamentos_funcionarios_v2 l
        LEFT JOIN clientes c ON l.cliente_id = c.id
        WHERE 1=1
    """
    params = []
    
    if mes_filtro:
        query += " AND l.mes = %s"
        params.append(mes_filtro)
    
    if cliente_filtro:
        query += " AND l.cliente_id = %s"
        params.append(cliente_filtro)
    
    query += " GROUP BY l.mes, l.cliente_id, l.status_lancamento ORDER BY l.mes DESC, c.nome"
    
    cursor.execute(query, params)
    lancamentos = cursor.fetchall()
    
    # Get clients for filter
    cursor.execute("SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome")
    clientes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('lancamentos_funcionarios/lista.html', 
                         lancamentos=lancamentos, 
                         meses=meses, 
                         clientes=clientes,
                         mes_filtro=mes_filtro,
                         cliente_filtro=cliente_filtro)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        mes = request.form.get('mes')
        cliente_id = request.form.get('cliente_id')
        
        # Process each employee's data
        funcionarios_ids = request.form.getlist('funcionario_id[]')
        
        for func_id in funcionarios_ids:
            # Get all rubrica values for this employee
            rubricas = request.form.getlist(f'rubrica_{func_id}[]')
            valores = request.form.getlist(f'valor_{func_id}[]')
            
            for i, rubrica_id in enumerate(rubricas):
                if rubrica_id and valores[i]:
                    valor = float(valores[i]) if valores[i] else 0
                    if valor != 0:
                        cursor.execute("""
                            INSERT INTO lancamentos_funcionarios_v2 (
                                cliente_id, funcionario_id, mes, rubrica_id, valor, 
                                status_lancamento
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            cliente_id,
                            func_id,
                            mes,
                            rubrica_id,
                            valor,
                            'PENDENTE'
                        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        flash('Lançamentos criados com sucesso!', 'success')
        return redirect(url_for('lancamentos_funcionarios.lista'))
    
    # GET request - show form
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get default month (previous month)
    mes_padrao = get_previous_month()
    
    # Get clientes
    cursor.execute("SELECT id, nome FROM clientes WHERE ativo = 1 ORDER BY nome")
    clientes = cursor.fetchall()
    
    # Get all rubricas
    cursor.execute("SELECT * FROM rubricas WHERE ativo = 1 ORDER BY ordem, nome")
    rubricas = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('lancamentos_funcionarios/novo.html', 
                         mes_padrao=mes_padrao,
                         clientes=clientes,
                         rubricas=rubricas)

@bp.route('/get-funcionarios/<int:cliente_id>')
@login_required
def get_funcionarios(cliente_id):
    """API endpoint to get employees by client"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get all active employees for the client
        cursor.execute("""
            SELECT 
                f.id,
                f.nome,
                f.categoria_id,
                f.salario_base,
                c.nome as categoria_nome
            FROM funcionarios f
            LEFT JOIN categorias_funcionarios c ON f.categoria_id = c.id
            WHERE f.ativo = 1 AND (f.cliente_id = %s OR f.cliente_id IS NULL)
            ORDER BY f.nome
        """, (cliente_id,))
        funcionarios = cursor.fetchall()
        
        # Also get motoristas as funcionarios
        cursor.execute("""
            SELECT 
                m.id,
                m.nome,
                'MOTORISTA' as categoria_nome,
                0 as salario_base
            FROM motoristas m
            WHERE m.ativo = 1
            ORDER BY m.nome
        """)
        motoristas = cursor.fetchall()
        
        # Combine both lists
        all_employees = funcionarios + motoristas
        
        return jsonify(all_employees)
    finally:
        cursor.close()
        conn.close()

@bp.route('/get-veiculos/<int:funcionario_id>')
@login_required
def get_veiculos(funcionario_id):
    """API endpoint to get vehicles for a driver"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            v.id,
            v.caminhao,
            v.placa,
            fmv.principal
        FROM funcionariomotoristaveiculos fmv
        INNER JOIN veiculos v ON fmv.veiculo_id = v.id
        WHERE fmv.funcionario_id = %s AND fmv.ativo = 1
        ORDER BY fmv.principal DESC, v.caminhao
    """, (funcionario_id,))
    veiculos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return jsonify(veiculos)

@bp.route('/detalhe/<mes>/<int:cliente_id>')
@login_required
def detalhe(mes, cliente_id):
    """Show detailed view of payroll entries for a specific month and client"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all lancamentos for this month and client
    cursor.execute("""
        SELECT 
            l.*,
            f.nome as funcionario_nome,
            r.nome as rubrica_nome,
            r.tipo as rubrica_tipo,
            v.caminhao
        FROM lancamentos_funcionarios_v2 l
        INNER JOIN funcionarios f ON l.funcionario_id = f.id
        INNER JOIN rubricas r ON l.rubrica_id = r.id
        LEFT JOIN veiculos v ON l.caminhao_id = v.id
        WHERE l.mes = %s AND l.cliente_id = %s
        ORDER BY f.nome, r.ordem
    """, (mes, cliente_id))
    lancamentos = cursor.fetchall()
    
    # Get client name
    cursor.execute("SELECT nome FROM clientes WHERE id = %s", (cliente_id,))
    cliente = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    # Group by employee
    funcionarios_data = {}
    for lanc in lancamentos:
        func_id = lanc['funcionario_id']
        if func_id not in funcionarios_data:
            funcionarios_data[func_id] = {
                'nome': lanc['funcionario_nome'],
                'rubricas': [],
                'total': 0
            }
        funcionarios_data[func_id]['rubricas'].append(lanc)
        
        # Calculate total (positive for benefits, negative for discounts)
        if lanc['rubrica_tipo'] in ['DESCONTO', 'IMPOSTO']:
            funcionarios_data[func_id]['total'] -= float(lanc['valor'])
        else:
            funcionarios_data[func_id]['total'] += float(lanc['valor'])
    
    return render_template('lancamentos_funcionarios/detalhe.html',
                         mes=mes,
                         cliente=cliente,
                         funcionarios_data=funcionarios_data)
