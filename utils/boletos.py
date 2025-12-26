#!/usr/bin/env python3
import os
import json
import copy
import logging
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
        # mantemos começo/fim para facilitar debug sem vazar dados inteiros
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
        # imprime payload completo (mascarizado)
        logger.info("SENDING-PAYLOAD (%s): %s", method_name, s)
    else:
        logger.debug("SENDING-PAYLOAD (%s): %s", method_name, s)


def _log_provider_response(method_name, resp_raw):
    # resp_raw pode ser dict, object, requests.Response ou string
    try:
        if hasattr(resp_raw, "status_code"):
            # requests.Response
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
    """
    Tenta extrair charge_id, link do boleto e barcode de formas comuns.
    Retorna (charge_id, boleto_url, barcode)
    """
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


def _build_body(frete, descricao_frete, data_vencimento, valor_total_centavos):
    """
    Body compatível com os métodos do SDK (high-level). Este usa o wrapper 'payment'
    com 'banking_billet' — é o formato que o SDK costuma aceitar.
    """
    cpf_cnpj = (frete.get("cliente_cnpj") or "").replace(".", "").replace("-", "").replace("/", "").strip()
    telefone = (frete.get("cliente_telefone") or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", "").strip()
    cep = (frete.get("cliente_cep") or "").replace("-", "").strip()
    if not cep or len(cep) != 8:
        cep = "74000000"

    nome_cliente = (frete.get("cliente_fantasia") or frete.get("cliente_nome") or "Cliente")[:80]

    items = [
        {
            "name": descricao_frete[:80],
            "amount": 1,
            "value": valor_total_centavos,
        }
    ]

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

    metadata = {
        "custom_id": str(frete["id"]),
        "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi"),
    }

    # Formato com wrapper 'payment' — usado para chamadas via SDK (create_charge, create_one_step_billet, etc)
    body = {
        "items": items,
        "payment": {"banking_billet": banking_billet},
        "metadata": metadata,
    }

    return body


def _build_one_step_body(frete, descricao_frete, data_vencimento, valor_total_centavos):
    """
    Monta o payload no formato esperado pelo endpoint one-step (raw HTTP).
    Alguns servidores/esquemas esperam 'payment' dentro do SDK, outros aceitam o formato
    'charge_type' + 'customer' no nível superior quando chamado via /v1/charge/one-step.
    Usamos esse formato para o fallback direto HTTP.
    """
    cpf_cnpj = (frete.get("cliente_cnpj") or "").replace(".", "").replace("-", "").replace("/", "").strip()
    telefone = (frete.get("cliente_telefone") or "").replace("(", "").replace(")", "").replace("-", "").replace(" ", "").strip()
    cep = (frete.get("cliente_cep") or "").replace("-", "").strip()
    if not cep or len(cep) != 8:
        cep = "74000000"

    nome_cliente = (frete.get("cliente_fantasia") or frete.get("cliente_nome") or "Cliente")[:80]

    items = [
        {
            "name": descricao_frete[:80],
            "amount": 1,
            "value": valor_total_centavos,
        }
    ]

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
    }

    metadata = {
        "custom_id": str(frete["id"]),
        "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi"),
    }

    one_step_body = {
        "items": items,
        "payment": {"banking_billet": {"expire_at": data_vencimento.strftime("%Y-%m-%d"), "customer": customer}},
        "metadata": metadata,
    }

    # Algumas variações do one-step aceitam 'charge_type' + 'customer' no topo; mantemos
    # a forma com 'payment' aqui (outra forma possível seria incluir 'charge_type': 'banking_billet').
    return one_step_body


def _try_sdk_methods(efi, body):
    tried = []
    response = None
    candidates = [
        "create_charge",
        "create_one_step_billet",
        "create_one_step_billet_charge",
        "create_billet",
        "create",
        "charges",
        "charge",
        "createCharge",
    ]
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


