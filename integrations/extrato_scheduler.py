"""
integrations/extrato_scheduler.py
=================================

Agendador in-process (APScheduler) do Extrato On-Line GRAVANDO — o mesmo
desenho do integrations/pix_scheduler.py.

A cada N minutos (default 10) lê, de cada conta que grava pela API
(routes/extrato_online.BANCOS com 'grava': True), os últimos 3 dias e hoje, e
lança no sistema o que ainda não está lá (integrations/extrato_grava). É o
que faz o PIX do troco aparecer conciliado no mesmo dia, sem esperar o OFX.

Três dias para trás: o banco às vezes lança atrasado, e reler o que já foi
gravado não custa nada (bank_api_ids impede gravar duas vezes).

Concorrência (gunicorn --workers N): cada worker cria o seu scheduler; o job
usa GET_LOCK global no MySQL para só UMA execução rodar por vez.

Liga/desliga por env (Railway):
    EXTRATO_SCHED_ENABLED = '1' (default) | '0' para desligar
    EXTRATO_SCHED_MINUTE  = minuto cron (default '*/10')
"""
import os
import threading
from datetime import date, timedelta

from utils.db import get_db_connection

_LOCK_NAME = "extrato_online_grava"
_started = False
_started_lock = threading.Lock()
DIAS_ATRAS = 3


def rodar(logger, hoje=None):
    """Uma passada por todas as contas que gravam. Devolve {chave: resumo}."""
    from integrations.banco_api import SemCredencial, proximo_dia_util
    from integrations.extrato_grava import sincronizar
    from routes.extrato_online import BANCOS
    from utils import pix_consulta
    hoje = hoje or date.today()
    resumo = {}
    for chave, banco in BANCOS.items():
        if not banco.get('grava'):
            continue
        conn = cur = None
        try:
            mod = banco['modulo']()
            # Sicoob no fim de semana/feriado: o PIX de hoje vem com a data do
            # próximo dia útil — pedido só até hoje, não viria.
            fim = proximo_dia_util(hoje) if banco.get('fds_no_dia_util') else hoje
            api = mod.ler(hoje - timedelta(days=DIAS_ATRAS), fim, incluir_hoje=True)
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            resumo[chave] = sincronizar(mod, api, cur, conn)
            if mod.account_id == pix_consulta.ACCOUNT_ID:
                # PIX Consulta: nome inteiro, documento e quando apareceu.
                # Separado: se falhar, o extrato já está gravado.
                try:
                    pix_consulta.anotar(conn, mod.account_id, api)
                except Exception:
                    logger.exception("[extrato_sched] %s: anotar PIX Consulta falhou", chave)
        except SemCredencial:
            resumo[chave] = 'sem credencial'
        except Exception:
            logger.exception("[extrato_sched] %s: falhou", chave)
            resumo[chave] = 'erro'
        finally:
            for c in (cur, conn):
                try:
                    if c is not None:
                        c.close()
                except Exception:
                    pass
    return resumo


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
            logger.info("[extrato_sched] outro worker já está gravando; pulando.")
            return
        with app.app_context():
            resumo = rodar(logger)
        if any(isinstance(v, dict) and (v.get('novos') or v.get('casados_ofx')) or v == 'erro'
               for v in resumo.values()):
            logger.info("[extrato_sched] %s", resumo)
    except Exception:
        logger.exception("[extrato_sched] falha ao gravar o extrato pela API.")
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
    """Liga o APScheduler do Extrato On-Line (idempotente por processo)."""
    global _started
    if os.environ.get("EXTRATO_SCHED_ENABLED", "1") != "1":
        app.logger.info("[extrato_sched] desabilitado (EXTRATO_SCHED_ENABLED != '1').")
        return
    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[extrato_sched] APScheduler indisponível; scheduler NÃO iniciado.")
            return
        minuto = os.environ.get("EXTRATO_SCHED_MINUTE", "*/10")
        try:
            import pytz
            tz = pytz.timezone("America/Sao_Paulo")
        except Exception:
            tz = None
        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(minute=minuto, timezone=tz),
            id="extrato_online_grava",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info("[extrato_sched] ligado: minuto '%s' (lock '%s').", minuto, _LOCK_NAME)
