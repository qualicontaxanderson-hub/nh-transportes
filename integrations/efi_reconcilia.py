"""
integrations/efi_reconcilia.py
==============================

Reconciliação com a EFI Pay: pergunta ao provedor quais boletos foram pagos,
liquidados ou cancelados no período e acerta a tabela `cobrancas`.

Por que existe fora da rota
---------------------------
Isto era o corpo de `financeiro.reconciliar_efi`, disparado por um botão. O
caminho normal deveria ser o webhook — a EFI avisa assim que o boleto é pago —
e a reconciliação seria só a rede de segurança. Mas o webhook depende de a EFI
conseguir alcançar o app, e isso pode falhar calado: URL errada, deploy fora
do ar na hora da notificação, notificação perdida.

Com a rotina aqui, o agendador (integrations/efi_scheduler.py) e o botão da
tela chamam exatamente o mesmo código.

Não duplica trabalho: só grava quando o status local está diferente do que a
EFI diz.
"""

import os
from datetime import date, timedelta

import requests

from utils.boletos import (_ensure_credentials_from_env, _get_bearer_token,
                           fetch_charge)
from utils.db import get_db_connection

_API_PROD = "https://cobrancas.api.efipay.com.br"
_API_HOMOLOG = "https://cobrancas-h.api.efipay.com.br"


class ErroEfi(Exception):
    """Falha ao falar com a EFI. `codigo` e `detalhe` viram resposta HTTP na rota."""

    def __init__(self, mensagem, codigo=None, detalhe=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.detalhe = detalhe


def _to_bool(valor, padrao=True):
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ('1', 'true', 't', 'yes', 'y', 'sim')


def credenciais(config=None):
    """Credenciais da EFI vindas do config do app ou do ambiente."""
    config = config or {}
    sandbox_raw = config.get("EFI_SANDBOX")
    if sandbox_raw is None:
        sandbox_raw = os.getenv("EFI_SANDBOX", "true")
    return _ensure_credentials_from_env({
        "client_id": config.get("EFI_CLIENT_ID") or os.getenv("EFI_CLIENT_ID"),
        "client_secret": config.get("EFI_CLIENT_SECRET") or os.getenv("EFI_CLIENT_SECRET"),
        "certificate": config.get("EFI_CERT_PATH") or os.getenv("EFI_CERT_PATH"),
        "sandbox": _to_bool(sandbox_raw, True),
    })


# Quais linhas do histórico são de fato o pagamento.
#
# O histórico começa na emissão, então pegar a primeira linha com data
# devolveria a data de EMISSÃO. E há um vizinho traiçoeiro: "Aguardando
# pagamento" contém "paga" dentro de "pagamento", e casaria com qualquer teste
# ingênuo — gravando a data em que o boleto passou a esperar como se fosse a
# data em que foi pago.
#
# Por isso a recusa vem antes da aceitação, e a varredura é de trás para a
# frente: vale a última linha que fala de pagamento consumado.
#
# Uma data errada aqui é pior do que nenhuma: some do radar e não bate com o
# extrato. Na dúvida, o campo fica em branco.
_RECUSA = ('aguard', 'waiting', 'pending', 'unpaid', 'nao pago', 'não pago')
_ACEITA = ('pago', 'paga', 'paid', 'liquidad', 'settled', 'baixad')


def _data_pagamento(charge):
    """Data em que o boleto foi pago, YYYY-MM-DD, ou None se não der para saber.

    Devolver None é um resultado legítimo: melhor a data em branco do que a
    data de emissão fazendo as vezes de data de pagamento.
    """
    if not isinstance(charge, dict):
        return None

    for chave in ("paid_at", "paidAt", "payment_date", "settled_at"):
        if charge.get(chave):
            return str(charge[chave])[:10]

    # O detalhe da cobrança aninha o pagamento em `payment`.
    pagamento = charge.get("payment")
    if isinstance(pagamento, dict):
        for chave in ("paid_at", "paidAt", "payment_date"):
            if pagamento.get(chave):
                return str(pagamento[chave])[:10]
        for sub in ("banking_billet", "credit_card", "pix"):
            bloco = pagamento.get(sub)
            if isinstance(bloco, dict):
                for chave in ("paid_at", "paidAt", "payment_date"):
                    if bloco.get(chave):
                        return str(bloco[chave])[:10]

    # Último recurso: a linha do histórico que fala de pagamento consumado.
    for h in reversed(charge.get("history") or []):
        if not isinstance(h, dict):
            continue
        texto = (str(h.get("message") or "") + " " + str(h.get("status") or "")).lower()
        if any(m in texto for m in _RECUSA):
            continue
        if any(m in texto for m in _ACEITA):
            quando = h.get("created_at") or h.get("date")
            if quando:
                return str(quando)[:10]
    return None


def _data_pagamento_completa(charge, charge_id, cred, logger):
    """A listagem da EFI não traz a data do pagamento — só o detalhe traz.

    Então, quando a listagem não sabe, buscamos o detalhe daquela cobrança. Só
    acontece para as que mudaram de status, não para a lista inteira.
    """
    quando = _data_pagamento(charge)
    if quando:
        return quando
    try:
        detalhe = fetch_charge(cred, charge_id)
        if isinstance(detalhe, dict):
            # O corpo útil às vezes vem embrulhado em "data".
            return _data_pagamento(detalhe.get("data") or detalhe)
    except Exception:
        if logger:
            logger.warning("[efi_recon] não deu para buscar o detalhe de %s", charge_id)
    return None


def inicio_que_cobre_abertos(dias_min=45, dias_max=365):
    """Desde quando perguntar à EFI, para não deixar boleto aberto fora do olhar.

    Uma janela fixa de N dias parece razoável até um boleto passar do prazo: a
    partir daí ele fica para trás da janela e o agendador nunca mais pergunta
    por ele. Foi o que aconteceu com três boletos de maio e junho.

    Então a janela se estica sozinha até alcançar a cobrança em aberto mais
    antiga, com teto para a consulta não crescer sem fim. Quando tudo está em
    dia, ela encolhe de volta para o mínimo.
    """
    piso = date.today() - timedelta(days=dias_min)
    teto = date.today() - timedelta(days=dias_max)
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT MIN(data_emissao) FROM cobrancas"
            " WHERE status NOT IN ('pago','cancelado') AND charge_id IS NOT NULL"
        )
        row = cur.fetchone()
        mais_antiga = row[0] if row else None
    except Exception:
        mais_antiga = None
    finally:
        for c in (cur, conn):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass

    if not mais_antiga:
        return piso.isoformat()
    return max(min(mais_antiga, piso), teto).isoformat()


