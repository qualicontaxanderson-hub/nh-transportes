# -*- coding: utf-8 -*-
"""Q-Colabore: chaves dos colaboradores e entrega do arquivo no Dropbox.

O agente que roda na maquina do colaborador e o mesmo do Qualicontax (Nuitka
standalone, versao 0.4.0). Ele so sabe duas coisas: pedir a data de corte e
mandar o arquivo. Toda a decisao mora aqui -- "burro na ponta, inteligencia na
nuvem". Por isso mudar a lista de extensoes ou a data de corte NAO exige tocar
nas cinco maquinas.

O contrato de HTTP e o do agente e nao pode mudar: ele decide pelo CODIGO, nao
pelo corpo da resposta.

    200 / 409  -> considera enviado, anota no caderninho dele
    413 / 415  -> recusa DEFINITIVA: move para "Nao enviados" e nunca reenvia
    401 / 403  -> chave invalida: pausa tudo e avisa na janela
    demais     -> tenta de novo no proximo ciclo, com recuo crescente

O 415 ser definitivo tem consequencia pratica: ampliar a lista de extensoes
depois NAO faz o agente reenviar o que ja foi recusado -- a pessoa teria que
salvar o arquivo de novo. Por isso a lista nasce completa.
"""
import hashlib
import re
import secrets
import unicodedata
from datetime import date

from utils.db import get_db_connection

# Pasta unica, a mesma que o importador de extrato ja varre. Sem subpasta por
# pessoa: quem separa e o conteudo do arquivo, nao o lugar dele.
PASTA_DESTINO = '/BANCOS/OFX/NOVO'

#: O agente nao filtra nada — manda tudo e deixa o servidor recusar. A lista
#: nasce completa de proposito (ver o 415 definitivo, no topo).
EXTENSOES_PERMITIDAS = ('.ofx', '.xlsx', '.xls', '.xlsm', '.csv')

#: 25 MB. O maior OFX que ja passou por aqui tem 85 KB, entao sobra folga de
#: 300x — e fecha a porta para arquivo enorme atravessar a internet a toa.
TAMANHO_MAX_BYTES = 25 * 1024 * 1024

_CHARS_PROIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_NOME_MAX = 200
_TOKEN_BYTES = 32          # 64 caracteres hexadecimais


# ── a chave ───────────────────────────────────────────────────────────────────

def hash_token(token):
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


def _linha(cur, uid):
    cur.execute("SELECT * FROM colabore_config WHERE usuario_id = %s", (uid,))
    return cur.fetchone()


def gerar_chave(usuario_id, admin_id, regerar=False, data_inicio=None):
    """Cria (ou rotaciona) a chave de um colaborador.

    Devolve o segredo em CLARO uma unica vez — depois disso so existe o hash,
    e nem o administrador consegue ver de novo. Perdeu, regera.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        atual = _linha(cur, usuario_id)
        if atual and atual.get('token_hash') and not regerar:
            return None, 'ja_existe'

        token = secrets.token_hex(_TOKEN_BYTES)
        dados = (hash_token(token), token[:8], data_inicio, admin_id)
        if atual:
            cur.execute("""
                UPDATE colabore_config
                   SET token_hash = %s, token_prefixo = %s,
                       data_inicio_captura = COALESCE(%s, data_inicio_captura),
                       token_gerado_por = %s, token_gerado_em = NOW(),
                       versao = versao + 1, ativo = 1
                 WHERE usuario_id = %s
            """, dados + (usuario_id,))
        else:
            cur.execute("""
                INSERT INTO colabore_config
                       (usuario_id, token_hash, token_prefixo,
                        data_inicio_captura, token_gerado_por, token_gerado_em,
                        versao, ativo)
                VALUES (%s, %s, %s, %s, %s, NOW(), 1, 1)
            """, (usuario_id,) + dados)
        conn.commit()
        return token, None
    finally:
        cur.close()
        conn.close()


def revogar_chave(usuario_id):
    """Desliga a chave sem apagar a linha.

    A linha fica para o historico continuar fazendo sentido, e o agente passa a
    tomar 403 — ele para de mandar e mostra o aviso, sem morrer.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE colabore_config SET ativo = 0 WHERE usuario_id = %s",
                    (usuario_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def definir_corte(usuario_id, data_inicio):
    """Muda a data de corte. O agente rele a cada ciclo — nao se toca na maquina.

    Data futura e recusada: o agente entenderia "nao mande nada" e ficaria
    parado sem ninguem saber por que.
    """
    if data_inicio and data_inicio > date.today():
        return False, 'futura'
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""UPDATE colabore_config SET data_inicio_captura = %s
                        WHERE usuario_id = %s""", (data_inicio, usuario_id))
        conn.commit()
        return cur.rowcount > 0, None
    finally:
        cur.close()
        conn.close()


def config_por_token(token):
    """A linha do colaborador dono desta chave, ou None.

    Procura pelo HASH: o segredo em claro nunca esteve no banco.
    """
    if not token:
        return None
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT c.*, u.nome_completo AS usuario_nome, u.username AS usuario_login
              FROM colabore_config c
              JOIN usuarios u ON u.id = c.usuario_id
             WHERE c.token_hash = %s
        """, (hash_token(token),))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def marcar_contato(usuario_id):
    """Carimba o ultimo contato — inclusive quando a chave esta revogada.

    E o que separa "maquina desligada" de "agente parado": sem isso, os dois
    casos se parecem exatamente igual na tela.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""UPDATE colabore_config SET ultimo_contato = NOW()
                        WHERE usuario_id = %s""", (usuario_id,))
        conn.commit()
    except Exception:
        pass
    finally:
        cur.close()
        conn.close()


