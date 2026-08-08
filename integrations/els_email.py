"""
integrations/els_email.py
=========================

Integração com o sistema de medição ELS (EXCELbr) VIA E-MAIL.

Lê a caixa que recebe as notificações do ELS (remetente
notificacao@sistemaels.com.br) e transforma DOIS tipos de e-mail em dados no
banco do app:

  1) "Fechamento de turno - ABERTURA"  -> LEITURA DIÁRIA DE TANQUE
        grava em `leitura_tanque_diaria` (uma linha por tanque por dia)
        campo-chave: "Volume atual"

  2) "Alarme descarga"                 -> ENTRADA DE MERCADORIA (DESCARGA)
        grava em `descargas_pendentes` SEMPRE como 'pendente'
        campo-chave: "Total da descarga"
        O vinculo correto e com a NF-e DE COMPRA e e feito pelo usuario na
        tela /estoque (Camada 2). Este modulo nao vincula nada sozinho.

Segue os padrões do app: usa utils.db.get_db_connection(), cria as tabelas de
forma idempotente (como routes/descargas.py) e é chamado pelo agendador
integrations/els_scheduler.py.

Configuração (variáveis de ambiente — configurar no Render):
    ELS_MAIL_IMAP_HOST   (default imap.titan.email)
    ELS_MAIL_IMAP_PORT   (default 993)
    ELS_MAIL_USER        (ex.: goiatuba@postonovohorizonte.com.br)
    ELS_MAIL_PASSWORD    (senha de app do provedor)
    ELS_MAIL_MAILBOX     (default INBOX)
    ELS_REMETENTE        (default notificacao@sistemaels.com.br)
    ELS_CLIENTE_ID       (id do posto na tabela clientes — OBRIGATÓRIO)
    ELS_MATCH_TOLERANCIA (litros de tolerância no casamento de frete; default 500)
    ELS_MATCH_JANELA_DIAS(janela de dias p/ procurar o frete; default 5)
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from html.parser import HTMLParser
from typing import Optional

from utils.db import get_db_connection

_log = logging.getLogger(__name__)

REMETENTE_PADRAO = "notificacao@sistemaels.com.br"


# ===========================================================================
# Configuração
# ===========================================================================

def _cfg(nome, default=None):
    return os.environ.get(nome, default)


def _cliente_id() -> Optional[int]:
    v = _cfg("ELS_CLIENTE_ID")
    try:
        return int(v) if v else None
    except ValueError:
        return None


# ===========================================================================
# Criação idempotente das tabelas (padrão de routes/descargas.py)
# ===========================================================================

def ensure_tables():
    """Cria leitura_tanque_diaria e descargas_pendentes se não existirem."""
    ddl_leitura = """
    CREATE TABLE IF NOT EXISTS `leitura_tanque_diaria` (
        `id`             INT AUTO_INCREMENT PRIMARY KEY,
        `cliente_id`     INT NULL,
        `data_leitura`   DATETIME NOT NULL COMMENT 'Data+hora exata da leitura (05:00, 12:30, 23:30...)',
        `titulo`         VARCHAR(40) NULL COMMENT 'Titulo do e-mail (ex.: ABERTURA)',
        `tanque`         INT NOT NULL,
        `produto_id`     INT NULL,
        `produto_nome`   VARCHAR(80) NULL,
        `volume_atual`   DECIMAL(14,3) NULL COMMENT 'Estoque inicial do dia (Volume atual)',
        `volume_20c`     DECIMAL(14,3) NULL,
        `capacidade`     DECIMAL(14,3) NULL,
        `volume_livre`   DECIMAL(14,3) NULL,
        `altura_mm`      DECIMAL(10,2) NULL,
        `agua_mm`        DECIMAL(10,2) NULL,
        `temperatura`    DECIMAL(6,2) NULL,
        `origem`         VARCHAR(30) NOT NULL DEFAULT 'els_email',
        `criado_em`      DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY `uq_leitura_dia_tanque` (`cliente_id`, `data_leitura`, `tanque`),
        INDEX `idx_leitura_data` (`data_leitura`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    ddl_pend = """
    CREATE TABLE IF NOT EXISTS `descargas_pendentes` (
        `id`               INT AUTO_INCREMENT PRIMARY KEY,
        `cliente_id`       INT NULL,
        `tanque`           INT NULL,
        `produto_nome`     VARCHAR(80) NULL,
        `produto_id`       INT NULL,
        `data_descarga`    DATE NULL,
        `data_inicial`     DATETIME NULL,
        `data_final`       DATETIME NULL,
        `volume_inicial`   DECIMAL(14,3) NULL,
        `volume_final`     DECIMAL(14,3) NULL,
        `total_descarga`   DECIMAL(14,3) NULL COMMENT 'Entrada de mercadoria (litros)',
        `total_descarga_20c` DECIMAL(14,3) NULL,
        `status`           ENUM('pendente','vinculada','ignorada') NOT NULL DEFAULT 'pendente',
        `frete_id`         INT NULL,
        `descarga_id`      INT NULL,
        `chave`            VARCHAR(64) NOT NULL COMMENT 'idempotência: tanque+data_final',
        `criado_em`        DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY `uq_pend_chave` (`chave`),
        INDEX `idx_pend_status` (`status`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(ddl_leitura)
        cur.execute(ddl_pend)
        conn.commit()
    except Exception:
        _log.warning("[els] falha ao criar tabelas ELS (não crítico).", exc_info=True)
    finally:
        cur.close()
        conn.close()


# ===========================================================================
# Modelos de dados extraídos do e-mail
# ===========================================================================

@dataclass
class MedicaoTanque:
    tanque: Optional[int] = None
    produto: Optional[str] = None
    capacidade_l: Optional[float] = None
    volume_livre_l: Optional[float] = None
    volume_atual_l: Optional[float] = None
    volume_atual_20c_l: Optional[float] = None
    altura_mm: Optional[float] = None
    agua_mm: Optional[float] = None
    temperatura_c: Optional[float] = None


@dataclass
class Abertura:
    data_hora: Optional[datetime] = None
    titulo: Optional[str] = None
    tanques: list = field(default_factory=list)


@dataclass
class Descarga:
    tanque: Optional[int] = None
    produto: Optional[str] = None
    capacidade_l: Optional[float] = None
    data_inicial: Optional[datetime] = None
    data_final: Optional[datetime] = None
    volume_inicial_l: Optional[float] = None
    volume_final_l: Optional[float] = None
    volume_livre_l: Optional[float] = None
    total_descarga_l: Optional[float] = None
    total_descarga_20c_l: Optional[float] = None


# ===========================================================================
# Parsing (validado contra e-mails reais do ELS)
# ===========================================================================

class _HTMLToText(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "tr", "li"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "tr", "li"):
            self._parts.append("\n")

    def get_text(self):
        return "".join(self._parts)


def _html_txt(html):
    p = _HTMLToText()
    p.feed(html)
    return p.get_text()


def num_br(valor):
    """'14.660 L' -> 14660.0 ; '4.959 L' -> 4959.0 ; ponto=milhar, vírgula=decimal."""
    if valor is None:
        return None
    limpo = re.sub(r"[^0-9,.\-]", "", str(valor).strip())
    if limpo in ("", "-", ".", ","):
        return None
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


def dt_br(valor):
    if not valor:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor.strip(), fmt)
        except ValueError:
            continue
    return None


def _campo(bloco, chave):
    padrao = re.compile(r"^\s*" + re.escape(chave) + r"\s*:\s*(.+?)\s*$",
                        re.IGNORECASE | re.MULTILINE)
    m = padrao.search(bloco)
    return m.group(1).strip() if m else None


def _num_tanque(valor):
    if not valor:
        return None
    m = re.match(r"\s*(\d+)", valor)
    return int(m.group(1)) if m else None


def _produto_de(valor):
    if not valor:
        return None
    return valor.split(" - ", 1)[1].strip() if " - " in valor else valor.strip()


def detectar_tipo(assunto, texto):
    alvo = f"{assunto}\n{texto[:150]}".lower()
    if "alarme descarga" in alvo or "descarga" in assunto.lower():
        return "DESCARGA"
    if "abertura" in alvo and "fechamento de turno" in alvo:
        return "ABERTURA"
    if "abertura" in assunto.lower():
        return "ABERTURA"
    return None


def parse_abertura(texto) -> Abertura:
    r = Abertura()
    r.data_hora = dt_br(_campo(texto, "Data/Hora"))
    r.titulo = _campo(texto, "Título") or _campo(texto, "Titulo")
    blocos = re.split(r"(?=^\s*Tanque\s*:\s*\d)", texto, flags=re.MULTILINE)
    for bloco in blocos:
        if not re.search(r"^\s*Tanque\s*:\s*\d", bloco, flags=re.MULTILINE):
            continue
        tv = _campo(bloco, "Tanque")
        t = MedicaoTanque(
            tanque=_num_tanque(tv),
            produto=_campo(bloco, "Produto") or _produto_de(tv),
            capacidade_l=num_br(_campo(bloco, "Capacidade")),
            volume_livre_l=num_br(_campo(bloco, "Volume livre")),
            volume_atual_20c_l=num_br(_campo(bloco, "Volume atual (20°C)")),
            volume_atual_l=num_br(_campo(bloco, "Volume atual")),
            altura_mm=num_br(_campo(bloco, "Altura")),
            agua_mm=num_br(_campo(bloco, "Água")),
            temperatura_c=num_br(_campo(bloco, "Temperatura")),
        )
        if t.tanque is not None:
            r.tanques.append(t)
    return r


def parse_descarga(texto) -> Optional[Descarga]:
    if "descarga" not in texto.lower():
        return None
    tv = _campo(texto, "Tanque")
    d = Descarga(
        tanque=_num_tanque(tv),
        produto=_produto_de(tv),
        capacidade_l=num_br(_campo(texto, "Capacidade")),
        data_inicial=dt_br(_campo(texto, "Data Inicial")),
        data_final=dt_br(_campo(texto, "Data Final")),
        volume_inicial_l=num_br(_campo(texto, "Volume inicial")),
        volume_final_l=num_br(_campo(texto, "Volume final")),
        volume_livre_l=num_br(_campo(texto, "Volume Livre")),
        total_descarga_20c_l=num_br(_campo(texto, "Total da descarga(20C)")),
        total_descarga_l=num_br(_campo(texto, "Total da descarga")),
    )
    return d if d.tanque is not None else None


# ===========================================================================
# IMAP
# ===========================================================================

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
    if plain and plain.strip():
        return plain
    return _html_txt(html) if html else ""


def _buscar(cfg_dias=1, apenas_nao_lidos=True):
    """Retorna [(uid, assunto, texto)] das mensagens do ELS.

    NAO marca como lida: a marcacao e feita por marcar_lidos(), somente apos a
    gravacao ter dado commit com sucesso. Assim um erro de gravacao NUNCA
    consome o e-mail em silencio (ele fica nao-lido e e reprocessado).
    Usa UID (identificador estavel) para casar com marcar_lidos().
    """
    host = _cfg("ELS_MAIL_IMAP_HOST", "imap.titan.email")
    port = int(_cfg("ELS_MAIL_IMAP_PORT", "993"))
    user = _cfg("ELS_MAIL_USER")
    pwd = _cfg("ELS_MAIL_PASSWORD")
    mailbox = _cfg("ELS_MAIL_MAILBOX", "INBOX")
    remetente = _cfg("ELS_REMETENTE", REMETENTE_PADRAO)
    if not user or not pwd:
        _log.warning("[els] ELS_MAIL_USER / ELS_MAIL_PASSWORD não configurados.")
        return []

    since = (date.today() - timedelta(days=cfg_dias)).strftime("%d-%b-%Y")
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
            # BODY.PEEK[] traz a mensagem inteira SEM setar \Seen. Um FETCH
            # RFC822/BODY[] marcaria o e-mail como lido como efeito colateral,
            # sabotando a idempotencia (a marcacao e feita so por marcar_lidos,
            # apos gravar com sucesso).
            typ, raw = M.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not raw or raw[0] is None:
                continue
            msg = email.message_from_bytes(raw[0][1])
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            out.append((uid_str, _decode(msg.get("Subject", "")), _texto_msg(msg)))
        return out
    finally:
        try:
            M.close()
        except Exception:
            pass
        M.logout()


def marcar_lidos(uids):
    """Marca \\Seen SOMENTE os e-mails cujos UIDs gravaram com sucesso."""
    if not uids:
        return
    host = _cfg("ELS_MAIL_IMAP_HOST", "imap.titan.email")
    port = int(_cfg("ELS_MAIL_IMAP_PORT", "993"))
    user = _cfg("ELS_MAIL_USER")
    pwd = _cfg("ELS_MAIL_PASSWORD")
    mailbox = _cfg("ELS_MAIL_MAILBOX", "INBOX")
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
# Resolução de produto e casamento de frete
# ===========================================================================

def resolver_produto_id(cur, nome):
    """Mapeia o nome do produto do e-mail para produto.id (match tolerante)."""
    if not nome:
        return None, None
    cur.execute("SELECT id, nome FROM produto")
    rows = cur.fetchall()
    alvo = nome.strip().upper()
    # 1) match exato
    for r in rows:
        if (r["nome"] or "").strip().upper() == alvo:
            return r["id"], r["nome"]
    # 2) contém (ex.: 'GASOLINA COMUM' casa 'GASOLINA')
    for r in rows:
        pn = (r["nome"] or "").strip().upper()
        if pn and (pn in alvo or alvo in pn):
            return r["id"], r["nome"]
    # 3) por palavra-chave principal
    for chave in ("GASOLINA", "ETANOL", "DIESEL S10", "DIESEL S500", "DIESEL", "ARLA"):
        if chave in alvo:
            for r in rows:
                if chave in (r["nome"] or "").strip().upper():
                    return r["id"], r["nome"]
    return None, None


# ---------------------------------------------------------------------------
# REMOVIDO: casar_frete()
#
# Ate 07/08/2026 este modulo tentava casar cada descarga automaticamente com a
# tabela `fretes`. Estava ERRADO: `fretes` e o controle interno de COBRANCA e
# nao tem relacao com a entrada de estoque. Pior, quando casava o codigo ainda
# INSERIA uma linha em `descargas` com status='finalizado', poluindo o controle
# interno com descargas que ninguem lancou.
#
# Agora a descarga nasce sempre 'pendente' e quem vincula e o usuario, contra a
# NF-e DE COMPRA, na tela /estoque (integrations/descarga_vinculo.py). O git
# guarda a versao antiga da funcao se algum dia ela fizer falta.
#
# Ficaram sem uso as configs ELS_MATCH_JANELA_DIAS e ELS_MATCH_TOLERANCIA — os
# mesmos nomes/valores viraram os defaults de descarga_vinculo.py.
# ---------------------------------------------------------------------------


# ===========================================================================
# Gravação
# ===========================================================================

def gravar_abertura(cur, ab: Abertura, cliente_id):
    # NAO truncar para .date(): preserva a hora exata da leitura (05:00, 12:30,
    # 23:30...) para guardar TODAS as medicoes do dia como registros separados.
    data_leitura = (ab.data_hora or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    titulo = ab.titulo
    n = 0
    for t in ab.tanques:
        produto_id, _ = resolver_produto_id(cur, t.produto)
        cur.execute(
            """
            INSERT INTO leitura_tanque_diaria
              (cliente_id, data_leitura, titulo, tanque, produto_id, produto_nome,
               volume_atual, volume_20c, capacidade, volume_livre,
               altura_mm, agua_mm, temperatura, origem)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'els_email')
            ON DUPLICATE KEY UPDATE
               titulo=VALUES(titulo),
               produto_id=VALUES(produto_id), produto_nome=VALUES(produto_nome),
               volume_atual=VALUES(volume_atual), volume_20c=VALUES(volume_20c),
               capacidade=VALUES(capacidade), volume_livre=VALUES(volume_livre),
               altura_mm=VALUES(altura_mm), agua_mm=VALUES(agua_mm),
               temperatura=VALUES(temperatura)
            """,
            (cliente_id, data_leitura, titulo, t.tanque, produto_id, t.produto,
             t.volume_atual_l, t.volume_atual_20c_l, t.capacidade_l,
             t.volume_livre_l, t.altura_mm, t.agua_mm, t.temperatura_c),
        )
        n += 1
    return n


def gravar_descarga(cur, dc: Descarga, cliente_id):
    """Grava em descargas_pendentes SEMPRE como 'pendente'.

    NAO casa mais com `fretes` e NAO cria linha em `descargas` (ver o bloco
    "REMOVIDO: casar_frete()" acima). O vinculo certo e com a NF-e de compra e
    quem faz e o usuario, na tela /estoque.
    """
    chave = f"{dc.tanque}-{(dc.data_final or dc.data_inicial or datetime.now()).strftime('%Y%m%d%H%M%S')}"
    produto_id, _ = resolver_produto_id(cur, dc.produto)
    data_ref = (dc.data_final or dc.data_inicial or datetime.now()).date()

    # idempotência: se já existe essa chave, não reprocessa
    cur.execute("SELECT id, status FROM descargas_pendentes WHERE chave=%s", (chave,))
    if cur.fetchone():
        return "duplicada"

    # frete_id/descarga_id continuam NULL: as colunas seguem no banco (dados
    # antigos preservados), mas o fluxo novo nao as preenche nem as exibe.
    frete_id = None
    descarga_id = None
    status = "pendente"

    cur.execute(
        """
        INSERT INTO descargas_pendentes
          (cliente_id, tanque, produto_nome, produto_id, data_descarga,
           data_inicial, data_final, volume_inicial, volume_final,
           total_descarga, total_descarga_20c, status, frete_id, descarga_id, chave)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (cliente_id, dc.tanque, dc.produto, produto_id,
         data_ref.strftime("%Y-%m-%d"), dc.data_inicial, dc.data_final,
         dc.volume_inicial_l, dc.volume_final_l, dc.total_descarga_l,
         dc.total_descarga_20c_l, status, frete_id, descarga_id, chave),
    )
    return status


