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
    # Convert mes from URL format (01-2026) to database format (01/2026)
    mes = mes.replace('-', '/')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get all lancamentos for this month and client
    # Using LEFT JOINs to handle both funcionarios and motoristas
    cursor.execute("""
        SELECT 
            l.*,
            COALESCE(f.nome, m.nome) as funcionario_nome,
            r.nome as rubrica_nome,
            r.tipo as rubrica_tipo,
            v.caminhao
        FROM lancamentosfuncionarios_v2 l
        LEFT JOIN funcionarios f ON l.funcionarioid = f.id
        LEFT JOIN motoristas m ON l.funcionarioid = m.id
        INNER JOIN rubricas r ON l.rubricaid = r.id
        LEFT JOIN veiculos v ON l.caminhaoid = v.id
        WHERE l.mes = %s AND l.clienteid = %s
        ORDER BY COALESCE(f.nome, m.nome), r.ordem
    """, (mes, cliente_id))
    lancamentos = cursor.fetchall()
    
    # Get list of motoristas with their info
    cursor.execute("SELECT id, nome FROM motoristas")
    motoristas = {row['id']: row['nome'] for row in cursor.fetchall()}
    
    # Get commission rubrica
    cursor.execute("SELECT id, nome FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo') LIMIT 1")
    rubrica_comissao = cursor.fetchone()
    
    # Get client name
    cursor.execute("SELECT razao_social as nome FROM clientes WHERE id = %s", (cliente_id,))
    cliente = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    # Filter out commissions for non-motoristas
    lancamentos_filtrados = []
    motoristas_com_lancamentos = set()
    
    for lanc in lancamentos:
        func_id = lanc['funcionarioid']
        
        # Check if this is a commission rubrica
        rubrica_nome = lanc.get('rubrica_nome', '')
        is_comissao = rubrica_nome in ['Comissão', 'Comissão / Aj. Custo']
        
        # Only exclude if it's a commission AND funcionario is not a motorista
        if is_comissao and func_id not in motoristas:
            continue  # Skip this lancamento (commission for non-motorista)
        
        # Track motoristas that already have lancamentos (only motoristas!)
        if func_id in motoristas:
            motoristas_com_lancamentos.add(func_id)
        
        lancamentos_filtrados.append(lanc)
    
    # Add commission entries for motoristas that don't have any lancamentos yet
    # This handles the case where motoristas should have commissions but they weren't saved
    if rubrica_comissao:
        # Get commissions from API
        try:
            from datetime import datetime
            mes_date = datetime.strptime(mes, '%m/%Y')
            mes_formatted = mes_date.strftime('%m/%Y')
            
            # Import here to avoid circular dependency
            import requests
            from flask import url_for, request
            
            # Build API URL
            api_url = url_for('lancamentos_funcionarios.get_comissoes', 
                            cliente_id=cliente_id, mes=mes_formatted, _external=False)
            
            # Get base URL from request
            base_url = request.url_root.rstrip('/')
            full_url = base_url + api_url
            
            response = requests.get(full_url)
            if response.status_code == 200:
                comissoes_data = response.json()
                
                # Add commission entries for motoristas not in lancamentos
                for motorista_id, comissao_valor in comissoes_data.items():
                    motorista_id_int = int(motorista_id)
                    if motorista_id_int not in motoristas_com_lancamentos and comissao_valor > 0:
                        # Create a lancamento entry for this commission
                        lancamento_comissao = {
                            'funcionarioid': motorista_id_int,
                            'funcionario_nome': motoristas.get(motorista_id_int, f'Motorista {motorista_id}'),
                            'rubricaid': rubrica_comissao['id'],
                            'rubrica_nome': rubrica_comissao['nome'],
                            'rubrica_tipo': 'PROVENTO',
                            'valor': comissao_valor,
                            'mes': mes,
                            'clienteid': cliente_id,
                            'statuslancamento': 'PENDENTE',
                            'caminhao': None,
                            'caminhaoid': None
                        }
                        lancamentos_filtrados.append(lancamento_comissao)
        except Exception as e:
            # If API call fails, just continue with filtered lancamentos
            print(f"Warning: Could not fetch commissions from API: {e}")
            pass
    
    lancamentos = lancamentos_filtrados
    
    # Sort lancamentos by funcionarioid for consistent ordering
    # This ensures that each employee's data is grouped correctly
    lancamentos.sort(key=lambda x: x['funcionarioid'])
    
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

