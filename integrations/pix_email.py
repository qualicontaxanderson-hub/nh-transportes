"""
integrations/pix_email.py
=========================

Lê os comprovantes de PIX ENVIADO que o banco manda por e-mail (Cora) e marca,
na solicitação de Troco PIX correspondente, que o dinheiro já saiu.

Por que existe: o frentista pega o cheque e pede o troco; a gente faz o PIX
pela conta do posto e o e-mail da Cora chega na hora. Mas a conciliação com o
extrato só acontece no dia seguinte, com o OFX. Nesse meio-tempo a tela dizia
"falta conciliar" tanto para o troco que ja foi pago quanto para o que ninguem
mandou ainda — e na correria e facil deixar de mandar.

O que este modulo NAO faz, de proposito:
  - nao concilia nada. Conciliar e casar com o lancamento do extrato, e isso
    continua sendo do usuario, no OFX do dia seguinte.
  - nao muda status, nem valor, nem nada da solicitacao. So diz "o PIX saiu, e
    saiu nesta hora".

Mesmo desenho do integrations/els_email.py (que traz a leitura de tanque e as
descargas por e-mail): IMAP com BODY.PEEK para nao marcar lido sem querer,
gravacao idempotente, e o e-mail so e marcado como lido depois do commit.

Configuração: nao precisa de nenhuma. Os avisos da Cora chegam na MESMA caixa
que ja recebe o ELS, entao caixa, senha, servidor e pasta sao herdados das
ELS_MAIL_* que ja estao no Railway. As variaveis abaixo existem para o dia em
que isso mudar, e quando presentes ganham da heranca:

    PIX_MAIL_IMAP_HOST  (senao ELS_MAIL_IMAP_HOST, senao imap.titan.email)
    PIX_MAIL_IMAP_PORT  (senao ELS_MAIL_IMAP_PORT, senao 993)
    PIX_MAIL_USER       (senao ELS_MAIL_USER)
    PIX_MAIL_PASSWORD   (senao ELS_MAIL_PASSWORD)
    PIX_MAIL_MAILBOX    (senao ELS_MAIL_MAILBOX, senao INBOX)
    PIX_MAIL_REMETENTE  (default cora.com.br — vale o dominio inteiro; este NAO
                         e herdado, o remetente do ELS e outro)
    PIX_MATCH_DIAS      (quantos dias atras procurar a solicitacao; default 3)
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from utils.db import get_db_connection

_log = logging.getLogger(__name__)

REMETENTE_PADRAO = "cora.com.br"


def _cfg(nome, default=None):
    """A configuração do PIX, caindo para a do ELS quando não houver.

    Os avisos da Cora chegam na MESMA caixa que recebe o ELS. Exigir
    PIX_MAIL_USER e PIX_MAIL_PASSWORD seria repetir no Railway uma senha que
    ja esta la — e um lugar a mais para a senha ficar velha no dia em que ela
    mudar. As PIX_* continuam valendo, e ganham de quem cair aqui: no dia em
    que os avisos forem para outra caixa, basta criar as duas.
    """
    v = os.environ.get(nome)
    if v:
        return v
    espelho = _ESPELHO_ELS.get(nome)
    if espelho:
        v = os.environ.get(espelho)
        if v:
            return v
    return default


# PIX_MAIL_X cai para ELS_MAIL_X: mesma caixa, mesma senha, mesmo servidor.
# O remetente NAO entra aqui — o do ELS e o sistema de medicao, e ler a Cora
# com aquele filtro nao traria e-mail nenhum.
_ESPELHO_ELS = {
    "PIX_MAIL_IMAP_HOST": "ELS_MAIL_IMAP_HOST",
    "PIX_MAIL_IMAP_PORT": "ELS_MAIL_IMAP_PORT",
    "PIX_MAIL_USER": "ELS_MAIL_USER",
    "PIX_MAIL_PASSWORD": "ELS_MAIL_PASSWORD",
    "PIX_MAIL_MAILBOX": "ELS_MAIL_MAILBOX",
}


def caixa_configurada():
    """Tem caixa para ler? (propria ou a herdada do ELS)"""
    return bool(_cfg("PIX_MAIL_USER") and _cfg("PIX_MAIL_PASSWORD"))


# ===========================================================================
# Tabela (idempotente, padrão do resto do app)
# ===========================================================================

def ensure_tables():
    """Cria troco_pix_comprovantes se não existir."""
    ddl = """
    CREATE TABLE IF NOT EXISTS `troco_pix_comprovantes` (
        `id`            INT AUTO_INCREMENT PRIMARY KEY,
        `message_id`    VARCHAR(255) NOT NULL COMMENT 'Message-ID do e-mail: a chave que impede gravar duas vezes',
        `enviado_em`    DATETIME NOT NULL COMMENT 'Hora do e-mail do banco = hora em que o PIX saiu',
        `valor`         DECIMAL(10,2) NOT NULL,
        `favorecido`    VARCHAR(200) NULL,
        `pagador`       VARCHAR(200) NULL COMMENT 'Conta de onde saiu (NH GTBA - CNPJ)',
        `assunto`       VARCHAR(255) NULL,
        `troco_pix_id`  INT NULL COMMENT 'Solicitacao casada; NULL = comprovante ainda sem dono',
        `criado_em`     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY `uq_message` (`message_id`),
        KEY `ix_troco` (`troco_pix_id`),
        KEY `ix_busca` (`valor`, `enviado_em`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(ddl)
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ===========================================================================
# Leitura do e-mail
# ===========================================================================

class _Texto(HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes = []
        self.pular = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.pular = True
        elif tag in ("br", "p", "div", "tr", "table", "li"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.pular = False

    def handle_data(self, data):
        if not self.pular:
            self.partes.append(data)

    def texto(self):
        return re.sub(r"[ \t]+", " ", "".join(self.partes))


def _html_txt(html):
    p = _Texto()
    p.feed(html or "")
    return p.texto()


def _decode(cab):
    try:
        return str(make_header(decode_header(cab)))
    except Exception:
        return cab or ""


def _texto_msg(msg):
    plain, html = None, None
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition") or ""):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            conteudo = payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/plain" and plain is None:
                plain = conteudo
            elif part.get_content_type() == "text/html" and html is None:
                html = conteudo
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        conteudo = payload.decode(charset, errors="replace") if payload else ""
        if msg.get_content_type() == "text/html":
            html = conteudo
        else:
            plain = conteudo
    # O corpo do aviso da Cora e HTML; o text/plain, quando vem, e o mesmo
    # texto sem marcacao. Vale o que tiver conteudo.
    if plain and plain.strip():
        return plain
    return _html_txt(html) if html else ""


# ===========================================================================
# Parser do aviso da Cora
# ===========================================================================

# "A transferência Pix feita de NH GTBA - 33.503.987/0001-16 no valor de
#  R$ 1000,08 para LUCILENE SILVA OLIVEIRA ALVES foi efetuada com sucesso :)"
_RE_ENVIO = re.compile(
    r"transfer[êe]ncia\s+pix\s+feita\s+de\s+(?P<pagador>.+?)\s+"
    r"no\s+valor\s+de\s+R\$\s*(?P<valor>[\d.,]+)\s+"
    r"para\s+(?P<favorecido>.+?)\s+foi\s+efetuada",
    re.IGNORECASE | re.DOTALL,
)


def num_br(valor):
    """'1.000,08' e '1000,08' viram 1000.08."""
    if valor is None:
        return None
    t = str(valor).strip().replace("R$", "").strip()
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".") if "," in t else t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def parse_envio(texto):
    """{'valor', 'favorecido', 'pagador'} do aviso, ou None se não for um."""
    if not texto:
        return None
    limpo = re.sub(r"\s+", " ", texto)
    m = _RE_ENVIO.search(limpo)
    if not m:
        return None
    valor = num_br(m.group("valor"))
    if not valor:
        return None
    return {
        "valor": valor,
        "favorecido": (m.group("favorecido") or "").strip()[:200],
        "pagador": (m.group("pagador") or "").strip()[:200],
    }


def _chave(nome):
    """Nome sem acento, sem pontuação e sem espaço dobrado, em maiúsculas.

    O nome no aviso do banco vem do cadastro da chave PIX; o nosso vem da
    tabela de clientes PIX. Sao digitados por gente diferente, entao comparar
    byte a byte erraria por um acento.
    """
    if not nome:
        return ""
    t = unicodedata.normalize("NFKD", str(nome))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip().upper()


def _buscar(dias=2, apenas_nao_lidos=True):
    """[(uid, message_id, assunto, quando, texto)] dos avisos do banco.

    Nao marca como lido: BODY.PEEK preserva o \\Seen, e marcar_lidos() so roda
    depois do commit. Assim uma falha de gravacao nunca come o e-mail calado.
    """
    host = _cfg("PIX_MAIL_IMAP_HOST", "imap.titan.email")
    port = int(_cfg("PIX_MAIL_IMAP_PORT", "993"))
    user = _cfg("PIX_MAIL_USER")
    pwd = _cfg("PIX_MAIL_PASSWORD")
    mailbox = _cfg("PIX_MAIL_MAILBOX", "INBOX")
    remetente = _cfg("PIX_MAIL_REMETENTE", REMETENTE_PADRAO)
    if not user or not pwd:
        _log.warning("[pix_mail] sem caixa: nem PIX_MAIL_USER/PASSWORD "
                     "nem ELS_MAIL_USER/PASSWORD estão configurados.")
        return []

    since = (date.today() - timedelta(days=dias)).strftime("%d-%b-%Y")
    partes = [f'FROM "{remetente}"', f'SENTSINCE {since}']
    if apenas_nao_lidos:
        partes.append("UNSEEN")
    criterio = "(" + " ".join(partes) + ")"

    M = imaplib.IMAP4_SSL(host, port)
    out = []
    try:
        M.login(user, pwd)
        M.select(mailbox)
        typ, dados = M.uid("SEARCH", None, criterio)
        if typ != "OK" or not dados or not dados[0]:
            return out
        for uid in dados[0].split():
            typ, raw = M.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not raw or raw[0] is None:
                continue
            msg = email.message_from_bytes(raw[0][1])
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            out.append((uid_str,
                        (msg.get("Message-ID") or "").strip()[:255],
                        _decode(msg.get("Subject", "")),
                        _quando(msg),
                        _texto_msg(msg)))
        return out
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()


def _quando(msg):
    """A hora do e-mail, no relógio de Brasília — é a hora em que o PIX saiu."""
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
    except Exception:
        return datetime.now()
    if dt is None:
        return datetime.now()
    try:
        import pytz
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(pytz.timezone("America/Sao_Paulo")).replace(tzinfo=None)
    except Exception:
        return dt.replace(tzinfo=None) if dt.tzinfo else dt


def marcar_lidos(uids):
    """Marca \\Seen SOMENTE os e-mails que já gravaram com sucesso."""
    if not uids:
        return
    host = _cfg("PIX_MAIL_IMAP_HOST", "imap.titan.email")
    port = int(_cfg("PIX_MAIL_IMAP_PORT", "993"))
    user = _cfg("PIX_MAIL_USER")
    pwd = _cfg("PIX_MAIL_PASSWORD")
    mailbox = _cfg("PIX_MAIL_MAILBOX", "INBOX")
    if not user or not pwd:
        return
    M = imaplib.IMAP4_SSL(host, port)
    try:
        M.login(user, pwd)
        M.select(mailbox)
        for uid in uids:
            M.uid("STORE", uid, "+FLAGS", "\\Seen")
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()


# ===========================================================================
# Casamento com a solicitação
# ===========================================================================

def casar(cur, valor, favorecido, quando, dias=None):
    """id da solicitação que esse comprovante paga, ou None.

    Casa por VALOR EXATO e NOME do favorecido, dentro de uma janela de dias
    para tras — o PIX sai no mesmo dia da solicitacao, mas o lancamento na
    tela pode vir depois.

    Uma solicitacao ja com comprovante nao entra: dois PIX iguais no mesmo dia
    para a mesma pessoa sao duas solicitacoes, e cada comprovante fica com a
    sua.
    """
    if dias is None:
        try:
            dias = int(_cfg("PIX_MATCH_DIAS", "3"))
        except ValueError:
            dias = 3
    fim = (quando or datetime.now()).date()
    ini = fim - timedelta(days=dias)
    cur.execute("""
        SELECT tp.id, tpc.nome_completo
          FROM troco_pix tp
          LEFT JOIN troco_pix_clientes tpc ON tpc.id = tp.troco_pix_cliente_id
          LEFT JOIN troco_pix_comprovantes cp ON cp.troco_pix_id = tp.id
         WHERE tp.data BETWEEN %s AND %s
           AND ABS(COALESCE(tp.troco_pix, 0) - %s) < 0.005
           AND cp.id IS NULL
         ORDER BY tp.data DESC, tp.id DESC
    """, (ini, fim, valor))
    alvo = _chave(favorecido)
    candidatos = cur.fetchall()
    for row in candidatos:
        rid = row["id"] if isinstance(row, dict) else row[0]
        nome = row["nome_completo"] if isinstance(row, dict) else row[1]
        if alvo and _chave(nome) == alvo:
            return rid
    # Sem nome batendo nao vale chutar pelo valor: o comprovante fica gravado
    # e sem dono, e aparece assim que a solicitacao certa for lancada.
    return None


def casar_orfaos(cur, dias=None):
    """Tenta dar dono aos comprovantes que chegaram antes da solicitação.

    Acontece o tempo todo: o PIX e feito na hora do pedido do frentista e a
    solicitacao e lancada na tela depois.
    """
    if dias is None:
        try:
            dias = int(_cfg("PIX_MATCH_DIAS", "3"))
        except ValueError:
            dias = 3
    cur.execute("""SELECT id, valor, favorecido, enviado_em
                     FROM troco_pix_comprovantes
                    WHERE troco_pix_id IS NULL
                      AND enviado_em >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    ORDER BY enviado_em""", (dias + 1,))
    casados = 0
    for row in list(cur.fetchall()):
        cid = row["id"] if isinstance(row, dict) else row[0]
        valor = float(row["valor"] if isinstance(row, dict) else row[1])
        favor = row["favorecido"] if isinstance(row, dict) else row[2]
        quando = row["enviado_em"] if isinstance(row, dict) else row[3]
        alvo = casar(cur, valor, favor, quando, dias)
        if alvo:
            cur.execute("UPDATE troco_pix_comprovantes SET troco_pix_id=%s WHERE id=%s",
                        (alvo, cid))
            casados += 1
    return casados


# ===========================================================================
# Rotina
# ===========================================================================

def processar(dias=2, apenas_nao_lidos=True):
    """Lê os avisos novos, grava e casa. Devolve o resumo do que aconteceu."""
    resumo = {"lidos": 0, "gravados": 0, "casados": 0, "repetidos": 0,
              "ignorados": 0}
    mensagens = _buscar(dias=dias, apenas_nao_lidos=apenas_nao_lidos)
    if not mensagens:
        return resumo
    ensure_tables()

    conn = cur = None
    ok_uids = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        for uid, msg_id, assunto, quando, texto in mensagens:
            resumo["lidos"] += 1
            dados = parse_envio(texto)
            if not dados:
                # Outro aviso qualquer do banco (PIX recebido, boleto, extrato).
                resumo["ignorados"] += 1
                ok_uids.append(uid)
                continue
            if not msg_id:
                # Sem Message-ID nao da pra garantir idempotencia; melhor
                # deixar o e-mail nao-lido do que gravar duas vezes amanha.
                resumo["ignorados"] += 1
                continue
            cur.execute("SELECT id FROM troco_pix_comprovantes WHERE message_id=%s",
                        (msg_id,))
            if cur.fetchone():
                resumo["repetidos"] += 1
                ok_uids.append(uid)
                continue
            alvo = casar(cur, dados["valor"], dados["favorecido"], quando, dias)
            cur.execute("""INSERT INTO troco_pix_comprovantes
                             (message_id, enviado_em, valor, favorecido, pagador,
                              assunto, troco_pix_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (msg_id, quando, dados["valor"], dados["favorecido"],
                         dados["pagador"], (assunto or "")[:255], alvo))
            resumo["gravados"] += 1
            if alvo:
                resumo["casados"] += 1
            ok_uids.append(uid)

        resumo["casados"] += casar_orfaos(cur, dias)
        conn.commit()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        _log.exception("[pix_mail] falha ao processar avisos de PIX")
        raise
    finally:
        for c in (cur, conn):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass

    # Só depois do commit: e-mail marcado como lido é e-mail que já está no
    # banco.
    try:
        marcar_lidos(ok_uids)
    except Exception:
        _log.exception("[pix_mail] gravou, mas não deu para marcar como lido")
    return resumo


def reprocessar(dias=7):
    """Relê inclusive os já lidos — para quando algo se perdeu no caminho."""
    return processar(dias=dias, apenas_nao_lidos=False)
