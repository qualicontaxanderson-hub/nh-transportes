from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime, timedelta
import calendar

bp = Blueprint('lancamentos_funcionarios', __name__, url_prefix='/lancamentos-funcionarios')


def _ensure_tipo_funcionario(conn):
    """
    Garante que a coluna tipo_funcionario existe em lancamentosfuncionarios_v2 e
    que todos os registros estão corretamente classificados.

    Regras de classificação (aplicadas em ordem de prioridade):
    1. funcionarioid existe APENAS em motoristas (sem colisão de ID) → 'motorista'
       (executado apenas na criação da coluna, como backfill inicial)
    2. Demais → 'funcionario' (DEFAULT da coluna)

    Repair (executado SEMPRE):
    - Reverte para 'funcionario' qualquer linha cujo funcionarioid existe na tabela
      funcionarios. Frentistas/outros sempre estão em funcionarios; motoristas NÃO
      estão. Isso corrige promoções incorretas de frentistas causadas por heurísticas
      anteriores baseadas em Comissão (que confundiam frentistas com motoristas
      quando IDs colidem entre as duas tabelas).
    - VALMIR, MARCOS ANTONIO e demais motoristas reais NÃO estão na tabela
      funcionarios, portanto suas linhas com tipo='motorista' são preservadas.

    NOTA: frentistas podem ter rubricas de Comissão (comissões manuais).
    Por isso a presença de Comissão NÃO é usada como desambiguador de tipo.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = 'lancamentosfuncionarios_v2'"
        " AND COLUMN_NAME = 'tipo_funcionario'"
    )
    if cur.fetchone()[0] == 0:
        # Adiciona a coluna com DEFAULT 'funcionario'
        cur.execute(
            "ALTER TABLE lancamentosfuncionarios_v2"
            " ADD COLUMN tipo_funcionario VARCHAR(12) NOT NULL DEFAULT 'funcionario'"
        )
        conn.commit()

        # Backfill 1: IDs que existem APENAS em motoristas (sem colisão) →
        # todas as linhas desse ID recebem 'motorista'
        cur.execute("""
            UPDATE lancamentosfuncionarios_v2 lf
            JOIN  motoristas   m ON m.id = lf.funcionarioid
            LEFT  JOIN funcionarios f ON f.id = lf.funcionarioid
            SET   lf.tipo_funcionario = 'motorista'
            WHERE f.id IS NULL
        """)
        conn.commit()

        # Repair: Reverte para 'funcionario' qualquer linha cujo funcionarioid
    # existe na tabela funcionarios (frentistas/outros sempre estão lá;
    # motoristas reais NÃO estão).
    cur.execute("""
        UPDATE lancamentosfuncionarios_v2 lf
        JOIN funcionarios f ON f.id = lf.funcionarioid
        SET lf.tipo_funcionario = 'funcionario'
        WHERE lf.tipo_funcionario != 'funcionario'
    """)
    conn.commit()
    cur.close()


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
    
    # Build WHERE clause
    where_conditions = ["1=1"]
    params = []
    
    if mes_filtro:
        where_conditions.append("l.mes = %s")
        params.append(mes_filtro)
    
    if cliente_filtro:
        where_conditions.append("l.clienteid = %s")
        params.append(cliente_filtro)
    
    where_clause = " AND ".join(where_conditions)
    
    query = f"""
        SELECT
            l.mes,
            l.clienteid,
            c.razao_social as cliente_nome,
            COUNT(DISTINCT l.funcionarioid) as total_funcionarios,
            SUM(l.valor) as total_valor,
            l.statuslancamento
        FROM lancamentosfuncionarios_v2 l
        LEFT JOIN clientes c ON l.clienteid = c.id
        WHERE {where_clause}
        GROUP BY l.mes, l.clienteid, c.razao_social, l.statuslancamento
        ORDER BY l.mes DESC, c.razao_social
    """
    
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
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        _ensure_tipo_funcionario(conn)

        if request.method == 'POST':
            mes = request.form.get('mes')
            clienteid = request.form.get('clienteid')

            # Process each employee's data
            funcionarios_ids = request.form.getlist('funcionarioid[]')
            funcionario_tipos = request.form.getlist('funcionario_tipo[]')

            for idx, func_id in enumerate(funcionarios_ids):
                tipo = funcionario_tipos[idx] if idx < len(funcionario_tipos) else 'funcionario'
                # Use namespaced field names to avoid collision between
                # funcionarios and motoristas that share the same numeric ID.
                tipo_prefix = 'm' if tipo == 'motorista' else 'f'
                rubricas = request.form.getlist(f'rubrica_{tipo_prefix}_{func_id}[]')
                valores = request.form.getlist(f'valor_{tipo_prefix}_{func_id}[]')

                for i, rubricaid in enumerate(rubricas):
                    if rubricaid and valores[i]:
                        valor = float(valores[i]) if valores[i] else 0
                        if valor != 0:
                            cursor.execute("""
                                INSERT INTO lancamentosfuncionarios_v2 (
                                    clienteid, funcionarioid, mes, rubricaid, valor,
                                    statuslancamento, tipo_funcionario
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    valor = VALUES(valor),
                                    tipo_funcionario = VALUES(tipo_funcionario),
                                    atualizadoem = CURRENT_TIMESTAMP
                            """, (
                                clienteid,
                                func_id,
                                mes,
                                rubricaid,
                                valor,
                                'PENDENTE',
                                tipo,
                            ))

            conn.commit()
            flash('Lançamentos salvos com sucesso! Valores existentes foram atualizados.', 'success')
            return redirect(url_for('lancamentos_funcionarios.lista'))

        # GET request - show form
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

        return render_template('lancamentos_funcionarios/novo.html',
                             mes_padrao=mes_padrao,
                             clientes=clientes,
                             rubricas=rubricas)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar lançamentos: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_funcionarios.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

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
        LEFT JOIN funcionarios f ON l.funcionarioid = f.id AND l.tipo_funcionario = 'funcionario'
        LEFT JOIN motoristas m ON l.funcionarioid = m.id AND l.tipo_funcionario = 'motorista'
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

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        _ensure_tipo_funcionario(conn)

        if request.method == 'POST':
            mes_form = request.form.get('mes')
            clienteid = request.form.get('clienteid')

            # Process each employee's data
            funcionarios_ids = request.form.getlist('funcionarioid[]')
            funcionario_tipos = request.form.getlist('funcionario_tipo[]')

            for idx, func_id in enumerate(funcionarios_ids):
                tipo = funcionario_tipos[idx] if idx < len(funcionario_tipos) else 'funcionario'
                # Use namespaced field names to avoid collision between
                # funcionarios and motoristas that share the same numeric ID.
                tipo_prefix = 'm' if tipo == 'motorista' else 'f'
                rubricas = request.form.getlist(f'rubrica_{tipo_prefix}_{func_id}[]')
                valores = request.form.getlist(f'valor_{tipo_prefix}_{func_id}[]')

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
                                    statuslancamento, tipo_funcionario
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    valor = VALUES(valor),
                                    tipo_funcionario = VALUES(tipo_funcionario),
                                    atualizadoem = CURRENT_TIMESTAMP
                            """, (
                                clienteid,
                                func_id,
                                mes_form,
                                rubricaid,
                                valor,
                                'PENDENTE',
                                tipo,
                            ))
                        else:
                            # If valor is 0 or empty, DELETE the record.
                            # Filter by tipo_funcionario to avoid accidentally
                            # deleting the colliding motorista/funcionario row
                            # when both share the same numeric funcionarioid.
                            cursor.execute("""
                                DELETE FROM lancamentosfuncionarios_v2
                                WHERE clienteid = %s
                                  AND funcionarioid = %s
                                  AND mes = %s
                                  AND rubricaid = %s
                                  AND tipo_funcionario = %s
                            """, (
                                clienteid,
                                func_id,
                                mes_form,
                                rubricaid,
                                tipo,
                            ))

            conn.commit()
            flash('Lançamentos atualizados com sucesso!', 'success')
            return redirect(url_for('lancamentos_funcionarios.lista'))

        # GET request - show form with existing data
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

        # Get existing lancamentos for this month and client.
        # Fetch tipo_funcionario so we can split the lookup by type and avoid
        # collisions between funcionarios.id and motoristas.id (both start at 1).
        cursor.execute("""
            SELECT funcionarioid, rubricaid, valor, tipo_funcionario
            FROM lancamentosfuncionarios_v2
            WHERE mes = %s AND clienteid = %s
        """, (mes, cliente_id))
        lancamentos_existentes = cursor.fetchall()

        # Build two separate dicts keyed by funcionarioid:
        #   valores_funcionario  — rows where tipo_funcionario = 'funcionario'
        #   valores_motorista    — rows where tipo_funcionario = 'motorista'
        # This prevents a frentista (e.g. João, funcionarios.id=3) from
        # inheriting a motorista's value (e.g. Valmir, motoristas.id=3).
        valores_funcionario = {}
        valores_motorista = {}
        for lanc in lancamentos_existentes:
            func_id = lanc['funcionarioid']
            tipo = lanc['tipo_funcionario']
            target = valores_motorista if tipo == 'motorista' else valores_funcionario
            if func_id not in target:
                target[func_id] = {}
            target[func_id][lanc['rubricaid']] = float(lanc['valor'])

        return render_template('lancamentos_funcionarios/novo.html',
                             mes_padrao=mes,
                             cliente_selecionado=cliente_id,
                             clientes=clientes,
                             rubricas=rubricas,
                             valores_funcionario=valores_funcionario,
                             valores_motorista=valores_motorista,
                             modo_edicao=True)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar lançamentos: {str(e)}', 'danger')
        return redirect(url_for('lancamentos_funcionarios.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/admin/limpar-comissoes-frentistas', methods=['POST'])
@login_required
@admin_required
def limpar_comissoes_frentistas():
    """
    Rota administrativa desativada.

    ATENÇÃO: frentistas podem ter lançamentos de Comissão legítimos
    (comissões manuais inseridas pelo formulário). A limpeza indiscriminada de
    comissões para todo funcionarioid presente na tabela 'funcionarios' apagaria
    dados válidos de frentistas como ROBERTA FERREIRA, RODRIGO CUNHA, JOÃO BATISTA.

    A classificação correta entre frentistas e motoristas é gerida pela coluna
    tipo_funcionario em lancamentosfuncionarios_v2, mantida por
    _ensure_tipo_funcionario().
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Apenas conta registros que seriam afetados; NÃO deleta nada.
        # Frentistas têm comissões legítimas — a deleção foi desativada.
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM lancamentosfuncionarios_v2
            WHERE rubricaid IN (SELECT id FROM rubricas WHERE nome IN ('Comissão', 'Comissão / Aj. Custo'))
            AND tipo_funcionario = 'funcionario'
        """)
        count_frentista_comissoes = cursor.fetchone()['total']

        return jsonify({
            'success': False,
            'message': (
                'Esta operação foi desativada. Frentistas podem ter comissões legítimas '
                'e a deleção automática apagaria dados válidos. '
                f'({count_frentista_comissoes} lançamentos de comissão de frentistas encontrados — mantidos.)'
            ),
            'registros_deletados': 0
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
