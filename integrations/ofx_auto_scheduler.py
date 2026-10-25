"""
integrations/ofx_auto_scheduler.py
==================================

Agendador in-process (APScheduler) da importação automática dos extratos OFX
que caem em /BANCOS/OFX/NOVO no Dropbox. Ver integrations/ofx_auto.py.
Mesmo desenho do integrations/cartao_arquivo_scheduler.py.

Concorrência (gunicorn --workers N): cada worker cria o seu scheduler; o job
usa GET_LOCK global no MySQL para só UMA execução rodar por vez.

Liga/desliga por env (Railway):
    OFX_AUTO_SCHED_ENABLED = '1' (default) | '0' para desligar
    OFX_AUTO_SCHED_MINUTE  = minuto cron (default '5-59/10': fora do minuto
                             do agendador do cartão, que usa a mesma pasta)
"""
import os
import threading

from utils.db import get_db_connection

_LOCK_NAME = "ofx_auto_import"
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
            return
        from integrations import ofx_auto
        with app.app_context():
            feitos = ofx_auto.processar()
        for nome, situacao, inseridos, msg in feitos:
            logger.info("[ofx_auto] %s: %s, %s inserido(s)%s", nome, situacao, inseridos,
                        f" — {msg}" if msg else "")
    except Exception:
        logger.exception("[ofx_auto] falha no job.")
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
    """Liga o APScheduler (idempotente por processo). Chamar em create_app()."""
    global _started
    if os.environ.get("OFX_AUTO_SCHED_ENABLED", "1") != "1":
        app.logger.info("[ofx_auto] desabilitado (OFX_AUTO_SCHED_ENABLED != '1').")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[ofx_auto] APScheduler indisponível; scheduler NÃO iniciado.")
            return
        minuto = os.environ.get("OFX_AUTO_SCHED_MINUTE", "5-59/10")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None
        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(minute=minuto, timezone=tz),
            id="ofx_auto_import",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info("[ofx_auto] ligado: minuto '%s' (lock '%s').", minuto, _LOCK_NAME)
