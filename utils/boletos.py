#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils/boletos.py

Funções para criar/consultar/Cancelar cobranças via Efipay e persistir
respostas de cancelamento na tabela `cobrancas`.

Atualizações importantes:
- marca frete como boleto_emitido após persistir cobranca (evita reemissão)
- usa BOLETOS_DIR configurável para salvar PDFs
- mantém compatibilidade com SDK/fallback direto
- adiciona função emitir_boleto_multiplo para agregar vários fretes em 1 cobrança
"""
import os
import json
import copy
import logging
import time
import re
from datetime import datetime, timedelta

import requests
from efipay import EfiPay
from utils.db import get_db_connection

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# controla logs de payloads completos (True/False via env var)
DEBUG_PAYLOAD = os.getenv("EFI_DEBUG_PAYLOAD", "false").lower() in ("1", "true", "yes")

# pasta gravável para salvar PDFs de boletos (configurável via env)
BOLETOS_DIR = os.getenv("BOLETOS_DIR", "/tmp/boletos")


def _sanitize_for_log(obj):
    """Cópia do objeto com campos sensíveis mascarados para logs."""
    try:
        o = copy.deepcopy(obj)
    except Exception:
        return "<unserializable>"

    def mask_string(s):
        if not isinstance(s, str):
            return s
        if len(s) <= 4:
            return "****"
        return s[:2] + "****" + s[-2:]

    def recurse(x):
        if isinstance(x, dict):
            for k in list(x.keys()):
                lk = k.lower()
                if lk in ("cpf", "cnpj", "phone_number", "telefone", "email", "client_secret", "certificate", "token"):
                    try:
                        x[k] = mask_string(x[k])
                    except Exception:
                        x[k] = "****"
                else:
                    recurse(x[k])
        elif isinstance(x, list):
            for item in x:
                recurse(item)

    try:
        recurse(o)
        return o
    except Exception:
        return "<sanitize-failed>"


def _log_send_attempt(method_name, body, extra_note=None):
    try:
        s = json.dumps(_sanitize_for_log(body), ensure_ascii=False)
    except Exception:
        s = "<unserializable>"
    logger.info("SENDING (%s) %s", method_name, extra_note or "")
    if DEBUG_PAYLOAD:
        logger.info("SENDING-PAYLOAD (%s): %s", method_name, s)
    else:
        logger.debug("SENDING-PAYLOAD (%s): %s", method_name, s)


def _log_provider_response(method_name, resp_raw):
    try:
        if hasattr(resp_raw, "status_code"):
            code = getattr(resp_raw, "status_code", None)
            text = getattr(resp_raw, "text", None)
            logger.info("PROVIDER RESPONSE (%s): status=%s, text_len=%s", method_name, code, len(text) if text else 0)
            if DEBUG_PAYLOAD:
                logger.info("PROVIDER RESPONSE (%s) TEXT: %s", method_name, (text or "")[:4000])
        elif isinstance(resp_raw, dict):
            logger.info("PROVIDER RESPONSE (%s): dict keys=%s", method_name, list(resp_raw.keys()))
            if DEBUG_PAYLOAD:
                logger.info("PROVIDER RESPONSE (%s) BODY: %s", method_name, json.dumps(_sanitize_for_log(resp_raw), ensure_ascii=False)[:4000])
        else:
            s = repr(resp_raw)
            logger.info("PROVIDER RESPONSE (%s): %s", method_name, s[:4000])
    except Exception:
        logger.exception("Erro ao logar provider response (%s)", method_name)


def _safe_get_charge_fields(response):
    if not response or not isinstance(response, dict):
        return None, None, None
    data = response.get("data") or response.get("charge") or response
    charge_id = data.get("id") or data.get("charge_id") or response.get("data", {}).get("id")
    boleto_url = None
    barcode = None
    try:
        if isinstance(data.get("payment"), dict):
            p = data.get("payment")
            boleto_url = (p.get("banking_billet") or {}).get("link") or p.get("link")
            barcode = (p.get("banking_billet") or {}).get("barcode") or p.get("barcode")
        if not boleto_url and isinstance(data.get("payments"), list) and data.get("payments"):
            p = data.get("payments")[0]
            boleto_url = (p.get("banking_billet") or {}).get("link") or p.get("link")
            barcode = (p.get("banking_billet") or {}).get("barcode") or p.get("barcode")
        if not boleto_url:
            boleto_url = (data.get("banking_billet") or {}).get("link") or response.get("link")
        if not barcode:
            barcode = (data.get("banking_billet") or {}).get("barcode")
    except Exception:
        logger.debug("Falha extraindo fields do response: %r", response)
    return charge_id, boleto_url, barcode


def _extract_charge_id(resp):
    try:
        if not isinstance(resp, dict):
            return None
        data = resp.get("data") or resp.get("charge") or resp
        if isinstance(data, dict):
            cid = data.get("id") or data.get("charge_id")
            if cid:
                return cid
        return resp.get("charge_id") or resp.get("id")
    except Exception:
        return None


def _build_body(frete, descricao_frete, data_vencimento, valor_total_centavos):
    cpf_cnpj = (frete.get("cliente_cnpj") or "").replace(".", "").replace("-", "").replace("/", "").strip()
    telefone = (frete.get("cliente_telefone") or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", "").strip()
    cep = (frete.get("cliente_cep") or "").replace("-", "").strip()
    if not cep or len(cep) != 8:
        cep = "74000000"
    nome_cliente = (frete.get("cliente_fantasia") or frete.get("cliente_nome") or "Cliente")[:80]
    items = [{"name": descricao_frete[:80], "amount": 1, "value": valor_total_centavos}]
    banking_billet = {
        "expire_at": data_vencimento.strftime("%Y-%m-%d"),
        "customer": {
            "name": nome_cliente,
            "cpf": cpf_cnpj if len(cpf_cnpj) == 11 else None,
            "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None,
            "phone_number": (telefone or "")[:11],
            "email": (frete.get("cliente_email") or "")[:100],
            "address": {
                "street": (frete.get("cliente_endereco") or "")[:80],
                "number": (frete.get("cliente_numero") or "")[:10],
                "neighborhood": (frete.get("cliente_bairro") or "")[:50],
                "zipcode": cep,
                "city": (frete.get("cliente_cidade") or "")[:50],
                "state": (frete.get("cliente_estado") or "")[:2].upper(),
            },
        },
    }
    metadata = {"custom_id": str(frete["id"]), "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi")}
    body = {"items": items, "payment": {"banking_billet": banking_billet}, "metadata": metadata}
    return body


def _build_charge_payload(frete, descricao_frete, data_vencimento, valor_total_centavos):
    items = [{"name": descricao_frete[:80], "amount": 1, "value": valor_total_centavos}]
    metadata = {"custom_id": str(frete["id"]), "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi")}
    return {"items": items, "metadata": metadata}


def _build_pay_payload(frete, descricao_frete, data_vencimento, valor_total_centavos):
    cpf_cnpj = (frete.get("cliente_cnpj") or "").replace(".", "").replace("-", "").replace("/", "").strip()
    telefone = (frete.get("cliente_telefone") or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", "").strip()
    cep = (frete.get("cliente_cep") or "").replace("-", "").strip()
    if not cep or len(cep) != 8:
        cep = "74000000"
    nome_cliente = (frete.get("cliente_fantasia") or frete.get("cliente_nome") or "Cliente")[:80]
    customer = {
        "name": nome_cliente,
        "cpf": cpf_cnpj if len(cpf_cnpj) == 11 else None,
        "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None,
        "phone_number": (telefone or "")[:11],
        "email": (frete.get("cliente_email") or "")[:100],
        "address": {
            "street": (frete.get("cliente_endereco") or "")[:80],
            "number": (frete.get("cliente_numero") or "")[:10],
            "neighborhood": (frete.get("cliente_bairro") or "")[:50],
            "zipcode": cep,
            "city": (frete.get("cliente_cidade") or "")[:50],
            "state": (frete.get("cliente_estado") or "")[:2].upper(),
        },
        "juridical_person": {"corporate_name": nome_cliente, "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None},
    }
    payment = {"payment": {"banking_billet": {"expire_at": data_vencimento.strftime("%Y-%m-%d"), "customer": customer}}}
    return payment


def _try_sdk_methods(efi, body):
    tried = []
    response = None
    candidates = ["create_charge", "create_one_step_billet", "create_one_step_billet_charge", "create_billet", "create", "charges", "charge", "createCharge"]
    for attr in dir(efi):
        if any(k in attr.lower() for k in ("charge", "billet", "boleto", "create")):
            if attr not in candidates:
                candidates.append(attr)
    for method in candidates:
        try:
            fn = getattr(efi, method, None)
            if callable(fn):
                tried.append(method)
                _log_send_attempt(method, body, extra_note="high-level SDK method")
                try:
                    resp = fn(body=body)
                except TypeError:
                    try:
                        resp = fn(body)
                    except TypeError:
                        resp = fn(body, None)
                _log_provider_response(method, resp)
                return True, resp, method
        except Exception as ex:
            logger.debug("Tentativa SDK método %s falhou: %s", method, ex)
            response = ex
            continue
    for attr in dir(efi):
        try:
            sub = getattr(efi, attr)
            if not hasattr(sub, "__dict__") and not hasattr(sub, "__class__"):
                continue
            for subm in dir(sub):
                if any(k in subm.lower() for k in ("create", "charge", "billet")):
                    try:
                        fn = getattr(sub, subm)
                        if callable(fn):
                            tried.append(f"{attr}.{subm}")
                            _log_send_attempt(f"{attr}.{subm}", body, extra_note="nested SDK method")
                            try:
                                resp = fn(body=body)
                            except TypeError:
                                resp = fn(body)
                            _log_provider_response(f"{attr}.{subm}", resp)
                            return True, resp, f"{attr}.{subm}"
                    except Exception as ex:
                        logger.debug("Tentativa SDK método %s.%s falhou: %s", attr, subm, ex)
                        response = ex
                        continue
        except Exception:
            continue
    return False, response, tried


def _sanitize_payment_payload(payload):
    """
    Remove propriedades que não fazem parte do schema aceito pela API de cobranças.
    Uso: antes de enviar um corpo para /charge/:id/pay ou /charge.
    - remove payment.banking_billet.customer.cnpj (duplicado)
    - remove payment.banking_billet.customer.cpf se for None (ou conforme necessidade)
    """
    try:
        if not isinstance(payload, dict):
            return payload
        payment = payload.get("payment")
        if not isinstance(payment, dict):
            return payload
        bb = payment.get("banking_billet")
        if not isinstance(bb, dict):
            return payload
        customer = bb.get("customer")
        if not isinstance(customer, dict):
            return payload

        # remover cnpj duplicado dentro de customer (deixa apenas juridical_person.cnpj)
        customer.pop("cnpj", None)

        # remover cpf se explicitamente None (muitos schemas preferem ausência em vez de null)
        if "cpf" in customer and (customer["cpf"] is None):
            customer.pop("cpf", None)

    except Exception:
        # se a sanitização falhar por qualquer razão, devolve o payload original
        return payload

    return payload


# Token cache (módulo) agora indexado por (client_id, sandbox)
_TOKEN_CACHE = {}  # keys: (client_id, bool(sandbox)) -> {"access_token": str, "expire_at": float}


def _ensure_credentials_from_env(credentials):
    """Preenche credenciais faltantes a partir das ENV para maior robustez."""
    if credentials is None:
        credentials = {}
    if not credentials.get("client_id"):
        credentials["client_id"] = os.getenv("EFI_CLIENT_ID")
    if not credentials.get("client_secret"):
        credentials["client_secret"] = os.getenv("EFI_CLIENT_SECRET")
    if "sandbox" not in credentials or credentials.get("sandbox") is None:
        credentials["sandbox"] = os.getenv("EFI_SANDBOX", "true").lower() == "true"
    return credentials


def _get_bearer_token(credentials):
    """
    Obtém e faz cache de um access_token via client_credentials no endpoint /authorize.
    Cache é indexado por (client_id, sandbox) para evitar usar token de prod contra sandbox (e vice-versa).
    """
    try:
        credentials = _ensure_credentials_from_env(credentials)
        now = time.time()
        client_id = credentials.get("client_id")
        sandbox = bool(credentials.get("sandbox", True))
        cache_key = (client_id, sandbox)

        entry = _TOKEN_CACHE.get(cache_key)
        if entry and entry.get("access_token") and entry.get("expire_at", 0) > now + 5:
            try:
                logger.info("_get_bearer_token: token em cache (client=%s sandbox=%s) expira em %.0fs",
                            client_id or "<no-id>", sandbox, entry.get("expire_at", 0) - now)
            except Exception:
                logger.debug("_get_bearer_token: token em cache")
            return entry.get("access_token")

        base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
        url = f"{base}/v1/authorize"

        client_secret = credentials.get("client_secret")
        if not client_id or not client_secret:
            logger.warning("_get_bearer_token: credentials incompletas")
            return None

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        auth = (client_id, client_secret)
        body = {"grant_type": "client_credentials"}

        resp = requests.post(url, headers=headers, auth=auth, json=body, timeout=15)
        if resp is None:
            return None
        if resp.status_code != 200:
            logger.warning("_get_bearer_token: status=%s text=%s (client=%s sandbox=%s)",
                           resp.status_code, (resp.text or "")[:1000], client_id or "<no-id>", sandbox)
            return None

        j = resp.json()
        token = j.get("access_token")
        expires_in = int(j.get("expires_in", 0) or 0)

        # tentar extrair key_id do payload (somente para log, sem validar assinatura)
        try:
            parts = token.split(".")
            if len(parts) > 1:
                import base64 as _base64, json as _json
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload_json = _json.loads(_base64.urlsafe_b64decode(payload_b64))
                key_id = payload_json.get("data", {}).get("key_id")
            else:
                key_id = None
        except Exception:
            key_id = None

        logger.info("_get_bearer_token: obtained token (len=%s) key_id=%s sandbox=%s client=%s",
                    len(token) if token else 0, key_id, sandbox, client_id or "<no-id>")

        # salvar no cache por (client_id, sandbox)
        _TOKEN_CACHE[cache_key] = {
            "access_token": token,
            "expire_at": now + max(0, expires_in - 10),
        }
        return token
    except Exception:
        logger.exception("Erro obtendo bearer token")
        return None


def _direct_post(credentials, path, body):
    """
    Post direto para API cobrancas usando Bearer token (obtido via client_credentials).
    Retorna o JSON parseado do provedor ou um dict com http_status/text quando não-JSON.
    """
    try:
        credentials = _ensure_credentials_from_env(credentials)
    except Exception:
        pass

    # sanitiza o body antes de enviar para evitar 400 por propriedades inesperadas
    try:
        body = _sanitize_payment_payload(body)
    except Exception:
        pass

    sandbox = credentials.get("sandbox", True)
    base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
    url = f"{base}/v1/{path.lstrip('/')}"

    # obter token (cached)
    token = _get_bearer_token(credentials)
    if not token:
        logger.warning("_direct_post: não foi possível obter token Bearer (401)")
        return {"http_status": 401, "content_type": "", "text": "Unauthorized"}

    headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
    except Exception as e:
        logger.exception("Erro HTTP no POST %s: %s", url, e)
        return {"http_error": str(e)}

    # tenta parsear JSON — se falhar, retorna texto bruto para diagnóstico
    content_type = resp.headers.get("Content-Type", "")
    text = resp.text or ""
    status = resp.status_code
    try:
        j = resp.json()
        return j
    except Exception:
        logger.warning("Resposta não-JSON do provedor (status=%s, content-type=%s). Texto (primeiros 2000 chars): %s", status, content_type, (text or "")[:2000])
        return {"http_status": status, "content_type": content_type, "text": text}


def _direct_create_charge(credentials, body):
    return _direct_post(credentials, "charge", body)


def _direct_pay_charge(credentials, charge_id, body):
    return _direct_post(credentials, f"charge/{charge_id}/pay", body)


def fetch_charge(credentials, charge_id):
    """
    Busca a charge no provedor (GET /v1/charge/{id}).
    Retorna o JSON parseado ou None/obj erro.
    """
    try:
        credentials = _ensure_credentials_from_env(credentials)
        token = _get_bearer_token(credentials) if "client_id" in credentials and "client_secret" in credentials else None

        sandbox = credentials.get("sandbox", True)
        base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
        url = f"{base}/v1/charge/{charge_id}"

        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        logger.info("fetch_charge: GET %s", url)
        resp = requests.get(url, headers=headers, timeout=15)
        logger.info("fetch_charge: status=%s len=%s", getattr(resp, "status_code", None), len(getattr(resp, "text", "") or ""))
        try:
            return resp.json()
        except Exception:
            return {"http_status": resp.status_code, "text": resp.text}
    except Exception:
        logger.exception("Erro em fetch_charge")
        return None


def fetch_boleto_pdf_stream(credentials, pdf_url):
    """
    Realiza GET para a URL do PDF do provedor e retorna o objeto requests.Response (stream=True).
    Estratégia:
      - se tiver token (via _get_bearer_token) tenta primeiro com Authorization
      - se a resposta for 401/403 ou o content-type não indicar PDF, tenta novamente sem Authorization
      - devolve o objeto requests.Response final (ou None se erro)
    """
    try:
        credentials = _ensure_credentials_from_env(credentials)
        token = _get_bearer_token(credentials) if "client_id" in credentials and "client_secret" in credentials else None

        # headers base
        headers = {"Accept": "application/pdf, application/octet-stream, */*"}
        tried_with_auth = False

        # tentativa 1: com Authorization (se tivermos token)
        if token:
            tried_with_auth = True
            headers_auth = dict(headers)
            headers_auth["Authorization"] = f"Bearer {token}"
            logger.info("fetch_boleto_pdf_stream: GET %s (try with auth=%s)", pdf_url, True)
            try:
                resp = requests.get(pdf_url, headers=headers_auth, stream=True, timeout=30, allow_redirects=True)
                logger.info("fetch_boleto_pdf_stream: status=%s (with auth)", getattr(resp, "status_code", None))
            except Exception:
                logger.exception("Erro HTTP em fetch_boleto_pdf_stream (with auth)")
                resp = None

            # se a resposta for OK e content-type parecer PDF, devolve
            if resp is not None and getattr(resp, "status_code", None) in (200, 204):
                ct = (resp.headers.get("Content-Type") or "").lower()
                if "pdf" in ct or "application/octet-stream" in ct or resp.headers.get("Content-Length"):
                    return resp
                # caso o provedor retorne 200 mas não seja PDF, vamos tentar sem auth abaixo

            # se 401/403, vamos tentar sem auth
            if resp is not None and getattr(resp, "status_code", None) in (401, 403):
                logger.info("fetch_boleto_pdf_stream: auth attempt returned %s, will retry without auth", resp.status_code)

        # tentativa 2: sem Authorization
        logger.info("fetch_boleto_pdf_stream: GET %s (try with auth=%s)", pdf_url, False)
        try:
            resp2 = requests.get(pdf_url, headers=headers, stream=True, timeout=30, allow_redirects=True)
            logger.info("fetch_boleto_pdf_stream: status=%s (without auth)", getattr(resp2, "status_code", None))
            return resp2
        except Exception:
            logger.exception("Erro HTTP em fetch_boleto_pdf_stream (without auth)")
            return None
    except Exception:
        logger.exception("Erro em fetch_boleto_pdf_stream")
        return None


def update_billet_expire(credentials, charge_id, new_date):
    """
    Atualiza expire_at do boleto no provedor: PUT para /v1/charge/{id}/billet
    Retorna (True, resp_json) em sucesso, (False, erro) em falha.
    """
    try:
        credentials = _ensure_credentials_from_env(credentials)
        token = _get_bearer_token(credentials) if "client_id" in credentials and "client_secret" in credentials else None

        sandbox = credentials.get("sandbox", True)
        base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
        url = f"{base}/v1/charge/{charge_id}/billet"

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        logger.info("update_billet_expire: PUT %s with new_date=%s (auth=%s)", url, new_date, bool(token))
        if token:
            headers["Authorization"] = f"Bearer {token}"
            resp = requests.put(url, headers=headers, json={"banking_billet": {"expire_at": new_date}}, timeout=15)
        else:
            # se não tiver token, tente basic auth com client creds (fallback)
            client_id = credentials.get("client_id")
            client_secret = credentials.get("client_secret")
            if not client_id or not client_secret:
                return False, "Credenciais ausentes"
            resp = requests.put(url, headers=headers, json={"banking_billet": {"expire_at": new_date}},
                                auth=(client_id, client_secret), timeout=15)

        logger.info("update_billet_expire: status=%s text_len=%s", getattr(resp, "status_code", None), len(getattr(resp, "text", "") or ""))
        try:
            j = resp.json()
            # considerar códigos 200/204 como sucesso
            if resp.status_code in (200, 204):
                return True, j
            return (True, j) if resp.status_code == 200 else (False, j)
        except Exception:
            return (resp.status_code == 200 or resp.status_code == 204), {"http_status": resp.status_code, "text": resp.text}
    except Exception:
        logger.exception("Erro em update_billet_expire")
        return False, "Exception ao atualizar vencimento"


def _persist_cancel_to_db(charge_id, provider_resp):
    """
    Tenta persistir no banco o resultado do cancelamento para auditoria.
    Não falha a execução principal se houver erro no DB; apenas loga.
    """
    try:
        if not charge_id:
            return
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # armazena JSON se possível; usamos string JSON para compatibilidade
            resp_text = provider_resp if isinstance(provider_resp, str) else json.dumps(provider_resp, ensure_ascii=False)
            cur.execute(
                "UPDATE cobrancas SET status=%s, provider_cancel_response=%s, data_cancelamento=NOW() WHERE charge_id=%s",
                ("cancelado", resp_text, int(charge_id)),
            )
            conn.commit()
            cur.close()
        except Exception:
            logger.exception("_persist_cancel_to_db: falha ao atualizar cobrancas")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    logger.exception("rollback falhou em _persist_cancel_to_db")
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                logger.exception("Erro fechando conexão em _persist_cancel_to_db")
    except Exception:
        logger.exception("Erro genérico em _persist_cancel_to_db")


def cancel_charge(credentials, charge_id):
    """
    Tenta cancelar uma charge no provedor.
    Retorna (True, resp_json_or_text) se conseguiu, (False, resp_or_text) se não.
    Estratégia:
      - tenta via SDK (se disponível)
      - tenta PUT /v1/charge/{id}/cancel (conforme documentação Efí)
      - se retornar 404/405 tenta DELETE /v1/charge/{id}
      - se não suportado, retorna erro com body para diagnóstico
    """
    try:
        credentials = _ensure_credentials_from_env(credentials)

        # validar / coercer charge_id para inteiro (evita 400 tipo inválido)
        try:
            cid_int = int(charge_id)
        except Exception:
            logger.warning("cancel_charge: charge_id inválido (deve ser inteiro): %r", charge_id)
            return False, {"error": "charge_id inválido, deve ser inteiro"}

        # 0) tentativa via SDK (se disponível) — alguns SDKs expõem método de cancelamento
        try:
            efi = EfiPay({"client_id": credentials.get("client_id"), "client_secret": credentials.get("client_secret"), "sandbox": credentials.get("sandbox", True)})
            for m in ("cancel_charge", "cancel", "void_charge", "delete_charge"):
                fn = getattr(efi, m, None)
                if callable(fn):
                    logger.info("cancel_charge: tentando via SDK método %s", m)
                    try:
                        # SDKs variam: tentamos passar id direto e também como named param
                        try:
                            r = fn(cid_int)
                        except TypeError:
                            r = fn(id=cid_int)
                        logger.info("cancel_charge SDK resposta: %r", r)
                        # Persistir tentativa caso seja dict de sucesso
                        try:
                            if isinstance(r, dict) and (r.get("code") == 200 or r.get("status") in ("canceled", "cancelled", "cancelado")):
                                _persist_cancel_to_db(cid_int, r)
                        except Exception:
                            logger.debug("persist SDK cancel falhou")
                        return True, r
                    except Exception as e:
                        logger.debug("SDK cancel %s falhou: %s", m, e)
        except Exception:
            logger.debug("cancel_charge: SDK tentativa falhou / indisponível")

        sandbox = credentials.get("sandbox", True)
        client_id = credentials.get("client_id")
        cache_key = (client_id, bool(sandbox))
        base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
        url_cancel = f"{base}/v1/charge/{cid_int}/cancel"

        # Log informativo sobre o ambiente/endpoint que será usado para o cancel
        try:
            logger.info("cancel_charge: will call cancel on base=%s sandbox=%s charge_id=%s", base, bool(sandbox), cid_int)
            # também logamos token/key_id se disponível (não expor token)
            entry = _TOKEN_CACHE.get(cache_key)
            tok = entry.get("access_token") if entry else None
            if tok:
                try:
                    import base64 as _base64, json as _json
                    p = tok.split(".")[1] + "=" * (-len(tok.split(".")[1]) % 4)
                    payload = _json.loads(_base64.urlsafe_b64decode(p))
                    logger.info("cancel_charge: token cached key_id=%s", payload.get("data", {}).get("key_id"))
                except Exception:
                    logger.info("cancel_charge: token cached (no key_id parsed)")
        except Exception:
            logger.debug("cancel_charge: falha ao logar ambiente/token")

        # Função auxiliar que executa o PUT com um token/creds atuais
        def _do_put_with_token(creds, url=url_cancel):
            token = _get_bearer_token(creds) if "client_id" in creds and "client_secret" in creds else None
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                # se não houver token, vamos deixar sem Authorization e requests tratará (ou usar basic auth no fallback)
                pass
            try:
                resp = requests.put(url, headers=headers, timeout=15)
                return resp, token
            except Exception as e:
                logger.exception("cancel_charge: PUT %s falhou: %s", url, e)
                return None, token

        logger.info("cancel_charge: tentando PUT %s (auth=Bearer? %s)", url_cancel, True)
        # primeira tentativa
        resp, used_token = _do_put_with_token(credentials)
        if resp is not None:
            logger.info("cancel_charge: PUT %s -> status=%s text=%s", url_cancel, getattr(resp, "status_code", None), (getattr(resp, "text", "") or "")[:2000])
            # sucesso
            if resp.status_code in (200, 204):
                try:
                    j = resp.json()
                except Exception:
                    j = {"http_status": resp.status_code, "text": resp.text}
                # persistir no DB (melhora auditabilidade)
                try:
                    _persist_cancel_to_db(cid_int, j)
                except Exception:
                    logger.debug("persist cancel response failed")
                return True, j
            # retry-on-401: limpar cache específico, re-obter token e tentar novamente (uma vez)
            if resp.status_code == 401:
                logger.info("cancel_charge: PUT retornou 401, limpando cache e tentando re-authorize + retry")
                try:
                    # limpar cache apenas para este client+env
                    _TOKEN_CACHE.pop(cache_key, None)
                except Exception:
                    logger.debug("falha limpando _TOKEN_CACHE")
                # segunda tentativa
                resp2, _ = _do_put_with_token(credentials)
                if resp2 is not None:
                    logger.info("cancel_charge: retry PUT %s -> status=%s text=%s", url_cancel, getattr(resp2, "status_code", None), (getattr(resp2, "text", "") or "")[:2000])
                    if resp2.status_code in (200, 204):
                        try:
                            j2 = resp2.json()
                        except Exception:
                            j2 = {"http_status": resp2.status_code, "text": resp2.text}
                        try:
                            _persist_cancel_to_db(cid_int, j2)
                        except Exception:
                            logger.debug("persist cancel response failed")
                        return True, j2
                    # retry failed fallback handled below...
                else:
                    return False, {"error": "PUT retry falhou (exceção no request)"}
            if resp.status_code not in (404, 405):
                try:
                    return False, resp.json()
                except Exception:
                    return False, {"http_status": resp.status_code, "text": resp.text}
        else:
            logger.debug("cancel_charge: sem resposta no primeiro PUT")

        # 2) tentar DELETE /v1/charge/{id} como fallback (mantendo comportamento anterior)
        url = f"{base}/v1/charge/{cid_int}"
        logger.info("cancel_charge: tentando DELETE %s (auth=client creds/token)", url)
        try:
            token = _get_bearer_token(credentials) if "client_id" in credentials and "client_secret" in credentials else None
            if token:
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                resp2 = requests.delete(url, headers=headers, timeout=15)
            else:
                client_id = credentials.get("client_id")
                client_secret = credentials.get("client_secret")
                resp2 = requests.delete(url, auth=(client_id, client_secret), timeout=15)
            logger.info("cancel_charge: DELETE %s -> status=%s text=%s", url, getattr(resp2, "status_code", None), (getattr(resp2, "text", "") or "")[:2000])
            if resp2.status_code in (200, 204):
                try:
                    j2 = resp2.json()
                except Exception:
                    j2 = {"http_status": resp2.status_code, "text": resp2.text}
                try:
                    _persist_cancel_to_db(cid_int, j2)
                except Exception:
                    logger.debug("persist cancel response failed")
                return True, j2
            else:
                try:
                    return False, resp2.json()
                except Exception:
                    return False, {"http_status": resp2.status_code, "text": resp2.text}
        except Exception as e:
            logger.exception("cancel_charge fallback DELETE falhou: %s", e)
            return False, str(e)

    except Exception as e:
        logger.exception("Erro em cancel_charge: %s", e)
        return False, str(e)


def _save_pdf_stream_to_path(resp, dest_path):
    try:
        # se o diretório pai não existe ou não é gravável, usamos BOLETOS_DIR como fallback
        dest_dir = os.path.dirname(dest_path) or BOLETOS_DIR
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            # fallback para BOLETOS_DIR
            dest_dir = BOLETOS_DIR
            try:
                os.makedirs(dest_dir, exist_ok=True)
            except Exception:
                logger.exception("Falha criando diretório de boletos fallback %s", dest_dir)
                return False
        final_path = os.path.join(dest_dir, os.path.basename(dest_path))
        with open(final_path, "wb") as fh:
            for chunk in resp.iter_content(1024 * 8):
                if not chunk:
                    continue
                fh.write(chunk)
        logger.info("PDF salvo em %s", final_path)
        return True
    except Exception:
        logger.exception("Erro salvando PDF em %s", dest_path)
        return False


def _parse_vencimento(vencimento_str):
    """Aceita YYYY-MM-DD ou DD/MM/YYYY. Retorna datetime.date ou None."""
    if not vencimento_str:
        return None
    s = str(vencimento_str).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


# ------------------------------
# Funções para emissão múltipla
# ------------------------------
def _build_charge_payload_multi(client_data, items, custom_id, data_vencimento):
    """
    Monta payload de criação de charge para múltiplos itens (fretes).
    client_data: dicionário com info do cliente (campos compatíveis).
    items: lista de dicts {"name", "amount", "value"} em centavos.
    custom_id: string livre para rastrear (ex: "multi:1,2,3:TIMESTAMP")
    """
    metadata = {"custom_id": custom_id, "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi")}
    body = {"items": items, "metadata": metadata}
    return body


def _build_pay_payload_multi(client_data, data_vencimento):
    """
    Monta payload de payment (banking_billet) para múltiplos fretes com dados do cliente.
    """
    cpf_cnpj = (client_data.get("cliente_cnpj") or "").replace(".", "").replace("-", "").replace("/", "").strip()
    telefone = (client_data.get("cliente_telefone") or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", "").strip()
    cep = (client_data.get("cliente_cep") or "").replace("-", "").strip()
    if not cep or len(cep) != 8:
        cep = "74000000"
    nome_cliente = (client_data.get("cliente_fantasia") or client_data.get("cliente_nome") or "Cliente")[:80]
    customer = {
        "name": nome_cliente,
        "cpf": cpf_cnpj if len(cpf_cnpj) == 11 else None,
        "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None,
        "phone_number": (telefone or "")[:11],
        "email": (client_data.get("cliente_email") or "")[:100],
        "address": {
            "street": (client_data.get("cliente_endereco") or "")[:80],
            "number": (client_data.get("cliente_numero") or "")[:10],
            "neighborhood": (client_data.get("cliente_bairro") or "")[:50],
            "zipcode": cep,
            "city": (client_data.get("cliente_cidade") or "")[:50],
            "state": (client_data.get("cliente_estado") or "")[:2].upper(),
        },
        "juridical_person": {"corporate_name": nome_cliente, "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None},
    }
    payment = {"payment": {"banking_billet": {"expire_at": data_vencimento.strftime("%Y-%m-%d"), "customer": customer}}}
    return payment


def emitir_boleto_multiplo(frete_ids, vencimento_str=None):
    """
    Emite UM boleto agregando vários fretes (todos pertencentes ao mesmo cliente).
    - frete_ids: lista de inteiros
    - vencimento_str: opcional YYYY-MM-DD ou DD/MM/YYYY
    Retorna dicionário com keys: success (bool), error (str), cobranca_id, charge_id, boleto_url, pdf_boleto, barcode
    """
    if not isinstance(frete_ids, (list, tuple)) or len(frete_ids) == 0:
        return {"success": False, "error": "frete_ids inválido ou vazio"}

    # normalizar ids para inteiros únicos
    try:
        ids = sorted(list({int(x) for x in frete_ids}))
    except Exception:
        return {"success": False, "error": "frete_ids deve conter inteiros"}

    parsed_date = _parse_vencimento(vencimento_str)
    if parsed_date:
        data_vencimento = datetime.combine(parsed_date, datetime.min.time())
    else:
        data_vencimento = datetime.now() + timedelta(days=7)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # buscar fretes e dados do cliente (assume todos os fretes têm cliente cadastrado)
        format_ids = ",".join(["%s"] * len(ids))
        sql = f"""
            SELECT f.id, f.clientes_id, f.valor_total_frete,
                   o.nome AS origem_nome, d.nome AS destino_nome,
                   c.razao_social AS cliente_nome, c.nome_fantasia AS cliente_fantasia,
                   c.cnpj AS cliente_cnpj, c.endereco AS cliente_endereco, c.numero AS cliente_numero,
                   c.complemento AS cliente_complemento, c.bairro AS cliente_bairro, c.municipio AS cliente_cidade,
                   c.uf AS cliente_estado, c.cep AS cliente_cep, c.telefone AS cliente_telefone, c.email AS cliente_email
            FROM fretes f
            INNER JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            WHERE f.id IN ({format_ids})
        """
        cursor.execute(sql, tuple(ids))
        rows = cursor.fetchall()
        if not rows or len(rows) != len(ids):
            return {"success": False, "error": "Um ou mais fretes não encontrados"}

        # validar mesmo cliente
        clientes_ids = {int(r.get("clientes_id")) for r in rows}
        if len(clientes_ids) != 1:
            return {"success": False, "error": "Os fretes selecionados pertencem a clientes diferentes. Selecione apenas fretes do mesmo cliente."}
        cliente_id = clientes_ids.pop()
        client_data = rows[0]  # usar dados do cliente do primeiro frete

        # verificar se algum frete já tem cobrança não-cancelada / boleto_emitido
        q = f"SELECT frete_id, status FROM cobrancas WHERE frete_id IN ({format_ids}) AND (status IS NULL OR status != 'cancelado')"
        cursor.execute(q, tuple(ids))
        existing = cursor.fetchall()
        if existing:
            bad_ids = [str(r.get("frete_id")) for r in existing if r.get("frete_id")]
            return {"success": False, "error": f"Existem cobranças ativas para os fretes: {','.join(bad_ids)}. Cancele-as antes de emitir."}

        # montar items (cada frete como item)
        items = []
        total_centavos = 0
        for r in rows:
            valor = float(r.get("valor_total_frete") or 0)
            if valor <= 0:
                return {"success": False, "error": f"Valor inválido/zerado no frete #{r.get('id')}"}
            cent = int(round(valor * 100))
            total_centavos += cent
            desc = f"Frete #{r.get('id')}"
            if r.get("origem_nome") and r.get("destino_nome"):
                desc += f" - {r.get('origem_nome')} para {r.get('destino_nome')}"
            items.append({"name": desc[:80], "amount": 1, "value": cent})

        if total_centavos <= 0:
            return {"success": False, "error": "Soma dos fretes inválida/zerada"}

        # montar payloads
        # gerar custom_id seguro: apenas A-Za-z0-9 _ - permitidos; evita ":" e "," que causavam validation_error
        raw_cid = "multi-" + "-".join(map(str, ids)) + "-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")
        safe_cid = re.sub(r'[^A-Za-z0-9_-]', '_', raw_cid)[:80]
        custom_id = safe_cid
        body_charge = _build_charge_payload_multi(client_data, items, custom_id, data_vencimento)
        body_pay = _build_pay_payload_multi(client_data, data_vencimento)

        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }

        # criar charge
        create_resp = None
        try:
            _log_send_attempt("direct_create_charge_multi", body_charge, extra_note="direct HTTP create multi")
            resp = _direct_create_charge(credentials, body_charge)
            _log_provider_response("direct_create_charge_multi", resp)
            create_resp = resp
            charge_id = _extract_charge_id(resp) or (resp.get("data") or {}).get("id")
        except Exception as e:
            logger.exception("Erro criando charge multiplos fretes: %s", e)
            create_resp = e
            charge_id = None

        if not charge_id:
            return {"success": False, "error": f"Falha ao criar transação de cobrança: {create_resp}"}

        # associar pagamento (pay)
        pay_resp = None
        try:
            _log_send_attempt("direct_pay_charge_multi", body_pay, extra_note=f"direct pay for charge {charge_id}")
            pay_resp = _direct_pay_charge(credentials, charge_id, body_pay)
            _log_provider_response("direct_pay_charge_multi", pay_resp)
        except Exception as e:
            logger.exception("Erro ao chamar pay para charge %s: %s", charge_id, e)
            pay_resp = e

        final_resp = pay_resp or create_resp

        # extrair campos
        charge_id_final, boleto_url, barcode = _safe_get_charge_fields(final_resp if isinstance(final_resp, dict) else create_resp)
        if not charge_id_final:
            charge_id_final = charge_id

        # tentar obter pdf
        pdf_boleto_path = None
        pdf_url = None
        try:
            data = (final_resp.get("data") if isinstance(final_resp, dict) else None) or {}
            pdf_obj = data.get("pdf") or {}
            pdf_url = pdf_obj.get("charge") or pdf_obj.get("boleto") or data.get("link") or data.get("billet_link")
            if not pdf_url:
                pb = (data.get("payment") or {}).get("banking_billet") or data.get("banking_billet") or {}
                if isinstance(pb, dict):
                    pdf_url = pb.get("pdf") or pb.get("link")
        except Exception:
            pdf_url = None

        if not pdf_url:
            # tentar fetch_charge
            tries = 3
            for i in range(tries):
                try:
                    time.sleep(1 + i)
                    fresh = fetch_charge(credentials, charge_id_final)
                    if isinstance(fresh, dict):
                        d = fresh.get("data") or fresh.get("charge") or fresh
                        pdf_url = (d.get("pdf") or {}).get("charge") or (d.get("payment") or {}).get("banking_billet", {}).get("link") or d.get("link")
                    if pdf_url:
                        break
                except Exception:
                    logger.debug("fetch_charge tentativa para pdf falhou")
        if pdf_url:
            try:
                resp = fetch_boleto_pdf_stream(credentials, pdf_url)
                if resp is not None and getattr(resp, "status_code", None) == 200:
                    safe_dir = BOLETOS_DIR
                    fname = f"boleto_{charge_id_final}.pdf"
                    dest = os.path.join(safe_dir, fname)
                    ok = _save_pdf_stream_to_path(resp, dest)
                    if ok:
                        pdf_boleto_path = dest
                    else:
                        pdf_boleto_path = pdf_url
                else:
                    pdf_boleto_path = pdf_url
            except Exception:
                logger.exception("Erro ao baixar pdf do provedor")
                pdf_boleto_path = pdf_url

        # Persistir cobranca (uma única)
        try:
            cursor.execute("""
                INSERT INTO cobrancas
                  (frete_id, id_cliente, valor, data_vencimento, status,
                   charge_id, link_boleto, pdf_boleto, data_emissao)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                None,
                client_data["clientes_id"],
                float(sum([float(r.get("valor_total_frete") or 0) for r in rows])),
                data_vencimento.date(),
                "pendente",
                str(charge_id_final),
                boleto_url,
                pdf_boleto_path,
                datetime.today().date(),
            ))
            cobranca_id = getattr(cursor, "lastrowid", None)
            conn.commit()
        except Exception:
            logger.exception("Erro ao inserir cobranca agregada")
            conn.rollback()
            return {"success": False, "error": "Erro ao persistir cobrança agregada no banco"}

        # criar relações na tabela cobrancas_fretes (necessita migration)
        try:
            for r in rows:
                try:
                    cursor.execute("INSERT INTO cobrancas_fretes (cobranca_id, frete_id) VALUES (%s, %s)", (cobranca_id, int(r.get("id"))))
                except Exception:
                    logger.exception("Falha inserindo relação cobranca-frete para frete %s", r.get("id"))
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # marcar fretes como boleto_emitido
        try:
            cursor.execute(f"UPDATE fretes SET boleto_emitido = TRUE WHERE id IN ({','.join(['%s']*len(ids))})", tuple(ids))
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("Falha ao marcar fretes boleto_emitido")

        return {"success": True, "cobranca_id": cobranca_id, "charge_id": charge_id_final, "boleto_url": boleto_url, "barcode": barcode, "pdf_boleto": pdf_boleto_path}

    except Exception as e:
        logger.exception("Erro emitir_boleto_multiplo: %s", e)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        try:
            error_message = str(e)
        except Exception:
            error_message = repr(e)
        return {"success": False, "error": error_message}
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


