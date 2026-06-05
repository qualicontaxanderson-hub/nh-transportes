from flask import Blueprint, request, current_app, jsonify
from utils.db import get_db_connection
from utils.boletos import fetch_boleto_pdf_stream, BOLETOS_DIR, _ensure_credentials_from_env, _get_bearer_token
import os
import json
import hmac
import hashlib
import requests
from datetime import datetime

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='')


def _to_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _fetch_notification_data(notification_token):
    """
    Busca os dados reais da notificação via GET /v1/notification/{token}.
    A EFI Pay v1 envia apenas o token no POST; os dados estão neste endpoint.
    Retorna o dict de dados da notificação ou None em caso de falha.
    """
    try:
        credentials = {
            "client_id": current_app.config.get("EFI_CLIENT_ID") or os.getenv("EFI_CLIENT_ID"),
            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or os.getenv("EFI_CLIENT_SECRET"),
            "sandbox": _to_bool(current_app.config.get("EFI_SANDBOX", os.getenv("EFI_SANDBOX", "true")), True),
            "certificate": current_app.config.get("EFI_CERT_PATH") or os.getenv("EFI_CERT_PATH"),
        }
        credentials = _ensure_credentials_from_env(credentials)
        sandbox = credentials.get("sandbox", True)
        base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
        url = f"{base}/v1/notification/{notification_token}"

        token = _get_bearer_token(credentials)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = requests.get(url, headers=headers, timeout=15)
        current_app.logger.info("[webhook/efi] GET notification/%s -> status=%s", notification_token[:8], resp.status_code)
        if resp.status_code == 200:
            return resp.json()
        current_app.logger.warning("[webhook/efi] notification lookup falhou: status=%s body=%s", resp.status_code, resp.text[:500])
    except Exception:
        current_app.logger.exception("[webhook/efi] erro buscando notification token")
    return None


def _try_extract_charge_id(payload):
    """
    Tenta extrair charge_id/id em vários formatos que o provedor pode enviar.
    Retorna None se não encontrar.
    """
    try:
        if not payload:
            return None

        # normalizar string JSON
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode('utf-8')
            except Exception:
                payload = None

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None

        # percorre listas
        if isinstance(payload, list):
            for item in payload:
                r = _try_extract_charge_id(item)
                if r:
                    return r
            return None

        # se for dict, procurar chaves comuns e recursivamente em 'data'/'notification' etc.
        if isinstance(payload, dict):
            # chaves simples
            for k in ('charge_id', 'id', 'chargeId', 'resource_id', 'resourceId'):
                if k in payload and payload.get(k):
                    return payload.get(k)

            # verificar metadata / attributes
            for nk in ('data', 'attributes', 'charge', 'resource', 'notification', 'body', 'payload'):
                if nk in payload:
                    candidate = payload.get(nk)
                    r = _try_extract_charge_id(candidate)
                    if r:
                        return r

            # tentativa por varredura de valores string contendo JSON
            for v in payload.values():
                if isinstance(v, str) and ('{' in v or '[' in v):
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


def _extract_fields(p):
    """
    Heurística para extrair pdf_url, status, paid_at, custom_id de um payload.
    """
    pdf_url = None
    status = None
    paid_at = None
    custom_id = None
    try:
        data = None
        if isinstance(p, dict):
            # preferir campos de nível lógico
            data = p.get('data') or p.get('charge') or p.get('resource') or p.get('attributes') or p
        else:
            data = p

        if isinstance(data, dict):
            # possíveis locais para url/pdf
            pdf_obj = data.get('pdf') or {}
            if isinstance(pdf_obj, dict):
                pdf_url = pdf_obj.get('charge') or pdf_obj.get('boleto') or pdf_obj.get('link')
            pdf_url = pdf_url or data.get('link') or data.get('billet_link') or (data.get('payment') or {}).get('banking_billet', {}).get('link')
            status = data.get('status') or data.get('payment_status') or data.get('state')
            paid_at = data.get('paid_at') or data.get('paidAt') or data.get('paid') or data.get('paid_at_date')
            # metadata/custom_id
            md = data.get('metadata') if isinstance(data.get('metadata'), dict) else None
            custom_id = data.get('custom_id') or (md.get('custom_id') if md else None)
        # fallback nível top-level
        if not pdf_url and isinstance(p, dict):
            pdf_url = p.get('pdf') or p.get('link')
    except Exception:
        current_app.logger.debug("[webhook/efi] falha extraindo fields")
    return pdf_url, status, paid_at, custom_id


