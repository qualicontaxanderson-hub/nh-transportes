from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from config import Config
import mysql.connector

bp = Blueprint('quilometragem', __name__, url_prefix='/quilometragem')

def get_db():
    """Retorna conexão com o banco de dados usando Config"""
    return mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=Config.DB_PORT
    )

def converter_para_decimal(valor):
    """Converte valores do formato brasileiro (1.234,56) para decimal (1234.56)"""
    if isinstance(valor, str):
        valor = valor.replace('.', '').replace(',', '.')
    return valor

@bp.route('/')
@login_required
def lista():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Filtros
    veiculos_id = request.args.get('veiculos_id', '')
    motoristas_id = request.args.get('motoristas_id', '')
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    
    # Query base com joins
    query = """
        SELECT 
            q.id,
            q.data,
            q.km_inicial,
            q.km_final,
            q.km_rodados,
            q.valor_combustivel,
            q.litros_abastecidos,
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
    
    # Buscar veículos e motoristas para os filtros
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('quilometragem/lista.html', 
                         quilometragens=quilometragens,
                         veiculos=veiculos,
                         motoristas=motoristas,
                         filtros={
                             'veiculos_id': veiculos_id,
                             'motoristas_id': motoristas_id,
                             'data_inicio': data_inicio,
                             'data_fim': data_fim
                         })

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
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
            observacoes = request.form.get('observacoes', '')
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO quilometragem 
                (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados, 
                 valor_combustivel, litros_abastecidos, observacoes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, observacoes))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Quilometragem cadastrada com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
            
        except Exception as e:
            flash(f'Erro ao cadastrar quilometragem: {str(e)}', 'danger')

    # GET - Carrega veículos, motoristas e último km_final do veículo padrão
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()

    km_inicial_sugerido = ''
    if veiculos:
        veiculo_padrao_id = veiculos[0]['id']
        cursor.execute("""
            SELECT km_final 
            FROM quilometragem
            WHERE veiculos_id = %s
            ORDER BY data DESC, id DESC
            LIMIT 1
        """, (veiculo_padrao_id,))
        row = cursor.fetchone()
        if row:
            km_inicial_sugerido = row['km_final']
    cursor.close()
    conn.close()
    
    return render_template(
        'quilometragem/novo.html',
        veiculos=veiculos,
        motoristas=motoristas,
        km_inicial_sugerido=km_inicial_sugerido
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
            observacoes = request.form.get('observacoes', '')
            
            cursor.execute("""
                UPDATE quilometragem 
                SET veiculos_id = %s, motoristas_id = %s, data = %s, 
                    km_inicial = %s, km_final = %s, km_rodados = %s,
                    valor_combustivel = %s, litros_abastecidos = %s, observacoes = %s
                WHERE id = %s
            """, (veiculos_id, motoristas_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, observacoes, id))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Quilometragem atualizada com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
            
        except Exception as e:
            flash(f'Erro ao atualizar quilometragem: {str(e)}', 'danger')
    
    # GET - Carregar dados para edição
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
    
    return redirect(url_for('quilometragem.lista')
)
