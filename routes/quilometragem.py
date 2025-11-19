from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from models import db

bp = Blueprint('quilometragem', __name__, url_prefix='/quilometragem')

def converter_para_decimal(valor):
    """Converte valores do formato brasileiro (1.234,56) para decimal (1234.56)"""
    if isinstance(valor, str):
        valor = valor.replace('.', '').replace(',', '.')
    return valor

@bp.route('/')
@login_required
def lista():
    cursor = db.cursor(dictionary=True)
    
    # Filtros
    veiculo_id = request.args.get('veiculo_id', '')
    motorista_id = request.args.get('motorista_id', '')
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
        LEFT JOIN veiculos v ON q.veiculo_id = v.id
        LEFT JOIN motoristas m ON q.motorista_id = m.id
        WHERE 1=1
    """
    
    params = []
    
    if veiculo_id:
        query += " AND q.veiculo_id = %s"
        params.append(veiculo_id)
    
    if motorista_id:
        query += " AND q.motorista_id = %s"
        params.append(motorista_id)
    
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
    
    cursor.execute("SELECT id, nome FROM motoristas WHERE ativo = 1 ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.close()
    
    return render_template('quilometragem/lista.html', 
                         quilometragens=quilometragens,
                         veiculos=veiculos,
                         motoristas=motoristas,
                         filtros={
                             'veiculo_id': veiculo_id,
                             'motorista_id': motorista_id,
                             'data_inicio': data_inicio,
                             'data_fim': data_fim
                         })

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            veiculo_id = request.form.get('veiculo_id')
            motorista_id = request.form.get('motorista_id')
            data = request.form.get('data')
            km_inicial = converter_para_decimal(request.form.get('km_inicial'))
            km_final = converter_para_decimal(request.form.get('km_final'))
            km_rodados = float(km_final) - float(km_inicial)
            valor_combustivel = converter_para_decimal(request.form.get('valor_combustivel'))
            litros_abastecidos = converter_para_decimal(request.form.get('litros_abastecidos'))
            observacoes = request.form.get('observacoes', '')
            
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO quilometragem 
                (veiculo_id, motorista_id, data, km_inicial, km_final, km_rodados, 
                 valor_combustivel, litros_abastecidos, observacoes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (veiculo_id, motorista_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, observacoes))
            
            db.commit()
            cursor.close()
            
            flash('Quilometragem cadastrada com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
            
        except Exception as e:
            flash(f'Erro ao cadastrar quilometragem: {str(e)}', 'danger')
            db.rollback()
    
    # GET - Carregar dados para o formulário
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas WHERE ativo = 1 ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.close()
    
    return render_template('quilometragem/novo.html', veiculos=veiculos, motoristas=motoristas)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            veiculo_id = request.form.get('veiculo_id')
            motorista_id = request.form.get('motorista_id')
            data = request.form.get('data')
            km_inicial = converter_para_decimal(request.form.get('km_inicial'))
            km_final = converter_para_decimal(request.form.get('km_final'))
            km_rodados = float(km_final) - float(km_inicial)
            valor_combustivel = converter_para_decimal(request.form.get('valor_combustivel'))
            litros_abastecidos = converter_para_decimal(request.form.get('litros_abastecidos'))
            observacoes = request.form.get('observacoes', '')
            
            cursor.execute("""
                UPDATE quilometragem 
                SET veiculo_id = %s, motorista_id = %s, data = %s, 
                    km_inicial = %s, km_final = %s, km_rodados = %s,
                    valor_combustivel = %s, litros_abastecidos = %s, observacoes = %s
                WHERE id = %s
            """, (veiculo_id, motorista_id, data, km_inicial, km_final, km_rodados,
                  valor_combustivel, litros_abastecidos, observacoes, id))
            
            db.commit()
            cursor.close()
            
            flash('Quilometragem atualizada com sucesso!', 'success')
            return redirect(url_for('quilometragem.lista'))
            
        except Exception as e:
            flash(f'Erro ao atualizar quilometragem: {str(e)}', 'danger')
            db.rollback()
    
    # GET - Carregar dados para edição
    cursor.execute("SELECT * FROM quilometragem WHERE id = %s", (id,))
    quilometragem = cursor.fetchone()
    
    if not quilometragem:
        flash('Quilometragem não encontrada!', 'danger')
        return redirect(url_for('quilometragem.lista'))
    
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas WHERE ativo = 1 ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.close()
    
    return render_template('quilometragem/editar.html', 
                         quilometragem=quilometragem,
                         veiculos=veiculos,
                         motoristas=motoristas)

@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    try:
        cursor = db.cursor()
        cursor.execute("DELETE FROM quilometragem WHERE id = %s", (id,))
        db.commit()
        cursor.close()
        flash('Quilometragem excluída com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir quilometragem: {str(e)}', 'danger')
        db.rollback()
    
    return redirect(url_for('quilometragem.lista'))
