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
