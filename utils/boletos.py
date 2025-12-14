import os
import logging
from datetime import datetime, timedelta
from time import sleep

from efipay import EfiPay
from utils.db import get_db_connection

logger = logging.getLogger(__name__)


def _safe_get_charge_fields(response):
    """
    Extrai charge_id, boleto_url e barcode de formas comuns na resposta.
    Suporta fontes 'data' | 'charge' e 'payment' (dict) ou 'payments' (list).
    """
    if not response or not isinstance(response, dict):
        return None, None, None

    data = response.get("data") or response.get("charge") or {}
    charge_id = data.get("charge_id") or data.get("id") or (response.get("data") or {}).get("id")

    payment = data.get("payment") or data.get("payments") or {}
    boleto_url = None
    barcode = None
    try:
        if isinstance(payment, list) and payment:
            p = payment[0]
        elif isinstance(payment, dict):
            p = payment
        else:
            p = {}
        boleto_url = (
            (p.get("banking_billet") or {}).get("link")
            or p.get("link")
            or (data.get("banking_billet") or {}).get("link")
        )
        barcode = (
            (p.get("banking_billet") or {}).get("barcode")
            or p.get("barcode")
            or (data.get("banking_billet") or {}).get("barcode")
        )
    except Exception:
        logger.debug("Falha tentando extrair boleto/payment fields: %r", payment)
    return charge_id, boleto_url, barcode


def _build_bodies(frete, descricao_frete, data_vencimento, valor_total_centavos):
    """
    Gera variantes do payload e garante que 'items' esteja presente no root
    (algumas versões do provedor exigem items em nível raiz mesmo quando usam
    'charge' ou 'charges').
    """
    cpf_cnpj = (
        frete["cliente_cnpj"].replace(".", "").replace("-", "").replace("/", "").strip()
        if frete.get("cliente_cnpj")
        else None
    )
    telefone = (
        frete["cliente_telefone"]
        .replace("(", "")
        .replace(")", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
        if frete.get("cliente_telefone")
        else None
    )
    cep = (frete.get("cliente_cep") or "").replace("-", "").strip()
    if not cep or len(cep) != 8:
        cep = "74000000"

    nome_cliente = (frete.get("cliente_fantasia") or frete.get("cliente_nome") or "Cliente")[:80]
    customer = {
        "name": nome_cliente,
        "cpf": cpf_cnpj if cpf_cnpj and len(cpf_cnpj) == 11 else None,
        "cnpj": cpf_cnpj if cpf_cnpj and len(cpf_cnpj) == 14 else None,
        "phone_number": (telefone or "")[:11],
        "email": (frete.get("cliente_email") or "")[:50],
        "address": {
            "street": (frete.get("cliente_endereco") or "Rua Exemplo")[:80],
            "number": (frete.get("cliente_numero") or "SN")[:10],
            "neighborhood": (frete.get("cliente_bairro") or "Centro")[:50],
            "zipcode": cep,
            "city": (frete.get("cliente_cidade") or "Goiania")[:50],
            "state": (frete.get("cliente_estado") or "GO")[:2].upper(),
        },
    }

    banking_billet = {
        "expire_at": data_vencimento.strftime("%Y-%m-%d"),
        "customer": customer,
    }

    items = [
        {
            "name": descricao_frete[:80],
            "amount": 1,
            "value": valor_total_centavos,
        }
    ]

    metadata = {
        "custom_id": str(frete["id"]),
        "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi"),
    }

    bodies = []

    # Variante A: antigo/único "payment"
    bodies.append({
        "payment": {"banking_billet": banking_billet},
        "items": items,
        "metadata": metadata,
    })

    # Variante B: plural "payments" (lista)
    bodies.append({
        "payments": [{"banking_billet": banking_billet}],
        "items": items,
        "metadata": metadata,
    })

    # Variante C: "charge" encapsulando (mantém items dentro de charge)
    bodies.append({
        "charge": {
            "payment": {"banking_billet": banking_billet},
            "items": items,
            "metadata": metadata,
        },
        # GARANTIA: adicionar items também no root para evitar erro de schema
        "items": items,
    })

    # Variante D: "charge" com "payments"
    bodies.append({
        "charge": {
            "payments": [{"banking_billet": banking_billet}],
            "items": items,
            "metadata": metadata,
        },
        "items": items,
    })

    # Variante E: "charges" array (algumas APIs aceitam lista de charges)
    bodies.append({
        "charges": [
            {
                "payments": [{"banking_billet": banking_billet}],
                "items": items,
                "metadata": metadata,
            }
        ],
        # também colocar items no root
        "items": items,
    })

    return bodies


