from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app, Response, stream_with_context, send_file, abort
from flask_login import login_required
from utils.db import get_db_connection
from utils.boletos import emitir_boleto_frete, emitir_boleto_multiplo, fetch_charge, fetch_boleto_pdf_stream, update_billet_expire, cancel_charge
from datetime import datetime, date
from calendar import monthrange
import os

financeiro_bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')


def _get_efi_credentials():
    """Helper function to get EFI credentials consistently across routes."""
    return {
        "client_id": current_app.config.get("EFI_CLIENT_ID") or os.getenv("EFI_CLIENT_ID"),
        "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or os.getenv("EFI_CLIENT_SECRET"),
        "sandbox": current_app.config.get("EFI_SANDBOX", True),
    }



@financeiro_bp.route('/recebimentos/')
@login_required
def recebimentos():
    """Lista todos os recebimentos/boletos com filtro de data e resumo"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Filtros de data - PADRÃO: mês/ano atual
        hoje = date.today()
        primeiro_dia_mes = date(hoje.year, hoje.month, 1)
        ultimo_dia = monthrange(hoje.year, hoje.month)[1]
        ultimo_dia_mes = date(hoje.year, hoje.month, ultimo_dia)
        
        data_inicio = request.args.get('data_inicio', primeiro_dia_mes.strftime('%Y-%m-%d'))
        data_fim = request.args.get('data_fim', ultimo_dia_mes.strftime('%Y-%m-%d'))

        try:
            # Buscar recebimentos/boletos emitidos no período
            cursor.execute("""
                SELECT 
                    c.*,
                    cl.razao_social AS cliente_nome,
                    cl.nome_fantasia AS cliente_fantasia,
                    f.id AS frete_id,
                    f.id AS frete_numero,
                    f.data_frete AS frete_data
                FROM cobrancas c
                LEFT JOIN clientes cl ON c.id_cliente = cl.id
                LEFT JOIN fretes f ON c.frete_id = f.id
                WHERE c.data_emissao BETWEEN %s AND %s
                ORDER BY c.data_vencimento DESC, c.data_emissao DESC
            """, (data_inicio, data_fim))
            recebimentos_lista = cursor.fetchall()
            current_app.logger.info(f"[recebimentos] Encontrados {len(recebimentos_lista)} recebimentos")
        except Exception as e:
            current_app.logger.error(f"[recebimentos] Erro SQL: {str(e)}")
            flash(f"Erro ao carregar recebimentos: {str(e)}", "danger")
            recebimentos_lista = []

        # Calcular resumos do período
        try:
            # Total de fretes no período
            cursor.execute("""
                SELECT COALESCE(SUM(f.valor_total_frete), 0) AS total_fretes
                FROM fretes f
                WHERE f.data_frete BETWEEN %s AND %s
            """, (data_inicio, data_fim))
            total_fretes = float(cursor.fetchone().get('total_fretes', 0) or 0)

            # Total de boletos emitidos no período (soma dos valores das cobranças)
            cursor.execute("""
                SELECT COALESCE(SUM(c.valor), 0) AS total_boletos
                FROM cobrancas c
                WHERE c.data_emissao BETWEEN %s AND %s
                AND (c.status IS NULL OR c.status != 'cancelado')
            """, (data_inicio, data_fim))
            total_boletos = float(cursor.fetchone().get('total_boletos', 0) or 0)

            # Diferença
            diferenca = total_fretes - total_boletos
        except Exception as e:
            current_app.logger.error(f"[recebimentos] Erro ao calcular resumos: {str(e)}")
            total_fretes = 0
            total_boletos = 0
            diferenca = 0

        # --- normalizar e calcular display_status para UI -------------------
        # Regras:
        # - 'pago' = pagamento registrado pelo provedor (pago_via_provedor = 1) ou charge_id presente e status='pago'
        # - 'quitado' = registro com status='pago' sem charge_id (pagamento manual)
        # - 'cancelado' = status local = 'cancelado'
        # - 'vencido' = data_vencimento < hoje e não pago/cancelado
        # - 'pendente' = default (a vencer ou sem data)
        try:
            today = date.today()
            for r in recebimentos_lista:
                try:
                    status_raw = (r.get('status') or '').strip().lower()
                except Exception:
                    status_raw = ''

                charge_id = r.get('charge_id') if isinstance(r, dict) else None
                try:
                    pago_via_provedor = bool(int(r.get('pago_via_provedor') or 0))
                except Exception:
                    pago_via_provedor = False

                # formatar data_vencimento para exibição
                dv = r.get('data_vencimento')
                r['data_vencimento_fmt'] = '-'
                try:
                    if dv:
                        if hasattr(dv, 'strftime'):
                            r['data_vencimento_fmt'] = dv.strftime('%d/%m/%Y')
                        else:
                            # aceitar string YYYY-MM-DD
                            try:
                                parsed = datetime.strptime(str(dv)[:10], '%Y-%m-%d').date()
                                r['data_vencimento_fmt'] = parsed.strftime('%d/%m/%Y')
                            except Exception:
                                r['data_vencimento_fmt'] = str(dv)
                except Exception:
                    r['data_vencimento_fmt'] = '-'

                # decidir display_status (prioridade)
                if status_raw == 'cancelado':
                    r['display_status'] = 'cancelado'
                elif pago_via_provedor or (charge_id not in (None, '', 0) and status_raw == 'pago'):
                    r['display_status'] = 'pago'
                elif status_raw == 'pago' and (charge_id in (None, '', 0) and not pago_via_provedor):
                    r['display_status'] = 'quitado'
                else:
                    venc = None
                    try:
                        if dv:
                            venc = dv if hasattr(dv, 'strftime') else datetime.strptime(str(dv)[:10], '%Y-%m-%d').date()
                    except Exception:
                        venc = None
                    if venc:
                        r['display_status'] = 'vencido' if venc < today else 'pendente'
                    else:
                        r['display_status'] = 'pendente'
        except Exception:
            current_app.logger.exception("[recebimentos] erro calculando display_status")
        # -------------------------------------------------------------------

        return render_template('financeiro/recebimentos.html', 
                             recebimentos=recebimentos_lista,
                             data_inicio=data_inicio,
                             data_fim=data_fim,
                             total_fretes=total_fretes,
                             total_boletos=total_boletos,
                             diferenca=diferenca)
    except Exception as e:
        current_app.logger.error(f"[recebimentos] Erro geral: {str(e)}")
        flash(f"Erro ao acessar recebimentos: {str(e)}", "danger")
        return render_template('financeiro/recebimentos.html', recebimentos=[],
                             data_inicio='', data_fim='',
                             total_fretes=0, total_boletos=0, diferenca=0)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def _wants_json():
    """Helper: detect if request expects JSON (AJAX or Accept header)."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json


