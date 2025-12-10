from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required
from utils.db import get_db_connection
from utils.boletos import emitir_boleto_frete
from datetime import datetime
import logging

financeiro_bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')
logger = logging.getLogger(__name__)


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

            # Normalizar tipos/formatos para evitar erros no template
            for row in recebimentos_lista:
                # normaliza data_vencimento para datetime se vier string
                dv = row.get('data_vencimento')
                if dv is not None and not hasattr(dv, 'strftime'):
                    try:
                        if isinstance(dv, str):
                            # tenta ISO 8601 ou YYYY-MM-DD
                            try:
                                parsed = datetime.fromisoformat(dv)
                            except Exception:
                                parsed = datetime.strptime(dv, '%Y-%m-%d')
                            row['data_vencimento'] = parsed
                        else:
                            # não reconhecido -> set None
                            current_app.logger.warning(f"[recebimentos] data_vencimento formato inesperado para id={row.get('id')}: {repr(dv)}")
                            row['data_vencimento'] = None
                    except Exception:
                        current_app.logger.exception(f"[recebimentos] falha ao parsear data_vencimento id={row.get('id')}: {repr(dv)}")
                        row['data_vencimento'] = None

                # garante que valor seja float
                try:
                    raw_val = row.get('valor')
                    if raw_val in (None, ''):
                        row['valor'] = 0.0
                    else:
                        # aceita formatos "1234.56" ou "1.234,56"
                        if isinstance(raw_val, str):
                            v = raw_val.replace('.', '').replace(',', '.')
                            row['valor'] = float(v)
                        else:
                            row['valor'] = float(raw_val)
                except Exception:
                    current_app.logger.exception(f"[recebimentos] valor inválido para id={row.get('id')}: {repr(row.get('valor'))}")
                    row['valor'] = 0.0

        except Exception as e:
            current_app.logger.exception(f"[recebimentos] Erro SQL ao buscar recebimentos: {e}")
            flash(f"Erro ao carregar recebimentos: {str(e)}", "danger")
            recebimentos_lista = []

        # Renderizar com proteção contra erros no template
        try:
            return render_template('financeiro/recebimentos.html', recebimentos=recebimentos_lista)
        except Exception:
            current_app.logger.exception("[recebimentos] Erro ao renderizar template de recebimentos")
            flash("Erro ao exibir recebimentos (ver logs).", "danger")
            return render_template('financeiro/recebimentos.html', recebimentos=[])

    except Exception as e:
        current_app.logger.exception(f"[recebimentos] Erro geral: {e}")
        flash(f"Erro ao acessar recebimentos: {str(e)}", "danger")
        return render_template('financeiro/recebimentos.html', recebimentos=[])

    finally:
        # Always close resources if they were created
        try:
            if cursor:
                cursor.close()
        except Exception:
            logger.exception("Erro ao fechar cursor em recebimentos")
        try:
            if conn:
                conn.close()
        except Exception:
            logger.exception("Erro ao fechar conexão em recebimentos")


@financeiro_bp.route('/emitir-boleto/<int:frete_id>/', methods=['POST'])
@login_required
def emitir_boleto_route(frete_id):
    """Emite boleto para um frete específico"""
    try:
        resultado = emitir_boleto_frete(frete_id)

        # Log do resultado para facilitar debug
        current_app.logger.info("Resultado emitir_boleto_frete(%s): %r", frete_id, resultado)

        # Ensure resultado is always a dict
        if not isinstance(resultado, dict):
            current_app.logger.error("Resultado inesperado de emitir_boleto_frete: %r", resultado)
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
            current_app.logger.warning("Falha ao emitir boleto para frete %s: %s", frete_id, error_msg)
            flash(f"Erro ao emitir boleto: {str(error_msg)}", "danger")
            return redirect(url_for('fretes.lista'))

    except Exception as e:
        current_app.logger.exception("[emitir_boleto_route] Erro processando boleto")
        flash(f"Erro ao processar boleto: {str(e)}", "danger")
        return redirect(url_for('fretes.lista'))
