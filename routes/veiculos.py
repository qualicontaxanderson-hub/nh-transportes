from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import mysql

veiculos_bp = Blueprint('veiculos', __name__)

# 1. LISTAR todos os veículos
@veiculos_bp.route('/')
@veiculos_bp.route('/listar')
def listar():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM veiculos ORDER BY id DESC")
    veiculos = cursor.fetchall()
    cursor.close()
    return render_template('veiculos/lista.html', veiculos=veiculos)

# 2. EXIBIR formulário para NOVO veículo
@veiculos_bp.route('/novo', methods=['GET'])
def novo():
    return render_template('veiculos/novo.html')  # ✅ CORRIGIDO de form.html para novo.html

# 3. EXIBIR formulário para EDITAR veículo
@veiculos_bp.route('/editar/<int:id>', methods=['GET'])
def editar(id):
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM veiculos WHERE id = %s", (id,))
    veiculo = cursor.fetchone()
    cursor.close()
    
    if not veiculo:
        flash('Veículo não encontrado!', 'error')
        return redirect(url_for('veiculos.listar'))
    
    # Transformar em dicionário para facilitar no template
    veiculo_dict = {
        'id': veiculo[0],
        'placa': veiculo[1],
        'modelo': veiculo[2],
        'ano': veiculo[3],
        'observacoes': veiculo[4] if len(veiculo) > 4 else None
    }
    
    return render_template('veiculos/novo.html', veiculo=veiculo_dict)

# 4. SALVAR (criar novo OU atualizar existente)
@veiculos_bp.route('/salvar', methods=['POST'])
@veiculos_bp.route('/salvar/<int:id>', methods=['POST'])
def salvar(id=None):
    placa = request.form.get('placa')
    modelo = request.form.get('modelo')
    ano = request.form.get('ano')
    observacoes = request.form.get('observacoes')
    
    cursor = mysql.connection.cursor()
    
    if id:  # ATUALIZAR veículo existente
        cursor.execute("""
            UPDATE veiculos 
            SET placa = %s, modelo = %s, ano = %s, observacoes = %s 
            WHERE id = %s
        """, (placa, modelo, ano, observacoes, id))
        flash('Veículo atualizado com sucesso!', 'success')
    else:  # CRIAR novo veículo
        cursor.execute("""
            INSERT INTO veiculos (placa, modelo, ano, observacoes) 
            VALUES (%s, %s, %s, %s)
        """, (placa, modelo, ano, observacoes))
        flash('Veículo cadastrado com sucesso!', 'success')
    
    mysql.connection.commit()
    cursor.close()
    
    return redirect(url_for('veiculos.listar'))

# 5. EXCLUIR veículo
@veiculos_bp.route('/excluir/<int:id>')
def excluir(id):
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
    mysql.connection.commit()
    cursor.close()
    
    flash('Veículo excluído com sucesso!', 'success')
    return redirect(url_for('veiculos.listar'))

