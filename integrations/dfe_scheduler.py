"""
Agendador in-process (APScheduler) da captura automatica de DFe.

Roda A CADA 20 MINUTOS (horario de Brasilia) a captura em massa
(scripts/captura_massa_dfe.py), respeitando a cota da SEFAZ. A cota da SEFAZ e
rigida (~1 consulta produtiva por hora por CNPJ) e o mesmo CNPJ tambem e
consultado por outro consumidor (NFStock/SGA), que mantem o relogio de 1h
quente. Tentar de 20 em 20 min NAO abusa -- so serve para PEGAR a janela assim
que ela abre (ate ~20 min depois), em vez de perde-la esperando 3h:
  - o proprio script pula se dfe_nsu.proximo_permitido ainda estiver no futuro
    (656 recente) e, se tomar 656 no meio, para e reagenda +1h;
  - aqui ainda fazemos um pre-check barato de proximo_permitido para nem
    disparar o processo a toa, MAS afrouxado (opcao ii): a captura tem 2 fases
    independentes -- NF-e (cursor dfe_nsu) e CT-e (cursor dfe_nsu_cte) -- com
    cotas SEPARADAS na SEFAZ. So pulamos o ciclo quando as DUAS estao de castigo
    por 656 ao mesmo tempo; se qualquer janela esta aberta, disparamos e cada
    fase se auto-regula la dentro. Assim a NF-e travada (656 do SGA) nao arrasta
    o CT-e junto.

Concorrencia (gunicorn --workers 2):
  cada worker cria o seu proprio scheduler, entao o job usa um LOCK global no
  MySQL (GET_LOCK) para garantir que APENAS UMA execucao rode por vez em todo o
  deploy. O worker que nao pega o lock so registra e sai. Assim nunca ha duas
  consultas simultaneas a SEFAZ (o que dispararia 656).

Liga/desliga por env (no servico web do Railway):
  DFE_SCHED_ENABLED = '1' (default) | '0' para desligar
  DFE_SCHED_HOURS   = horas do disparo em cron (default '*' = toda hora)
  DFE_SCHED_MINUTE  = minuto do disparo em cron (default '*/20' = a cada 20 min)
"""
import os
import sys
import subprocess
import threading

import mysql.connector

from utils.db import CONNECTION_PARAMS
from integrations import dfe_log

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


def _estado_cota(cur):
    """Pre-check AFROUXADO (opcao ii): so vale a pena pular o ciclo inteiro
    quando as DUAS fases estao de castigo por 656 AO MESMO TEMPO. Se QUALQUER
    janela estiver aberta -- NF-e (dfe_nsu) OU CT-e (dfe_nsu_cte) -- devolve None
    para DISPARAR o subprocess; cada fase se auto-regula la dentro. Assim a NF-e
    travada (656 do SGA) nao arrasta o CT-e junto. Comparacao sempre no relogio
    do BANCO (NOW()).

    Devolve (cliente_id, cnpj, ult_nsu, prox_nfe, prox_cte) SO quando ambas
    bloqueadas (para o log do 'pulado_cota'); None se ao menos uma janela esta
    aberta -- inclusive se dfe_nsu_cte ainda nem existe (1a vez), caso em que o
    CT-e esta 'aberto' e o subprocess a cria."""
    cur.execute(
        "SELECT cliente_id, cnpj, ult_nsu, proximo_permitido FROM dfe_nsu "
        "WHERE proximo_permitido IS NOT NULL AND proximo_permitido > NOW() "
        "LIMIT 1"
    )
    row_nfe = cur.fetchone()
    if not row_nfe:
        return None                       # janela NF-e aberta -> dispara
    try:
        cur.execute(
            "SELECT proximo_permitido FROM dfe_nsu_cte "
            "WHERE proximo_permitido IS NOT NULL AND proximo_permitido > NOW() "
            "LIMIT 1"
        )
        row_cte = cur.fetchone()
    except Exception:
        return None                       # tabela ainda nao existe -> CT-e aberto
    if not row_cte:
        return None                       # janela CT-e aberta -> dispara
    cli, cnpj, ult_nsu, prox_nfe = row_nfe
    return cli, cnpj, ult_nsu, prox_nfe, row_cte[0]   # AMBAS bloqueadas


