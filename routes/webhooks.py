from flask import Blueprint, request, current_app, jsonify
from utils.db import get_db_connection
from utils.boletos import fetch_boleto_pdf_stream, BOLETOS_DIR
import os
import time

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='')

@webhooks_bp.route('/webhooks/efi', methods=['POST'])
def webhooks_efi():
    """
    Recebe notificações (webhook) do provedor Efí (EFI).
    Espera JSON com payload que contém 'data' ou corpo com fields como:
      - data.id or data.charge_id
      - data.payment.banking_billet.link  (link do boleto / PDF)
      - data.pdf.charge  (ou data.link)
      - data.status (status da charge)
      - data.paid_at / data.paid (opcional)
    A ação:
      - atualiza a linha na tabela cobrancas WHERE charge_id = ?
      - salva link_boleto com a URL do provedor se encontrada
      - tenta baixar e salvar o PDF em BOLETOS_DIR (opcional), grava pdf_boleto com o path salvo
      - atualiza status/data_pagamento quando aplicável
    Retorna 200 sempre que receber o webhook (não expõe detalhes ao provedor).
    """
    try:
        j = request.get_json(silent=True)
        current_app.logger.info("[webhook/efi] recebido payload keys=%s", list(j.keys()) if isinstance(j, dict) else type(j))
        if not j:
            current_app.logger.warning("[webhook/efi] payload vazio ou inválido")
            return jsonify({"ok": False, "error": "invalid json"}), 400

        # padrão: payload pode vir em { "data": { ... } } ou direto
        data = j.get('data') if isinstance(j, dict) and 'data' in j else j
        if not isinstance(data, dict):
            current_app.logger.warning("[webhook/efi] payload.data não é dict")
            return jsonify({"ok": False}), 200

        # extrair charge_id (várias formas)
        charge_id = None
        for k in ('id', 'charge_id', 'chargeId'):
            v = data.get(k)
            if v:
                charge_id = v
                break
        if not charge_id:
            # também checar em top-level do payload
            for k in ('id', 'charge_id', 'chargeId'):
                v = j.get(k) if isinstance(j, dict) else None
                if v:
                    charge_id = v
                    break

        # extrair possíveis URLs de boleto/pdf
        pdf_url = None
        try:
            pdf_obj = data.get('pdf') or {}
            pdf_url = pdf_obj.get('charge') or pdf_obj.get('boleto') or data.get('link') or data.get('billet_link')
            if not pdf_url:
                pb = (data.get('payment') or {}).get('banking_billet') or {}
                pdf_url = pb.get('link') or pb.get('pdf') or pb.get('boleto')
        except Exception:
            pdf_url = None

        status = data.get('status') or None

        # conectar ao banco e atualizar registro se charge_id estiver presente
        if charge_id:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                # se tivermos pdf_url e for uma URL, tentamos baixar e salvar (não bloqueante demais)
                saved_path = None
                if pdf_url and isinstance(pdf_url, str) and (pdf_url.startswith('http://') or pdf_url.startswith('https://')):
                    try:
                        # montar credenciais para fetch_boleto_pdf_stream baseadas em env (igual ao resto do app)
                        credentials = {
                            "client_id": current_app.config.get("EFI_CLIENT_ID") or os.getenv("EFI_CLIENT_ID"),
                            "client_secret": current_app.config.get("EFI_CLIENT_SECRET") or os.getenv("EFI_CLIENT_SECRET"),
                            "sandbox": current_app.config.get("EFI_SANDBOX", True),
                        }
                        resp = fetch_boleto_pdf_stream(credentials, pdf_url)
                        if resp is not None and getattr(resp, "status_code", None) == 200:
                            # garantir dir
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
                                saved_path = None
                        else:
                            current_app.logger.info("[webhook/efi] fetch_boleto_pdf_stream retornou status=%s para url=%s", getattr(resp, "status_code", None) if resp else None, pdf_url)
                    except Exception:
                        current_app.logger.exception("[webhook/efi] erro tentando baixar pdf_url para charge %s", charge_id)

                # montar update dinamicamente
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
                # se payload indicar pagamento, tentar setar data_pagamento/status pago
                # alguns providers informam paid_at or paid
                paid_at = data.get('paid_at') or data.get('paidAt') or data.get('paid') or None
                if paid_at:
                    updates.append("status = %s")
                    params.append('pago')
                    try:
                        # armazena data_pagamento se o campo existir
                        updates.append("data_pagamento = %s")
                        # tenta normalizar para date (se for timestamp/string)
                        params.append(str(paid_at)[:10])
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
        else:
            current_app.logger.warning("[webhook/efi] charge_id não encontrado no webhook payload")

        # responder 200 OK para o provedor
        return jsonify({"ok": True}), 200

    except Exception:
        current_app.logger.exception("[webhook/efi] exceção gerando resposta")
        # para o provedor, retornamos 200 mesmo em erro para não ficar em retry infinito,
        # mas logamos a exceção para investigação.
        return jsonify({"ok": False}), 200
