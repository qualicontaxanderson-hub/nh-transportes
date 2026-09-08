# -*- coding: utf-8 -*-
"""NH-Robo: chaves dos colaboradores e entrega do arquivo no Dropbox.

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

from utils import nhrobo_periodo
from utils.db import get_db_connection
from utils.fuso import agora_brasilia, hoje_brasilia

# Pasta unica, a mesma que o importador de extrato ja varre. Sem subpasta por
# pessoa: quem separa e o conteudo do arquivo, nao o lugar dele.
PASTA_DESTINO = '/BANCOS/OFX/NOVO'

#: O agente nao filtra nada — manda tudo e deixa o servidor recusar, entao esta
#: linha e o unico lugar a mexer: acrescentar um tipo NAO exige tocar em maquina
#: nenhuma.
#:
#: A lista nasce completa de proposito. O 415 e recusa DEFINITIVA: o agente
#: anota no caderninho dele e nunca mais tenta aquele arquivo. Liberar um tipo
#: depois so vale para arquivo NOVO — o que ja foi recusado exige a pessoa
#: salvar de novo.
#:
#: `.pdf` entrou em 07/09/2026 por essa razao, antes de existir quem o consuma:
#: hoje ele so se acumula em /BANCOS/OFX/NOVO esperando alguem pegar a mao. O
#: preco de deixar de fora seria pedir a cinco pessoas que re-salvassem tudo no
#: dia em que ele fosse liberado.
EXTENSOES_PERMITIDAS = ('.ofx', '.xlsx', '.xls', '.xlsm', '.csv', '.pdf')

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
    cur.execute("SELECT * FROM nhrobo_config WHERE usuario_id = %s", (uid,))
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
        # A hora entra na TUPLA, e nao como NOW() no SQL: o relogio do container
        # e UTC. Ela fica junto do resto para os dois caminhos (INSERT e UPDATE)
        # nao terem contagens de %s diferentes -- foi assim que o 500 nasceu.
        dados = (hash_token(token), token[:8], data_inicio, admin_id,
                 agora_brasilia())
        if atual:
            cur.execute("""
                UPDATE nhrobo_config
                   SET token_hash = %s, token_prefixo = %s,
                       data_inicio_captura = COALESCE(%s, data_inicio_captura),
                       token_gerado_por = %s, token_gerado_em = %s,
                       versao = versao + 1, ativo = 1
                 WHERE usuario_id = %s
            """, dados + (usuario_id,))
        else:
            cur.execute("""
                INSERT INTO nhrobo_config
                       (usuario_id, token_hash, token_prefixo,
                        data_inicio_captura, token_gerado_por, token_gerado_em,
                        versao, ativo)
                VALUES (%s, %s, %s, %s, %s, %s, 1, 1)
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
        cur.execute("UPDATE nhrobo_config SET ativo = 0 WHERE usuario_id = %s",
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
    if data_inicio and data_inicio > hoje_brasilia():
        return False, 'futura'
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""UPDATE nhrobo_config SET data_inicio_captura = %s
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
              FROM nhrobo_config c
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
        cur.execute("""UPDATE nhrobo_config SET ultimo_contato = %s
                        WHERE usuario_id = %s""", (agora_brasilia(), usuario_id))
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


# ── o instalador ──────────────────────────────────────────────────────────────

#: Onde o .zip do agente fica. FORA de /BANCOS/OFX/NOVO de proposito: aquela
#: pasta e varrida pelo importador de extrato, e um .zip la dentro so ia
#: confundir. Publicar versao nova e largar o arquivo aqui -- o link que os
#: colaboradores usam nao muda.
PASTA_INSTALADOR = '/BANCOS/NHROBO'


def instalador():
    """(nome, bytes) do .zip mais novo, ou (None, None) quando nao ha nenhum.

    O colaborador NUNCA toca no Dropbox: quem busca e o servidor, e ele entrega
    pelo app, onde a pessoa ja entra. Se dependesse de um link do Dropbox, o
    robo perderia o proprio sentido.
    """
    from dropbox.exceptions import ApiError
    try:
        entradas = _dbx().files_list_folder(PASTA_INSTALADOR).entries
    except ApiError:
        return None, None
    zips = [e for e in entradas
            if getattr(e, 'size', None) is not None
            and e.name.lower().startswith('nhrobo')
            and e.name.lower().endswith('.zip')]
    if not zips:
        return None, None
    # O mais novo pelo carimbo do proprio Dropbox, e nao pelo nome: ordenar
    # "1.10.0" por texto poria ele antes de "1.9.0".
    zips.sort(key=lambda e: getattr(e, 'server_modified', None) or 0, reverse=True)
    escolhido = zips[0]
    _, resposta = _dbx().files_download('%s/%s' % (PASTA_INSTALADOR, escolhido.name))
    return escolhido.name, resposta.content


def registrar_recebido(usuario_id, nome_original, nome_final, ext, tamanho, ip,
                       conteudo=None):
    """A linha do historico. O periodo e lido AQUI, com o arquivo ainda em maos.

    Depois deste ponto o conteudo so existe no Dropbox: descobrir o periodo mais
    tarde custaria baixar o arquivo de volta, um por um. O identificador nunca
    levanta excecao -- sem periodo a linha entra do mesmo jeito, com travessao
    na tela, porque perder a linha e pior do que nao saber o mes.
    """
    tipo, p_ini, p_fim, p_fonte = nhrobo_periodo.identificar(
        nome_original or nome_final, conteudo, ext)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO nhrobo_recebidos
                   (usuario_id, nome_original, nome_final, ext, tamanho_bytes,
                    destino, ip, doc_tipo, periodo_ini, periodo_fim, periodo_fonte,
                    recebido_em)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (usuario_id, nome_original[:255], nome_final[:255], ext[:12],
              tamanho, PASTA_DESTINO[:255], (ip or '')[:45],
              tipo, p_ini, p_fim, p_fonte, agora_brasilia()))
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
                   TIMESTAMPDIFF(MINUTE, c.ultimo_contato, %s) AS min_sem_contato,
                   (SELECT COUNT(*) FROM nhrobo_recebidos r
                     WHERE r.usuario_id = u.id) AS enviados,
                   (SELECT MAX(r.recebido_em) FROM nhrobo_recebidos r
                     WHERE r.usuario_id = u.id) AS ultimo_envio
              FROM usuarios u
              LEFT JOIN nhrobo_config c ON c.usuario_id = u.id
             WHERE u.ativo = 1
             ORDER BY (c.token_hash IS NULL), u.nome_completo
        """, (agora_brasilia(),))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def meus_envios(usuario_id, limite=300):
    """O que ESTE usuario mandou, do mais novo para o mais velho.

    Existe para o colaborador conferir sozinho, sem passar pelo administrador e
    sem ligar para o tecnico -- que era o custo real de cada "sera que chegou?".
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, nome_original, nome_final, ext, tamanho_bytes, recebido_em
              FROM nhrobo_recebidos
             WHERE usuario_id = %s
             ORDER BY recebido_em DESC
             LIMIT %s
        """, (int(usuario_id), int(limite)))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def meu_estado(usuario_id):
    """A situacao da chave e do ultimo sinal desta pessoa, ou None sem chave.

    E o que separa "nao chegou" de "o robo nem esta falando": sem isto a tela
    mostraria uma lista velha e completa, e a pessoa a leria como prova de que o
    sistema perdeu o arquivo dela.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT c.token_prefixo, c.ativo AS chave_ativa, c.data_inicio_captura,
                   c.ultimo_contato,
                   TIMESTAMPDIFF(MINUTE, c.ultimo_contato, %s) AS min_sem_contato,
                   (SELECT COUNT(*) FROM nhrobo_recebidos r
                     WHERE r.usuario_id = c.usuario_id) AS enviados
              FROM nhrobo_config c
             WHERE c.usuario_id = %s
        """, (agora_brasilia(), int(usuario_id)))
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def recebidos(limite=200):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT r.*, u.nome_completo, u.username
              FROM nhrobo_recebidos r
              JOIN usuarios u ON u.id = r.usuario_id
             ORDER BY r.recebido_em DESC
             LIMIT %s
        """, (int(limite),))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


