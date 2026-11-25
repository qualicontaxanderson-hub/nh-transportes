"""
utils/auditoria.py
==================

Quem fez o que (pedido do usuario em 25/11/2026: "quero que comece a gravar
quem fez tudo"). Toda acao que MUDA alguma coisa -- POST, PUT, PATCH, DELETE --
feita por um usuario logado vira uma linha em ``auditoria_acoes``: quem,
quando, em qual tela (endpoint e caminho), com quais dados e se deu certo.

Nasceu porque quatro PIX enviados (R$ 124 mil) apareceram conciliados como
recebimento e nao havia como saber quem foi: a conciliacao gravava o e-mail do
usuario, e o cadastro de usuarios nao tem e-mail.

- So usuario logado: o robo e os webhooks nao sao "quem".
- Senha, token, certificado e afins nunca sao gravados (viram ***).
- Erro aqui fica aqui: a gravacao e depois da resposta pronta, em conexao
  propria, e qualquer falha so vai para o log.
- Consulta (GET) nao e gravada.
"""
import json
import logging

logger = logging.getLogger(__name__)

_METODOS = ('POST', 'PUT', 'PATCH', 'DELETE')
_SEGREDO = ('senha', 'password', 'passwd', 'token', 'secret', 'segredo', 'csrf',
            'cert', 'pfx', 'p12', 'chave_privada', 'private', 'api_key', 'apikey',
            'authorization', 'client_id', 'credencial')
_MAX_VALOR = 300
_MAX_DADOS = 6000
_tabela_ok = False


def _garantir(conn):
    """DDL faz commit implicito -- por isso roda antes, uma vez por processo."""
    global _tabela_ok
    if _tabela_ok:
        return
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auditoria_acoes (
            id          BIGINT AUTO_INCREMENT PRIMARY KEY,
            momento     DATETIME     NOT NULL,
            usuario_id  INT          NULL,
            usuario     VARCHAR(80)  NULL,
            nome        VARCHAR(120) NULL,
            nivel       VARCHAR(30)  NULL,
            metodo      VARCHAR(8)   NOT NULL,
            endpoint    VARCHAR(120) NULL,
            caminho     VARCHAR(300) NOT NULL,
            status      SMALLINT     NULL,
            ip          VARCHAR(60)  NULL,
            dados       TEXT         NULL,
            KEY ix_momento (momento),
            KEY ix_usuario (usuario, momento),
            KEY ix_endpoint (endpoint, momento)
        ) DEFAULT CHARSET=utf8mb4""")
    conn.commit()
    cur.close()
    _tabela_ok = True


def _limpo(chave, valor):
    k = (chave or '').lower()
    if any(s in k for s in _SEGREDO):
        return '***'
    if isinstance(valor, (dict, list)):
        return _limpar(valor)
    v = valor if isinstance(valor, (int, float, bool)) or valor is None else str(valor)
    if isinstance(v, str) and len(v) > _MAX_VALOR:
        v = v[:_MAX_VALOR] + '…(%d)' % len(v)
    return v


def _limpar(obj):
    if isinstance(obj, dict):
        return {str(k): _limpo(str(k), v) for k, v in list(obj.items())[:200]}
    if isinstance(obj, list):
        return [_limpo('', v) for v in obj[:200]]
    return _limpo('', obj)


def _dados(request):
    d = {}
    try:
        if request.args:
            d['query'] = _limpar({k: (v if len(v) > 1 else v[0])
                                  for k, v in request.args.lists()})
        if request.form:
            d['form'] = _limpar({k: (v if len(v) > 1 else v[0])
                                 for k, v in request.form.lists()})
        if request.is_json:
            j = request.get_json(silent=True)
            if j is not None:
                d['json'] = _limpar(j)
        if request.files:
            d['arquivos'] = [f.filename for f in request.files.values() if f and f.filename][:50]
    except Exception:
        logger.debug('[auditoria] nao deu para ler os dados do pedido', exc_info=True)
    txt = json.dumps(d, ensure_ascii=False, default=str) if d else None
    if txt and len(txt) > _MAX_DADOS:
        txt = txt[:_MAX_DADOS] + '…(%d)' % len(txt)
    return txt


def registrar(request, response, user):
    """Grava a acao. Nunca levanta."""
    conn = None
    try:
        if request.method not in _METODOS:
            return
        if not getattr(user, 'is_authenticated', False):
            return
        from utils.db import get_db_connection
        from utils.fuso import agora_brasilia
        ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
        linha = (agora_brasilia().replace(tzinfo=None), getattr(user, 'id', None),
                 (getattr(user, 'username', None) or '')[:80],
                 (getattr(user, 'nome_completo', None) or '')[:120],
                 (str(getattr(user, 'nivel', '') or ''))[:30],
                 request.method, (request.endpoint or '')[:120], request.path[:300],
                 getattr(response, 'status_code', None), ip[:60], _dados(request))
        conn = get_db_connection()
        _garantir(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO auditoria_acoes
                (momento, usuario_id, usuario, nome, nivel, metodo, endpoint, caminho, status, ip, dados)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", linha)
        conn.commit()
        cur.close()
    except Exception:
        logger.warning('[auditoria] nao gravou a acao %s %s', request.method,
                       getattr(request, 'path', ''), exc_info=True)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def iniciar(app):
    """Liga o registro: depois de cada resposta, grava a acao do usuario."""
    from flask import request
    from flask_login import current_user

    @app.after_request
    def _auditar(response):
        try:
            if request.method in _METODOS:
                registrar(request, response, current_user)
        except Exception:
            app.logger.warning('[auditoria] falha no gancho.', exc_info=True)
        return response