@financeiro_bp.route('/emitir-boleto/<int:frete_id>/', methods=['POST'])
@login_required
def emitir_boleto_route(frete_id):
    """Emite boleto para um frete específico (aceita campo 'vencimento' opcional YYYY-MM-DD ou DD/MM/YYYY)."""
    try:
        vencimento = None
        if request.is_json:
            try:
                payload = request.get_json(silent=True) or {}
                vencimento = payload.get('vencimento') or payload.get('new_vencimento') or None
            except Exception:
                vencimento = None
        else:
            vencimento = request.form.get('vencimento') or request.form.get('new_vencimento') or None

        resultado = emitir_boleto_frete(frete_id, vencimento_str=vencimento)
        if not isinstance(resultado, dict):
            msg = "Erro inesperado ao emitir boleto: resposta inválida"
            current_app.logger.error(f"[emitir_boleto] resposta inválida: {repr(resultado)}")
            if _wants_json():
                return jsonify({"success": False, "error": msg}), 500
            flash(msg, "danger")
            return redirect(url_for('fretes.lista'))

        if resultado.get('success'):
            charge_id = resultado.get('charge_id')
            boleto_url = resultado.get('boleto_url') or resultado.get('link_boleto')
            barcode = resultado.get('barcode')
            pdf_boleto = resultado.get('pdf_boleto')

            if _wants_json():
                payload = {"success": True, "charge_id": charge_id}
                if boleto_url:
                    payload["boleto_url"] = boleto_url
                if pdf_boleto:
                    payload["pdf_boleto"] = pdf_boleto
                if barcode:
                    payload["barcode"] = barcode
                return jsonify(payload), 200

            flash(f"Boleto emitido com sucesso! Charge ID: {charge_id}", "success")
            return redirect(url_for('financeiro.recebimentos'))
        else:
            error_msg = str(resultado.get('error', 'Erro desconhecido'))
            current_app.logger.warning(f"[emitir_boleto] erro: {error_msg}")
            if _wants_json():
                return jsonify({"success": False, "error": error_msg}), 400
            flash(f"Erro ao emitir boleto: {error_msg}", "danger")
            return redirect(url_for('fretes.lista'))
    except Exception as e:
        current_app.logger.exception("Erro emitir_boleto_route: %s", e)
        if _wants_json():
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"Erro ao processar boleto: {str(e)}", "danger")
        return redirect(url_for('fretes.lista'))