def _try_payment_variants(efi, original_body, credentials):
    variants_payloads = []
    base_items = original_body.get("items")
    base_meta = original_body.get("metadata")

    if "payment" in original_body:
        p = original_body["payment"]
        if isinstance(p, dict) and p.get("banking_billet"):
            full = {}
            if base_items is not None:
                full["items"] = base_items
            full["payments"] = [{"banking_billet": p["banking_billet"]}]
            if base_meta is not None:
                full["metadata"] = base_meta
            variants_payloads.append((full, "payments_banking_billet"))

        full = {}
        if base_items is not None:
            full["items"] = base_items
        full["payments"] = [p]
        if base_meta is not None:
            full["metadata"] = base_meta
        variants_payloads.append((full, "payments_wrap_simple"))

        if isinstance(p, dict) and p.get("banking_billet"):
            full = {}
            if base_items is not None:
                full["items"] = base_items
            full["banking_billet"] = p["banking_billet"]
            if base_meta is not None:
                full["metadata"] = base_meta
            variants_payloads.append((full, "banking_billet_top"))

        full = {}
        if base_items is not None:
            full["items"] = base_items
        full["payments"] = [{"payment": p}]
        if base_meta is not None:
            full["metadata"] = base_meta
        variants_payloads.append((full, "payments_payment_wrapper"))

    if not variants_payloads:
        return False, None, None, None

    for alt_body, vname in variants_payloads:
        _log_send_attempt(f"variant:{vname}", alt_body, extra_note="payment-variant")
        try:
            s2, resp2, m2 = _try_sdk_methods(efi, alt_body)
        except Exception as ex_try:
            s2, resp2, m2 = False, ex_try, None

        if s2:
            _log_provider_response(f"variant:{vname}", resp2)
            return True, resp2, m2, alt_body

        try:
            if hasattr(efi, "send") and callable(getattr(efi, "send")):
                try:
                    params = {"path": "/one_step_charge", "method": "POST"}
                    _log_send_attempt(f"send_variant:{vname}", alt_body, extra_note="low-level send")
                    resp2 = efi.send(credentials, params, alt_body, {})
                    _log_provider_response(f"send_variant:{vname}", resp2)
                    return True, resp2, "send", alt_body
                except TypeError:
                    logger.debug("efi.send com assinatura TypeError; tentando request")
                    if hasattr(efi, "request") and callable(getattr(efi, "request")):
                        _log_send_attempt("request", alt_body, extra_note="low-level request after send TypeError")
                        try:
                            resp2 = efi.request(credentials, body=alt_body)
                        except TypeError:
                            resp2 = efi.request(body=alt_body)
                        _log_provider_response("request", resp2)
                        return True, resp2, "request", alt_body
                except Exception as ex_send:
                    logger.debug("Tentativa efi.send falhou: %s", ex_send)
            if hasattr(efi, "request") and callable(getattr(efi, "request")):
                try:
                    _log_send_attempt("request", alt_body, extra_note="low-level request")
                    try:
                        resp2 = efi.request(credentials, body=alt_body)
                    except TypeError:
                        resp2 = efi.request(body=alt_body)
                    _log_provider_response("request", resp2)
                    return True, resp2, "request", alt_body
                except Exception as exr:
                    logger.debug("efi.request com alt_body '%s' falhou: %s", vname, exr)
        except Exception as ex_low:
            logger.debug("Erro ao tentar fallback low-level com alt_body '%s': %s", vname, ex_low)

    return False, None, None, None


def _direct_one_step_request(credentials, body):
    """
    Envia diretamente o body para o endpoint /v1/charge/one-step usando requests.
    Retorna dict (parsed JSON) ou lança exceção.
    """
    sandbox = credentials.get("sandbox", True)
    base = "https://cobrancas-h.api.efipay.com.br" if sandbox else "https://cobrancas.api.efipay.com.br"
    url = f"{base}/v1/charge/one-step"

    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("Credentials incompletas para chamada direta One-Step")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        resp = requests.post(url, json=body, auth=(client_id, client_secret), headers=headers, timeout=30)
    except Exception:
        raise

    try:
        j = resp.json()
    except Exception:
        resp.raise_for_status()
        raise ValueError("Resposta não-JSON do provedor")

    return j


