"""
integrations/vendas_pagamentos_scheduler.py
===========================================

Agendador in-process (APScheduler) da leitura do pagamento de cada cupom no
XML da nota (pasta SAIDAS do Posto no Dropbox). Ver integrations/vendas_pagamentos.py.
Mesmo desenho do integrations/ofx_auto_scheduler.py.

Concorrência (gunicorn --workers N): cada worker cria o seu scheduler; o job
usa GET_LOCK global no MySQL para só UMA execução rodar por vez.

Liga/desliga por env (Railway):
    VENDAS_PAG_SCHED_ENABLED = '1' (default) | '0' para desligar
    VENDAS_PAG_SCHED_MINUTE  = minuto cron (default '8-59/10': fora dos
                               minutos do OFX e do cartão)
"""
import os
import threading

from utils.db import get_db_connection

_LOCK_NAME = "vendas_pagamentos"
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
        from integrations import vendas_pagamentos
        with app.app_context():
            r = vendas_pagamentos.processar()
        if r.get('erro') or r.get('lidos') or r.get('falhas'):
            logger.info("[vendas_pag] %s", r)
    except Exception:
        logger.exception("[vendas_pag] falha no job.")
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
    if os.environ.get("VENDAS_PAG_SCHED_ENABLED", "1") != "1":
        app.logger.info("[vendas_pag] desabilitado (VENDAS_PAG_SCHED_ENABLED != '1').")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[vendas_pag] APScheduler indisponível; scheduler NÃO iniciado.")
            return
        minuto = os.environ.get("VENDAS_PAG_SCHED_MINUTE", "8-59/10")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None
        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(minute=minuto, timezone=tz),
            id="vendas_pagamentos",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info("[vendas_pag] ligado: minuto '%s' (lock '%s').", minuto, _LOCK_NAME)
