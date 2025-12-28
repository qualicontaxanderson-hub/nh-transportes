from flask import Blueprint, request, current_app, jsonify, redirect
from utils.db import get_db_connection
from utils.boletos import fetch_boleto_pdf_stream, BOLETOS_DIR
import os
import json

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='')

def _try_extract_charge_id(payload):
    """
    Tenta extrair charge_id/id em vários formatos que o provedor pode enviar.
    Suporta payloads com:
      - { "data": { "id": ... } }
      - { "data": { "charge_id": ... } }
      - { "charge": { ... } }
      - { "notification": { "data": {...} } }
      - { "notification": { "charge": {...} } }
      - { "notification": { "resource": {...} } }
      - { "notification": {...} } onde notification pode ser lista/dict/str contendo json
      - fallback: procurar por keys com nome parecido em todo dict (recursivamente limitado)
    """
    try:
        if not payload:
            return None

        # normalize simple types
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None

        # helper to check candidate dict for id-like keys
        def check_dict(d):
            if not isinstance(d, dict):
                return None
            for k in ('charge_id', 'id', 'chargeId', 'resource_id', 'resourceId'):
                if k in d and d[k]:
                    return d[k]
            # also check nested 'data' or 'attributes'
            for nk in ('data', 'attributes', 'charge', 'resource', 'body'):
                v = d.get(nk)
                if isinstance(v, (dict, list)):
                    r = _try_extract_charge_id(v)
                    if r:
                        return r
            return None

        # if payload is a list, iterate
        if isinstance(payload, list):
            for item in payload:
                r = _try_extract_charge_id(item)
                if r:
                    return r
            return None

        # common top-level keys
        for top in ('notification', 'data', 'charge', 'resource', 'body', 'payload'):
            if top in payload:
                candidate = payload.get(top)
                r = check_dict(candidate) if isinstance(candidate, dict) else _try_extract_charge_id(candidate)
                if r:
                    return r

        # fallback: check top-level directly
        r = check_dict(payload)
        if r:
            return r

        # last resort: scan stringified values (some providers embed JSON string)
        for v in payload.values() if isinstance(payload, dict) else []:
            if isinstance(v, str) and ('{' in v):
                try:
                    parsed = json.loads(v)
                    r = _try_extract_charge_id(parsed)
                    if r:
                        return r
                except Exception:
                    continue
    except Exception:
        current_app.logger.exception("Erro extraindo charge_id do payload")
    return None


@webhooks_bp.route('/webhooks/efi', methods=['POST'])
def webhooks_efi():
    """
    Recebe notificações (webhook) do provedor Efipay (EFI).
    Tenta extrair charge_id e atualizar cobrancas (link_boleto, pdf_boleto, status, data_pagamento).
    Responde 200 sempre que possível (para evitar retries do provedor).
    """
    try:
        # obter payload flexível
        payload = request.get_json(silent=True)
        if payload is None:
            # tentar form data
            if request.form:
                payload = {k: request.form.get(k) for k in request.form.keys()}
            else:
                raw = request.data.decode('utf-8', errors='ignore').strip()
                if raw:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        payload = {"raw_body": raw}
                else:
                    payload = {}

        current_app.logger.info("[webhook/efi] recebido payload keys=%s", list(payload.keys()) if isinstance(payload, dict) else type(payload))

        # detectar provável "data" a partir de wrapper 'notification' ou similar
        # mas a função _try_extract_charge_id já tenta múltiplas estratégias
        charge_id = _try_extract_charge_id(payload)

        # extrair pdf/link/status/paid_at com heurística
        def _extract_fields(p):
            pdf_url = None
            status = None
            paid_at = None
            custom_id = None
            try:
                # navegar para um 'data' caso exista
                if isinstance(p, dict):
                    data = p.get('data') or p.get('charge') or p.get('resource') or p.get('attributes') or p
                else:
                    data = p
                if isinstance(data, dict):
                    # pdf/url candidates
                    pdf_obj = data.get('pdf') or {}
                    if isinstance(pdf_obj, dict):
                        pdf_url = pdf_obj.get('charge') or pdf_obj.get('boleto') or pdf_obj.get('link')
                    pdf_url = pdf_url or data.get('link') or data.get('billet_link') or (data.get('payment') or {}).get('banking_billet', {}).get('link')
                    status = data.get('status') or data.get('payment_status') or data.get('state')
                    paid_at = data.get('paid_at') or data.get('paidAt') or data.get('paid')
                    custom_id = data.get('custom_id') or data.get('metadata', {}).get('custom_id') if data.get('metadata') else data.get('custom_id')
                # if no pdf_url yet, try top-level
                if not pdf_url and isinstance(p, dict):
                    pdf_url = p.get('pdf') or p.get('link')
            except Exception:
                current_app.logger.debug("[webhook/efi] falha extraindo fields")
            return pdf_url, status, paid_at, custom_id

        pdf_url, status, paid_at, custom_id = _extract_fields(payload if charge_id is None else payload)

        if not charge_id:
            current_app.logger.warning("[webhook/efi] charge_id não encontrado no webhook payload")
            # ainda assim podemos logar e responder 200
            return jsonify({"ok": True, "note": "no_charge_id"}), 200

        # atualizar DB
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            saved_path = None

            # se vier pdf_url, tentar baixar e salvar localmente
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
                except Exception:
                    current_app.logger.exception("[webhook/efi] erro tentando baixar pdf_url para charge %s", charge_id)

            # montar UPDATE dinâmico
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
                # gravar status pago + data_pagamento (apenas data)
                updates.append("status = %s")
                params.append("pago")
                try:
                    params.append(str(paid_at)[:10])
                    updates.append("data_pagamento = %s")
                except Exception:
                    pass

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

        return jsonify({"ok": True}), 200

    except Exception:
        current_app.logger.exception("[webhook/efi] exceção gerando resposta")
        # responder 200 para o provedor (evita retries agressivos) mas indicar falha internamente
        return jsonify({"ok": False}), 200