def _validate_signature(raw_body):
    """
    Se a variável de ambiente EFI_WEBHOOK_SECRET estiver definida, valida header HMAC-SHA256
    cabecalho esperado: X-EFI-SIGNATURE com hex HMAC.
    Se não houver secret configurado, retorna True (não valida).
    Usa raw_body (bytes) exatamente como recebido para calcular HMAC.
    """
    secret = current_app.config.get("EFI_WEBHOOK_SECRET") or os.getenv("EFI_WEBHOOK_SECRET")
    if not secret:
        return True
    sig_header = request.headers.get("X-EFI-SIGNATURE") or request.headers.get("X-Signature") or request.headers.get("X-Hub-Signature")
    if not sig_header:
        current_app.logger.warning("[webhook/efi] secret configurado mas assinatura ausente")
        return False
    try:
        # raw_body deve ser bytes; se não for, converte de forma previsível
        raw = raw_body if isinstance(raw_body, (bytes, bytearray)) else (raw_body.encode('utf-8') if isinstance(raw_body, str) else json.dumps(raw_body).encode('utf-8'))
        expected = hmac.new(secret.encode('utf-8'), raw, hashlib.sha256).hexdigest()
        # permitir header com 'sha256=...' ou apenas hex
        if sig_header.startswith('sha256='):
            sig_val = sig_header.split('=', 1)[1]
        else:
            sig_val = sig_header
        return hmac.compare_digest(expected, sig_val)
    except Exception:
        current_app.logger.exception("[webhook/efi] falha validando assinatura")
        return False