def _job(app, origem='agendador'):
    """Executado pelo scheduler. Garantidamente unico por deploy via GET_LOCK.

    origem ('agendador'|'manual') so rotula o log e e repassada ao subprocess
    via DFE_ORIGEM, para dfe_consulta_log saber QUEM disparou cada rodada."""
    logger = app.logger
    conn = cur = None
    got = 0
    try:
        conn = _conn_direta()
        cur = conn.cursor()
        dfe_log.garantir_tabela(cur)

        cur.execute("SELECT GET_LOCK(%s, 0)", (_LOCK_NAME,))
        row = cur.fetchone()
        got = row[0] if row else 0
        if got != 1:
            logger.info("[dfe_sched] outro worker/deploy ja esta capturando; pulando.")
            dfe_log.registrar(
                cur, origem, 'pulado_lock',
                detalhe='outro worker/deploy ja estava capturando (GET_LOCK negado)')
            return

        # Pre-check de cota AFROUXADO (opcao ii): so pula o ciclo se AMBAS as
        # fases (NF-e e CT-e) estiverem bloqueadas por 656 ao mesmo tempo. Se uma
        # janela esta aberta, dispara -- cada fase se auto-regula no subprocess.
        # Este ramo era INVISIVEL no banco -- a rodada sumia sem rastro. Agora
        # deixa linha, que e justamente o que faltava para auditar os ciclos.
        estado = _estado_cota(cur)
        if estado:
            cli, cnpj, ult_nsu, prox_nfe, prox_cte = estado
            logger.info("[dfe_sched] NF-e e CT-e ambas com proximo_permitido no futuro "
                        "(656 nas duas); pulando ciclo.")
            dfe_log.registrar(
                cur, origem, 'pulado_cota', cliente_id=cli, cnpj=cnpj,
                ult_nsu_env=ult_nsu,
                detalhe='ambas as fases bloqueadas (NF-e ate %s; CT-e ate %s); '
                        'nem disparou a captura' % (prox_nfe, prox_cte))
            return

        logger.info("[dfe_sched] iniciando captura em massa (%s)...", _SCRIPT)
        env = dict(os.environ, DFE_ORIGEM=origem)
        res = subprocess.run(
            [sys.executable, _SCRIPT],
            cwd=_RAIZ, capture_output=True, text=True, timeout=_SUBPROC_TIMEOUT,
            env=env,
        )
        cauda = (res.stdout or "")[-1500:]
        logger.info("[dfe_sched] captura terminou (rc=%s). Fim do log:\n%s",
                    res.returncode, cauda)
        if res.returncode != 0:
            logger.warning("[dfe_sched] stderr (fim):\n%s", (res.stderr or "")[-1500:])
            # O subprocess loga as consultas que chegou a fazer; este 'erro'
            # cobre o caso de ele morrer ANTES disso (import, certificado, OOM).
            dfe_log.registrar(
                cur, origem, 'erro',
                detalhe='captura saiu com rc=%s; stderr: %s'
                        % (res.returncode, (res.stderr or '').strip()[-200:]))
    except subprocess.TimeoutExpired:
        logger.warning("[dfe_sched] captura excedeu %ss; sera retomada no proximo ciclo.",
                       _SUBPROC_TIMEOUT)
        if cur is not None:
            dfe_log.registrar(cur, origem, 'erro',
                              detalhe='captura excedeu o timeout de %ss e foi morta'
                                      % _SUBPROC_TIMEOUT)
    except Exception as exc:
        logger.exception("[dfe_sched] falha no job de captura.")
        if cur is not None:
            dfe_log.registrar(cur, origem, 'erro',
                              detalhe='%s: %s' % (type(exc).__name__, exc))
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

        # Minuto do disparo em cron. Aceita expressao ('*/20', '5,25,45'...),
        # nao so um inteiro fixo -- por isso repassamos a string crua ao
        # CronTrigger. Default '*/20' = a cada 20 min.
        minuto = os.environ.get('DFE_SCHED_MINUTE', '*/20')

        # Horas do disparo em cron; default '*' (toda hora). Combinado com
        # minuto '*/20', dispara a cada 20 min. Nao abusa da SEFAZ: o proprio
        # ciclo se auto-regula -- apos um 656 grava proximo_permitido=+1h e a
        # pre-checagem de cota nem dispara a captura enquanto o bloqueio vale.
        # Assim tentamos de 20 em 20 min so para PEGAR a janela assim que ela
        # abre (ate ~20 min depois), em vez de perde-la esperando 3h.
        horas = os.environ.get('DFE_SCHED_HOURS', '*')

        # Fuso de Brasilia: o container roda em UTC, entao fixamos o timezone
        # para os horarios acima serem em horario de Brasilia (UTC-3).
        # APScheduler 3.x so aceita timezones do pytz.
        try:
            import pytz
            tz = pytz.timezone('America/Sao_Paulo')
        except Exception:
            tz = None
            app.logger.warning(
                "[dfe_sched] pytz indisponivel; usando fuso padrao do container (UTC)."
            )

        sched = BackgroundScheduler(daemon=True, timezone=tz)
        sched.add_job(
            lambda: _job(app),
            trigger=CronTrigger(hour=horas, minute=minuto, timezone=tz),  # cada 20 min, BR
            id='dfe_captura',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        sched.start()
        _started = True
        app.logger.info(
            "[dfe_sched] scheduler ligado: captura nas horas '%s' (America/Sao_Paulo), "
            "minuto %s (lock global '%s').", horas, minuto, _LOCK_NAME,
        )


def disparar_captura_async(app):
    """Dispara UMA captura AGORA, em background (mesma rotina do agendador).

    Reutiliza _job(): GET_LOCK global (nao roda em paralelo com o agendador nem
    com outro disparo), pre-check de proximo_permitido (nao consulta se a cota
    ainda esta fechada) e subprocess com timeout. Retorna na hora; o trabalho
    segue na thread daemon. Usado pela rota POST /dfe/capturar-agora, para forcar
    uma coleta sem depender de terminal/CLI."""
    t = threading.Thread(
        target=_job, args=(app, 'manual'), name='dfe-captura-manual', daemon=True,
    )
    t.start()
    return t
