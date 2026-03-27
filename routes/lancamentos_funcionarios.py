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

    Backfill inicial (apenas quando a coluna é criada):
    - IDs que existem APENAS em motoristas (sem colisão) → tipo='motorista'
    - Demais → tipo='funcionario' (DEFAULT)

    Repair (executado SEMPRE) — 3 passos para tratar colisão de IDs:

    PROBLEMA: funcionarios.id e motoristas.id são auto_increment independentes
    e podem ter o mesmo número (ex.: Roberta/funcionarios.id=2 colide com
    Marcos Antonio/motoristas.id=2; João/funcionarios.id=1 colide com
    Valmir/motoristas.id=1). O critério CORRETO de desambiguação:
    - Para IDs sem colisão (existem apenas em uma tabela), o tipo é determinado
      pela tabela em que o ID existe.
    - Para IDs com colisão (existem em AMBAS as tabelas), ambos os registros
      (tipo='funcionario' e tipo='motorista') podem ser legítimos — um pertence
      ao frentista e o outro ao motorista. NÃO se deve apagar nenhum deles.
    - Linhas tipo='funcionario' duplicadas (mesmo tipo) para IDs exclusivos de
      motoristas são artefatos de código antigo → apagadas pelo Passo 1.

    Passo 1: DELETE tipo='funcionario' duplicatas APENAS para IDs exclusivos de
             motoristas (f.id IS NULL). IDs com colisão são preservados.
    Passo 2: UPDATE tipo='motorista'→'funcionario' para IDs sem colisão em funcionarios.
    Passo 3: UPDATE tipo='funcionario'→'motorista' para IDs sem colisão em motoristas.

    Unique key: cria uq_lancamento_tipo(clienteid, funcionarioid, mes, rubricaid,
    tipo_funcionario) se ainda não existir, permitindo que João (frentista id=1)
    e Valmir (motorista id=1) coexistam com a mesma rubrica/mês sem colisão.

    NOTA: frentistas podem ter rubricas de Comissão (comissões manuais); a
    presença de Comissão NÃO é usada como critério de tipo.
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

    # Repair (executado SEMPRE) — 3 passos para lidar com colisão de IDs:
    #
    # Problema: funcionarios.id e motoristas.id são auto_increment independentes
    # e podem ter o mesmo número (ex.: Roberta/funcionarios.id=2 e
    # Marcos Antonio/motoristas.id=2).  Versões anteriores do repair usavam
    # apenas o JOIN por ID para decidir o tipo, o que causava:
    #   - tipo='motorista' para linhas de frentistas (rubricas de salário/VA)
    #   - tipo='funcionario' para linhas de motoristas (comissão)
    # O critério correto é: se existe uma linha tipo='motorista' E uma linha
    # tipo='funcionario' para EXATAMENTE o mesmo (fid, rubrica, mes, cliente),
    # a linha tipo='funcionario' é a cópia corrompida → deve ser removida.

    # Passo 1 — Deleta tipo='funcionario' duplicatas de dados de motoristas.
    # Quando o mesmo (funcionarioid, rubricaid, mes, clienteid) existe como
    # tipo='motorista' (correto) E tipo='funcionario' (corrompido), remove o
    # tipo='funcionario'. Apenas para IDs que existem EXCLUSIVAMENTE em
    # motoristas (f.id IS NULL): IDs com colisão (fid presente em AMBAS as
    # tabelas, ex.: João=1 e Valmir=1) são preservados — o tipo='funcionario'
    # é legítimo de João e não deve ser apagado.
    cur.execute("""
        DELETE lf FROM lancamentosfuncionarios_v2 lf
        INNER JOIN motoristas   m ON m.id = lf.funcionarioid
        LEFT  JOIN funcionarios f ON f.id = lf.funcionarioid
        INNER JOIN lancamentosfuncionarios_v2 lf2
            ON  lf2.funcionarioid    = lf.funcionarioid
            AND lf2.rubricaid        = lf.rubricaid
            AND lf2.mes              = lf.mes
            AND lf2.clienteid        = lf.clienteid
            AND lf2.tipo_funcionario = 'motorista'
        WHERE lf.tipo_funcionario = 'funcionario'
          AND f.id IS NULL
    """)
    conn.commit()

    # Passo 2 — Corrige tipo='motorista' para linhas de frentistas sem colisão.
    # Para IDs que existem APENAS em funcionarios (não em motoristas), qualquer
    # linha tipo='motorista' é classificação errada → muda para 'funcionario'.
    # IDs com colisão são preservados: se fid=X está em AMBAS as tabelas, o
    # LEFT JOIN encontra m.id IS NOT NULL e a linha NÃO é alterada.
    cur.execute("""
        UPDATE lancamentosfuncionarios_v2 lf
        JOIN  funcionarios f ON f.id = lf.funcionarioid
        LEFT  JOIN motoristas m ON m.id = lf.funcionarioid
        SET   lf.tipo_funcionario = 'funcionario'
        WHERE lf.tipo_funcionario = 'motorista'
          AND m.id IS NULL
    """)
    conn.commit()

    # Passo 3 — Corrige tipo='funcionario' para linhas de motoristas sem colisão.
    # Para IDs que existem APENAS em motoristas (não em funcionarios), qualquer
    # linha tipo='funcionario' é classificação errada → muda para 'motorista'.
    # Recupera dados que versões anteriores do repair converteram incorretamente.
    cur.execute("""
        UPDATE lancamentosfuncionarios_v2 lf
        JOIN  motoristas m ON m.id = lf.funcionarioid
        LEFT  JOIN funcionarios f ON f.id = lf.funcionarioid
        SET   lf.tipo_funcionario = 'motorista'
        WHERE lf.tipo_funcionario = 'funcionario'
          AND f.id IS NULL
    """)
    conn.commit()

    # Garante constraint unique que inclui tipo_funcionario — essencial para que
    # ON DUPLICATE KEY UPDATE funcione corretamente e para que dois funcionários
    # com o mesmo ID numérico (ex.: João=frentista id=1 e Valmir=motorista id=1)
    # possam coexistir com rubrica/mês/cliente iguais sem se sobrescrever.
    #
    # Antes de criar o índice: remove eventuais linhas duplicadas dentro do mesmo
    # tipo (artefato de código antigo sem constraint), mantendo o registro mais
    # recente (maior id).
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = 'lancamentosfuncionarios_v2'
          AND INDEX_NAME   = 'uq_lancamento_tipo'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("""
            DELETE lf1 FROM lancamentosfuncionarios_v2 lf1
            INNER JOIN lancamentosfuncionarios_v2 lf2
                ON  lf1.clienteid        = lf2.clienteid
                AND lf1.funcionarioid    = lf2.funcionarioid
                AND lf1.mes              = lf2.mes
                AND lf1.rubricaid        = lf2.rubricaid
                AND lf1.tipo_funcionario = lf2.tipo_funcionario
                AND lf1.id < lf2.id
        """)
        conn.commit()
        cur.execute("""
            ALTER TABLE lancamentosfuncionarios_v2
            ADD UNIQUE KEY uq_lancamento_tipo
                (clienteid, funcionarioid, mes, rubricaid, tipo_funcionario)
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
    _ensure_tipo_funcionario(conn)
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
        tipo_func = lanc.get('tipo_funcionario', 'funcionario')

        # Track motoristas that already have lancamentos
        if tipo_func == 'motorista':
            motoristas_com_lancamentos.add(func_id)

        # All DB entries are explicitly saved via the form — include them all.
        # Frentistas may have Comissão entries (manual commissions) which must
        # NOT be filtered out. No ID-based lookup needed; tipo_funcionario
        # already disambiguates the two tables that share auto-increment IDs.
        
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
                            'tipo_funcionario': 'motorista',
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
    
    # Sort lancamentos by (funcionarioid, tipo_funcionario) to keep frentistas
    # and motoristas with the same numeric ID in separate, consistent groups.
    lancamentos.sort(key=lambda x: (x['funcionarioid'], x.get('tipo_funcionario', 'funcionario')))
    
    # Group by (funcionarioid, tipo_funcionario) to prevent ID collision between
    # funcionarios and motoristas tables (both auto-increment from 1).
    # E.g. João Batista (frentista id=1) and VALMIR (motorista id=1) must be
    # shown as separate employees.
    funcionarios_data = {}
    for lanc in lancamentos:
        func_id = lanc['funcionarioid']
        tipo = lanc.get('tipo_funcionario', 'funcionario')
        key = (func_id, tipo)
        if key not in funcionarios_data:
            funcionarios_data[key] = {
                'nome': lanc['funcionario_nome'],
                'rubricas': [],
                'total': 0
            }
        funcionarios_data[key]['rubricas'].append(lanc)
        
        # Calculate total (positive for benefits, negative for discounts)
        if lanc['rubrica_tipo'] in ['DESCONTO', 'IMPOSTO']:
            funcionarios_data[key]['total'] -= float(lanc['valor'])
        else:
            funcionarios_data[key]['total'] += float(lanc['valor'])
    
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
