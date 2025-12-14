import os
import json
import copy
import logging
from datetime import datetime, timedelta

from efipay import EfiPay
from utils.db import get_db_connection

logger = logging.getLogger(__name__)


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
                if lk in ("cpf", "cnpj", "phone_number", "telefone", "email"):
                    x[k] = mask_string(x[k])
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


def _safe_get_charge_fields(response):
    """
    Tenta extrair charge_id, link do boleto e barcode de formas comuns.
    Retorna (charge_id, boleto_url, barcode)
    """
    if not response or not isinstance(response, dict):
        return None, None, None

    # respostas podem vir em 'data' ou 'charge'
    data = response.get("data") or response.get("charge") or response

    # tentativa de extrair id
    charge_id = data.get("id") or data.get("charge_id") or response.get("data", {}).get("id")

    boleto_url = None
    barcode = None

    # payment pode ser dict ou lista em vários níveis
    try:
        # caminhos comuns
        if isinstance(data.get("payment"), dict):
            p = data.get("payment")
            boleto_url = (p.get("banking_billet") or {}).get("link") or p.get("link")
            barcode = (p.get("banking_billet") or {}).get("barcode") or p.get("barcode")
        if not boleto_url and isinstance(data.get("payments"), list) and data.get("payments"):
            p = data.get("payments")[0]
            boleto_url = (p.get("banking_billet") or {}).get("link") or p.get("link")
            barcode = (p.get("banking_billet") or {}).get("barcode") or p.get("barcode")
        # fallback direto em data
        if not boleto_url:
            boleto_url = (data.get("banking_billet") or {}).get("link") or response.get("link")
        if not barcode:
            barcode = (data.get("banking_billet") or {}).get("barcode")
    except Exception:
        logger.debug("Falha extraindo fields do response: %r", response)

    return charge_id, boleto_url, barcode