@webhooks_bp.route('/webhooks/efi', methods=['POST'])
def webhooks_efi():
    """
    Recebe notificações (webhook) do provedor Efipay (EFI).
    Extrai charge_id e atualiza cobrancas (link_boleto, pdf_boleto, status, data_pagamento, pago_via_provedor).
    Responde 200 para o provedor sempre que possível.
    """
    conn = None
    cur = None
    try:
        raw_body = request.get_data()  # bytes
        # validar assinatura se configurada
        if not _validate_signature(raw_body):
            current_app.logger.warning("[webhook/efi] assinatura inválida")
            return jsonify({"ok": False, "reason": "invalid_signature"}), 400

        # tentar obter JSON de forma tolerante
        payload = None
        try:
            payload = request.get_json(silent=True)
        except Exception:
            payload = None

        if payload is None:
            # tentar form data
            if request.form:
                payload = {k: request.form.get(k) for k in request.form.keys()}
            else:
                raw = raw_body.decode('utf-8', errors='ignore').strip()
                if raw:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        payload = {"raw_body": raw}
                else:
                    payload = {}

        current_app.logger.info("[webhook/efi] recebido payload type=%s keys=%s", type(payload).__name__, list(payload.keys()) if isinstance(payload, dict) else [])

        # EFI Pay v1: o POST só traz notification_token; buscar dados reais via GET /v1/notification/{token}
        if isinstance(payload, dict):
            notif_token = payload.get("notification_token") or payload.get("token")
            if notif_token and isinstance(notif_token, str) and len(notif_token) > 8:
                current_app.logger.info("[webhook/efi] notification_token detectado, buscando dados reais")
                notif_data = _fetch_notification_data(notif_token)
                if notif_data:
                    current_app.logger.info("[webhook/efi] notification data obtida: type=%s", type(notif_data).__name__)
                    # Normalizar: EFI retorna {"code":200,"data":[{...charge...}]} ou {"data":{...charge...}}
                    merged = notif_data if isinstance(notif_data, dict) else {}
                    inner = merged.get("data")
                    if isinstance(inner, list) and inner:
                        # lista de eventos — extrair o primeiro que tenha charge ou id
                        for event in inner:
                            if isinstance(event, dict):
                                charge = event.get("charge") or event
                                if isinstance(charge, dict) and (charge.get("id") or charge.get("charge_id")):
                                    merged = {**payload, **charge}
                                    break
                        else:
                            merged = {**payload, **merged}
                    elif isinstance(inner, dict):
                        charge = inner.get("charge") or inner
                        merged = {**payload, **charge}
                    else:
                        merged = {**payload, **merged}
                    payload = merged
                    current_app.logger.info("[webhook/efi] payload normalizado keys=%s", list(payload.keys()) if isinstance(payload, dict) else [])

        # extrair charge_id
        charge_id = _try_extract_charge_id(payload)

        if not charge_id:
            current_app.logger.warning("[webhook/efi] charge_id não encontrado no webhook payload")
            return jsonify({"ok": True, "note": "no_charge_id"}), 200

        # extrair campos do payload
        pdf_url, status, paid_at, custom_id = _extract_fields(payload)

        # interpretar pagamento com heurística
        is_paid = False
        if paid_at:
            is_paid = True
        else:
            try:
                if status and isinstance(status, str) and status.strip().lower() in ('pago', 'paid', 'confirmed', 'paid_and_confirmed', 'confirmed_paid', 'paid_at', 'settled'):
                    is_paid = True
            except Exception:
                is_paid = False

        # normalizar paid_at para YYYY-MM-DD se possível
        paid_date = None
        if paid_at:
            try:
                s = str(paid_at)
                if s.endswith('Z'):
                    s = s.replace('Z', '+00:00')
                # tentativa mais direta
                dt = datetime.fromisoformat(s)
                paid_date = dt.date().isoformat()
            except Exception:
                # fallback simples: pegar os primeiros 10 chars
                try:
                    paid_date = str(paid_at)[:10]
                except Exception:
                    paid_date = None

        # atualizar DB
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            saved_path = None
            # baixar pdf se vier link público
            if pdf_url and isinstance(pdf_url, str) and (pdf_url.startswith('http://') or pdf_url.startswith('https://')):
                try:
                    credentials = {
                        "client_id": current_app.config.get("EFI_CLIENT_ID") or os.getenv("EFI_CLIENT_ID"),
                        "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or os.getenv("EFI_CLIENT_SECRET"),
                        "sandbox": _to_bool(current_app.config.get("EFI_SANDBOX", os.getenv("EFI_SANDBOX", "true")), True),
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

            # montar UPDATE dinâmico (ordem dos params importa)
            updates = []
            params = []

            if pdf_url:
                updates.append("link_boleto = %s")
                params.append(pdf_url)
            if saved_path:
                updates.append("pdf_boleto = %s")
                params.append(saved_path)

            if is_paid:
                updates.append("status = %s")
                params.append("pago")
                updates.append("pago_via_provedor = %s")
                params.append(1)
                if paid_date:
                    updates.append("data_pagamento = %s")
                    params.append(paid_date)
            else:
                if status:
                    updates.append("status = %s")
                    params.append(status)

            if updates:
                # charge_id deve ser usado como string (não converter para int)
                params.append(str(charge_id))
                sql = "UPDATE cobrancas SET " + ", ".join(updates) + " WHERE charge_id = %s"
                try:
                    cur.execute(sql, tuple(params))
                    # verificar se atualizou alguma linha
                    if getattr(cur, "rowcount", None) == 0:
                        current_app.logger.warning("[webhook/efi] UPDATE não afetou linhas para charge_id=%s", charge_id)
                    else:
                        current_app.logger.info("[webhook/efi] atualizou cobrancas charge_id=%s cols=%s", charge_id, updates)
                    conn.commit()
                except Exception:
                    current_app.logger.exception("[webhook/efi] falha update cobrancas charge_id=%s", charge_id)

        except Exception:
            current_app.logger.exception("[webhook/efi] erro DB ao processar charge_id=%s", charge_id)
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

        return jsonify({"ok": True}), 200

    except Exception:
        current_app.logger.exception("[webhook/efi] exceção gerando resposta")
        # responder 200 para o provedor mas indicar falha internamente
        return jsonify({"ok": False}), 200
