from flask import Blueprint, jsonify, current_app
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
    """AO VIVO: últimas 5 vendas (não canceladas) para o card do dashboard.

    SOMENTE LEITURA. Não altera nada. Para cada nota mostra o ITEM de maior
    valor (produto/qtd/R$ do item, coerentes entre si) e, se houver mais de um
    item, quantos itens extras (`extra`) existem na nota. Retorna JSON.
    """
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT v.id, v.dh_emissao, "
            "COALESCE(NULLIF(TRIM(v.vendedor_raw),''),'—') AS vendedor "
            "FROM vendas_xml v WHERE v.situacao <> 'cancelada' "
            "ORDER BY v.dh_emissao DESC, v.id DESC LIMIT 5"
        )
        notas = cur.fetchall()
        principal = {}
        qt_itens = {}
        if notas:
            ids = [n['id'] for n in notas]
            place = ",".join(["%s"] * len(ids))
            cur.execute(
                "SELECT i.venda_id, i.produto_xml, i.quantidade, i.unidade, "
                "       i.valor_total, p.nome AS produto_nome "
                "  FROM vendas_xml_itens i "
                "  LEFT JOIN produto p ON p.id = i.produto_id "
                " WHERE i.venda_id IN (" + place + ") "
                " ORDER BY i.venda_id, i.valor_total DESC", ids)
            for it in cur.fetchall():
                qt_itens[it['venda_id']] = qt_itens.get(it['venda_id'], 0) + 1
                principal.setdefault(it['venda_id'], it)  # 1º = item de maior valor

        vendas = []
        for n in notas:
            it = principal.get(n['id']) or {}
            # O produto classificado; sem classificacao, o nome cru do XML --
            # que e a verdade daquele item, e nao um palpite.
            produto = it.get('produto_nome') or it.get('produto_xml') or '—'
            vendas.append({
                'id': n['id'],
                'hora': n['dh_emissao'].strftime('%H:%M') if n['dh_emissao'] else '',
                'produto': produto,
                'vendedor': n['vendedor'],
                'litros': float(it.get('quantidade') or 0),
                'unidade': it.get('unidade') or '',
                'valor': float(it.get('valor_total') or 0),   # <== valor DO ITEM
                'extra': max(0, qt_itens.get(n['id'], 0) - 1),  # itens além do principal
            })
        return jsonify({'ok': True, 'vendas': vendas})
    except Exception:
        current_app.logger.exception('[api/vendas/ultimas] falha')
        return jsonify({'ok': False, 'vendas': []}), 500
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
