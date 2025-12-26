#!/usr/bin/env python3
import os
import json
import copy
import logging
import time
from datetime import datetime, timedelta

import requests
from efipay import EfiPay
from utils.db import get_db_connection

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# controla logs de payloads completos (True/False via env var)
DEBUG_PAYLOAD = os.getenv("EFI_DEBUG_PAYLOAD", "false").lower() in ("1", "true", "yes")


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


# Token cache (módulo) e helper para obter Bearer token via client_credentials
_TOKEN_CACHE = {"access_token": None, "expire_at": 0.0}


def _get_bearer_token(credentials):
    """
    Obtém e faz cache de um access_token via client_credentials no endpoint /authorize.
    Retorna o token string ou None em caso de falha.
    """
    try:
        now = time.time()
        token = _TOKEN_CACHE.get("access_token")
        if token and _TOKEN_CACHE.get("expire_at", 0) > now + 5:
            return token

        sandbox = credentials.get("sandbox", True)
        base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
        url = f"{base}/v1/authorize"

        client_id = credentials.get("client_id")
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
            logger.warning("_get_bearer_token: status=%s text=%s", resp.status_code, (resp.text or "")[:1000])
            return None

        j = resp.json()
        token = j.get("access_token")
        expires_in = int(j.get("expires_in", 0) or 0)
        # cache com margem de segurança (-10s)
        _TOKEN_CACHE["access_token"] = token
        _TOKEN_CACHE["expire_at"] = now + max(0, expires_in - 10)
        return token
    except Exception:
        logger.exception("Erro obtendo bearer token")
        return None


def _direct_post(credentials, path, body):
    """
    Post direto para API cobrancas usando Bearer token (obtido via client_credentials).
    Retorna o JSON parseado do provedor ou um dict com http_status/text quando não-JSON.
    """
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

        if vencimento_str:
            try:
                data_vencimento = datetime.strptime(vencimento_str, "%Y-%m-%d")
            except Exception:
                return {"success": False, "error": "Formato de vencimento inválido (use YYYY-MM-DD)"}
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
            try:
                cursor.execute(
                    """
                    INSERT INTO cobrancas
                      (id_cliente, valor, data_vencimento, status,
                       charge_id, link_boleto, pdf_boleto, data_emissao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        frete["clientes_id"],
                        frete["valor_total_frete"],
                        data_vencimento.date(),
                        "pendente",
                        charge_id_final,
                        boleto_url,
                        None,
                        datetime.today().date(),
                    ),
                )
                cobranca_id = getattr(cursor, "lastrowid", None)
                conn.commit()
            except Exception:
                logger.exception("Erro ao inserir cobranca para frete_id=%s", frete_id)
                conn.rollback()
                return {"success": False, "error": "Erro ao persistir cobrança no banco"}

            return {"success": True, "cobranca_id": cobranca_id, "charge_id": charge_id_final, "boleto_url": boleto_url, "barcode": barcode}

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
