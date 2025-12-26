from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app, Response, stream_with_context
from flask_login import login_required
from utils.db import get_db_connection
from utils.boletos import emitir_boleto_frete, fetch_charge, fetch_boleto_pdf_stream, update_billet_expire, cancel_charge

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
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@financeiro_bp.route('/emitir-boleto/<int:frete_id>/', methods=['POST'])
@login_required
def emitir_boleto_route(frete_id):
    """Emite boleto para um frete específico (aceita campo 'vencimento' opcional YYYY-MM-DD)."""
    try:
        vencimento = None
        if request.form:
            vencimento = request.form.get('vencimento') or request.form.get('new_vencimento') or None
        resultado = emitir_boleto_frete(frete_id, vencimento_str=vencimento)
        if not isinstance(resultado, dict):
            flash(f"Erro inesperado ao emitir boleto: resposta inválida", "danger")
            return redirect(url_for('fretes.lista'))
        if resultado.get('success'):
            flash(f"Boleto emitido com sucesso! Charge ID: {resultado.get('charge_id')}", "success")
            return redirect(url_for('financeiro.recebimentos'))
        else:
            error_msg = resultado.get('error', 'Erro desconhecido')
            flash(f"Erro ao emitir boleto: {str(error_msg)}", "danger")
            return redirect(url_for('fretes.lista'))
    except Exception as e:
        current_app.logger.exception("Erro emitir_boleto_route: %s", e)
        flash(f"Erro ao processar boleto: {str(e)}", "danger")
        return redirect(url_for('fretes.lista'))


# visualizar / imprimir (proxy já implementado)
@financeiro_bp.route('/visualizar-boleto/<int:charge_id>/')
@login_required
def visualizar_boleto(charge_id):
    try:
        credentials = {
            "client_id": current_app.config.get("EFI_CLIENT_ID") or None,
            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or None,
            "sandbox": current_app.config.get("EFI_SANDBOX", True),
        }
        charge = fetch_charge(credentials, charge_id)
        if not charge or not isinstance(charge, dict):
            flash("Não foi possível obter dados da cobrança no provedor.", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        data = charge.get("data") or charge
        pdf_url = (data.get("pdf") or {}).get("charge") or (data.get("payment") or {}).get("banking_billet", {}).get("link") or data.get("link")
        if not pdf_url:
            flash("URL do PDF não encontrada na resposta do provedor.", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        resp = fetch_boleto_pdf_stream(credentials, pdf_url)
        if not resp or getattr(resp, "status_code", None) != 200:
            text = getattr(resp, "text", "") if isinstance(resp, dict) else (getattr(resp, "text", "") or "")
            flash(f"Falha ao buscar PDF do provedor: {str(text)[:200]}", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        headers = {}
        content_type = resp.headers.get("Content-Type", "application/pdf")
        headers['Content-Type'] = content_type
        headers['Content-Disposition'] = f'inline; filename=boleto_{charge_id}.pdf'
        return Response(stream_with_context(resp.iter_content(chunk_size=8192)), headers=headers)
    except Exception as e:
        current_app.logger.exception("Erro em visualizar_boleto: %s", e)
        flash(f"Erro ao visualizar boleto: {str(e)}", "danger")
        return redirect(url_for('financeiro.recebimentos'))


# marcar como pago (local)
@financeiro_bp.route('/marcar-pago/<int:charge_id>/', methods=['POST'])
@login_required
def marcar_pago(charge_id):
    """
    Marca a cobrança localmente como paga. Isso NÃO substitui uma confirmação de pagamento
    do provedor — é um ato administrativo.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # atualiza status; tenta também atualizar data_pagamento se a coluna existir
        try:
            cursor.execute("UPDATE cobrancas SET status = %s WHERE charge_id = %s", ("pago", charge_id))
            # tenta setar data_pagamento se existir na tabela (não quebra se não existir)
            try:
                cursor.execute("ALTER TABLE cobrancas ADD COLUMN IF NOT EXISTS data_pagamento DATE;")
            except Exception:
                # algumas versões do DB não suportam IF NOT EXISTS — ignorar
                pass
            try:
                cursor.execute("UPDATE cobrancas SET data_pagamento = %s WHERE charge_id = %s", (datetime.today().date(), charge_id))
            except Exception:
                # coluna pode não existir; ignorar
                pass
            conn.commit()
            flash("Cobrança marcada como PAGO (local).", "success")
        except Exception as e:
            conn.rollback()
            current_app.logger.exception("Erro ao marcar pago: %s", e)
            flash("Falha ao marcar como pago.", "danger")
    except Exception as e:
        current_app.logger.exception("Erro em marcar_pago: %s", e)
        flash("Erro ao marcar como pago.", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('financeiro.recebimentos'))


# cancelar boleto (tenta provider then local)
@financeiro_bp.route('/cancelar-boleto/<int:charge_id>/', methods=['POST'])
@login_required
def cancelar_boleto(charge_id):
    """
    Tenta cancelar a cobrança no provedor e atualiza o registro local como 'cancelado'
    para permitir reemissão.
    """
    conn = None
    cursor = None
    try:
        credentials = {
            "client_id": current_app.config.get("EFI_CLIENT_ID") or None,
            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or None,
            "sandbox": current_app.config.get("EFI_SANDBOX", True),
        }
        success, resp = cancel_charge(credentials, charge_id)
        if not success:
            flash(f"Falha ao cancelar no provedor: {resp}", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        # atualizar status local
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE cobrancas SET status = %s WHERE charge_id = %s", ("cancelado", charge_id))
            conn.commit()
            flash("Boleto cancelado com sucesso (provedor + local).", "success")
        except Exception as e:
            conn.rollback()
            current_app.logger.exception("Falha ao atualizar status local após cancelamento: %s", e)
            flash("Boleto cancelado no provedor, mas falha ao atualizar registro local.", "warning")
    except Exception as e:
        current_app.logger.exception("Erro em cancelar_boleto: %s", e)
        flash(f"Erro ao cancelar boleto: {str(e)}", "danger")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('financeiro.recebimentos'))