def _buscar(base, headers, situacao, begin_date, end_date, logger):
    """Todas as páginas de cobranças da EFI para uma situação."""
    achados = []
    page = 1
    while True:
        params = {
            "charge_type": "billet",
            "status": situacao,
            "begin_date": begin_date,
            "end_date": end_date,
            "limit": 100,
            "page": page,
        }
        r = requests.get(base + "/v1/charges", headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            if logger:
                logger.error("[efi_recon] %s ao buscar status=%s: %s",
                             r.status_code, situacao, r.text[:600])
            raise ErroEfi("EFI Pay retornou %s ao buscar status=%s." % (r.status_code, situacao),
                          codigo=r.status_code, detalhe=r.text[:300])
        dados = r.json()
        pagina = dados.get("data") or []
        achados.extend(pagina)
        paginacao = dados.get("paginate") or {}
        if page >= int(paginacao.get("totalPages") or 1) or not pagina:
            break
        page += 1
    return achados


def reconciliar(begin_date=None, end_date=None, config=None, logger=None):
    """Acerta `cobrancas` com o que a EFI diz. Devolve um resumo.

    Levanta ErroEfi quando não dá para falar com o provedor — quem chamou
    decide se isso vira 502 na tela ou linha de log no agendador.
    """
    begin_date = begin_date or (date.today() - timedelta(days=90)).isoformat()
    end_date = end_date or date.today().isoformat()

    cred = credenciais(config)
    base = _API_HOMOLOG if cred.get("sandbox", True) else _API_PROD

    token = _get_bearer_token(cred)
    if not token:
        raise ErroEfi("Não foi possível obter token EFI Pay. Verifique as credenciais.")

    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}

    pagos = _buscar(base, headers, "paid", begin_date, end_date, logger)
    liquidados = _buscar(base, headers, "settled", begin_date, end_date, logger)
    cancelados = _buscar(base, headers, "canceled", begin_date, end_date, logger)

    if logger:
        logger.info("[efi_recon] EFI: paid=%d settled=%d canceled=%d (%s -> %s)",
                    len(pagos), len(liquidados), len(cancelados), begin_date, end_date)

    atual_pagos, atual_cancelados, ja_corretos, nao_encontrados = [], [], [], []
    sem_data = []   # baixados sem data: some do radar se ninguém contar

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for charge in (pagos + liquidados):
            charge_id = str(charge.get("id") or charge.get("charge_id") or "").strip()
            if not charge_id:
                continue
            cur.execute("SELECT id, status FROM cobrancas WHERE charge_id = %s LIMIT 1",
                        (charge_id,))
            row = cur.fetchone()
            if not row:
                nao_encontrados.append(charge_id)
                continue
            if (row.get("status") or "").lower() == "pago":
                ja_corretos.append(charge_id)
                continue
            quando = _data_pagamento_completa(charge, charge_id, cred, logger)
            if quando is None:
                sem_data.append(charge_id)
            cur.execute(
                "UPDATE cobrancas SET status = 'pago', pago_via_provedor = 1,"
                " data_pagamento = %s WHERE charge_id = %s",
                (quando, charge_id),
            )
            conn.commit()
            atual_pagos.append(charge_id)
            if logger:
                logger.info("[efi_recon] pago charge_id=%s", charge_id)

        for charge in cancelados:
            charge_id = str(charge.get("id") or charge.get("charge_id") or "").strip()
            if not charge_id:
                continue
            cur.execute("SELECT id, status FROM cobrancas WHERE charge_id = %s LIMIT 1",
                        (charge_id,))
            row = cur.fetchone()
            if not row:
                nao_encontrados.append(charge_id)
                continue
            if (row.get("status") or "").lower() == "cancelado":
                ja_corretos.append(charge_id)
                continue
            if (row.get("status") or "").lower() == "pago":
                # Recebido por fora (Pix etc.): baixa manual + boleto
                # cancelado na EFI de proposito. O cancelamento de la NAO
                # pode apagar o pago daqui.
                ja_corretos.append(charge_id)
                continue
            cur.execute(
                "UPDATE cobrancas SET status = 'cancelado', data_cancelamento = NOW()"
                " WHERE charge_id = %s",
                (charge_id,),
            )
            conn.commit()
            atual_cancelados.append(charge_id)
            if logger:
                logger.info("[efi_recon] cancelado charge_id=%s", charge_id)
    finally:
        for c in (cur, conn):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass

    return {
        "periodo": {"begin_date": begin_date, "end_date": end_date},
        "total_efi": len(pagos) + len(liquidados) + len(cancelados),
        "atualizados_pagos": len(atual_pagos),
        "atualizados_cancelados": len(atual_cancelados),
        "ja_corretos": len(ja_corretos),
        "nao_encontrados": len(nao_encontrados),
        "sem_data_pagamento": len(sem_data),
    }