@bp.route('/editar/<mes>/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(mes, cliente_id):
    """Edit existing payroll entries for a specific month and client"""
    # Convert mes from URL format (01-2026) to database format (01/2026)
    mes = mes.replace('-', '/')
    
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        mes_form = request.form.get('mes')
        clienteid = request.form.get('clienteid')
        
        # Process each employee's data
        funcionarios_ids = request.form.getlist('funcionarioid[]')
        
        for func_id in funcionarios_ids:
            # Get all rubrica values for this employee
            rubricas = request.form.getlist(f'rubrica_{func_id}[]')
            valores = request.form.getlist(f'valor_{func_id}[]')
            
            for i, rubricaid in enumerate(rubricas):
                if rubricaid:
                    # Convert valor to float, treating empty string as 0
                    valor_str = valores[i] if i < len(valores) else ''
                    valor = float(valor_str) if valor_str else 0
                    
                    if valor != 0:
                        # Insert or update the value
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
                            mes_form,
                            rubricaid,
                            valor,
                            'PENDENTE'
                        ))
                    else:
                        # If valor is 0 or empty, DELETE the record to truly remove it
                        cursor.execute("""
                            DELETE FROM lancamentosfuncionarios_v2
                            WHERE clienteid = %s 
                              AND funcionarioid = %s 
                              AND mes = %s 
                              AND rubricaid = %s
                        """, (
                            clienteid,
                            func_id,
                            mes_form,
                            rubricaid
                        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        flash('Lançamentos atualizados com sucesso!', 'success')
        return redirect(url_for('lancamentos_funcionarios.lista'))
    
    # GET request - show form with existing data
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
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
    
    # Get existing lancamentos for this month and client
    cursor.execute("""
        SELECT funcionarioid, rubricaid, valor
        FROM lancamentosfuncionarios_v2
        WHERE mes = %s AND clienteid = %s
    """, (mes, cliente_id))
    lancamentos_existentes = cursor.fetchall()
    
    # Convert to dict for easy lookup: {funcionario_id: {rubrica_id: valor}}
    valores_existentes = {}
    for lanc in lancamentos_existentes:
        func_id = lanc['funcionarioid']
        if func_id not in valores_existentes:
            valores_existentes[func_id] = {}
        valores_existentes[func_id][lanc['rubricaid']] = float(lanc['valor'])
    
    cursor.close()
    conn.close()
    
    return render_template('lancamentos_funcionarios/novo.html', 
                         mes_padrao=mes,
                         cliente_selecionado=cliente_id,
                         clientes=clientes,
                         rubricas=rubricas,
                         valores_existentes=valores_existentes,
                         modo_edicao=True)


@bp.route('/admin/limpar-comissoes-frentistas', methods=['POST'])
@login_required
@admin_required
def limpar_comissoes_frentistas():
    """
    Rota administrativa para limpar comissões incorretas de frentistas do banco de dados.
    Remove todos os lançamentos de comissões para funcionários que não são motoristas.
    
    IMPORTANTE: Funcionários estão na tabela 'funcionarios', motoristas na tabela 'motoristas'.
    Comissões devem existir APENAS para IDs que estão na tabela 'motoristas'.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # First, count how many will be affected
        # Query corrigida: verifica se funcionarioid está na tabela 'funcionarios'
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM lancamentosfuncionarios_v2
            WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
            AND funcionarioid IN (SELECT id FROM funcionarios)
        """)
        count_before = cursor.fetchone()['total']
        
        # Delete commissions for funcionarios (non-motoristas)
        # Query corrigida: deleta se funcionarioid está na tabela 'funcionarios'
        cursor.execute("""
            DELETE FROM lancamentosfuncionarios_v2
            WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
            AND funcionarioid IN (SELECT id FROM funcionarios)
        """)
        
        conn.commit()
        deleted_count = cursor.rowcount
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Limpeza concluída com sucesso!',
            'registros_esperados': count_before,
            'registros_deletados': deleted_count
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