# ── o arquivo ─────────────────────────────────────────────────────────────────

def sanitizar_nome(nome):
    """So o nome do arquivo, sem caminho e sem caractere que o Dropbox recusa."""
    nome = unicodedata.normalize('NFC', nome or '')
    nome = nome.replace('\\', '/').split('/')[-1]      # mata "..\\..\\senha.txt"
    nome = nome.replace('..', '_')
    nome = _CHARS_PROIBIDOS.sub('_', nome).strip(' .')
    if not nome:
        nome = 'arquivo'
    if len(nome) > _NOME_MAX:
        base, _, ext = nome.rpartition('.')
        ext = ('.' + ext) if base else ''
        base = base or nome
        nome = base[:_NOME_MAX - len(ext)] + ext
    return nome


def extensao(nome):
    i = nome.rfind('.')
    return nome[i:].lower() if i > 0 else ''


def _dbx():
    from integrations.dropbox_ofx import _criar_dbx
    return _criar_dbx()


def ja_esta_la(nome, tamanho):
    """True quando o mesmo nome JA existe com o mesmo tamanho.

    E o reenvio do mesmo arquivo — devolver 409 faz o agente marcar como
    enviado e parar de tentar, em vez de encher a pasta de copias.
    """
    from dropbox.exceptions import ApiError
    try:
        meta = _dbx().files_get_metadata('%s/%s' % (PASTA_DESTINO, nome))
    except ApiError:
        return False
    return getattr(meta, 'size', None) == tamanho


def guardar(nome, conteudo):
    """Grava no Dropbox e devolve o nome que ficou la.

    `autorename` e do proprio Dropbox: nome ocupado com tamanho DIFERENTE vira
    "extrato (1).ofx". Nada e sobrescrito nunca — dois colaboradores mandando
    "extrato.ofx" no mesmo dia geram dois arquivos, e quem e quem se descobre
    pela tela, nao pelo nome.
    """
    from dropbox.files import WriteMode
    meta = _dbx().files_upload(conteudo, '%s/%s' % (PASTA_DESTINO, nome),
                               mode=WriteMode.add, autorename=True)
    return meta.name


def registrar_recebido(usuario_id, nome_original, nome_final, ext, tamanho, ip):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO colabore_recebidos
                   (usuario_id, nome_original, nome_final, ext, tamanho_bytes,
                    destino, ip)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (usuario_id, nome_original[:255], nome_final[:255], ext[:12],
              tamanho, PASTA_DESTINO[:255], (ip or '')[:45]))
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── leitura para as telas ─────────────────────────────────────────────────────

def painel():
    """Uma linha por usuario ativo, com o estado da chave e o que ele mandou."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT u.id, u.nome_completo, u.username, u.nivel, u.ativo AS usuario_ativo,
                   c.token_prefixo, c.ativo AS chave_ativa, c.data_inicio_captura,
                   c.ultimo_contato, c.versao, c.token_gerado_em,
                   TIMESTAMPDIFF(MINUTE, c.ultimo_contato, NOW()) AS min_sem_contato,
                   (SELECT COUNT(*) FROM colabore_recebidos r
                     WHERE r.usuario_id = u.id) AS enviados,
                   (SELECT MAX(r.recebido_em) FROM colabore_recebidos r
                     WHERE r.usuario_id = u.id) AS ultimo_envio
              FROM usuarios u
              LEFT JOIN colabore_config c ON c.usuario_id = u.id
             WHERE u.ativo = 1
             ORDER BY (c.token_hash IS NULL), u.nome_completo
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def recebidos(limite=200):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT r.*, u.nome_completo, u.username
              FROM colabore_recebidos r
              JOIN usuarios u ON u.id = r.usuario_id
             ORDER BY r.recebido_em DESC
             LIMIT %s
        """, (int(limite),))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
