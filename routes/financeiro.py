from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app, Response, stream_with_context
from flask_login import login_required
from utils.db import get_db_connection
from utils.boletos import emitir_boleto_frete, fetch_charge, fetch_boleto_pdf_stream, update_billet_expire

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
        # ler vencimento enviado pelo formulário (opcional)
        vencimento = None
        if request.form:
            vencimento = request.form.get('vencimento') or request.form.get('new_vencimento') or None

        resultado = emitir_boleto_frete(frete_id, vencimento_str=vencimento)
        
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
            flash(f"Erro ao emitir boleto: {str(error_msg)}", "danger")
            return redirect(url_for('fretes.lista'))

    except Exception as e:
        current_app.logger.exception("Erro emitir_boleto_route: %s", e)
        flash(f"Erro ao processar boleto: {str(e)}", "danger")
        return redirect(url_for('fretes.lista'))


# --- NOVAS ROTAS: visualizar/baixar PDF e alterar vencimento ---

@financeiro_bp.route('/visualizar-boleto/<int:charge_id>/')
@login_required
def visualizar_boleto(charge_id):
    """
    Proxy que busca o PDF do provedor e faz stream para o navegador.
    Isso evita expor tokens no cliente e permite o navegador abrir/imprimir o PDF.
    """
    try:
        # obtém dados da charge no provedor para localizar a URL do PDF
        credentials = {
            "client_id": current_app.config.get("EFI_CLIENT_ID") or None,
            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or None,
            "sandbox": current_app.config.get("EFI_SANDBOX", True),
        }
        charge = fetch_charge(credentials, charge_id)
        if not charge or not isinstance(charge, dict):
            flash("Não foi possível obter dados da cobrança no provedor.", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        # procurar a URL do PDF em possíveis caminhos do JSON
        pdf_url = None
        data = charge.get("data") or charge
        # campos mais comuns
        pdf_url = (data.get("pdf") or {}).get("charge") or (data.get("payment") or {}).get("banking_billet", {}).get("link") or data.get("link")
        if not pdf_url:
            flash("URL do PDF não encontrada na resposta do provedor.", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        # busca o conteúdo do PDF do provedor e repassa ao cliente
        resp = fetch_boleto_pdf_stream(credentials, pdf_url)
        if not resp or getattr(resp, "status_code", None) != 200:
            # resp pode ser dict em erro; se for Response, usar resp.text
            text = getattr(resp, "text", "") if isinstance(resp, dict) else (getattr(resp, "text", "") or "")
            flash(f"Falha ao buscar PDF do provedor: {str(text)[:200]}", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        headers = {}
        content_type = resp.headers.get("Content-Type", "application/pdf")
        headers['Content-Type'] = content_type
        # force inline so the browser opens it in a tab
        headers['Content-Disposition'] = f'inline; filename=boleto_{charge_id}.pdf'

        return Response(stream_with_context(resp.iter_content(chunk_size=8192)), headers=headers)
    except Exception as e:
        current_app.logger.exception("Erro em visualizar_boleto: %s", e)
        flash(f"Erro ao visualizar boleto: {str(e)}", "danger")
        return redirect(url_for('financeiro.recebimentos'))


@financeiro_bp.route('/alterar-vencimento/<int:charge_id>/', methods=['GET', 'POST'])
@login_required
def alterar_vencimento(charge_id):
    """
    GET: mostra formulário para alterar data de vencimento.
    POST: chama o provedor para atualizar expire_at e atualiza tabela cobrancas.
    """
    conn = None
    cursor = None
    try:
        if request.method == 'GET':
            # busca dados locais para pré-preencher (se existirem)
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM cobrancas WHERE charge_id = %s LIMIT 1", (charge_id,))
            cobr = cursor.fetchone()
            return render_template('financeiro/alterar_vencimento.html', cobranca=cobr, charge_id=charge_id)

        # POST: aplicar alteração
        new_date = request.form.get('new_vencimento')
        if not new_date:
            flash("Informe uma nova data de vencimento (YYYY-MM-DD).", "warning")
            return redirect(url_for('financeiro.alterar_vencimento', charge_id=charge_id))

        credentials = {
            "client_id": current_app.config.get("EFI_CLIENT_ID") or None,
            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or None,
            "sandbox": current_app.config.get("EFI_SANDBOX", True),
        }
        success, resp = update_billet_expire(credentials, charge_id, new_date)
        if not success:
            flash(f"Falha ao atualizar vencimento no provedor: {resp}", "danger")
            return redirect(url_for('financeiro.recebimentos'))

        # atualizar data_vencimento na tabela cobrancas (se existir)
        conn = conn or get_db_connection()
        cursor = cursor or conn.cursor(dictionary=True)
        try:
            cursor.execute("UPDATE cobrancas SET data_vencimento = %s WHERE charge_id = %s", (new_date, charge_id))
            conn.commit()
        except Exception:
            conn.rollback()
            current_app.logger.exception("Falha ao atualizar data_vencimento local para charge %s", charge_id)

        flash("Vencimento atualizado com sucesso.", "success")
        return redirect(url_for('financeiro.recebimentos'))

    except Exception as e:
        current_app.logger.exception("Erro em alterar_vencimento: %s", e)
        flash(f"Erro ao alterar vencimento: {str(e)}", "danger")
        return redirect(url_for('financeiro.recebimentos'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