#: Quem pode aparecer no filtro por tipo, e como cada um se chama na tela. A
#: ordem e a da lista do filtro -- os que mais chegam primeiro.
TIPOS_DOC = [
    ('extrato',     'Extrato bancário'),
    ('planilha',    'Planilha'),
    ('nfe',         'NF-e'),
    ('nfce',        'NFC-e'),
    ('cte',         'CT-e'),
    ('sped',        'SPED'),
    ('xml',         'XML (outro)'),
    ('pdf',         'PDF'),
    ('texto',       'Texto'),
    ('imagem',      'Imagem'),
    ('zip',         'ZIP'),
    ('certificado', 'Certificado'),
    ('declaracao',  'Declaração'),
    ('recibo',      'Recibo'),
]
ROTULO_DOC = dict(TIPOS_DOC)


def historico(data_ini=None, data_fim=None, usuario_id=None, tipo=None,
              limite=500):
    """O que chegou, de quem, quando e de que periodo.

    Uma lista so, sem paginacao, com teto: cinco pessoas mandando extrato e
    planilha nao produzem volume que justifique paginar, e a lista inteira na
    tela e o que deixa o Ctrl+F do navegador funcionar -- que e como a pessoa
    procura o arquivo dela de verdade.
    """
    onde, args = ['1=1'], []
    if data_ini:
        onde.append('r.recebido_em >= %s')
        args.append('%s 00:00:00' % data_ini)
    if data_fim:
        onde.append('r.recebido_em <= %s')
        args.append('%s 23:59:59' % data_fim)
    if usuario_id:
        onde.append('r.usuario_id = %s')
        args.append(int(usuario_id))
    if tipo:
        # 'sem' e uma escolha do filtro, nao um tipo: e como se pergunta "o que
        # chegou que eu ainda nao sei o que e".
        if tipo == 'sem':
            onde.append('r.doc_tipo IS NULL')
        else:
            onde.append('r.doc_tipo = %s')
            args.append(tipo)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT r.id, r.usuario_id, r.nome_original, r.nome_final, r.ext,
                   r.tamanho_bytes, r.recebido_em, r.ip,
                   r.doc_tipo, r.periodo_ini, r.periodo_fim, r.periodo_fonte,
                   u.nome_completo, u.username
              FROM nhrobo_recebidos r
              JOIN usuarios u ON u.id = r.usuario_id
             WHERE %s
             ORDER BY r.recebido_em DESC
             LIMIT %%s
        """ % ' AND '.join(onde), tuple(args) + (int(limite),))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def quem_ja_mandou():
    """As pessoas que aparecem no filtro: so quem tem envio, nao o cadastro todo.

    Filtro que oferece oito nomes para dois que mandaram alguma coisa faz a
    pessoa procurar onde nao ha nada.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT u.id, u.nome_completo, u.username, COUNT(*) AS envios
              FROM nhrobo_recebidos r
              JOIN usuarios u ON u.id = r.usuario_id
             GROUP BY u.id, u.nome_completo, u.username
             ORDER BY u.nome_completo
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()