def emitir_boleto_frete(frete_id, vencimento_str=None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""SELECT
                f.id, f.clientes_id, f.valor_total_frete,
                o.nome AS origem_nome, d.nome AS destino_nome,
                c.razao_social AS cliente_nome, c.nome_fantasia AS cliente_fantasia,
                c.cnpj AS cliente_cnpj, c.endereco AS cliente_endereco, c.numero AS cliente_numero,
                c.complemento AS cliente_complemento, c.bairro AS cliente_bairro, c.municipio AS cliente_cidade,
                c.uf AS cliente_estado, c.cep AS cliente_cep, c.telefone AS cliente_telefone, c.email AS cliente_email
            FROM fretes f
            INNER JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            WHERE f.id = %s""", (frete_id,))
        frete = cursor.fetchone()

        if not frete:
            return {"success": False, "error": "Frete não encontrado"}
        if not frete.get("cliente_email"):
            return {"success": False, "error": "Cliente sem e-mail cadastrado"}
        if not frete.get("cliente_telefone"):
            return {"success": False, "error": "Cliente sem telefone cadastrado"}
        if not frete.get("cliente_cnpj"):
            return {"success": False, "error": "Cliente sem CNPJ cadastrado"}

        parsed_date = _parse_vencimento(vencimento_str)
        if parsed_date:
            data_vencimento = datetime.combine(parsed_date, datetime.min.time())
        else:
            data_vencimento = datetime.now() + timedelta(days=7)

        try:
            valor_total_centavos = int(float(frete["valor_total_frete"] or 0) * 100)
        except Exception:
            logger.exception("valor_total_frete inválido para frete_id=%s: %r", frete_id, frete.get("valor_total_frete"))
            return {"success": False, "error": "Valor do frete inválido ou zerado"}
        if valor_total_centavos <= 0:
            return {"success": False, "error": "Valor do frete inválido ou zerado"}

        descricao_frete = f"Frete #{frete['id']}"
        if frete.get("origem_nome") and frete.get("destino_nome"):
            descricao_frete += f" - {frete['origem_nome']} para {frete['destino_nome']}"

        body_sdk = _build_body(frete, descricao_frete, data_vencimento, valor_total_centavos)
        body_charge = _build_charge_payload(frete, descricao_frete, data_vencimento, valor_total_centavos)
        body_pay = _build_pay_payload(frete, descricao_frete, data_vencimento, valor_total_centavos)

        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }

        efi = None
        try:
            efi = EfiPay(credentials)
            try:
                getattr(efi, "create_charge")
            except Exception:
                pass
        except Exception:
            logger.exception("Falha ao instanciar EfiPay SDK")
            efi = None

        # 1) criar charge
        charge_id = None
        create_response = None
        if efi:
            try:
                _log_send_attempt("create_charge", body_charge, extra_note="SDK create charge")
                s_ok, create_response, _ = _try_sdk_methods(efi, body_charge)
                if s_ok and isinstance(create_response, dict):
                    charge_id = _extract_charge_id(create_response)
            except Exception as ex:
                logger.debug("Erro ao criar charge via SDK: %s", ex)
                create_response = ex

        if not charge_id and efi:
            try:
                if hasattr(efi, "send") and callable(getattr(efi, "send")):
                    params = {"path": "/charge", "method": "POST"}
                    _log_send_attempt("send:create_charge", body_charge, extra_note="low-level send")
                    try:
                        resp_low = efi.send(credentials, params, body_charge, {})
                        _log_provider_response("send:create_charge", resp_low)
                        create_response = resp_low
                        if isinstance(resp_low, dict):
                            charge_id = _extract_charge_id(resp_low)
                    except Exception:
                        pass
                elif hasattr(efi, "request") and callable(getattr(efi, "request")):
                    try:
                        resp_low = efi.request(credentials, body=body_charge)
                    except TypeError:
                        resp_low = efi.request(body=body_charge)
                    _log_provider_response("request:create_charge", resp_low)
                    create_response = resp_low
                    if isinstance(resp_low, dict):
                        charge_id = _extract_charge_id(resp_low)
            except Exception:
                logger.debug("Fallback SDK create_charge falhou")

        if not charge_id:
            try:
                _log_send_attempt("direct_create_charge", body_charge, extra_note="direct HTTP fallback create")
                resp_direct = _direct_create_charge(credentials, body_charge)
                _log_provider_response("direct_create_charge", resp_direct)
                create_response = resp_direct
                if isinstance(resp_direct, dict):
                    charge_id = _extract_charge_id(resp_direct)
            except Exception as ex_direct:
                logger.debug("Direct create charge falhou: %s", ex_direct)
                create_response = ex_direct

        if not charge_id:
            logger.warning("Não foi possível obter charge_id. create_response=%r", create_response)
            return {"success": False, "error": f"Falha ao criar transação de cobrança: {create_response}"}

        # 2) associar pagamento à charge
        pay_response = None
        paid_success = False

        # tentativa via SDK (pode acabar invocando create_charge se o método for inadequado)
        if efi:
            try:
                # montar body para SDK incluindo id + payment (e garantir items/metadata para evitar validation_error)
                payment_body_for_sdk = {"id": charge_id, **body_pay}
                if "items" not in payment_body_for_sdk:
                    try:
                        payment_body_for_sdk["items"] = body_charge.get("items", [])
                    except Exception:
                        payment_body_for_sdk["items"] = []
                try:
                    if "metadata" not in payment_body_for_sdk:
                        payment_body_for_sdk["metadata"] = body_charge.get("metadata", {})
                except Exception:
                    payment_body_for_sdk.setdefault("metadata", {})

                _log_send_attempt("sdk_pay_attempt", payment_body_for_sdk, extra_note="try SDK pay variants")
                s_ok, pay_response, _ = _try_sdk_methods(efi, payment_body_for_sdk)
                if s_ok and isinstance(pay_response, dict):
                    if "data" in pay_response or "charge" in pay_response or pay_response.get("id") or pay_response.get("charge_id"):
                        paid_success = True
            except Exception:
                logger.debug("Erro ao tentar pay via SDK")

        # fallback direto HTTP para /charge/{id}/pay
        if not paid_success:
            try:
                _log_send_attempt("direct_pay_charge", body_pay, extra_note=f"direct HTTP pay for charge {charge_id}")
                resp_pay = _direct_pay_charge(credentials, charge_id, body_pay)
                _log_provider_response("direct_pay_charge", resp_pay)
                pay_response = resp_pay
                if isinstance(resp_pay, dict) and ("data" in resp_pay or "charge" in resp_pay or resp_pay.get("id") or resp_pay.get("charge_id")):
                    paid_success = True
                else:
                    # se veio resposta não-JSON ou validation que pede items, tentamos pay incluindo items+metadata
                    reason_text = ""
                    if isinstance(resp_pay, dict) and resp_pay.get("text"):
                        reason_text = resp_pay.get("text")[:1000]
                    elif isinstance(resp_pay, dict) and resp_pay.get("error"):
                        reason_text = str(resp_pay.get("error"))
                    logger.info("direct_pay_charge não retornou dados: %s", reason_text)
                    # tentativa alternativa: incluir items + metadata no POST /charge/{id}/pay
                    alt_body = {}
                    try:
                        alt_body.update({"items": body_charge.get("items", [])})
                        # manter payment
                        alt_body.update(body_pay)
                        alt_body.update({"metadata": body_charge.get("metadata", {})})
                        _log_send_attempt("direct_pay_charge_alt_with_items", alt_body, extra_note=f"direct HTTP pay alt for charge {charge_id}")
                        resp_pay_alt = _direct_pay_charge(credentials, charge_id, alt_body)
                        _log_provider_response("direct_pay_charge_alt_with_items", resp_pay_alt)
                        pay_response = resp_pay_alt
                        if isinstance(resp_pay_alt, dict) and ("data" in resp_pay_alt or "charge" in resp_pay_alt or resp_pay_alt.get("id") or resp_pay_alt.get("charge_id")):
                            paid_success = True
                    except Exception:
                        logger.debug("Tentativa alternativa de pay (com items) falhou")
            except Exception as ex_pay:
                logger.debug("Direct pay falhou: %s", ex_pay)
                pay_response = ex_pay

        final_response = pay_response if pay_response is not None else create_response

        if paid_success and isinstance(final_response, dict):
            charge_id_final, boleto_url, barcode = _safe_get_charge_fields(final_response)
            if not charge_id_final:
                charge_id_final = charge_id

            # -----------------------------------------------------------------
            # Tentar obter e salvar o PDF automaticamente (tentativas e fallback)
            pdf_boleto_path = None
            pdf_url = None
            try:
                data = final_response.get("data") or final_response.get("charge") or final_response
                if isinstance(data, dict):
                    pdf_obj = data.get("pdf") or {}
                    pdf_url = pdf_obj.get("charge") or pdf_obj.get("boleto") or data.get("link") or data.get("billet_link")
                    if not pdf_url:
                        # checar nested payment banking_billet
                        pb = (data.get("payment") or {}).get("banking_billet") or data.get("banking_billet") or {}
                        if isinstance(pb, dict):
                            pdf_url = pb.get("pdf") or pb.get("link")
            except Exception:
                pdf_url = None

            # se não veio no response, tentar obter via fetch_charge algumas vezes
            if not pdf_url:
                tries = 3
                for i in range(tries):
                    try:
                        time.sleep(1 + i)  # backoff 1s,2s,3s
                        fresh = fetch_charge(credentials, charge_id_final)
                        if isinstance(fresh, dict):
                            d = fresh.get("data") or fresh.get("charge") or fresh
                            if isinstance(d, dict):
                                pdf_obj = d.get("pdf") or {}
                                pdf_url = pdf_obj.get("charge") or pdf_obj.get("boleto") or d.get("link") or d.get("billet_link") or (d.get("payment") or {}).get("banking_billet", {}).get("link"[...])
                        if pdf_url:
                            break
                    except Exception:
                        logger.debug("Tentativa %s fetch_charge para obter pdf falhou", i + 1)

            if pdf_url:
                try:
                    resp = fetch_boleto_pdf_stream(credentials, pdf_url)
                    if resp is not None and getattr(resp, "status_code", None) == 200:
                        # usar BOLETOS_DIR (configurável) em vez de diretório fixo
                        safe_dir = BOLETOS_DIR
                        fname = f"boleto_{charge_id_final}.pdf"
                        dest = os.path.join(safe_dir, fname)
                        ok = _save_pdf_stream_to_path(resp, dest)
                        if ok:
                            pdf_boleto_path = dest
                        else:
                            # fallback: guardar a URL do provedor
                            pdf_boleto_path = pdf_url
                    else:
                        logger.info("fetch_boleto_pdf_stream retornou status não-200 ou resp None: %s", getattr(resp, "status_code", None) if resp else None)
                        pdf_boleto_path = pdf_url
                except Exception:
                    logger.exception("Erro ao tentar baixar pdf do provedor")
                    pdf_boleto_path = pdf_url
            else:
                logger.info("Nenhuma URL de PDF encontrada para charge %s", charge_id_final)
                pdf_boleto_path = None
            # -----------------------------------------------------------------

            try:
                cursor.execute(
                    """
                    INSERT INTO cobrancas
                      (frete_id, id_cliente, valor, data_vencimento, status,
                       charge_id, link_boleto, pdf_boleto, data_emissao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        frete["id"],
                        frete["clientes_id"],
                        frete["valor_total_frete"],
                        data_vencimento.date(),
                        "pendente",
                        charge_id_final,
                        boleto_url,
                        pdf_boleto_path,
                        datetime.today().date(),
                    ),
                )
                cobranca_id = getattr(cursor, "lastrowid", None)
                conn.commit()
            except Exception:
                logger.exception("Erro ao inserir cobranca para frete_id=%s", frete_id)
                conn.rollback()
                return {"success": False, "error": "Erro ao persistir cobrança no banco"}

            # marcar frete como já tendo boleto emitido (impede re-emissão)
            try:
                try:
                    cur2 = conn.cursor()
                    cur2.execute("UPDATE fretes SET boleto_emitido = TRUE WHERE id = %s", (frete["id"],))
                    conn.commit()
                    cur2.close()
                except Exception:
                    logger.exception("Falha ao marcar frete %s boleto_emitido", frete["id"])
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            except Exception:
                logger.exception("Erro marcando frete boleto_emitido (silenciado)")

            return {"success": True, "cobranca_id": cobranca_id, "charge_id": charge_id_final, "boleto_url": boleto_url, "barcode": barcode, "pdf_boleto": pdf_boleto_path}

        if isinstance(final_response, dict) and final_response.get("error") == "validation_error":
            err_desc = final_response.get("error_description") or final_response.get("message") or final_response
            return {"success": False, "error": f"Resposta inválida do provedor de cobrança: {err_desc}"}

        if isinstance(final_response, dict):
            return {"success": False, "error": f"Resposta inválida do provedor de cobrança: {final_response}"}
        if isinstance(final_response, Exception):
            return {"success": False, "error": f"Erro ao chamar provedor: {str(final_response)}"}

        return {"success": False, "error": "Resposta inválida do provedor de cobrança"}

    except Exception as e:
        logger.exception("Erro ao emitir boleto para frete_id=%s", frete_id)
        try:
            if conn:
                conn.rollback()
        except Exception:
            logger.exception("Falha ao dar rollback")
        try:
            error_message = str(e)
        except Exception:
            try:
                error_message = repr(e)
            except Exception:
                error_message = f"{type(e).__name__}: Erro ao processar boleto"
        return {"success": False, "error": error_message}
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            logger.exception("Erro ao fechar cursor em emitir_boleto_frete")
        try:
            if conn:
                conn.close()
        except Exception:
            logger.exception("Erro ao fechar conexao em emitir_boleto_frete")
