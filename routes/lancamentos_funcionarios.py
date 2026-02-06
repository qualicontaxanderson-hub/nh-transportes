from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime, timedelta
import calendar

bp = Blueprint('lancamentos_funcionarios', __name__, url_prefix='/lancamentos-funcionarios')

def get_previous_month():
    """Get previous month in MM/YYYY format"""
    today = datetime.now()
    first_day = today.replace(day=1)
    last_month = first_day - timedelta(days=1)
    return f"{last_month.month:02d}/{last_month.year}"

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get unique months for filtering
    cursor.execute("""
        SELECT DISTINCT mes 
        FROM lancamentosfuncionarios_v2 
        ORDER BY mes DESC
    """)
    meses = cursor.fetchall()
    
    # Get filter parameters
    mes_filtro = request.args.get('mes')
    cliente_filtro = request.args.get('clienteid')
    
    # Build query
    query = """
        SELECT 
            l.mes,
            l.clienteid,
            c.razao_social as cliente_nome,
            COUNT(DISTINCT l.funcionarioid) as total_funcionarios,
            SUM(l.valor) as total_valor,
            l.statuslancamento
        FROM lancamentosfuncionarios_v2 l
        LEFT JOIN clientes c ON l.clienteid = c.id
        WHERE 1=1
    """
    params = []
    
    if mes_filtro:
        query += " AND l.mes = %s"
        params.append(mes_filtro)
    
    if cliente_filtro:
        query += " AND l.clienteid = %s"
        params.append(cliente_filtro)
    
    query += " GROUP BY l.mes, l.clienteid, l.statuslancamento ORDER BY l.mes DESC, c.razao_social"
    
    cursor.execute(query, params)
    lancamentos = cursor.fetchall()
    
    # Get clients for filter - only those with products configured
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social as nome 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
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
        clienteid = request.form.get('clienteid')
        
        # Process each employee's data
        funcionarios_ids = request.form.getlist('funcionarioid[]')
        
        for func_id in funcionarios_ids:
            # Get all rubrica values for this employee
            rubricas = request.form.getlist(f'rubrica_{func_id}[]')
            valores = request.form.getlist(f'valor_{func_id}[]')
            
            for i, rubricaid in enumerate(rubricas):
                if rubricaid and valores[i]:
                    valor = float(valores[i]) if valores[i] else 0
                    if valor != 0:
                        cursor.execute("""
                            INSERT INTO lancamentosfuncionarios_v2 (
                                clienteid, funcionarioid, mes, rubricaid, valor, 
                                statuslancamento
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE 
                                valor = VALUES(valor),
                                atualizadoem = CURRENT_TIMESTAMP
                        """, (
                            clienteid,
                            func_id,
                            mes,
                            rubricaid,
                            valor,
                            'PENDENTE'
                        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        flash('Lançamentos salvos com sucesso! Valores existentes foram atualizados.', 'success')
        return redirect(url_for('lancamentos_funcionarios.lista'))
    
    # GET request - show form
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get default month (previous month)
    mes_padrao = get_previous_month()
    
    # Get clientes - only those with products configured
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social as nome 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
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
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get all active employees for the client
        cursor.execute("""
            SELECT 
                f.id,
                f.nome,
                f.categoria,
                COALESCE(f.salario_base, 0) as salario_base,
                'funcionario' as tipo
            FROM funcionarios f
            WHERE f.ativo = 1 AND (f.id_cliente = %s OR f.id_cliente IS NULL)
            ORDER BY f.nome
        """, (cliente_id,))
        funcionarios = cursor.fetchall()
        
        # Also get motoristas that receive commission for this client
        cursor.execute("""
            SELECT 
                m.id,
                m.nome,
                'MOTORISTA' as categoria,
                CAST(0 AS DECIMAL(12,2)) as salario_base,
                'motorista' as tipo
            FROM motoristas m
            WHERE m.paga_comissao = 1
            ORDER BY m.nome
        """)
        motoristas = cursor.fetchall()
        
        # Combine both lists
        all_employees = funcionarios + motoristas
        
        return jsonify(all_employees)
    except Exception as e:
        import logging
        logging.error(f"Error in get_funcionarios: {str(e)}")
        return jsonify({'error': 'Erro ao carregar funcionários'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/get-comissoes/<int:cliente_id>/<mes>')
@login_required
def get_comissoes(cliente_id, mes):
    """API endpoint to get commission data for motoristas for a specific month"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Convert MM-YYYY or MM/YYYY to date range (accept both formats)
        try:
            # Accept both MM-YYYY (URL format) and MM/YYYY (display format)
            if '-' in mes:
                month_str, year_str = mes.split('-')
            else:
                month_str, year_str = mes.split('/')
            month = int(month_str)
            year = int(year_str)
            
            # First day of the month
            data_inicio = f"{year}-{month:02d}-01"
            
            # Last day of the month
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            data_fim = f"{year}-{month:02d}-{last_day}"
        except Exception as e:
            import logging
            logging.error(f"Error parsing month in get_comissoes: {str(e)}")
            return jsonify({})
        
        # Get commission totals per motorista for the month (across ALL clients)
        cursor.execute("""
            SELECT 
                m.id as motorista_id,
                m.nome as motorista_nome,
                COALESCE(SUM(f.comissao_motorista), 0) as comissao_total
            FROM motoristas m
            LEFT JOIN fretes f ON m.id = f.motoristas_id 
                AND f.data_frete >= %s 
                AND f.data_frete <= %s
            WHERE m.paga_comissao = 1
            GROUP BY m.id, m.nome
            HAVING comissao_total > 0
        """, (data_inicio, data_fim))
        
        comissoes = cursor.fetchall()
        
        # Convert to dictionary for easy lookup
        comissoes_dict = {c['motorista_id']: float(c['comissao_total']) for c in comissoes}
        
        return jsonify(comissoes_dict)
    except Exception as e:
        import logging
        logging.error(f"Error in get_comissoes: {str(e)}")
        return jsonify({})
    finally:
        if cursor:
            cursor.close()
        conn.close()

@bp.route('/get-veiculos/<int:funcionario_id>')
@login_required
def get_veiculos(funcionario_id):
    """API endpoint to get vehicles for a driver"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT 
                v.id,
                v.caminhao,
                v.placa,
                fmv.principal
            FROM funcionariomotoristaveiculos fmv
            INNER JOIN veiculos v ON fmv.veiculoid = v.id
            WHERE fmv.funcionarioid = %s AND fmv.ativo = 1
            ORDER BY fmv.principal DESC, v.caminhao
        """, (funcionario_id,))
        veiculos = cursor.fetchall()
        
        return jsonify(veiculos)
    finally:
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
        FROM lancamentosfuncionarios_v2 l
        INNER JOIN funcionarios f ON l.funcionarioid = f.id
        INNER JOIN rubricas r ON l.rubricaid = r.id
        LEFT JOIN veiculos v ON l.caminhaoid = v.id
        WHERE l.mes = %s AND l.clienteid = %s
        ORDER BY f.nome, r.ordem
    """, (mes, cliente_id))
    lancamentos = cursor.fetchall()
    
    # Get client name
    cursor.execute("SELECT razao_social as nome FROM clientes WHERE id = %s", (cliente_id,))
    cliente = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    # Group by employee
    funcionarios_data = {}
    for lanc in lancamentos:
        func_id = lanc['funcionarioid']
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
