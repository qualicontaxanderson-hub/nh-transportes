"""
integrations/pix_scheduler.py
=============================

Agendador in-process (APScheduler) da leitura dos comprovantes de PIX enviado
por e-mail — o mesmo desenho do integrations/els_scheduler.py.

Roda a cada N minutos (default 5) chamando integrations.pix_email.processar(),
que lê os avisos NÃO LIDOS do banco e marca, na solicitação de Troco PIX, que o
dinheiro já saiu — e a que horas. Não concilia nada: isso continua sendo do
usuário, com o OFX do dia seguinte.

Cinco minutos, e não dez como o ELS: o aviso do banco chega no instante do PIX,
e quem está na tela quer ver logo que o troco saiu. Como só lê e-mail não lido
e só marca como lido depois de gravar, rodar de 5 em 5 não duplica nada.

Concorrência (gunicorn --workers N): cada worker cria o seu scheduler, então o
job usa GET_LOCK global no MySQL para que só UMA execução rode por vez.

A caixa e a mesma do ELS (os avisos da Cora chegam junto com o sistema de
medicao), entao nao ha nada a configurar para ele comecar a rodar.

Liga/desliga por env (configurar no Railway):
    PIX_SCHED_ENABLED = '1' (default) | '0' para desligar
    PIX_SCHED_MINUTE  = minuto cron (default '*/5')
    PIX_SCHED_HOURS   = horas cron (default '*')
"""
import os
import threading

from utils.db import get_db_connection
from integrations import pix_email

_LOCK_NAME = "pix_email_import"
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
            logger.info("[pix_sched] outro worker já está lendo; pulando.")
            return
        resumo = pix_email.processar(dias=2)
        if resumo and any(v for k, v in resumo.items() if k not in ("ignorados", "lidos")):
            logger.info("[pix_sched] comprovantes de PIX: %s", resumo)
    except Exception:
        logger.exception("[pix_sched] falha ao ler os comprovantes de PIX.")
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
    """Liga o APScheduler do PIX (idempotente por processo). Chamar em create_app()."""
    global _started
    if os.environ.get("PIX_SCHED_ENABLED", "1") != "1":
        app.logger.info("[pix_sched] desabilitado (PIX_SCHED_ENABLED != '1').")
        return
    if not pix_email.caixa_configurada():
        # Sem caixa nao ha o que ler; ligar o job so encheria o log de aviso a
        # cada 5 minutos. Caixa aqui e a do PIX ou a herdada do ELS — os
        # avisos da Cora chegam na mesma que ja recebe o sistema de medicao.
        app.logger.info("[pix_sched] sem caixa configurada (PIX_MAIL_* nem "
                        "ELS_MAIL_*); scheduler não iniciado.")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[pix_sched] APScheduler indisponível; scheduler NÃO iniciado.")
            return

        minuto = os.environ.get("PIX_SCHED_MINUTE", "*/5")
        horas = os.environ.get("PIX_SCHED_HOURS", "*")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None

        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(hour=horas, minute=minuto, timezone=tz),
            id="pix_email_import",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info(
            "[pix_sched] ligado: comprovantes de PIX nas horas '%s' minuto '%s' "
            "(America/Sao_Paulo, lock '%s').", horas, minuto, _LOCK_NAME,
        )


def disparar_async(app):
    """Dispara UMA leitura AGORA em background (mesma rotina do agendador)."""
    t = threading.Thread(target=_job, args=(app,), name="pix-import-manual", daemon=True)
    t.start()
    return t