# ===========================================================================
# Orquestração (chamada pelo scheduler)
# ===========================================================================

def processar(dias=1):
    """Busca e-mails novos do ELS, roteia por tipo e grava. Retorna um resumo."""
    ensure_tables()
    cliente_id = _cliente_id()
    if cliente_id is None:
        _log.warning("[els] ELS_CLIENTE_ID não configurado; abortando.")
        return {"erro": "ELS_CLIENTE_ID ausente"}

    resumo = {"aberturas": 0, "leituras": 0, "descargas_vinculadas": 0,
              "descargas_pendentes": 0, "ignorados": 0}
    mensagens = _buscar(cfg_dias=dias, apenas_nao_lidos=True)
    if not mensagens:
        return resumo

    ok_uids = []  # so os e-mails gravados com sucesso -> marcados lidos no fim
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for uid, assunto, texto in mensagens:
            tipo = detectar_tipo(assunto, texto)
            try:
                if tipo == "ABERTURA":
                    ab = parse_abertura(texto)
                    resumo["leituras"] += gravar_abertura(cur, ab, cliente_id)
                    resumo["aberturas"] += 1
                    conn.commit()
                elif tipo == "DESCARGA":
                    dc = parse_descarga(texto)
                    if dc:
                        st = gravar_descarga(cur, dc, cliente_id)
                        if st == "vinculada":
                            resumo["descargas_vinculadas"] += 1
                        elif st == "pendente":
                            resumo["descargas_pendentes"] += 1
                        conn.commit()
                    else:
                        resumo["ignorados"] += 1
                else:
                    resumo["ignorados"] += 1
                # Chegou aqui sem excecao (gravou ou foi ignorado deliberadamente):
                # pode marcar como lido. Falhas caem no except e NAO marcam.
                ok_uids.append(uid)
            except Exception:
                conn.rollback()
                _log.warning("[els] falha ao processar '%s'.", assunto, exc_info=True)
    finally:
        cur.close()
        conn.close()
    marcar_lidos(ok_uids)  # so os UIDs que gravaram; falhas ficam nao-lidas
    _log.info("[els] resumo: %s", resumo)
    return resumo
