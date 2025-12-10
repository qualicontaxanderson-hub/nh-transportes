from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from utils.db import get_db_connection
from utils.boletos import emitir_boleto_frete

financeiro_bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')


@financeiro_bp.route('/recebimentos/')
@login_required
def recebimentos():
    """Lista todos os recebimentos/boletos"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Try to execute the query
        cursor.execute("""
            SELECT 
                r.*,
                f.id as frete_numero,
                c.razao_social as cliente_nome,
                c.nome_fantasia as cliente_fantasia
            FROM recebimentos r
            LEFT JOIN fretes f ON r.frete_id = f.id
            LEFT JOIN clientes c ON r.cliente_id = c.id
            ORDER BY r.data_vencimento DESC, r.created_at DESC
        """)
        recebimentos_lista = cursor.fetchall()
        
        # Log for debugging
        from flask import current_app
        current_app.logger.info(f"[recebimentos] Encontrados {len(recebimentos_lista)} recebimentos")
        
        return render_template('financeiro/recebimentos.html', recebimentos=recebimentos_lista)

    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"[recebimentos] Erro: {str(e)}")
        flash(f"Erro ao carregar recebimentos: {str(e)}", "danger")
        return render_template('financeiro/recebimentos.html', recebimentos=[])

    finally:
        cursor.close()
        conn.close()


@financeiro_bp.route('/emitir-boleto/<int:frete_id>/', methods=['POST'])
@login_required
def emitir_boleto_route(frete_id):
    """Emite boleto para um frete específico"""
    try:
        resultado = emitir_boleto_frete(frete_id)
        
        # Ensure resultado is always a dict
        if not isinstance(resultado, dict):
            flash(f"Erro inesperado ao emitir boleto: resposta inválida", "danger")
            return redirect(url_for('fretes.lista'))

        if resultado.get('success'):
            flash(
                f"Boleto emitido com sucesso! Charge ID: {resultado.get('charge_id')}",
                "success",
            )
            return redirect(url_for('financeiro.recebimentos'))
        else:
            error_msg = resultado.get('error', 'Erro desconhecido')
            flash(f"Erro ao emitir boleto: {error_msg}", "danger")
            return redirect(url_for('fretes.lista'))

    except Exception as e:
        flash(f"Erro ao processar boleto: {str(e)}", "danger")
        return redirect(url_for('fretes.lista'))
