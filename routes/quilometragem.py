from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from config import Config
import mysql.connector
from datetime import date

bp = Blueprint('quilometragem', __name__, url_prefix='/quilometragem')

def get_db():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=Config.DB_PORT
    )

def converter_para_decimal(valor):
    if isinstance(valor, str):
        valor = valor.replace('.', '').replace(',', '.')
    return valor

def get_ultimo_km_veiculo(veiculos_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT km_final as ultimo_km
        FROM quilometragem
        WHERE veiculos_id = %s
        ORDER BY data DESC, id DESC
        LIMIT 1
    """, (veiculos_id,))
    resultado = cursor.fetchone()
    if not resultado:
        cursor.execute("""
            SELECT km_inicial as ultimo_km
            FROM quilometragem_inicial
            WHERE veiculos_id = %s
        """, (veiculos_id,))
        resultado = cursor.fetchone()
    cursor.close()
    conn.close()
    return float(resultado['ultimo_km']) if resultado else None

@bp.route('/')
@login_required
def lista():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Default to current month if no filters provided
    hoje = date.today()
    primeiro_dia_mes = hoje.replace(day=1)
    data_inicio_default = primeiro_dia_mes.strftime('%Y-%m-%d')
    data_fim_default = hoje.strftime('%Y-%m-%d')
    
    veiculos_id = request.args.get('veiculos_id', '')
    motoristas_id = request.args.get('motoristas_id', '')
    data_inicio = request.args.get('data_inicio', data_inicio_default)
    data_fim = request.args.get('data_fim', data_fim_default)
    query = """
        SELECT 
            q.id,
            q.data,
            q.km_inicial,
            q.km_final,
            q.km_rodados,
            q.valor_combustivel,
            q.litros_abastecidos,
            q.valor_produtos_diversos,
            q.observacoes,
            v.placa,
            v.modelo,
            m.nome as motorista_nome
        FROM quilometragem q
        LEFT JOIN veiculos v ON q.veiculos_id = v.id
        LEFT JOIN motoristas m ON q.motoristas_id = m.id
        WHERE 1=1
    """
    params = []
    if veiculos_id:
        query += " AND q.veiculos_id = %s"
        params.append(veiculos_id)
    if motoristas_id:
        query += " AND q.motoristas_id = %s"
        params.append(motoristas_id)
    if data_inicio:
        query += " AND q.data >= %s"
        params.append(data_inicio)
    if data_fim:
        query += " AND q.data <= %s"
        params.append(data_fim)
    query += " ORDER BY q.data DESC, q.id DESC"
    cursor.execute(query, params)
    quilometragens = cursor.fetchall()
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.execute("""
        SELECT 
            v.id,
            v.placa,
            v.modelo,
            qi.km_inicial,
            qi.data_cadastro
        FROM veiculos v
        LEFT JOIN quilometragem_inicial qi ON v.id = qi.veiculos_id
        WHERE v.ativo = 1
        ORDER BY v.placa
    """)
    veiculos_km_inicial = cursor.fetchall()
    # RESUMO agrupado por veículo - mostra apenas veículos com abastecimentos
    resumo_query = """
        SELECT 
            v.placa,
            v.modelo,
            COUNT(q.id) as quantidade_abastecimentos,
            SUM(q.litros_abastecidos) as total_litros,
            SUM(q.km_rodados) as total_km,
            SUM(q.valor_combustivel) as total_valor
        FROM quilometragem q
        INNER JOIN veiculos v ON q.veiculos_id = v.id
        WHERE 1=1
    """
    resumo_params = []
    if veiculos_id:
        resumo_query += " AND q.veiculos_id = %s"
        resumo_params.append(veiculos_id)
    if motoristas_id:
        resumo_query += " AND q.motoristas_id = %s"
        resumo_params.append(motoristas_id)
    if data_inicio:
        resumo_query += " AND q.data >= %s"
        resumo_params.append(data_inicio)
    if data_fim:
        resumo_query += " AND q.data <= %s"
        resumo_params.append(data_fim)
    resumo_query += " GROUP BY v.placa, v.modelo ORDER BY v.placa"
    cursor.execute(resumo_query, resumo_params)
    resumo_veiculos = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'quilometragem/lista.html',
        registros=quilometragens,
        veiculos=veiculos,
        motoristas=motoristas,
        veiculos_km_inicial=veiculos_km_inicial,
        filtros={
            'veiculos_id': veiculos_id,
            'motoristas_id': motoristas_id,
            'data_inicio': data_inicio,
            'data_fim': data_fim
        },
        resumo_veiculos=resumo_veiculos
    )

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            veiculos_id = request.form.get('veiculos_id')
            motoristas_id = request.form.get('motoristas_id')
            data = request.form.get('data')
            km_final = converter_para_decimal(request.form.get('km_final'))
            valor_combustivel = converter_para_decimal(request.form.get('valor_combustivel'))
            litros_abastecidos = converter_para_decimal(request.form.get('litros_abastecidos'))
            valor_produtos_diversos = converter_para_decimal(request.form.get('valor_produtos_diversos', '0'))
            observacoes = request.form.get('observacoes', '')
            km_inicial = get_ultimo_km_veiculo(veiculos_id)
            if km_inicial is None:
                flash('Erro: Este veículo não possui KM inicial cadastrado. Configure o KM inicial primeiro.', 'danger')
                return redirect(url_for('quilometragem.novo'))
            km_rodados = float(km_final) - float(km_inicial)
            if km_rodados <= 0:
                flash('Erro: KM Final deve ser maior que o KM Inicial atual.', 'danger')
                return redirect(url_for('quilometragem.novo'))
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO quilometragem 
                (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados, 
                 valor_combustivel, litros_abastecidos, valor_produtos_diversos, observacoes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, valor_produtos_diversos, observacoes))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Quilometragem cadastrada com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar quilometragem: {str(e)}', 'danger')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'quilometragem/novo.html',
        veiculos=veiculos,
        motoristas=motoristas
    )

@bp.route('/novo-produto', methods=['GET', 'POST'])
@login_required
def novo_produto():
    """Rota para lançar apenas produtos diversos, sem abastecimento"""
    if request.method == 'POST':
        try:
            veiculos_id = request.form.get('veiculos_id')
            motoristas_id = request.form.get('motoristas_id')
            data = request.form.get('data')
            valor_produtos_diversos = converter_para_decimal(request.form.get('valor_produtos_diversos', '0'))
            observacoes = request.form.get('observacoes', '')
            
            # Para produtos sem abastecimento, vamos usar valores zerados/nulos para combustível
            # mas ainda precisamos do KM para manter a consistência da tabela
            km_inicial = get_ultimo_km_veiculo(veiculos_id)
            if km_inicial is None:
                flash('Erro: Este veículo não possui KM inicial cadastrado. Configure o KM inicial primeiro.', 'danger')
                return redirect(url_for('quilometragem.novo_produto'))
            
            # Usar o mesmo KM inicial como KM final para produtos sem abastecimento
            km_final = km_inicial
            km_rodados = 0
            valor_combustivel = 0
            litros_abastecidos = 0
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO quilometragem 
                (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados, 
                 valor_combustivel, litros_abastecidos, valor_produtos_diversos, observacoes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, valor_produtos_diversos, observacoes))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Produtos diversos cadastrados com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar produtos: {str(e)}', 'danger')
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'quilometragem/novo_produto.html',
        veiculos=veiculos,
        motoristas=motoristas
    )

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        try:
            veiculos_id = request.form.get('veiculos_id')
            motoristas_id = request.form.get('motoristas_id')
            data = request.form.get('data')
            km_inicial = converter_para_decimal(request.form.get('km_inicial'))
            km_final = converter_para_decimal(request.form.get('km_final'))
            km_rodados = float(km_final) - float(km_inicial)
            valor_combustivel = converter_para_decimal(request.form.get('valor_combustivel'))
            litros_abastecidos = converter_para_decimal(request.form.get('litros_abastecidos'))
            valor_produtos_diversos = converter_para_decimal(request.form.get('valor_produtos_diversos', '0'))
            observacoes = request.form.get('observacoes', '')
            cursor.execute("""
                UPDATE quilometragem 
                SET veiculos_id = %s, motoristas_id = %s, data = %s, 
                    km_inicial = %s, km_final = %s, km_rodados = %s,
                    valor_combustivel = %s, litros_abastecidos = %s, valor_produtos_diversos = %s, observacoes = %s
                WHERE id = %s
            """, (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, valor_produtos_diversos, observacoes, id))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Quilometragem atualizada com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
        except Exception as e:
            flash(f'Erro ao atualizar quilometragem: {str(e)}', 'danger')
    cursor.execute("SELECT * FROM quilometragem WHERE id = %s", (id,))
    quilometragem = cursor.fetchone()
    if not quilometragem:
        flash('Quilometragem não encontrada!', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('quilometragem.lista'))
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('quilometragem/editar.html', 
                         quilometragem=quilometragem,
                         veiculos=veiculos,
                         motoristas=motoristas)

@bp.route('/configurar-km-inicial', methods=['POST'])
@login_required
def configurar_km_inicial():
    try:
        veiculos_id = request.form.get('veiculos_id')
        km_inicial = converter_para_decimal(request.form.get('km_inicial'))
        observacoes = request.form.get('observacoes', '')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM quilometragem_inicial WHERE veiculos_id = %s", (veiculos_id,))
        existe = cursor.fetchone()
        if existe:
            cursor.execute("""
                UPDATE quilometragem_inicial 
                SET km_inicial = %s, observacoes = %s
                WHERE veiculos_id = %s
            """, (km_inicial, observacoes, veiculos_id))
            flash('KM inicial atualizado com sucesso!', 'success')
        else:
            cursor.execute("""
                INSERT INTO quilometragem_inicial (veiculos_id, km_inicial, observacoes)
                VALUES (%s, %s, %s)
            """, (veiculos_id, km_inicial, observacoes))
            flash('KM inicial cadastrado com sucesso!', 'success')
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        flash(f'Erro ao configurar KM inicial: {str(e)}', 'danger')
    return redirect(url_for('quilometragem.lista'))

@bp.route('/api/get-ultimo-km/<int:veiculos_id>')
@login_required
def get_ultimo_km(veiculos_id):
    ultimo_km = get_ultimo_km_veiculo(veiculos_id)
    return jsonify({'ultimo_km': ultimo_km if ultimo_km else 0})

@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM quilometragem WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Quilometragem excluída com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir quilometragem: {str(e)}', 'danger')
    return redirect(url_for('quilometragem.lista'))
