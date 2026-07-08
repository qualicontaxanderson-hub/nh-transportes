"""
Agendador in-process (APScheduler) da captura automatica de DFe.

Roda de HORA EM HORA a captura em massa (scripts/captura_massa_dfe.py),
respeitando a cota da SEFAZ:
  - o proprio script pula se dfe_nsu.proximo_permitido ainda estiver no futuro
    (656 recente) e, se tomar 656 no meio, para e reagenda +1h;
  - aqui ainda fazemos um pre-check barato de proximo_permitido para nem
    disparar o processo a toa.

Concorrencia (gunicorn --workers 2):
  cada worker cria o seu proprio scheduler, entao o job usa um LOCK global no
  MySQL (GET_LOCK) para garantir que APENAS UMA execucao rode por vez em todo o
  deploy. O worker que nao pega o lock so registra e sai. Assim nunca ha duas
  consultas simultaneas a SEFAZ (o que dispararia 656).

Liga/desliga por env (no servico web do Railway):
  DFE_SCHED_ENABLED = '1' (default) | '0' para desligar
  DFE_SCHED_MINUTE  = minuto do disparo em cada hora (default '5')
"""
import os
import sys
import subprocess
import threading

import mysql.connector

from utils.db import CONNECTION_PARAMS

_LOCK_NAME = 'dfe_captura'
_SUBPROC_TIMEOUT = 20 * 60  # 20 min (o script tem teto de 40 lotes + pausas de 20s)

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_RAIZ, 'scripts', 'captura_massa_dfe.py')

_started = False
_started_lock = threading.Lock()


def _conn_direta():
    """Conexao DEDICADA (fora do pool) para segurar o GET_LOCK durante toda a
    captura sem prender uma conexao do pool do app. autocommit=True para nao
    deixar transacao ociosa aberta durante os minutos de captura."""
    params = dict(CONNECTION_PARAMS)
    params['autocommit'] = True
    return mysql.connector.connect(**params)


def _proximo_no_futuro(cur):
    """True se a SEFAZ pediu para aguardar (proximo_permitido > agora)."""
    cur.execute(
        "SELECT 1 FROM dfe_nsu "
        "WHERE proximo_permitido IS NOT NULL AND proximo_permitido > NOW() "
        "LIMIT 1"
    )
    return cur.fetchone() is not None


def _job(app):
    """Executado pelo scheduler. Garantidamente unico por deploy via GET_LOCK."""
    logger = app.logger
    conn = cur = None
    got = 0
    try:
        conn = _conn_direta()
        cur = conn.cursor()

        cur.execute("SELECT GET_LOCK(%s, 0)", (_LOCK_NAME,))
        row = cur.fetchone()
        got = row[0] if row else 0
        if got != 1:
            logger.info("[dfe_sched] outro worker/deploy ja esta capturando; pulando.")
            return

        # Pre-check de cota: nao dispara se a janela ainda esta fechada.
        if _proximo_no_futuro(cur):
            logger.info("[dfe_sched] proximo_permitido no futuro (656 recente); pulando ciclo.")
            return

        logger.info("[dfe_sched] iniciando captura em massa (%s)...", _SCRIPT)
        res = subprocess.run(
            [sys.executable, _SCRIPT],
            cwd=_RAIZ, capture_output=True, text=True, timeout=_SUBPROC_TIMEOUT,
        )
        cauda = (res.stdout or "")[-1500:]
        logger.info("[dfe_sched] captura terminou (rc=%s). Fim do log:\n%s",
                    res.returncode, cauda)
        if res.returncode != 0:
            logger.warning("[dfe_sched] stderr (fim):\n%s", (res.stderr or "")[-1500:])
    except subprocess.TimeoutExpired:
        logger.warning("[dfe_sched] captura excedeu %ss; sera retomada no proximo ciclo.",
                       _SUBPROC_TIMEOUT)
    except Exception:
        logger.exception("[dfe_sched] falha no job de captura.")
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

    if os.environ.get('DFE_SCHED_ENABLED', '1') != '1':
        app.logger.info("[dfe_sched] desabilitado (DFE_SCHED_ENABLED != '1').")
        return

    with _started_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            app.logger.warning("[dfe_sched] APScheduler nao instalado; scheduler NAO iniciado.")
            return

        try:
            minuto = int(os.environ.get('DFE_SCHED_MINUTE', '5'))
        except ValueError:
            minuto = 5

        sched = BackgroundScheduler(daemon=True)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(minute=minuto),   # de hora em hora, no minuto X
            id='dfe_captura_horaria',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info(
            "[dfe_sched] scheduler ligado: captura de hora em hora no minuto %s "
            "(lock global '%s').", minuto, _LOCK_NAME,
        )
