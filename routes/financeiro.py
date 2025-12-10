from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required
from utils.db import get_db_connection
from utils.boletos import emitir_boleto_frete

financeiro_bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')


@financeiro_bp.route('/recebimentos/')
@login_required
def recebimentos():
    """Lista todos os recebimentos/boletos"""
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Query cobrancas table (which doesn't have frete_id column)
            # The table schema only has: id_cliente, valor, data_vencimento, status,
            # charge_id, link_boleto, pdf_boleto, data_emissao
            cursor.execute("""
                SELECT 
                    c.*,
                    cl.razao_social as cliente_nome,
                    cl.nome_fantasia as cliente_fantasia
                FROM cobrancas c
                LEFT JOIN clientes cl ON c.id_cliente = cl.id
                ORDER BY c.data_vencimento DESC, c.data_emissao DESC
            """)
            recebimentos_lista = cursor.fetchall()
            
            # Log for debugging
            current_app.logger.info(f"[recebimentos] Encontrados {len(recebimentos_lista)} recebimentos")
            
        except Exception as e:
            current_app.logger.error(f"[recebimentos] Erro SQL: {str(e)}")
            flash(f"Erro ao carregar recebimentos: {str(e)}", "danger")
            recebimentos_lista = []
        
        return render_template('financeiro/recebimentos.html', recebimentos=recebimentos_lista)
            
    except Exception as e:
        current_app.logger.error(f"[recebimentos] Erro geral: {str(e)}")
        flash(f"Erro ao acessar recebimentos: {str(e)}", "danger")
        return render_template('financeiro/recebimentos.html', recebimentos=[])
    
    finally:
        # Always close resources if they were created
        if cursor:
            cursor.close()
        if conn:
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
            # Ensure error_msg is always a string
            flash(f"Erro ao emitir boleto: {str(error_msg)}", "danger")
            return redirect(url_for('fretes.lista'))

    except Exception as e:
        flash(f"Erro ao processar boleto: {str(e)}", "danger")
        return redirect(url_for('fretes.lista'))
