import os
from datetime import datetime, timedelta
import logging
from efipay import EfiPay
from utils.db import get_db_connection

logger = logging.getLogger(__name__)


def _safe_get_charge_fields(response):
    """
    Tenta extrair charge_id, boleto_url e barcode de formas comuns na resposta.
    Suporta 'payment' como dict ou 'payments' como lista.
    """
    if not response or not isinstance(response, dict):
        return None, None, None

    data = response.get('data') or response.get('charge') or {}
    # charge id
    charge_id = data.get('charge_id') or data.get('id') or response.get('data', {}).get('id')

    # payment pode ser dict ou list
    payment = data.get('payment') or data.get('payments') or {}
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
            (p.get('banking_billet') or {}).get('link')
            or p.get('link')
            or (response.get('data') or {}).get('banking_billet', {}).get('link')
        )
        barcode = (
            (p.get('banking_billet') or {}).get('barcode')
            or p.get('barcode')
            or (response.get('data') or {}).get('banking_billet', {}).get('barcode')
        )
    except Exception:
        logger.debug("Falha tentando extrair boleto/payment fields: %r", payment)
    return charge_id, boleto_url, barcode


def emitir_boleto_frete(frete_id, vencimento_str=None):
    """
    Emite um boleto via Efí para um frete específico.
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

        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }
        efi = EfiPay(credentials)

        if vencimento_str:
            try:
                data_vencimento = datetime.strptime(vencimento_str, "%Y-%m-%d")
            except Exception:
                return {"success": False, "error": "Formato de vencimento inválido (use YYYY-MM-DD)"}
        else:
            data_vencimento = datetime.now() + timedelta(days=7)

        cpf_cnpj = (
            frete["cliente_cnpj"]
            .replace(".", "")
            .replace("-", "")
            .replace("/", "")
            .strip()
        )
        telefone = (
            frete["cliente_telefone"]
            .replace("(", "")
            .replace(")", "")
            .replace("-", "")
            .replace(" ", "")
            .strip()
        )
        cep = (frete.get("cliente_cep") or "").replace("-", "").strip()
        if not cep or len(cep) != 8:
            cep = "74000000"

        nome_cliente = (
            frete.get("cliente_fantasia")
            or frete.get("cliente_nome")
            or "Cliente"
        )

        descricao_frete = f"Frete #{frete['id']}"
        if frete.get("origem_nome") and frete.get("destino_nome"):
            descricao_frete += f" - {frete['origem_nome']} para {frete['destino_nome']}"

        try:
            valor_total_centavos = int(float(frete["valor_total_frete"] or 0) * 100)
        except Exception:
            logger.exception("valor_total_frete inválido para frete_id=%s: %r", frete_id, frete.get("valor_total_frete"))
            return {"success": False, "error": "Valor do frete inválido ou zerado"}

        if valor_total_centavos <= 0:
            return {"success": False, "error": "Valor do frete inválido ou zerado"}

        # --> ALTERAÇÃO: usar 'payments' como lista (schema esperado por muitas APIs)
        body = {
            "payments": [
                {
                    "banking_billet": {
                        "expire_at": data_vencimento.strftime("%Y-%m-%d"),
                        "customer": {
                            "name": nome_cliente[:80],
                            "cpf": cpf_cnpj if len(cpf_cnpj) == 11 else None,
                            "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None,
                            "phone_number": telefone[:11],
                            "email": frete["cliente_email"][:50],
                            "address": {
                                "street": (frete.get("cliente_endereco") or "Rua Exemplo")[:80],
                                "number": (frete.get("cliente_numero") or "SN")[:10],
                                "neighborhood": (frete.get("cliente_bairro") or "Centro")[:50],
                                "zipcode": cep,
                                "city": (frete.get("cliente_cidade") or "Goiania")[:50],
                                "state": (frete.get("cliente_estado") or "GO")[:2].upper(),
                            },
                        },
                    }
                }
            ],
            "items": [
                {
                    "name": descricao_frete[:80],
                    "amount": 1,
                    "value": valor_total_centavos,
                }
            ],
            "metadata": {
                "custom_id": str(frete_id),
                "notification_url": os.getenv("EFI_NOTIFICATION_URL", "https://nh-transportes.onrender.com/webhooks/efi"),
            },
        }

        # Logs temporários para depuração (remova após confirmar que funciona)
        try:
            logger.debug("EFI create_charge body: %s", body)
        except Exception:
            logger.debug("EFI create_charge body: <failed to stringify>")

        try:
            response = efi.create_charge(body=body)
            logger.debug("EFI create_charge response: %r", response)
        except Exception as ex:
            logger.exception("Exception ao chamar efi.create_charge for frete_id=%s", frete_id)
            return {"success": False, "error": str(ex)}

        if isinstance(response, Exception):
            logger.exception("create_charge retornou um objeto de exceção para frete_id=%s: %r", frete_id, response)
            try:
                msg = getattr(response, 'message', None) or str(response)
            except Exception:
                msg = repr(response)
            return {"success": False, "error": f"Erro do provedor: {msg}"}

        if not isinstance(response, dict) or ('data' not in response and 'charge' not in response):
            logger.error("Resposta inválida ao criar charge: %r", response)
            return {"success": False, "error": "Resposta inválida do provedor de cobrança"}

        charge_id, boleto_url, barcode = _safe_get_charge_fields(response)

        if not charge_id:
            logger.error("charge_id ausente na resposta: %r", response)
            return {"success": False, "error": "Charge ID ausente na resposta do provedor"}

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
            cobranca_id = getattr(cursor, 'lastrowid', None)
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