def emitir_boleto_frete(frete_id, vencimento_str=None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                f.id,
                f.clientes_id,
                f.valor_total_frete,
                o.nome AS origem_nome,
                d.nome AS destino_nome,
                c.razao_social AS cliente_nome,
                c.nome_fantasia AS cliente_fantasia,
                c.cnpj AS cliente_cnpj,
                c.endereco AS cliente_endereco,
                c.numero AS cliente_numero,
                c.complemento AS cliente_complemento,
                c.bairro AS cliente_bairro,
                c.municipio AS cliente_cidade,
                c.uf AS cliente_estado,
                c.cep AS cliente_cep,
                c.telefone AS cliente_telefone,
                c.email AS cliente_email
            FROM fretes f
            INNER JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            WHERE f.id = %s
            """,
            (frete_id,),
        )
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

        # Monta dois corpos: um compatível com SDK (body_sdk) e outro para one-step direto (body_one_step)
        body_sdk = _build_body(frete, descricao_frete, data_vencimento, valor_total_centavos)
        body_one_step = _build_one_step_body(frete, descricao_frete, data_vencimento, valor_total_centavos)

        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }
        efi = None
        try:
            efi = EfiPay(credentials)
            # Workaround: inicializar endpoints internos do SDK
            try:
                getattr(efi, "create_charge")
            except Exception:
                pass
        except Exception as ex:
            logger.exception("Falha ao instanciar EfiPay SDK: %s", ex)
            return {"success": False, "error": "Falha ao inicializar cliente de cobrança"}

        try:
            if hasattr(efi, "authenticate") and callable(getattr(efi, "authenticate")):
                try:
                    efi.authenticate()
                    logger.info("EfiPay.authenticate() executado com sucesso")
                except Exception as ex_auth:
                    logger.warning("EfiPay.authenticate() falhou (continuando): %s", ex_auth)
        except Exception:
            logger.debug("Ignorando erro ao verificar authenticate() no SDK", exc_info=True)

        try:
            logger.info("EFI create_charge body (sanitizado): %s", _sanitize_for_log(body_sdk))
        except Exception:
            logger.info("EFI create_charge body: <unserializable>")

        # Tenta via SDK primeiro usando body_sdk
        success, response, method = _try_sdk_methods(efi, body_sdk)

        # Se SDK não conseguiu (None/Exception), tenta fallbacks (send/request) com body_sdk
        if not success:
            try:
                if hasattr(efi, "send") and callable(getattr(efi, "send")):
                    params = {"path": "/one_step_charge", "method": "POST"}
                    _log_send_attempt("send", body_sdk, extra_note="low-level send")
                    try:
                        resp_low = efi.send(credentials, params, body_sdk, {})
                        _log_provider_response("send", resp_low)
                        success = True
                        response = resp_low
                        method = "send"
                    except TypeError:
                        logger.debug("efi.send com assinatura TypeError; tentando request")
                        if hasattr(efi, "request") and callable(getattr(efi, "request")):
                            _log_send_attempt("request", body_sdk, extra_note="low-level request after send TypeError")
                            try:
                                resp_low = efi.request(credentials, body=body_sdk)
                            except TypeError:
                                resp_low = efi.request(body=body_sdk)
                            _log_provider_response("request", resp_low)
                            success = True
                            response = resp_low
                            method = "request"
                    except Exception as ex_send:
                        logger.debug("Tentativa efi.send falhou: %s", ex_send)
                elif hasattr(efi, "request") and callable(getattr(efi, "request")):
                    _log_send_attempt("request", body_sdk, extra_note="low-level request")
                    try:
                        resp_low = efi.request(credentials, body=body_sdk)
                    except TypeError:
                        resp_low = efi.request(body=body_sdk)
                    _log_provider_response("request", resp_low)
                    success = True
                    response = resp_low
                    method = "request"
            except Exception as ex:
                logger.debug("Erro ao tentar fallback send/request: %s", ex)

        # Se a resposta do SDK indicar que o provedor reclama de '/payment' ou '/payments' ou '/charge_type',
        # tentamos o fallback direto HTTP para /v1/charge/one-step usando body_one_step.
        try:
            last_response = response
            needs_direct_one_step = False
            if isinstance(last_response, dict):
                prop = None
                err = last_response.get("error") or ""
                err_desc = last_response.get("error_description") or {}
                # error_description pode ser dict ou string
                if isinstance(err_desc, dict):
                    prop = err_desc.get("property") or ""
                elif isinstance(err_desc, str):
                    prop = err_desc
                msg = str(last_response.get("message") or last_response.get("error_description") or "")
                if err == "validation_error" and ("/payment" in prop or "/payments" in prop or "/charge_type" in prop or "/payment" in msg or "/payments" in msg or "/charge_type" in msg):
                    needs_direct_one_step = True
        except Exception:
            needs_direct_one_step = False

        # Primeiro tentamos variantes (quando o provider reclama de /payment)
        if needs_direct_one_step:
            logger.info("Provider reclama de '/payment'/'/payments' ou '/charge_type' — tentando variantes de payload via SDK")
            try:
                s2, resp2, m2, used_body = _try_payment_variants(efi, body_sdk, credentials)
            except Exception as ex:
                logger.debug("Erro executando _try_payment_variants: %s", ex)
                s2, resp2, m2, used_body = False, None, None, None

            if s2:
                _log_provider_response("variant-final", resp2)
                if isinstance(resp2, dict) and ("data" in resp2 or "charge" in resp2):
                    charge_id2, boleto_url2, barcode2 = _safe_get_charge_fields(resp2)
                    if charge_id2:
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
                                    charge_id2,
                                    boleto_url2,
                                    None,
                                    datetime.today().date(),
                                ),
                            )
                            cobranca_id = getattr(cursor, "lastrowid", None)
                            conn.commit()
                        except Exception:
                            logger.exception("Erro ao inserir cobranca (alt) para frete_id=%s", frete_id)
                            conn.rollback()
                            return {"success": False, "error": "Erro ao persistir cobrança no banco (alt)"}

                        logger.info("Sucesso com variante (método=%s)", m2)
                        return {
                            "success": True,
                            "cobranca_id": cobranca_id,
                            "charge_id": charge_id2,
                            "boleto_url": boleto_url2,
                            "barcode": barcode2,
                        }
                    else:
                        logger.warning("Alt response sem charge_id: %r", resp2)

            # Se variantes falharam, tentamos direto one-step com body_one_step
            logger.info("Tentando fallback direto HTTP /v1/charge/one-step com formato one-step")
            try:
                _log_send_attempt("direct_http_one_step", body_one_step, extra_note="direct HTTP fallback after validation_error")
                resp_direct = _direct_one_step_request(credentials, body_one_step)
                _log_provider_response("direct_http_one_step", resp_direct)
                if isinstance(resp_direct, dict) and ("data" in resp_direct or "charge" in resp_direct):
                    success = True
                    response = resp_direct
                    method = "direct_http_one_step"
            except Exception as ex_direct:
                logger.debug("Tentativa direct HTTP one-step falhou: %s", ex_direct)

        # Se não precisou de tratamento especial, e success ainda é False, tentamos fallback direto também
        if not success:
            try:
                _log_send_attempt("direct_http_one_step", body_one_step, extra_note="direct HTTP fallback (final)")
                resp_direct = _direct_one_step_request(credentials, body_one_step)
                _log_provider_response("direct_http_one_step", resp_direct)
                if isinstance(resp_direct, dict) and ("data" in resp_direct or "charge" in resp_direct):
                    success = True
                    response = resp_direct
                    method = "direct_http_one_step"
            except Exception as ex_direct:
                logger.debug("Tentativa direct HTTP one-step (final) falhou: %s", ex_direct)

        if isinstance(response, Exception):
            logger.exception("SDK método retornou exceção (método=%r): %r", method, response)

        logger.info("EFI create_charge response (method=%r): %r", method, response)
        last_response = response

        # Se após todos os esforços tivermos sucesso com response contendo data/charge => persistir
        if success and isinstance(last_response, dict) and ("data" in last_response or "charge" in last_response):
            charge_id, boleto_url, barcode = _safe_get_charge_fields(last_response)
            if not charge_id:
                logger.warning("charge_id ausente na resposta do provedor: %r", last_response)
            else:
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
                            charge_id,
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

                return {
                    "success": True,
                    "cobranca_id": cobranca_id,
                    "charge_id": charge_id,
                    "boleto_url": boleto_url,
                    "barcode": barcode,
                }

        # Se a resposta final for validation_error — devolve a mensagem amigável para UI
        if isinstance(last_response, dict) and last_response.get("error") == "validation_error":
            err_desc = last_response.get("error_description") or last_response.get("message") or last_response
            return {"success": False, "error": f"Resposta inválida do provedor de cobrança: {err_desc}"}

        if isinstance(last_response, dict):
            return {"success": False, "error": f"Resposta inválida do provedor de cobrança: {last_response}"}
        if isinstance(last_response, Exception):
            return {"success": False, "error": f"Erro ao chamar provedor: {str(last_response)}"}

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
