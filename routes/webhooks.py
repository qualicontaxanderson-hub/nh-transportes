from flask import Blueprint, request, current_app, jsonify
from utils.db import get_db_connection
from utils.boletos import fetch_boleto_pdf_stream, BOLETOS_DIR
import os
import json

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='')

@webhooks_bp.route('/webhooks/efi', methods=['POST'])
def webhooks_efi():
    """
    Recebe notificações (webhook) do provedor Efí (EFI).
    Atualiza cobrancas com link_boleto/pdf_boleto/status quando possível.
    Responde 200 ao provedor para evitar retrys excessivos.
    """
    try:
        # tentar JSON primeiro (silencioso)
        j = request.get_json(silent=True)
        if not j:
            # tentar interpretar body como form-encoded ou texto (alguns providers usam outro content-type)
            try:
                if request.form:
                    # converte ImmutableMultiDict para dict
                    j = {k: request.form.get(k) for k in request.form.keys()}
                else:
                    data_text = request.data.decode('utf-8', errors='ignore').strip()
                    if data_text:
                        # tentar json parse
                        try:
                            j = json.loads(data_text)
                        except Exception:
                            j = {"raw_body": data_text}
                    else:
                        j = {}
            except Exception:
                j = {}

        current_app.logger.info("[webhook/efi] recebido payload keys=%s", list(j.keys()) if isinstance(j, dict) else type(j))
        data = j.get('data') if isinstance(j, dict) and 'data' in j else j if isinstance(j, dict) else {}

        # extrair charge_id
        charge_id = None
        for k in ('id', 'charge_id', 'chargeId'):
            v = data.get(k) if isinstance(data, dict) else None
            if v:
                charge_id = v
                break
        # extrair pdf/link/status
        pdf_url = None
        try:
            pdf_obj = data.get('pdf') or {}
            pdf_url = pdf_obj.get('charge') or pdf_obj.get('boleto') or data.get('link') or data.get('billet_link')
            if not pdf_url:
                pb = (data.get('payment') or {}).get('banking_billet') or {}
                pdf_url = pb.get('link') or pb.get('pdf') or pb.get('boleto')
        except Exception:
            pdf_url = None
        status = data.get('status') if isinstance(data, dict) else None
        paid_at = data.get('paid_at') or data.get('paidAt') or data.get('paid') if isinstance(data, dict) else None

        if charge_id:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                saved_path = None
                if pdf_url and isinstance(pdf_url, str) and (pdf_url.startswith('http://') or pdf_url.startswith('https://')):
                    try:
                        credentials = {
                            "client_id": current_app.config.get("EFI_CLIENT_ID") or os.getenv("EFI_CLIENT_ID"),
                            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or os.getenv("EFI_CLIENT_SECRET"),
                            "sandbox": current_app.config.get("EFI_SANDBOX", True),
                        }
                        resp = fetch_boleto_pdf_stream(credentials, pdf_url)
                        if resp is not None and getattr(resp, "status_code", None) == 200:
                            try:
                                os.makedirs(BOLETOS_DIR, exist_ok=True)
                                fname = f"boleto_{charge_id}.pdf"
                                dest = os.path.join(BOLETOS_DIR, fname)
                                with open(dest, "wb") as fh:
                                    for chunk in resp.iter_content(8192):
                                        if chunk:
                                            fh.write(chunk)
                                saved_path = dest
                                current_app.logger.info("[webhook/efi] PDF salvo em %s para charge %s", dest, charge_id)
                            except Exception:
                                current_app.logger.exception("[webhook/efi] falha ao salvar pdf para charge %s", charge_id)
                                saved_path = None
                    except Exception:
                        current_app.logger.exception("[webhook/efi] erro tentando baixar pdf_url para charge %s", charge_id)

                updates = []
                params = []
                if pdf_url:
                    updates.append("link_boleto = %s")
                    params.append(pdf_url)
                if saved_path:
                    updates.append("pdf_boleto = %s")
                    params.append(saved_path)
                if status:
                    updates.append("status = %s")
                    params.append(status)
                if paid_at:
                    updates.append("status = %s")
                    params.append('pago')
                    updates.append("data_pagamento = %s")
                    params.append(str(paid_at)[:10])

                if updates:
                    params.append(int(charge_id))
                    sql = "UPDATE cobrancas SET " + ", ".join(updates) + " WHERE charge_id = %s"
                    try:
                        cur.execute(sql, tuple(params))
                        conn.commit()
                        current_app.logger.info("[webhook/efi] atualizou cobrancas charge_id=%s cols=%s", charge_id, updates)
                    except Exception:
                        current_app.logger.exception("[webhook/efi] falha update cobrancas charge_id=%s", charge_id)
                cur.close()
                conn.close()
            except Exception:
                current_app.logger.exception("[webhook/efi] erro DB ao processar charge_id=%s", charge_id)
        else:
            current_app.logger.warning("[webhook/efi] charge_id não encontrado no webhook payload")

        # sempre responder 200 (provavelmente o provedor espera 200; evita retries excessivos)
        return jsonify({"ok": True}), 200

    except Exception:
        current_app.logger.exception("[webhook/efi] exceção gerando resposta")
        return jsonify({"ok": False}), 200