def _build_body(frete, descricao_frete, data_vencimento, valor_total_centavos):
    """
    Constrói o payload canônico (conforme exemplos Efipay):
    {
      "items": [...],
      "payment": { "banking_billet": { ... } },
      "metadata": { ... }
    }
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

    body = {
        "items": items,
        "payment": {"banking_billet": banking_billet},
        "metadata": metadata,
    }

    return body


def _try_sdk_methods(efi, body):
    """
    Tenta invocar o SDK Efipay com diferentes nomes de métodos que podem existir
    na versão instalada. Retorna (success_bool, response, method_tried)
    """
    tried = []
    response = None

    # lista explícita de candidatos comuns
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

    # adicionar dinamicamente métodos contendo keywords
    for attr in dir(efi):
        if any(k in attr.lower() for k in ("charge", "billet", "boleto", "create")):
            if attr not in candidates:
                candidates.append(attr)

    # tentar métodos diretos em efi
    for method in candidates:
        try:
            fn = getattr(efi, method, None)
            if callable(fn):
                tried.append(method)
                # tentar chamadas com variações (body kw, body positional)
                try:
                    resp = fn(body=body)
                except TypeError:
                    try:
                        resp = fn(body)
                    except TypeError:
                        # tentar sem wrapper, alguns SDKs usam diferentes assinaturas
                        resp = fn(body, None)
                return True, resp, method
        except Exception as ex:
            logger.debug("Tentativa SDK método %s falhou: %s", method, ex)
            response = ex
            continue

    # tentar acessar objetos aninhados (e.g., efi.charges.create)
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
                            try:
                                resp = fn(body=body)
                            except TypeError:
                                resp = fn(body)
                            return True, resp, f"{attr}.{subm}"
                    except Exception as ex:
                        logger.debug("Tentativa SDK método %s.%s falhou: %s", attr, subm, ex)
                        response = ex
                        continue
        except Exception:
            continue

    return False, response, tried


def emitir_boleto_frete(frete_id, vencimento_str=None):
    """
    Emite boleto para o frete indicado. Retorna dict com sucesso/erro.
    """
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

        # validações
        if not frete.get("cliente_email"):
            return {"success": False, "error": "Cliente sem e-mail cadastrado"}
        if not frete.get("cliente_telefone"):
            return {"success": False, "error": "Cliente sem telefone cadastrado"}
        if not frete.get("cliente_cnpj"):
            return {"success": False, "error": "Cliente sem CNPJ cadastrado"}

        # calcular vencimento
        if vencimento_str:
            try:
                data_vencimento = datetime.strptime(vencimento_str, "%Y-%m-%d")
            except Exception:
                return {"success": False, "error": "Formato de vencimento inválido (use YYYY-MM-DD)"}
        else:
            data_vencimento = datetime.now() + timedelta(days=7)

        # valor em centavos
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

        body = _build_body(frete, descricao_frete, data_vencimento, valor_total_centavos)

        # instanciar cliente efipay
        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }
        efi = None
        try:
            efi = EfiPay(credentials)
        except Exception as ex:
            logger.exception("Falha ao instanciar EfiPay SDK: %s", ex)
            return {"success": False, "error": "Falha ao inicializar cliente de cobrança"}

        # Tentar autenticar explicitamente quando suportado (corrige o problema detectado)
        try:
            if hasattr(efi, "authenticate") and callable(getattr(efi, "authenticate")):
                try:
                    efi.authenticate()
                    logger.info("EfiPay.authenticate() executado com sucesso")
                except Exception as ex_auth:
                    # não abortar aqui — alguns SDKs aceitam chamadas sem chamar authenticate explicitamente
                    logger.warning("EfiPay.authenticate() falhou (continuando para tentativas): %s", ex_auth)
        except Exception:
            logger.debug("Ignorando erro ao verificar authenticate() no SDK", exc_info=True)

        # log sanitizado do body (temporário)
        try:
            logger.info("EFI create_charge body: %s", json.dumps(_sanitize_for_log(body), ensure_ascii=False))
        except Exception:
            logger.info("EFI create_charge body: <unserializable>")

        # Tentar métodos do SDK que possam existir na versão instalada (alta-nível)
        success, response, method = _try_sdk_methods(efi, body)

        # Se não encontrou um método de alto nível, tentar fallback de baixo nível usando send/request
        if not success:
            try:
                # tentar efi.send(credentials, params, body, headers_complement) se disponível
                if hasattr(efi, "send") and callable(getattr(efi, "send")):
                    params = {"path": "/one_step_charge", "method": "POST"}
                    headers_complement = {}
                    try:
                        logger.info("Tentando fallback: efi.send(credentials, params, body, headers_complement)")
                        resp_low = efi.send(credentials, params, body, headers_complement)
                        success = True
                        response = resp_low
                        method = "send"
                    except TypeError:
                        # assinatura diferente — tentar request
                        logger.debug("efi.send aceito, mas com assinatura diferente; tentando efi.request(...)")
                        try:
                            # tentar request usando body=... (alguns SDKs usam request(settings, **kwargs))
                            if hasattr(efi, "request") and callable(getattr(efi, "request")):
                                try:
                                    resp_low = efi.request(credentials, body=body)
                                except TypeError:
                                    # alternativa: request(body=body) or request(settings, body)
                                    try:
                                        resp_low = efi.request(body=body)
                                    except Exception:
                                        resp_low = efi.request(credentials, body=body)
                                success = True
                                response = resp_low
                                method = "request"
                        except Exception as ex_low:
                            logger.debug("Fallback request via efi.request falhou: %s", ex_low)
                    except Exception as ex_send:
                        logger.debug("Tentativa efi.send falhou: %s", ex_send)
                elif hasattr(efi, "request") and callable(getattr(efi, "request")):
                    # tentar request se send não existir
                    try:
                        logger.info("Tentando fallback: efi.request(credentials, body=...)")
                        try:
                            resp_low = efi.request(credentials, body=body)
                        except TypeError:
                            resp_low = efi.request(body=body)
                        success = True
                        response = resp_low
                        method = "request"
                    except Exception as ex_req:
                        logger.debug("Tentativa efi.request falhou: %s", ex_req)
            except Exception as ex:
                logger.debug("Erro ao tentar fallback send/request: %s", ex)

        # Se retorno for exceção, formatar
        if isinstance(response, Exception):
            logger.exception("SDK método tentou e retornou exceção (método=%r): %r", method, response)

        # log da resposta (pode ser dict ou objeto)
        logger.info("EFI create_charge response (method=%r): %r", method, response)

        # interpretar resposta
        last_response = response

        # --- Adição: se o provedor reclamou especificamente de '/payment', tentar uma variante com 'payments' ---
        try:
            need_retry_payment_variant = False
            if isinstance(last_response, dict):
                prop = last_response.get("property") or ""
                # mensagem também pode vir em 'message' ou 'error_description'
                msg = str(last_response.get("message") or last_response.get("error_description") or "")
                if prop == "/payment" or "/payment" in msg or msg.find("Propriedade desconhecida") != -1 and "/payment" in str(last_response):
                    need_retry_payment_variant = True
            if need_retry_payment_variant:
                logger.info("Resposta do provedor indica problema com '/payment' — tentando alternativa com 'payments'...")
                # reconstrói alternativa: transforma payment => payments: [ { 'banking_billet': ... } ]
                alt_body = dict(body)
                payment_obj = alt_body.pop("payment", None)
                if payment_obj is not None:
                    bb = None
                    if isinstance(payment_obj, dict):
                        bb = payment_obj.get("banking_billet") or payment_obj
                    # colocar em payments como lista
                    alt_body["payments"] = [{"banking_billet": bb} if isinstance(bb, dict) else bb]
                    # tentar novamente com SDK (alta-nível)
                    try:
                        s2, resp2, m2 = _try_sdk_methods(efi, alt_body)
                    except Exception as ex_try:
                        logger.debug("Tentativa alta-nível com alt_body falhou: %s", ex_try)
                        s2, resp2, m2 = False, ex_try, None
                    # se alta-nível falhar, tentar low-level como antes
                    if not s2:
                        try:
                            if hasattr(efi, "send") and callable(getattr(efi, "send")):
                                try:
                                    params = {"path": "/one_step_charge", "method": "POST"}
                                    resp2 = efi.send(credentials, params, alt_body, {})
                                    s2 = True
                                    m2 = "send"
                                except Exception as exs:
                                    logger.debug("efi.send com alt_body falhou: %s", exs)
                            if not s2 and hasattr(efi, "request") and callable(getattr(efi, "request")):
                                try:
                                    resp2 = efi.request(credentials, body=alt_body)
                                    s2 = True
                                    m2 = "request"
                                except Exception as exr:
                                    logger.debug("efi.request com alt_body falhou: %s", exr)
                        except Exception as ex_low:
                            logger.debug("Erro ao tentar fallback low-level com alt_body: %s", ex_low)
                    # se obteve resposta válida, processar e persistir como no fluxo principal
                    if s2 and isinstance(resp2, dict) and ("data" in resp2 or "charge" in resp2):
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

                            return {
                                "success": True,
                                "cobranca_id": cobranca_id,
                                "charge_id": charge_id2,
                                "boleto_url": boleto_url2,
                                "barcode": barcode2,
                            }
                        else:
                            logger.warning("Alt response sem charge_id: %r", resp2)
        except Exception:
            logger.debug("Erro durante tentativa de alternativa para /payment", exc_info=True)
        # --- fim da adição ---

        if success and isinstance(response, dict) and ("data" in response or "charge" in response):
            charge_id, boleto_url, barcode = _safe_get_charge_fields(response)
            if not charge_id:
                logger.warning("charge_id ausente na resposta do provedor: %r", response)
                # continuar para fallback/persistência de erro
            else:
                # persistir cobrança
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

        # tratar casos de validation_error retornados pelo provedor
        if isinstance(last_response, dict) and last_response.get("error") == "validation_error":
            err_desc = last_response.get("error_description") or last_response.get("message") or last_response
            return {"success": False, "error": f"Resposta inválida do provedor de cobrança: {err_desc}"}

        # se chegou aqui, tentar formatar erro legível
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
