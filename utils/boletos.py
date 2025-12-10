import os
from datetime import datetime, timedelta
from efipay import EfiPay
from utils.db import get_db_connection


def emitir_boleto_frete(frete_id):
    """
    Emite um boleto via Efí (antiga Gerencianet) para um frete específico.

    Retorna:
        dict: {
          "success": True/False,
          "error": str (quando success=False),
          "cobranca_id": int,
          "charge_id": str,
          "boleto_url": str,
          "barcode": str
        }
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Buscar dados do frete e cliente (nomes/colunas atualizados)
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

        # Credenciais Efí
        credentials = {
            "client_id": os.getenv("EFI_CLIENT_ID"),
            "client_secret": os.getenv("EFI_CLIENT_SECRET"),
            "certificate": os.getenv("EFI_CERT_PATH"),
            "sandbox": os.getenv("EFI_SANDBOX", "true").lower() == "true",
        }
        efi = EfiPay(credentials)

        data_vencimento = datetime.now() + timedelta(days=7)

        # Normalizações
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

        valor_total_centavos = int(
            float(frete["valor_total_frete"] or 0) * 100
        )
        if valor_total_centavos <= 0:
            return {
                "success": False,
                "error": "Valor do frete inválido ou zerado",
            }

        body = {
            "payment": {
                "banking_billet": {
                    "expire_at": data_vencimento.strftime("%Y-%m-%d"),
                    "customer": {
                        "name": nome_cliente[:80],
                        "cpf": cpf_cnpj if len(cpf_cnpj) == 11 else None,
                        "cnpj": cpf_cnpj if len(cpf_cnpj) == 14 else None,
                        "phone_number": telefone[:11],
                        "email": frete["cliente_email"][:50],
                        "address": {
                            "street": (frete.get("cliente_endereco") or "Rua Exemplo")[
                                :80
                            ],
                            "number": (frete.get("cliente_numero") or "SN")[:10],
                            "neighborhood": (
                                frete.get("cliente_bairro") or "Centro"
                            )[:50],
                            "zipcode": cep,
                            "city": (frete.get("cliente_cidade") or "Goiania")[:50],
                            "state": (frete.get("cliente_estado") or "GO")[
                                :2
                            ].upper(),
                        },
                    },
                }
            },
            "items": [
                {
                    "name": descricao_frete[:80],
                    "amount": 1,
                    "value": valor_total_centavos,
                }
            ],
            "metadata": {
                "custom_id": str(frete_id),
                "notification_url": os.getenv(
                    "EFI_NOTIFICATION_URL",
                    "https://nh-transportes.onrender.com/webhooks/efi",
                ),
            },
        }

        response = efi.create_charge(body=body)

        charge_id = response["data"]["charge_id"]
        boleto_url = response["data"]["payment"]["banking_billet"]["link"]
        barcode = response["data"]["payment"]["banking_billet"]["barcode"]

        # Gravar em COBRANCAS (schema atual)
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
        cobranca_id = cursor.lastrowid

        conn.commit()

        return {
            "success": True,
            "cobranca_id": cobranca_id,
            "charge_id": charge_id,
            "boleto_url": boleto_url,
            "barcode": barcode,
        }

    except Exception as e:
        conn.rollback()
        # Convert exception to string - handles all exception types properly
        return {"success": False, "error": str(e)}
    finally:
        cursor.close()
        conn.close()
