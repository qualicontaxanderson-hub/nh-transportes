import os
from decimal import Decimal
from datetime import datetime, timedelta
import pymysql
from efipay import EfiPay
from utils.db import get_db_connection  # se quiser usar aqui também


def get_efi_client(conn=None):
    """
    Monta o cliente EfiPay usando variáveis de ambiente.
    Se preferir, pode buscar dados de uma tabela de configuração.
    """
    options = {
        "client_id": os.environ.get("EFI_CLIENT_ID"),
        "client_secret": os.environ.get("EFI_CLIENT_SECRET"),
        "certificate": os.environ.get("EFI_CERT_PATH"),
        "sandbox": os.environ.get("EFI_SANDBOX", "true").lower() == "true"
    }
    efi = EfiPay(options)
    # se futuramente quiser usar webhook, coloque a URL real aqui
    url_callback = os.environ.get("EFI_NOTIFICATION_URL", "")
    return efi, url_callback


def emitir_boleto_frete(conn, frete_id):
    """
    Emite um boleto no EFI para um frete específico.
    Grava na tabela cobrancas e retorna (id_cobranca, link_boleto).
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # 1. Buscar frete + cliente
    cursor.execute(
        """
        SELECT
            f.id AS frete_id,
            f.data_frete,
            f.valor_total_frete,
            f.clientes_id,
            c.razao_social,
            c.nome_fantasia,
            c.cnpj,
            c.email,
            c.telefone,
            c.endereco,
            c.numero,
            c.bairro,
            c.municipio,
            c.uf,
            c.cep
        FROM fretes f
        JOIN clientes c ON c.id = f.clientes_id
        WHERE f.id = %s
        LIMIT 1
        """,
        (frete_id,)
    )
    frete = cursor.fetchone()

    if not frete:
        raise Exception(f"Frete {frete_id} não encontrado.")
    if not frete["valor_total_frete"]:
        raise Exception("Frete sem valor_total_frete definido; não é possível emitir boleto.")

    # normalizações
    cnpj_limpo = "".join(filter(str.isdigit, frete["cnpj"] or ""))
    telefone_numeros = "".join(filter(str.isdigit, frete["telefone"] or ""))
    if len(telefone_numeros) < 10:
        telefone_numeros = ""
    cep_numeros = "".join(filter(str.isdigit, frete["cep"] or ""))
    if len(cep_numeros) != 8:
        cep_numeros = ""
    cidade = frete["municipio"] or ""

    valor = Decimal(str(frete["valor_total_frete"]))
    data_vencimento = datetime.today().date() + timedelta(days=3)

    # 2. Criar cobrança local
    cursor2 = conn.cursor()
    cursor2.execute(
        """
        INSERT INTO cobrancas (id_cliente, valor, data_vencimento, status, data_emissao)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (
            frete["clientes_id"],
            int(valor),
            data_vencimento,
            "pendente",
            datetime.now().date()
        )
    )
    cobranca_id = cursor2.lastrowid
    conn.commit()

    # 3. Cliente EFI
    efi, url_callback = get_efi_client(conn)

    nome_exibicao = frete["nome_fantasia"] or frete["razao_social"]

    body = {
        "items": [
            {
                "name": f"Frete {frete['frete_id']}",
                "value": int(valor * 100),
                "amount": 1
            }
        ],
        "payment": {
            "banking_billet": {
                "expire_at": data_vencimento.strftime("%Y-%m-%d"),
                "customer": {
                    "name": nome_exibicao,
                    "juridical_person": {
                        "corporate_name": frete["razao_social"],
                        "cnpj": cnpj_limpo
                    },
                    "email": frete["email"],
                    "phone_number": telefone_numeros,
                    "address": {
                        "street": frete["endereco"],
                        "number": frete["numero"],
                        "neighborhood": frete["bairro"],
                        "zipcode": cep_numeros,
                        "city": cidade,
                        "state": frete["uf"]
                    }
                }
            }
        },
        "metadata": {
            "custom_id": str(cobranca_id)
        }
    }

    # 4. Chamada EFI
    response = efi.create_one_step_charge(params=None, body=body)

    if isinstance(response, dict):
        data = response.get("data", response)
    else:
        raise response

    charge_id = data.get("charge_id")
    link_boleto = data.get("billet_link") or data.get("link")
    pdf_boleto = None
    if isinstance(data.get("pdf"), dict):
        pdf_boleto = data["pdf"].get("charge")
    status_api = data.get("status", "emitido")

    # 5. Atualizar cobrança
    cursor2.execute(
        """
        UPDATE cobrancas
        SET charge_id = %s,
            link_boleto = %s,
            pdf_boleto = %s,
            status = %s
        WHERE id = %s
        """,
        (
            charge_id,
            link_boleto,
            pdf_boleto,
            status_api,
            cobranca_id
        )
    )
    conn.commit()

    cursor.close()
    cursor2.close()

    return cobranca_id, link_boleto
