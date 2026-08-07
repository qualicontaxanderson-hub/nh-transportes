"""
integrations/els_scheduler.py
=============================

Agendador in-process (APScheduler) da importação automática do ELS por e-mail.

Roda a cada N minutos (default 10, horário de Brasília) chamando
integrations.els_email.processar(), que lê os e-mails NÃO LIDOS do ELS
(ABERTURA -> leitura diária; Alarme descarga -> entrada/descarga) e grava no
banco. Como só processa e-mails não lidos e os marca como lidos, rodar de 10 em
10 min não duplica nada e garante que a ABERTURA das 05:00 entre até ~05:10.

Concorrência (gunicorn --workers N): cada worker cria o seu scheduler, então o
job usa GET_LOCK global no MySQL para que só UMA execução rode por vez.

Liga/desliga por env (configurar no Render):
    ELS_SCHED_ENABLED = '1' (default) | '0' para desligar
    ELS_SCHED_MINUTE  = minuto cron (default '*/10' = a cada 10 min)
    ELS_SCHED_HOURS   = horas cron (default '*' = toda hora)

Chamar iniciar_scheduler(app) dentro de create_app(), como já é feito com o
dfe_scheduler.
"""
import os
import threading

from utils.db import get_db_connection
from integrations import els_email

_LOCK_NAME = "els_email_import"
_started = False
_started_lock = threading.Lock()


def _job(app):
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
            logger.info("[els_sched] outro worker já está importando; pulando.")
            return
        resumo = els_email.processar(dias=1)
        if resumo and any(v for k, v in resumo.items() if k != "ignorados"):
            logger.info("[els_sched] importação ELS: %s", resumo)
    except Exception:
        logger.exception("[els_sched] falha no job de importação ELS.")
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
    """Liga o APScheduler do ELS (idempotente por processo). Chamar em create_app()."""
    global _started
    if os.environ.get("ELS_SCHED_ENABLED", "1") != "1":
        app.logger.info("[els_sched] desabilitado (ELS_SCHED_ENABLED != '1').")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[els_sched] APScheduler indisponível; scheduler NÃO iniciado.")
            return

        minuto = os.environ.get("ELS_SCHED_MINUTE", "*/10")
        horas = os.environ.get("ELS_SCHED_HOURS", "*")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None

        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(hour=horas, minute=minuto, timezone=tz),
            id="els_email_import",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info(
            "[els_sched] ligado: importação ELS nas horas '%s' minuto '%s' "
            "(America/Sao_Paulo, lock '%s').", horas, minuto, _LOCK_NAME,
        )


def disparar_async(app):
    """Dispara UMA importação AGORA em background (mesma rotina do agendador)."""
    t = threading.Thread(target=_job, args=(app,), name="els-import-manual", daemon=True)
    t.start()
    return t
