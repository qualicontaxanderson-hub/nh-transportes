from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from extensions import mysql

veiculos_bp = Blueprint('veiculos', __name__, url_prefix='/veiculos')

# ==================== LISTAR ====================
@veiculos_bp.route('/')
@veiculos_bp.route('/listar')
@login_required
def listar():
    """Lista todos os veículos cadastrados"""
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT id, placa, modelo, ano, observacoes 
        FROM veiculos 
        ORDER BY id DESC
    """)
    veiculos_raw = cursor.fetchall()
    cursor.close()
    
    # Converter tuplas em dicionários
    veiculos = []
    for v in veiculos_raw:
        veiculos.append({
            'id': v[0],
            'placa': v[1],
            'modelo': v[2],
            'ano': v[3],
            'observacoes': v[4]
        })
    
    return render_template('veiculos/lista.html', veiculos=veiculos)


# ==================== NOVO ====================
@veiculos_bp.route('/novo', methods=['GET'])
@login_required
def novo():
    """Exibe formulário para cadastrar novo veículo"""
    return render_template('veiculos/novo.html')


# ==================== EDITAR ====================
@veiculos_bp.route('/editar/<int:id>', methods=['GET'])
@login_required
def editar(id):
    """Exibe formulário para editar veículo existente"""
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM veiculos WHERE id = %s", (id,))
    veiculo_raw = cursor.fetchone()
    cursor.close()
    
    if not veiculo_raw:
        flash('Veículo não encontrado!', 'danger')
        return redirect(url_for('veiculos.listar'))
    
    # Transformar em dicionário
    veiculo = {
        'id': veiculo_raw[0],
        'placa': veiculo_raw[1],
        'modelo': veiculo_raw[2],
        'ano': veiculo_raw[3],
        'observacoes': veiculo_raw[4] if len(veiculo_raw) > 4 else None
    }
    
    return render_template('veiculos/novo.html', veiculo=veiculo)


# ==================== SALVAR ====================
@veiculos_bp.route('/salvar', methods=['POST'])
@veiculos_bp.route('/salvar/<int:id>', methods=['POST'])
@login_required
def salvar(id=None):
    """Salva novo veículo ou atualiza existente"""
    placa = request.form.get('placa', '').strip().upper()
    modelo = request.form.get('modelo', '').strip()
    ano = request.form.get('ano', '').strip()
    observacoes = request.form.get('observacoes', '').strip()
    
    # Validações
    if not placa or not modelo:
        flash('Placa e Modelo são obrigatórios!', 'warning')
        return redirect(url_for('veiculos.novo'))
    
    # Converter ano para inteiro ou None
    ano_int = None
    if ano:
        try:
            ano_int = int(ano)
        except ValueError:
            flash('Ano inválido!', 'warning')
            return redirect(url_for('veiculos.novo'))
    
    cursor = mysql.connection.cursor()
    
    try:
        if id:  # ATUALIZAR
            cursor.execute("""
                UPDATE veiculos 
                SET placa = %s, modelo = %s, ano = %s, observacoes = %s 
                WHERE id = %s
            """, (placa, modelo, ano_int, observacoes or None, id))
            flash('Veículo atualizado com sucesso!', 'success')
        else:  # CRIAR NOVO
            cursor.execute("""
                INSERT INTO veiculos (placa, modelo, ano, observacoes) 
                VALUES (%s, %s, %s, %s)
            """, (placa, modelo, ano_int, observacoes or None))
            flash('Veículo cadastrado com sucesso!', 'success')
        
        mysql.connection.commit()
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Erro ao salvar veículo: {str(e)}', 'danger')
    finally:
        cursor.close()
    
    return redirect(url_for('veiculos.listar'))


# ==================== EXCLUIR ====================
@veiculos_bp.route('/excluir/<int:id>', methods=['GET', 'POST'])
@login_required
def excluir(id):
    """Exclui um veículo"""
    cursor = mysql.connection.cursor()
    
    try:
        cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
        mysql.connection.commit()
        flash('Veículo excluído com sucesso!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Erro ao excluir veículo: {str(e)}', 'danger')
    finally:
        cursor.close()
    
    return redirect(url_for('veiculos.listar'))
