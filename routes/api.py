from flask import Blueprint, jsonify, current_app, request
from flask_login import login_required

from models.rota import Rota
from utils.db import get_db_connection

api_bp = Blueprint('api', __name__, url_prefix='/api')

# O nome do produto NAO sai do cod_ANP (17/09/2026). Havia aqui um de-para
# ANP -> nome, com um "se o cprod for 64, escreve ARLA" pregado do lado. O ANP
# identifica familia, nao produto: o 620505001 sozinho cobre 37 itens do posto.
# Hoje o item ja carrega o produto que o usuario classificou (produto_id), e o
# nome sai do cadastro -- o mesmo nome que os relatorios mostram.


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


@api_bp.route('/vendas/ultimas', methods=['GET'])
@login_required
def vendas_ultimas():
    """AO VIVO: as ultimas vendas (nao canceladas) para o card do dashboard.

    SOMENTE LEITURA. ?n= quantas (1 a 20; padrao 5). Para cada nota, o ITEM
    de maior valor (produto/qtd/R$ do item), quantos itens extras existem
    (`extra`), o numero da nota, o acrescimo e a classe de recebimento.
    """
    try:
        n = max(1, min(20, int(request.args.get('n') or 5)))
    except (TypeError, ValueError):
        n = 5
    conn = cur = None
    try:
        from utils.dashboard_cards import ultimas_vendas
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        return jsonify({'ok': True, 'vendas': ultimas_vendas(cur, n)})
    except Exception:
        current_app.logger.exception('[api/vendas/ultimas] falha')
        return jsonify({'ok': False, 'vendas': []}), 500
    finally:
        for c in (cur, conn):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


@api_bp.route('/dashboard/cartoes', methods=['GET'])
@login_required
def dashboard_cartoes():
    """Card Cartoes x operadora da inicial: os numeros do Conf. Cartoes (aba
    Operadora) do mes corrente. Cache de 15 min em utils.dashboard_cards."""
    try:
        from utils.dashboard_cards import cartoes_operadora
        return jsonify({'ok': True, **cartoes_operadora()})
    except Exception:
        current_app.logger.exception('[api/dashboard/cartoes] falha')
        return jsonify({'ok': False}), 500