@financeiro_bp.route('/emitir-boleto-multiple/', methods=['POST'])
@login_required
def emitir_boleto_multiple_route():
    """
    Emite um único boleto para múltiplos fretes (POST JSON):
    { "frete_ids": [1,2,3], "vencimento": "YYYY-MM-DD" }
    Retorna JSON com success e charge_id/boleto_url/pdf_boleto.
    """
    try:
        if not request.is_json:
            return jsonify({"success": False, "error": "Requisição deve ser JSON"}), 400
        payload = request.get_json(silent=True) or {}
        frete_ids = payload.get("frete_ids") or payload.get("ids") or []
        vencimento = payload.get("vencimento") or payload.get("new_vencimento") or None

        if not isinstance(frete_ids, (list, tuple)) or len(frete_ids) == 0:
            return jsonify({"success": False, "error": "frete_ids ausentes ou inválidos"}), 400

        resultado = emitir_boleto_multiplo(frete_ids, vencimento_str=vencimento)
        if not isinstance(resultado, dict):
            current_app.logger.error("emitir_boleto_multiple_route: resposta inválida")
            return jsonify({"success": False, "error": "Resposta inválida do utilitário"}), 500

        if resultado.get("success"):
            resp = {"success": True, "charge_id": resultado.get("charge_id")}
            if resultado.get("boleto_url"):
                resp["boleto_url"] = resultado.get("boleto_url")
            if resultado.get("pdf_boleto"):
                resp["pdf_boleto"] = resultado.get("pdf_boleto")
            if resultado.get("barcode"):
                resp["barcode"] = resultado.get("barcode")
            return jsonify(resp), 200
        else:
            return jsonify({"success": False, "error": resultado.get("error", "Erro desconhecido")}), 400
    except Exception as e:
        current_app.logger.exception("Erro emitir_boleto_multiple_route: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@financeiro_bp.route('/prorrogar-boleto/<charge_id>/', methods=['POST'])
@login_required
def prorrogar_boleto(charge_id):
    """
    Prorroga (altera) vencimento do boleto no provedor e atualiza localmente.
    Espera JSON { "new_date": "YYYY-MM-DD" } ou form data.
    """
    try:
        new_date = None
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            new_date = payload.get("new_date") or payload.get("new_vencimento")
        else:
            new_date = request.form.get('new_date') or request.form.get('new_vencimento')

        if not new_date:
            return jsonify({"success": False, "error": "new_date ausente"}), 400

        credentials = _get_efi_credentials()
        success, resp = update_billet_expire(credentials, charge_id, new_date)
        if not success:
            current_app.logger.warning("[prorrogar_boleto] falha provedor: %r", resp)
            return jsonify({"success": False, "error": resp}), 400

        # atualizar localmente data_vencimento se houver registro
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE cobrancas SET data_vencimento = %s WHERE charge_id = %s", (new_date, str(charge_id)))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            current_app.logger.exception("[prorrogar_boleto] falha atualizando DB para charge %s", charge_id)

        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.exception("Erro em prorrogar_boleto: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@financeiro_bp.route('/reemitir-boleto/<charge_id>/', methods=['POST'])
@login_required
def reemitir_boleto(charge_id):
    """
    Reemite boleto para a mesma cobrança (após cancelamento).
    Fluxo:
      - busca cobranca por charge_id
      - só permite reemissão se status == 'cancelado'
      - tenta reemitir:
          * se cobrancas.frete_id presente -> emitir_boleto_frete(frete_id)
          * else se existe mapping em cobrancas_freites -> emitir_boleto_multiplo(list_of_fretes)
          * else se o corpo da requisição fornecer frete_id -> emitir_boleto_frete(frete_id)
    Retorna JSON com resultado do utilitário de emissão.
    """
    try:
        payload = request.get_json(silent=True) or {}
        override_frete_id = payload.get("frete_id") or None

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, frete_id, status FROM cobrancas WHERE charge_id = %s LIMIT 1", (str(charge_id),))
        cobr = cur.fetchone()
        if not cobr:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Cobrança não encontrada"}), 404

        status = (cobr.get("status") or "").strip().lower()
        if status != "cancelado":
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Só é possível reemitir boleto quando a cobrança estiver 'cancelado'."}), 400

        # prioridade: frete_id do payload -> frete_id da cobranca -> cobrancas_freites mapping
        if override_frete_id:
            try:
                fid = int(override_frete_id)
                cur.close()
                conn.close()
                resultado = emitir_boleto_frete(fid)
                return jsonify(resultado), (200 if resultado.get("success") else 400)
            except Exception:
                pass

        if cobr.get("frete_id"):
            try:
                fid = int(cobr.get("frete_id"))
                cur.close()
                conn.close()
                resultado = emitir_boleto_frete(fid)
                return jsonify(resultado), (200 if resultado.get("success") else 400)
            except Exception:
                pass

        # tentar buscar relações em cobrancas_freites (agrupada)
        try:
            cur.execute("SELECT frete_id FROM cobrancas_freites WHERE cobranca_id = %s", (int(cobr.get("id")),))
            rows = cur.fetchall()
            frete_ids = [int(r.get("frete_id")) for r in rows if r.get("frete_id")]
            cur.close()
            conn.close()
            if frete_ids:
                resultado = emitir_boleto_multiplo(frete_ids)
                return jsonify(resultado), (200 if resultado.get("success") else 400)
        except Exception:
            # tentar com nome alternativo da tabela se usar outro nome
            try:
                cur.execute("SELECT frete_id FROM cobrancas_fretes WHERE cobranca_id = %s", (int(cobr.get("id")),))
                rows = cur.fetchall()
                frete_ids = [int(r.get("frete_id")) for r in rows if r.get("frete_id")]
                cur.close()
                conn.close()
                if frete_ids:
                    resultado = emitir_boleto_multiplo(frete_ids)
                    return jsonify(resultado), (200 if resultado.get("success") else 400)
            except Exception:
                current_app.logger.debug("reemitir_boleto: cobrancas_freites não existe ou falhou a query")

        # sem frete identificado
        cur.close()
        conn.close()
        return jsonify({"success": False, "error": "Não foi possível determinar frete(s) para reemissão. Forneça 'frete_id' no corpo da requisição."}), 400
    except Exception as e:
        current_app.logger.exception("Erro em reemitir_boleto: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@financeiro_bp.route('/quitar-frete/', methods=['POST'])
@login_required
def quitar_frete():
    """
    Quitar um ou vários fretes (pagamento em dinheiro/antecipado).
    Espera JSON: { "frete_ids": [1,2], "data_pagamento": "YYYY-MM-DD" }
    Cria/atualiza registros em cobrancas com status='pago' e marca fretes.boleto_emitido = TRUE.
    """
    try:
        if not request.is_json:
            return jsonify({"success": False, "error": "Requisição deve ser JSON"}), 400
        payload = request.get_json(silent=True) or {}
        frete_ids = payload.get("frete_ids") or payload.get("ids") or []
        data_pagamento = payload.get("data_pagamento") or payload.get("data") or None

        if not frete_ids:
            return jsonify({"success": False, "error": "frete_ids ausentes"}), 400
        # normalize
        try:
            ids = [int(x) for x in frete_ids]
        except Exception:
            return jsonify({"success": False, "error": "frete_ids inválidos"}), 400

        if not data_pagamento:
            data_pagamento = datetime.today().date().isoformat()

        conn = get_db_connection()
        cur = conn.cursor()
        saved = []
        failed = []
        try:
            for fid in ids:
                try:
                    cur.execute("SELECT id, clientes_id, valor_total_frete FROM fretes WHERE id = %s LIMIT 1", (fid,))
                    frete = cur.fetchone()
                    if not frete:
                        failed.append({"id": fid, "error": "frete não encontrado"})
                        continue
                    cliente_id = frete[1] if isinstance(frete, (list, tuple)) else frete.get("clientes_id")
                    valor = frete[2] if isinstance(frete, (list, tuple)) else frete.get("valor_total_frete") or 0

                    cur.execute("""
                        INSERT INTO cobrancas (frete_id, id_cliente, valor, data_vencimento, status, charge_id, data_emissao, data_pagamento, pago_via_provedor)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        fid,
                        cliente_id,
                        float(valor),
                        None,
                        "pago",
                        None,
                        datetime.today().date(),
                        data_pagamento,
                        0
                    ))
                    cobr_id = getattr(cur, "lastrowid", None) or None

                    try:
                        cur.execute("UPDATE fretes SET boleto_emitido = TRUE WHERE id = %s", (fid,))
                    except Exception:
                        current_app.logger.exception("Falha marcando frete boleto_emitido para %s", fid)

                    conn.commit()
                    saved.append({"frete_id": fid, "cobranca_id": cobr_id})
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    current_app.logger.exception("Erro ao quitar frete %s: %s", fid, e)
                    failed.append({"id": fid, "error": str(e)})
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        if failed and not saved:
            return jsonify({"success": False, "error": "Falha ao quitar todos os fretes", "details": failed}), 500
        return jsonify({"success": True, "saved": saved, "failed": failed}), 200

    except Exception as e:
        current_app.logger.exception("Erro em quitar_frete: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@financeiro_bp.route('/visualizar-boleto/<int:charge_id>/')
@login_required
def visualizar_boleto(charge_id):
    """
    Primeiro tenta servir PDF salvo localmente (pdf_boleto em cobrancas).
    - se pdf_boleto for um caminho local existente -> serve com send_file inline
    - se pdf_boleto for uma URL -> redireciona para a URL (abrir no provedor)
    Se não houver pdf_boleto ou estiver inválido, faz fetch ao provedor e stream (com fetch_boleto_pdf_stream).
    """
    try:
        row = None
        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT pdf_boleto, link_boleto FROM cobrancas WHERE charge_id = %s LIMIT 1", (charge_id,))
            row = cur.fetchone()
            try:
                cur.close()
                conn.close()
            except Exception:
                pass
        except Exception:
            row = None
            try:
                if 'cur' in locals() and cur:
                    cur.close()
                if 'conn' in locals() and conn:
                    conn.close()
            except Exception:
                pass

        if row:
            pdf_boleto = row.get("pdf_boleto")
            link_boleto = row.get("link_boleto")
            if pdf_boleto:
                if isinstance(pdf_boleto, str) and (pdf_boleto.startswith('/') or pdf_boleto.startswith('.')):
                    try:
                        if os.path.exists(pdf_boleto):
                            return send_file(pdf_boleto, mimetype='application/pdf', as_attachment=False, download_name=f"boleto_{charge_id}.pdf")
                    except Exception:
                        current_app.logger.exception("visualizar_boleto: falha ao servir arquivo local %s", pdf_boleto)
                else:
                    try:
                        if pdf_boleto.startswith('http://') or pdf_boleto.startswith('https://'):
                            return redirect(pdf_boleto)
                    except Exception:
                        pass
            if link_boleto and isinstance(link_boleto, str) and (link_boleto.startswith('http://') or link_boleto.startswith('https://')):
                return redirect(link_boleto)

        credentials = _get_efi_credentials()
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
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM cobrancas WHERE charge_id = %s LIMIT 1", (charge_id,))
            cobr = cursor.fetchone()
            return render_template('financeiro/alterar_vencimento.html', cobranca=cobr, charge_id=charge_id)

        new_date = request.form.get('new_vencimento')
        if not new_date:
            flash("Informe uma nova data de vencimento (YYYY-MM-DD).", "warning")
            return redirect(url_for('financeiro.alterar_vencimento', charge_id=charge_id))

        credentials = _get_efi_credentials()
        success, resp = update_billet_expire(credentials, charge_id, new_date)
        if not success:
            flash(f"Falha ao atualizar vencimento no provedor: {resp}", "danger")
            return redirect(url_for('financeiro.recebimentos'))

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


@financeiro_bp.route('/marcar-pago/<int:charge_id>/', methods=['POST'])
@login_required
def marcar_pago(charge_id):
    """
    Marca a cobrança localmente como paga (admin).
    Proteção: se a cobrança foi marcada como paga via provedor (pago_via_provedor=TRUE),
    NÃO permite marcar/alterar localmente para evitar inconsistências.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verificar se esta cobrança foi marcada pelo provedor
        try:
            cursor.execute("SELECT pago_via_provedor, status FROM cobrancas WHERE charge_id = %s LIMIT 1", (str(charge_id),))
            row = cursor.fetchone()
        except Exception:
            row = None

        if row:
            try:
                if int(row.get('pago_via_provedor') or 0):
                    flash("Pagamento registrado pelo provedor (EFI). Reversão/alteração não permitida pelo sistema.", "danger")
                    return redirect(url_for('financeiro.recebimentos'))
            except Exception:
                # se dado malformado, prevenir alteração por segurança
                flash("Não é possível alterar este registro automaticamente (verifique com o financeiro).", "danger")
                return redirect(url_for('financeiro.recebimentos'))

        # Se não for pago via provedor, permitir marcar como pago (admin)
        try:
            # usar cursor sem dictionary para updates
            cursor.close()
            cursor = conn.cursor()
            cursor.execute("UPDATE cobrancas SET status = %s WHERE charge_id = %s", ("pago", charge_id))
            try:
                cursor.execute("ALTER TABLE cobrancas ADD COLUMN IF NOT EXISTS data_pagamento DATE;")
            except Exception:
                pass
            try:
                cursor.execute("UPDATE cobrancas SET data_pagamento = %s WHERE charge_id = %s", (datetime.today().date(), charge_id))
            except Exception:
                pass
            conn.commit()
            flash("Cobrança marcada como PAGO (local).", "success")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            current_app.logger.exception("Erro ao marcar pago: %s", e)
            flash("Falha ao marcar como pago.", "danger")
    except Exception as e:
        current_app.logger.exception("Erro em marcar_pago: %s", e)
        flash("Erro ao marcar como pago.", "danger")
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return redirect(url_for('financeiro.recebimentos'))


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
        credentials = _get_efi_credentials()
        success, resp = cancel_charge(credentials, charge_id)
        if not success:
            flash(f"Falha ao cancelar no provedor: {resp}", "danger")
            return redirect(url_for('financeiro.recebimentos'))

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


@financeiro_bp.route('/consultar-status-efi/<int:charge_id>/', methods=['GET'])
@login_required
def consultar_status_efi(charge_id):
    """
    Consulta o status atual da cobrança no provedor EFI (Efipay).
    Retorna JSON com informações atualizadas da charge.
    """
    try:
        credentials = _get_efi_credentials()
        
        # Buscar informações da charge no provedor
        charge_data = fetch_charge(credentials, charge_id)
        
        # Log para debug
        current_app.logger.info(f"[consultar_status_efi] charge_id={charge_id}, response_type={type(charge_data).__name__}")
        if isinstance(charge_data, dict):
            current_app.logger.info(f"[consultar_status_efi] response_keys={list(charge_data.keys())}")
        else:
            current_app.logger.warning(f"[consultar_status_efi] response não é dict: {str(charge_data)[:200]}")
        
        if not charge_data or not isinstance(charge_data, dict):
            return jsonify({
                "success": False, 
                "error": f"Não foi possível consultar a cobrança no provedor EFI (tipo de resposta: {type(charge_data).__name__})"
            }), 400
        
        # Verificar se há erro HTTP na resposta (http_status ou code)
        error_code = charge_data.get("http_status") or charge_data.get("code")
        if error_code and error_code != 200:
            error_text = charge_data.get("text", "") or charge_data.get("message", "") or "Erro desconhecido"
            current_app.logger.warning(f"[consultar_status_efi] Erro {error_code}: {error_text[:200]}")
            
            # Mensagem de erro mais específica para 401
            if error_code == 401:
                sandbox_status = "SANDBOX (homologação)" if current_app.config.get("EFI_SANDBOX", True) else "PRODUÇÃO"
                error_msg = (
                    f"❌ Acesso Negado (401 Unauthorized)\n\n"
                    f"As credenciais não têm permissão para consultar esta cobrança.\n\n"
                    f"🔍 Possíveis causas:\n"
                    f"1. A cobrança foi criada com credenciais diferentes\n"
                    f"2. O certificado não tem permissão de leitura (apenas criação)\n"
                    f"3. Ambiente incorreto - Atual: {sandbox_status}\n"
                    f"4. Charge ID {charge_id} não pertence à sua conta EFI\n\n"
                    f"💡 Solução: Teste com uma cobrança criada recentemente por este sistema."
                )
            else:
                error_msg = f"Erro ao consultar EFI (código {error_code}): {error_text[:100]}"
            
            # Retornar 200 com sucesso False para que frontend processe a mensagem
            return jsonify({
                "success": False,
                "error": error_msg,
                "error_code": error_code,
                "charge_id": charge_id,
                "status": "erro_autorizacao" if error_code == 401 else "erro_consulta"
            }), 200
        
        # Extrair dados relevantes da resposta com múltiplas tentativas
        data = charge_data.get("data") or charge_data.get("charge") or charge_data
        
        # Log estrutura para debug
        current_app.logger.info(f"[consultar_status_efi] data_type={type(data).__name__}")
        if isinstance(data, dict):
            current_app.logger.info(f"[consultar_status_efi] data_keys={list(data.keys())}")
            current_app.logger.info(f"[consultar_status_efi] status={data.get('status')}, total={data.get('total')}")
        else:
            current_app.logger.warning(f"[consultar_status_efi] data não é dict: {str(data)[:200]}")
        
        # Informações básicas da cobrança
        status = data.get("status") or "desconhecido"
        
        # Tentar extrair valor de múltiplas formas
        total = data.get("total") or data.get("value") or 0
        if not total and isinstance(data.get("items"), list) and len(data.get("items", [])) > 0:
            # Tentar somar valores dos itens
            try:
                total = sum(item.get("value", 0) * item.get("amount", 1) for item in data["items"])
            except (TypeError, ValueError, KeyError):
                total = 0
        
        # Informações de pagamento
        payment = data.get("payment") or {}
        if isinstance(payment, list) and len(payment) > 0:
            payment = payment[0]
        
        banking_billet = payment.get("banking_billet") or {} if isinstance(payment, dict) else {}
        
        # Data de vencimento
        expire_at = banking_billet.get("expire_at") or data.get("expire_at") or payment.get("expire_at")
        
        # Informações de pagamento
        paid_at = data.get("paid_at") or payment.get("paid_at")
        payment_method = payment.get("method") or "boleto"
        
        # Link do boleto
        link = banking_billet.get("link") or data.get("link") or banking_billet.get("pdf")
        barcode = banking_billet.get("barcode") or data.get("barcode")
        
        # Montar resposta estruturada (sem raw_data para evitar vazamento de informações)
        result = {
            "success": True,
            "charge_id": charge_id,
            "status": status,
            "total": total,
            "expire_at": expire_at,
            "paid_at": paid_at,
            "payment_method": payment_method,
            "link": link,
            "barcode": barcode
        }
        
        # Traduzir status para português
        status_translation = {
            "new": "Nova",
            "waiting": "Aguardando",
            "paid": "Pago",
            "unpaid": "Não Pago",
            "refunded": "Reembolsado",
            "contested": "Contestado",
            "canceled": "Cancelado",
            "settled": "Quitado",
            "link": "Link Gerado",
            "expired": "Expirado"
        }
        result["status_label"] = status_translation.get(status.lower(), status)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception("Erro em consultar_status_efi: %s", e)
        return jsonify({
            "success": False, 
            "error": f"Erro ao consultar status: {str(e)}"
        }), 500


@financeiro_bp.route('/reverter-conciliacao/<int:tx_id>/', methods=['POST'])
@login_required
def reverter_conciliacao(tx_id):
    """Reverte a conciliação de uma transação bancária: volta para status='pendente',
    limpa forma_recebimento_id, fornecedor_id, conciliado_em, conciliado_por e tipo_conciliacao,
    e remove os vínculos em lancamentos_despesas e troco_pix.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, tipo, status, descricao FROM bank_transactions WHERE id = %s LIMIT 1",
            (tx_id,),
        )
        tx = cursor.fetchone()
        if not tx:
            flash("Transação não encontrada.", "danger")
            return redirect(request.referrer or url_for('financeiro.recebimento'))
        if tx['status'] != 'conciliado':
            flash("Apenas transações conciliadas podem ter a conciliação revertida.", "warning")
            return redirect(request.referrer or url_for('financeiro.recebimento'))

        cursor_w = conn.cursor()
        # Desvincular lancamentos_despesas (graceful: tabela pode não ter a coluna)
        try:
            cursor_w.execute(
                "UPDATE lancamentos_despesas SET bank_transaction_id = NULL WHERE bank_transaction_id = %s",
                (tx_id,),
            )
        except Exception as exc_ld:
            current_app.logger.warning("reverter_conciliacao: não foi possível desvincular lancamentos_despesas tx=%s: %s", tx_id, exc_ld)

        # Desvincular troco_pix (graceful: coluna pode não existir ainda)
        try:
            cursor_w.execute(
                "UPDATE troco_pix SET bank_transaction_id = NULL WHERE bank_transaction_id = %s",
                (tx_id,),
            )
        except Exception as exc_tp:
            current_app.logger.warning("reverter_conciliacao: não foi possível desvincular troco_pix tx=%s: %s", tx_id, exc_tp)

        # Reverter a transação — tenta com tipo_conciliacao (migration >= 20260224)
        try:
            cursor_w.execute(
                """UPDATE bank_transactions
                   SET status = 'pendente',
                       forma_recebimento_id = NULL,
                       fornecedor_id        = NULL,
                       conciliado_em        = NULL,
                       conciliado_por       = NULL,
                       tipo_conciliacao     = NULL
                   WHERE id = %s""",
                (tx_id,),
            )
        except Exception:
            # Fallback: tipo_conciliacao não existe (migration pendente)
            conn.rollback()
            try:
                cursor_w.execute(
                    """UPDATE bank_transactions
                       SET status = 'pendente',
                           forma_recebimento_id = NULL,
                           fornecedor_id        = NULL,
                           conciliado_em        = NULL,
                           conciliado_por       = NULL
                       WHERE id = %s""",
                    (tx_id,),
                )
            except Exception as exc_fb:
                raise exc_fb

        conn.commit()
        flash(
            f"Conciliação da transação #{tx_id} revertida com sucesso. Agora está pendente.",
            "success",
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Erro em reverter_conciliacao tx_id=%s: %s", tx_id, e)
        flash(f"Erro ao reverter conciliação: {e}", "danger")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    # Redireciona de volta à página de origem (recebimento ou pagamentos)
    referrer = request.referrer or ''
    if 'pagamento' in referrer:
        return redirect(url_for('financeiro.pagamentos'))
    return redirect(url_for('financeiro.recebimento'))


def _get_bank_transactions(tipo, request_args, exclude_transfers=False):
    """Busca transações bancárias filtradas por tipo (CREDIT ou DEBIT) com filtros opcionais.

    exclude_transfers: quando True (usado na página de Pagamentos), exclui DEBITs que são
    transferências entre contas — identificados pelo CREDIT sintético com hash_dedup
    'TRANSFER_<id>' ou pela coluna tipo_conciliacao='transferencia'.
    """
    from datetime import date
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    conta_id = request_args.get('conta_id', '').strip()
    empresa_id = request_args.get('empresa_id', '').strip()
    forma_recebimento_id = request_args.get('forma_recebimento_id', '').strip()
    status = request_args.get('status', '').strip()
    data_inicio = request_args.get('data_inicio', '').strip()
    data_fim = request_args.get('data_fim', '').strip()

    # Filtros dinâmicos
    where = ["bt.tipo = %s"]
    params = [tipo]
    if conta_id:
        where.append("bt.account_id = %s")
        params.append(conta_id)
    elif empresa_id:
        # Filtra pelas contas que pertencem à empresa selecionada
        where.append("ba.cliente_id = %s")
        params.append(empresa_id)
    if forma_recebimento_id:
        where.append("bt.forma_recebimento_id = %s")
        params.append(forma_recebimento_id)
    if status:
        where.append("bt.status = %s")
        params.append(status)
    if data_inicio:
        where.append("bt.data_transacao >= %s")
        params.append(data_inicio)
    if data_fim:
        where.append("bt.data_transacao <= %s")
        params.append(data_fim)

    # Exclui transferências entre contas da página de Pagamentos.
    # Condição 1: existe um CREDIT sintético TRANSFER_<id> (transferência concluída).
    # Condição 2: tipo_conciliacao='transferencia' (transferência órfã ou sem CREDIT).
    # A condição 2 usa try/except para não quebrar em BDs sem a coluna (migration pendente).
    if exclude_transfers and tipo == 'DEBIT':
        where.append(
            "NOT EXISTS ("
            "  SELECT 1 FROM bank_transactions cr"
            "  WHERE cr.hash_dedup = CONCAT('TRANSFER_', bt.id)"
            "  AND cr.tipo = 'CREDIT'"
            ")"
        )
        # tipo_conciliacao pode não existir antes da migration; testado separadamente abaixo.
        _tc_filter = "(bt.tipo_conciliacao IS NULL OR bt.tipo_conciliacao != 'transferencia')"
    else:
        _tc_filter = None

    where_sql = " AND ".join(where)

    def _run_query(extra_filter):
        w = (where_sql + " AND " + extra_filter) if extra_filter else where_sql
        cursor.execute(
            f"""SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao,
                       bt.cnpj_cpf, bt.memo, bt.status, bt.fornecedor_id,
                       bt.forma_recebimento_id,
                       ba.apelido AS conta_apelido, ba.banco_nome,
                       f.razao_social AS fornecedor_nome,
                       fr.nome AS forma_recebimento_nome,
                       (bt.status='conciliado'
                        AND bt.fornecedor_id IS NULL
                        AND bt.forma_recebimento_id IS NULL
                        AND bt.tipo='DEBIT') AS is_despesa
                FROM bank_transactions bt
                INNER JOIN bank_accounts ba ON bt.account_id = ba.id
                LEFT JOIN fornecedores f ON bt.fornecedor_id = f.id
                LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
                WHERE {w}
                ORDER BY bt.data_transacao DESC
                LIMIT 500""",
            params,
        )
        return cursor.fetchall()

    def _run_totais(extra_filter):
        w = (where_sql + " AND " + extra_filter) if extra_filter else where_sql
        cursor.execute(
            f"""SELECT SUM(bt.valor) AS total,
                       SUM(CASE WHEN bt.status='conciliado' THEN 1 ELSE 0 END) AS conciliados,
                       SUM(CASE WHEN bt.status='pendente' THEN 1 ELSE 0 END) AS pendentes
                FROM bank_transactions bt
                INNER JOIN bank_accounts ba ON bt.account_id = ba.id
                WHERE {w}""",
            params,
        )
        return cursor.fetchone() or {}

    try:
        transacoes = _run_query(_tc_filter)
        totais = _run_totais(_tc_filter)
    except Exception as exc:
        # Fallback: tipo_conciliacao não existe (migration pendente) — usa apenas NOT EXISTS.
        # ProgrammingError errno 1054 = Unknown column.
        import mysql.connector
        if not isinstance(exc, mysql.connector.errors.ProgrammingError):
            raise
        conn.rollback()
        transacoes = _run_query(None)
        totais = _run_totais(None)

    # Lista de contas para o filtro (inclui cliente_id para cascata empresa→conta no JS)
    cursor.execute(
        """SELECT ba.id, ba.apelido, ba.banco_nome,
                  ba.cliente_id,
                  c.razao_social AS empresa_nome
           FROM bank_accounts ba
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           WHERE ba.ativo = 1
           ORDER BY c.razao_social, ba.apelido, ba.banco_nome"""
    )
    contas = cursor.fetchall()

    # Lista de empresas (clientes) que possuem contas bancárias ativas
    cursor.execute(
        """SELECT DISTINCT c.id, c.razao_social
           FROM clientes c
           INNER JOIN bank_accounts ba ON ba.cliente_id = c.id AND ba.ativo = 1
           ORDER BY c.razao_social"""
    )
    empresas = cursor.fetchall()

    # Lista de formas de recebimento ativas
    cursor.execute(
        "SELECT id, nome FROM formas_recebimento WHERE ativo = 1 ORDER BY nome"
    )
    formas = cursor.fetchall()

    cursor.close()
    conn.close()

    return transacoes, totais, contas, empresas, formas


@financeiro_bp.route('/recebimento/')
@login_required
def recebimento():
    """Exibe os créditos bancários importados via OFX."""
    transacoes, totais, contas, empresas, formas = _get_bank_transactions('CREDIT', request.args)
    return render_template(
        'financeiro/recebimento.html',
        transacoes=transacoes,
        total_creditos=totais.get('total') or 0,
        total_conciliados=totais.get('conciliados') or 0,
        total_pendentes=totais.get('pendentes') or 0,
        contas=contas,
        empresas=empresas,
        formas=formas,
        empresa_id_filter=request.args.get('empresa_id', ''),
        conta_id_filter=request.args.get('conta_id', ''),
        forma_recebimento_id_filter=request.args.get('forma_recebimento_id', ''),
        status_filter=request.args.get('status', ''),
        data_inicio=request.args.get('data_inicio', ''),
        data_fim=request.args.get('data_fim', ''),
    )


@financeiro_bp.route('/pagamentos/')
@login_required
def pagamentos():
    """Exibe os débitos bancários importados via OFX (exclui transferências entre contas)."""
    transacoes, totais, contas, empresas, formas = _get_bank_transactions('DEBIT', request.args, exclude_transfers=True)
    return render_template(
        'financeiro/pagamentos.html',
        transacoes=transacoes,
        total_debitos=totais.get('total') or 0,
        total_conciliados=totais.get('conciliados') or 0,
        total_pendentes=totais.get('pendentes') or 0,
        contas=contas,
        conta_id_filter=request.args.get('conta_id', ''),
        status_filter=request.args.get('status', ''),
        data_inicio=request.args.get('data_inicio', ''),
        data_fim=request.args.get('data_fim', ''),
    )


@financeiro_bp.route('/contas/')
@login_required
def contas():
    """Lista as contas bancárias cadastradas no sistema de importação OFX."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT ba.id, ba.banco_nome, ba.agencia, ba.conta, ba.apelido,
                  ba.ativo, ba.criado_em, ba.cliente_id,
                  c.razao_social AS empresa_nome,
                  (SELECT COUNT(*) FROM bank_transactions bt WHERE bt.account_id = ba.id) AS total_transacoes
           FROM bank_accounts ba
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           ORDER BY ba.ativo DESC, ba.apelido, ba.banco_nome"""
    )
    contas_list = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('financeiro/contas.html', contas=contas_list)


@financeiro_bp.route('/transferencias/')
@login_required
def transferencias():
    """Lista as transferências entre contas registradas via conciliação OFX."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Filtros
    f_data_ini = request.args.get('data_ini', '').strip()
    f_data_fim = request.args.get('data_fim', '').strip()
    f_conta    = request.args.get('account_id', '').strip()

    lista       = []
    totais      = {}
    orfaos      = []
    candidatos  = []
    contas      = []
    erro_db     = None

    try:
        # Query principal: parte do lado CREDIT (hash_dedup LIKE 'TRANSFER_%')
        # Não usa ba.cliente_id pois essa coluna pode não existir ainda
        # (depende da migration 20260223_pending_all_idempotente.sql).
        where = ["bt.tipo = 'CREDIT'",
                 "bt.status IN ('conciliado', 'pendente')",
                 "bt.hash_dedup LIKE 'TRANSFER\\_%'"]
        params = []
        if f_data_ini:
            where.append("bt.data_transacao >= %s")
            params.append(f_data_ini)
        if f_data_fim:
            where.append("bt.data_transacao <= %s")
            params.append(f_data_fim)
        if f_conta:
            where.append("(bt.account_id = %s OR bt_orig.account_id = %s)")
            params += [f_conta, f_conta]

        where_sql = ' AND '.join(where)

        cursor.execute(
            f"""SELECT bt.id AS id_credit, bt_orig.id AS id,
                       bt.data_transacao, bt.valor, bt_orig.descricao AS descricao,
                       bt.status AS credit_status,
                       ba_orig.apelido AS conta_orig_apelido, ba_orig.banco_nome AS banco_orig,
                       ba_dest.apelido AS conta_dest_apelido, ba_dest.banco_nome AS banco_dest
                FROM bank_transactions bt
                LEFT  JOIN bank_transactions bt_orig
                       ON bt_orig.id = CAST(SUBSTRING(bt.hash_dedup, 10) AS UNSIGNED)
                INNER JOIN bank_accounts ba_dest ON ba_dest.id = bt.account_id
                LEFT  JOIN bank_accounts ba_orig ON ba_orig.id = bt_orig.account_id
                WHERE {where_sql}
                ORDER BY bt.data_transacao DESC
                LIMIT 500""",
            params,
        )
        lista = cursor.fetchall()

        # Totais
        cursor.execute(
            f"""SELECT SUM(bt.valor) AS total_valor, COUNT(*) AS total_qtd
                FROM bank_transactions bt
                WHERE {where_sql}""",
            params,
        )
        totais = cursor.fetchone() or {}

        # DEBITs "órfãos": só DEBITs com tipo_conciliacao='transferencia' explícito
        # (coluna adicionada pela migration 20260224_add_tipo_conciliacao.sql).
        # Sem fallback — antes da migration, orfaos fica [] para não mostrar despesas.
        migration_aplicada = False
        try:
            cursor.execute(
                """SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao, bt.cnpj_cpf,
                          ba.apelido AS conta_apelido, ba.banco_nome,
                          'novo' AS origem_orfao
                   FROM bank_transactions bt
                   INNER JOIN bank_accounts ba ON ba.id = bt.account_id
                   WHERE bt.tipo = 'DEBIT'
                     AND bt.status = 'conciliado'
                     AND bt.tipo_conciliacao = 'transferencia'
                     AND NOT EXISTS (
                         SELECT 1 FROM bank_transactions cr
                         WHERE cr.hash_dedup = CONCAT('TRANSFER_', bt.id)
                           AND cr.tipo = 'CREDIT'
                     )
                   ORDER BY bt.data_transacao DESC
                   LIMIT 200"""
            )
            orfaos = cursor.fetchall()
            migration_aplicada = True  # query com tipo_conciliacao funcionou
        except Exception:
            orfaos = []

        # Contas para o filtro (sem cliente_id)
        cursor.execute(
            """SELECT ba.id, ba.apelido, ba.banco_nome
               FROM bank_accounts ba
               WHERE ba.ativo = 1
               ORDER BY ba.apelido"""
        )
        contas = cursor.fetchall()

        # Candidatos: DEBITs conciliados manualmente cuja descrição contém "Transf"
        # Inclui também aqueles com tipo_conciliacao='transferencia' sem CREDIT criado
        try:
            cursor.execute(
                """SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao, bt.cnpj_cpf,
                          ba.apelido AS conta_apelido, ba.banco_nome,
                          bt.tipo_conciliacao, bt.conciliado_por
                   FROM bank_transactions bt
                   INNER JOIN bank_accounts ba ON ba.id = bt.account_id
                   WHERE bt.tipo = 'DEBIT'
                     AND bt.status = 'conciliado'
                     AND (
                       bt.tipo_conciliacao = 'transferencia'
                       OR (
                         (bt.tipo_conciliacao IS NULL OR bt.tipo_conciliacao = '')
                         AND bt.conciliado_por NOT IN ('auto', 'auto-regra')
                         AND bt.descricao LIKE '%Transf%'
                       )
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM bank_transactions cr
                         WHERE cr.hash_dedup = CONCAT('TRANSFER_', bt.id)
                     )
                   ORDER BY bt.data_transacao DESC
                   LIMIT 200"""
            )
            candidatos = cursor.fetchall()
        except Exception:
            try:
                cursor.execute(
                    """SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao, bt.cnpj_cpf,
                              ba.apelido AS conta_apelido, ba.banco_nome,
                              NULL AS tipo_conciliacao, bt.conciliado_por
                       FROM bank_transactions bt
                       INNER JOIN bank_accounts ba ON ba.id = bt.account_id
                       WHERE bt.tipo = 'DEBIT'
                         AND bt.status = 'conciliado'
                         AND bt.conciliado_por NOT IN ('auto', 'auto-regra')
                         AND bt.descricao LIKE '%Transf%'
                       ORDER BY bt.data_transacao DESC
                       LIMIT 200"""
                )
                candidatos = cursor.fetchall()
            except Exception:
                candidatos = []

    except Exception as e:
        current_app.logger.exception("Erro em /financeiro/transferencias/")
        erro_db = str(e)
        migration_aplicada = False
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'financeiro/transferencias.html',
        transferencias=lista,
        total_valor=totais.get('total_valor') or 0,
        total_qtd=totais.get('total_qtd') or 0,
        orfaos=orfaos,
        candidatos=candidatos,
        contas=contas,
        erro_db=erro_db,
        migration_aplicada=migration_aplicada,
        f_data_ini=f_data_ini,
        f_data_fim=f_data_fim,
        f_conta=f_conta,
    )