def emitir_boleto_frete(frete_id, vencimento_str=None):
    """
    Função principal para emissão. Tenta várias variantes de body (configurável via EFI_TRY_VARIANTS).
    Retorna um dict com a mesma estrutura usada pela aplicação.
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

        if not frete.get("cliente_email"):
            return {"success": False, "error": "Cliente sem e-mail cadastrado"}

        if not frete.get("cliente_telefone"):
            return {"success": False, "error": "Cliente sem telefone cadastrado"}

        if not frete.get("cliente_cnpj"):
            return {"success": False, "error": "Cliente sem CNPJ cadastrado"}

        # Credenciais e cliente da lib
        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }
        efi = EfiPay(credentials)

        # vencimento
        if vencimento_str:
            try:
                data_vencimento = datetime.strptime(vencimento_str, "%Y-%m-%d")
            except Exception:
                return {"success": False, "error": "Formato de vencimento inválido (use YYYY-MM-DD)"}
        else:
            data_vencimento = datetime.now() + timedelta(days=7)

        # calcular valor em centavos
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

        bodies = _build_bodies(frete, descricao_frete, data_vencimento, valor_total_centavos)

        try_variants = os.getenv("EFI_TRY_VARIANTS", "true").lower() == "true"

        last_response = None
        attempted = 0

        for idx, body in enumerate(bodies):
            # if try_variants is False, try only the first variant
            if idx > 0 and not try_variants:
                break

            attempted += 1
            # log temporário — cuidado com dados pessoais. NÃO inclua client_secret.
            try:
                logger.info("Attempt %d - EFI create_charge body keys: %s", attempted, list(body.keys()))
            except Exception:
                logger.info("Attempt %d - EFI create_charge body: <unstringifiable>", attempted)

            # print also to ensure appearing in Render logs console
            print(f"EFI create_charge attempt={attempted} body_keys={list(body.keys())}")

            try:
                response = efi.create_charge(body=body)
                logger.info("EFI create_charge response (attempt=%d): %r", attempted, response)
                print(f"EFI create_charge response (attempt={attempted}): {response}")
            except Exception as ex:
                logger.exception("Exception ao chamar efi.create_charge attempt=%s frete_id=%s", attempted, frete_id)
                last_response = ex
                # if it's a network/timeout, optionally retry a couple times; here we continue to next variant
                continue

            last_response = response

            # If response is an Exception-like object, treat as error and continue
            if isinstance(response, Exception):
                continue

            # If provider returned explicit validation error about property, try next variant
            # Many providers return a dict with 'error'/'error_description' keys
            if isinstance(response, dict) and response.get("error") == "validation_error":
                # log and continue to next variant
                logger.warning("Provider validation_error on attempt=%d: %r", attempted, response.get("error_description"))
                # decide to try next variant
                continue

            # If response looks successful (contains data/charge), accept it
            if isinstance(response, dict) and ("data" in response or "charge" in response):
                charge_id, boleto_url, barcode = _safe_get_charge_fields(response)
                if not charge_id:
                    # maybe provider returned data but different structure; try next variant
                    logger.warning("charge_id ausente na resposta no attempt=%d: %r", attempted, response)
                    continue

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

            # otherwise, try next variant
            sleep(0.2)

        # se chegou aqui, todas as variantes falharam
        logger.error("Todas variantes testadas (%d) falharam. last_response=%r", attempted, last_response)
        # formatar mensagem de erro legível para UI
        if isinstance(last_response, dict):
            # prefer error_description if present
            if last_response.get("error_description"):
                err_desc = last_response.get("error_description")
                return {"success": False, "error": f"Resposta inválida do provedor de cobrança: {err_desc}"}
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
