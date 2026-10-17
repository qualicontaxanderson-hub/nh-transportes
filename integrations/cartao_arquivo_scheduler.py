"""
integrations/cartao_arquivo_scheduler.py
========================================

Agendador in-process (APScheduler) da leitura dos arquivos das operadoras de
cartao (hoje: X7 BANK) que o NH-Robo deixa em /BANCOS/OFX/NOVO no Dropbox.
Ver utils/cartao_arquivo.py.

Concorrencia (gunicorn --workers N): cada worker cria o seu scheduler, entao o
job usa GET_LOCK global no MySQL para que so UMA execucao rode por vez.

Liga/desliga por env (configurar no Railway):
    CARTAO_ARQ_SCHED_ENABLED = '1' (default) | '0' para desligar
    CARTAO_ARQ_SCHED_MINUTE  = minuto cron (default '*/10')
"""
import os
import threading

from utils.db import get_db_connection
from utils import cartao_arquivo

_LOCK_NAME = "cartao_arquivo_import"
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
        feitos = cartao_arquivo.processar_dropbox()
        for nome, op, nl, nv, erro in feitos:
            if erro:
                logger.warning("[cartao_arq] %s: %s", nome, erro)
            else:
                logger.info("[cartao_arq] %s (%s): %s lotes, %s vendas", nome, op, nl, nv)
        # Casa a venda da operadora com o cupom fiscal (utils/cartao_cupom).
        # O cupom chega o dia inteiro e o arquivo da operadora pode vir antes
        # ou depois dele: refaz a janela dos ultimos 45 dias a cada rodada.
        try:
            from datetime import date, timedelta
            from utils import cartao_cupom
            hoje = date.today()
            n = cartao_cupom.refazer(conn, hoje - timedelta(days=45), hoje)
            if feitos:
                logger.info("[cartao_arq] cupons casados: %s", n)
        except Exception:
            logger.exception("[cartao_arq] falha casando venda x cupom.")
    except Exception:
        logger.exception("[cartao_arq] falha no job.")
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
    if os.environ.get("CARTAO_ARQ_SCHED_ENABLED", "1") != "1":
        app.logger.info("[cartao_arq] desabilitado (CARTAO_ARQ_SCHED_ENABLED != '1').")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[cartao_arq] APScheduler indisponivel; scheduler NAO iniciado.")
            return

        minuto = os.environ.get("CARTAO_ARQ_SCHED_MINUTE", "*/10")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None

        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(minute=minuto, timezone=tz),
            id="cartao_arquivo_import",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info("[cartao_arq] ligado: minuto '%s' (lock '%s').", minuto, _LOCK_NAME)
