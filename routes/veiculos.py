from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app import db
from models.veiculo import Veiculo

veiculos_bp = Blueprint('veiculos', __name__)

@veiculos_bp.route('/veiculos')
@login_required
def index():
    """Página principal de veículos"""
    return render_template('veiculos/lista.html')

@veiculos_bp.route('/veiculos/novo', methods=['GET', 'POST'])
@login_required
def novo():
    """Cadastrar novo veículo"""
    if request.method == 'POST':
        try:
            veiculo = Veiculo(
                placa=request.form['placa'].upper(),
                modelo=request.form['modelo'],
                ano=request.form['ano'],
                tipo=request.form.get('tipo', ''),
                status=request.form.get('status', 'ativo'),
                capacidade=request.form.get('capacidade', '')
            )
            db.session.add(veiculo)
            db.session.commit()
            flash('Veículo cadastrado com sucesso!', 'success')
            return redirect(url_for('veiculos.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar veículo: {str(e)}', 'error')
    
    return render_template('veiculos/novo.html')

@veiculos_bp.route('/veiculos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    """Editar veículo existente"""
    veiculo = Veiculo.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            veiculo.placa = request.form['placa'].upper()
            veiculo.modelo = request.form['modelo']
            veiculo.ano = request.form['ano']
            veiculo.tipo = request.form.get('tipo', '')
            veiculo.status = request.form.get('status', 'ativo')
            veiculo.capacidade = request.form.get('capacidade', '')
            
            db.session.commit()
            flash('Veículo atualizado com sucesso!', 'success')
            return redirect(url_for('veiculos.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar veículo: {str(e)}', 'error')
    
    return render_template('veiculos/editar.html', veiculo=veiculo)

@veiculos_bp.route('/veiculos/excluir/<int:id>', methods=['POST'])
@login_required
def excluir(id):
    """Excluir veículo"""
    try:
        veiculo = Veiculo.query.get_or_404(id)
        db.session.delete(veiculo)
        db.session.commit()
        flash('Veículo excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir veículo: {str(e)}', 'error')
    
    return redirect(url_for('veiculos.index'))

@veiculos_bp.route('/veiculos/listar', methods=['GET'])
@login_required
def listar_veiculos():
    """API endpoint para listar veículos em JSON"""
    try:
        veiculos = Veiculo.query.all()
        
        veiculos_data = []
        for veiculo in veiculos:
            veiculos_data.append({
                'id': veiculo.id,
                'placa': veiculo.placa,
                'modelo': veiculo.modelo,
                'ano': veiculo.ano,
                'tipo': veiculo.tipo if hasattr(veiculo, 'tipo') else '',
                'status': veiculo.status if hasattr(veiculo, 'status') else 'ativo',
                'capacidade': veiculo.capacidade if hasattr(veiculo, 'capacidade') else ''
            })
        
        return jsonify(veiculos_data), 200
        
    except Exception as e:
        print(f"Erro ao listar veículos: {str(e)}")
        return jsonify({'error': str(e)}), 500
