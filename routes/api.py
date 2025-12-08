from flask import Blueprint, jsonify
from models.rota import Rota

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/rota/<int:origem_id>/<int:destino_id>', methods=['GET'])
def get_rota(origem_id, destino_id):
    """Buscar valor de CTe por rota (ORIGEM x DESTINO)"""
    rota = Rota.query.filter_by(
        origem_id=origem_id,
        destino_id=destino_id,
        ativo=True
    ).first()

    if rota:
        return jsonify({'valor_por_litro': float(rota.valor_por_litro)})
    else:
        return jsonify({'valor_por_litro': 0}), 404
