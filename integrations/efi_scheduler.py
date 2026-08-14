"""
integrations/efi_scheduler.py
=============================

Agendador in-process (APScheduler) da baixa automática dos boletos da EFI Pay.

Por que ele existe
------------------
A baixa deveria chegar sozinha pelo webhook (`/webhooks/efi`): a EFI avisa
assim que o boleto é pago. Só que o webhook falha calado — a URL de aviso é
gravada em CADA cobrança no momento da emissão, então basta ela estar errada
uma vez para os boletos daquele lote nunca avisarem, e ninguém percebe até
alguém reparar que o extrato não bate. Foi exatamente o que aconteceu: a URL
apontava para o servidor antigo, que saiu do ar.

Este agendador é a rede de segurança. Ele pergunta à EFI, de tempos em tempos,
quais boletos foram pagos ou cancelados, e acerta o banco. Se o webhook estiver
funcionando, ele não acha nada para fazer e sai barato.

Concorrência (gunicorn --workers N): cada worker cria o seu scheduler, então o
job usa GET_LOCK global no MySQL para que só UMA execução rode por vez.

Liga/desliga por env (configurar no Railway):
    EFI_SCHED_ENABLED = '1' (default) | '0' para desligar
    EFI_SCHED_MINUTE  = minuto cron (default '7,37' = duas vezes por hora)
    EFI_SCHED_HOURS   = horas cron (default '6-22' = ao longo do dia)
    EFI_SCHED_DIAS    = quantos dias para trás consultar (default 45)

Chamar iniciar_scheduler(app) dentro de create_app(), como já é feito com o
dfe_scheduler e o els_scheduler.
"""

import os
import threading
from datetime import date, timedelta

from utils.db import get_db_connection

_LOCK_NAME = "efi_reconcilia"
_started = False
_started_lock = threading.Lock()


def _job(app):
    from integrations.efi_reconcilia import ErroEfi, reconciliar

    logger = app.logger
    conn = cur = None
    got = 0
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT GET_LOCK(%s, 0)", (_LOCK_NAME,))
        row = cur.fetchone()
        got = row[0] if row else 0
        if got != 1:
            logger.info("[efi_sched] outro worker já está reconciliando; pulando.")
            return

        try:
            dias = int(os.environ.get("EFI_SCHED_DIAS", "45"))
        except ValueError:
            dias = 45

        with app.app_context():
            resumo = reconciliar(
                begin_date=(date.today() - timedelta(days=dias)).isoformat(),
                end_date=date.today().isoformat(),
                config=app.config,
                logger=logger,
            )

        # Só faz barulho quando mexeu em alguma coisa: rodando de meia em meia
        # hora, registrar "nada a fazer" enterraria o log.
        if resumo["atualizados_pagos"] or resumo["atualizados_cancelados"]:
            logger.info("[efi_sched] baixa automática: %d pago(s), %d cancelado(s).",
                        resumo["atualizados_pagos"], resumo["atualizados_cancelados"])
    except ErroEfi as e:
        logger.warning("[efi_sched] EFI não respondeu: %s", e.mensagem)
    except Exception:
        logger.exception("[efi_sched] falha no job de reconciliação EFI.")
    finally:
        try:
            if got == 1 and cur is not None:
                cur.execute("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))
                cur.fetchall()
        except Exception:
            pass
        for c in (cur, conn):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


def iniciar_scheduler(app):
    """Liga o APScheduler da EFI (idempotente por processo). Chamar em create_app()."""
    global _started
    if os.environ.get("EFI_SCHED_ENABLED", "1") != "1":
        app.logger.info("[efi_sched] desabilitado (EFI_SCHED_ENABLED != '1').")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[efi_sched] APScheduler indisponível; scheduler NÃO iniciado.")
            return

        minuto = os.environ.get("EFI_SCHED_MINUTE", "7,37")
        horas = os.environ.get("EFI_SCHED_HOURS", "6-22")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None

        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(hour=horas, minute=minuto, timezone=tz),
            id="efi_reconcilia",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )
        sched.start()
        _started = True
        app.logger.info(
            "[efi_sched] ligado: baixa automática nas horas '%s' minuto '%s' "
            "(America/Sao_Paulo, lock '%s').", horas, minuto, _LOCK_NAME,
        )


def disparar_async(app):
    """Dispara UMA reconciliação AGORA em background (mesma rotina do agendador)."""
    t = threading.Thread(target=_job, args=(app,), name="efi-recon-manual", daemon=True)
    t.start()
    return t
