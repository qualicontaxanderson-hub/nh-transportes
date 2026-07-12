# -*- coding: utf-8 -*-
# ============================================================================
#  PROCESSA UM LOTE de DFe da SEFAZ (distDFeInt) e SALVA. ISOLADO.
#
#  SO CONSULTA E SALVA -- NUNCA manifesta (nenhuma ciencia/confirmacao/evento).
#  Faz UMA unica consulta (1 lote de ate 50 docs), processa, grava e ENCERRA.
#  NAO faz loop de varios lotes (isso e o proximo passo).
#
#  Reaproveita TODA a cadeia ja validada em scripts/consulta_sefaz.py
#  (abrir certificado A1, mTLS em memoria, montar SOAP, requisicao). So adiciona
#  o processamento/gravacao por cima.
#
#  Gravacao:
#    - dfe_documentos : 1 linha por NOTA (nfeProc). Idempotente (UNIQUE chave).
#    - dfe_itens      : itens da nota. Idempotente (UNIQUE documento_id,n_item).
#    - dfe_eventos    : 1 linha por EVENTO (procEventoNFe). Tabela NOVA isolada;
#                       criada aqui com CREATE TABLE IF NOT EXISTS. Idempotente
#                       (UNIQUE chave_evento). dfe_documentos fica SO com notas.
#                       Cancelamento (tpEvento=110111) tambem faz
#                       UPDATE dfe_documentos SET situacao='cancelada'
#                       WHERE chave = <chNFe da nota afetada>.
#    - dfe_nsu        : avanca ult_nsu/max_nsu, ult_consulta, ult_status.
#
#  Resumos (resNFe/resEvento) sao REDUNDANTES: so contados, nunca gravados.
#  Transacao por documento: erro em 1 doc faz rollback so dele, loga e segue.
#  XML de cada doc guardado sobe pro Dropbox ANTES de gravar no banco.
# ============================================================================
import os
import sys
import gzip
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Raiz do projeto E a pasta scripts/ no sys.path (para importar consulta_sefaz).
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_SCRIPTS)
for _p in (_RAIZ, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import pymysql

# Reaproveita TUDO do script de consulta que ja funcionou (cStat 138).
import consulta_sefaz as cs
from integrations.dropbox_dfe import montar_caminho, upload_xml

# Retencao placeholder do XML (definitiva sera decidida depois).
DIAS_RETENCAO = 90

# tpEvento de cancelamento de NF-e.
TP_CANCELAMENTO = "110111"


# ==========================================================================
# DDL da tabela NOVA e ISOLADA de eventos (idempotente).
#   dfe_documentos = SO notas. Eventos ficam aqui, com chave propria.
# ==========================================================================
DDL_EVENTOS = """
CREATE TABLE IF NOT EXISTS dfe_eventos (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id    INT           NOT NULL,
    chave_evento  VARCHAR(60)   NOT NULL,   -- Id do evento (ID+tpEvento+chNFe+nSeq)
    ch_nfe        CHAR(44)      NOT NULL,   -- chave da NOTA afetada
    tp_evento     VARCHAR(6)    NULL,       -- ex.: 110111 = cancelamento
    n_seq         INT           NULL,
    descricao     VARCHAR(160)  NULL,       -- descEvento / xEvento
    dh_evento     DATETIME      NULL,
    nsu           BIGINT        NULL,
    schema_dfe    VARCHAR(40)   NULL,
    org_cnpj      VARCHAR(14)   NULL,       -- CNPJ do autor do evento
    xml_caminho   VARCHAR(300)  NULL,
    xml_expira_em DATE          NULL,
    criado_em     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_chave_evento (chave_evento),
    KEY ix_chnfe (ch_nfe),
    KEY ix_tp (tp_evento),
    KEY ix_expira (xml_expira_em)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


# ==========================================================================
# Helpers de parsing (namespaces ignorados; busca por nome local).
# Reaproveita cs._find / cs._text / cs._local.
# ==========================================================================
def _digitos(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _to_int(v):
    d = _digitos(v)
    return int(d) if d else None


def _parse_dh(s):
    """'2026-07-01T10:20:30-03:00' -> ('2026-07-01 10:20:30', 2026, 7)."""
    if not s:
        return None, None, None
    core = s.strip()[:19]  # YYYY-MM-DDTHH:MM:SS
    try:
        dt = datetime.strptime(core, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None, None, None
    return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.year, dt.month


def _chave_de_infnfe(infnfe_el):
    """Extrai a chave 44 do atributo Id (ex.: 'NFe5226...') do infNFe."""
    if infnfe_el is None:
        return None
    idv = infnfe_el.get("Id") or infnfe_el.get("id") or ""
    ch = _digitos(idv)
    return ch if len(ch) == 44 else (ch[-44:] if len(ch) > 44 else None)


# ==========================================================================
# Extracao de uma NOTA (nfeProc) -> dict de cabecalho + lista de itens.
# ==========================================================================
def extrair_nota(root):
    infnfe = cs._find(root, "infNFe")
    chave = _chave_de_infnfe(infnfe)
    if not chave:
        # fallback: chNFe dentro do protNFe
        chave = _digitos(cs._text(root, "chNFe"))
        chave = chave if len(chave) == 44 else None
    if not chave:
        raise ValueError("nota sem chave de 44 digitos (infNFe/protNFe)")

    ide = cs._find(root, "ide")
    numero = cs._text(ide, "nNF") if ide is not None else None
    serie = cs._text(ide, "serie") if ide is not None else None
    modelo = cs._text(ide, "mod") if ide is not None else None
    dh_txt, ano, mes = _parse_dh(cs._text(ide, "dhEmi") if ide is not None else None)

    emit = cs._find(root, "emit")
    emit_cnpj = _digitos(cs._text(emit, "CNPJ")) if emit is not None else None
    emit_nome = cs._text(emit, "xNome") if emit is not None else None
    if emit_nome:
        emit_nome = emit_nome[:160]

    dest = cs._find(root, "dest")
    dest_cnpj = None
    if dest is not None:
        dest_cnpj = _digitos(cs._text(dest, "CNPJ") or cs._text(dest, "CPF")) or None

    total = cs._find(root, "ICMSTot")
    valor_total = cs._text(total, "vNF") if total is not None else cs._text(root, "vNF")

    # Situacao a partir do protNFe (100/150 autorizado; 11x/30x denegada).
    prot = cs._find(root, "protNFe")
    cstat_prot = cs._text(prot, "cStat") if prot is not None else None
    situacao = "autorizado"
    if cstat_prot in ("110", "301", "302", "303"):
        situacao = "denegada"

    # Itens (det).
    itens = []
    for det in root.iter():
        if cs._local(det.tag) != "det":
            continue
        prod = cs._find(det, "prod")
        if prod is None:
            continue
        itens.append({
            "n_item": _to_int(det.get("nItem")) or (len(itens) + 1),
            "produto_xml": (cs._text(prod, "xProd") or "")[:160] or None,
            # cProd = codigo do produto no sistema do FORNECEDOR (emit_cnpj).
            # cEAN = GTIN/EAN (codigo de barras); pode vir 'SEM GTIN'.
            # Juntos com emit_cnpj (no cabecalho) alimentam o de-para futuro
            # CNPJ+cProd -> meu produto.
            "cprod_fornecedor": (cs._text(prod, "cProd") or "")[:60] or None,
            "cean": (cs._text(prod, "cEAN") or "")[:20] or None,
            "cod_anp": cs._text(prod, "cProdANP"),   # so combustivel
            "ncm": cs._text(prod, "NCM"),
            "unidade": (cs._text(prod, "uCom") or "")[:6] or None,
            "quantidade": cs._text(prod, "qCom"),
            "valor_unitario": cs._text(prod, "vUnCom"),
            "valor_total": cs._text(prod, "vProd"),
        })

    return {
        "chave": chave, "tipo": "NFe", "numero": numero, "serie": serie,
        "modelo": modelo, "dh_txt": dh_txt, "ano": ano, "mes": mes,
        "emit_cnpj": emit_cnpj, "emit_nome": emit_nome, "dest_cnpj": dest_cnpj,
        "valor_total": valor_total, "situacao": situacao, "itens": itens,
    }


# ==========================================================================
# Extracao de um EVENTO (procEventoNFe) -> dict.
# ==========================================================================
def extrair_evento(root):
    inf = cs._find(root, "infEvento")
    idv = (inf.get("Id") or inf.get("id") or "") if inf is not None else ""
    chave_evento = idv.strip() or None

    ch_nfe = _digitos(cs._text(inf, "chNFe")) if inf is not None else None
    ch_nfe = ch_nfe if (ch_nfe and len(ch_nfe) == 44) else None
    tp_evento = cs._text(inf, "tpEvento") if inf is not None else None
    n_seq = _to_int(cs._text(inf, "nSeqEvento")) if inf is not None else None
    org_cnpj = _digitos(cs._text(inf, "CNPJ")) if inf is not None else None
    dh_txt, ano, mes = _parse_dh(cs._text(inf, "dhEvento") if inf is not None else None)

    # descricao: descEvento (detEvento) ou xEvento (retEvento).
    descricao = cs._text(root, "descEvento") or cs._text(root, "xEvento")
    if descricao:
        descricao = descricao[:160]

    if not chave_evento:
        # fallback: monta a chave a partir das partes (ID+tpEvento+chNFe+nSeq)
        if tp_evento and ch_nfe and n_seq is not None:
            chave_evento = f"ID{tp_evento}{ch_nfe}{str(n_seq).zfill(2)}"
        else:
            raise ValueError("evento sem Id/chave_evento identificavel")

    return {
        "chave_evento": chave_evento[:60], "ch_nfe": ch_nfe, "tp_evento": tp_evento,
        "n_seq": n_seq, "org_cnpj": org_cnpj, "descricao": descricao,
        "dh_txt": dh_txt, "ano": ano, "mes": mes,
    }


# ==========================================================================
# Extracao de um RESUMO de nota (resNFe) -> dict de cabecalho (sem itens).
# O resNFe so traz: chNFe, CNPJ/CPF+xNome do emitente, dhEmi, tpNF, vNF e
# cSitNFe. numero/serie/modelo saem da propria chave (posicoes fixas).
# ==========================================================================
def extrair_resumo_nota(root):
    chave = _digitos(cs._text(root, "chNFe"))
    if len(chave) != 44:
        raise ValueError("resNFe sem chNFe de 44 digitos")

    # chave = cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3) nNF(9) tpEmis(1) cNF(8) cDV(1)
    modelo = chave[20:22]
    serie = chave[22:25].lstrip("0") or "0"
    numero = chave[25:34].lstrip("0") or "0"

    dh_txt, ano, mes = _parse_dh(cs._text(root, "dhEmi"))
    emit_cnpj = _digitos(cs._text(root, "CNPJ") or cs._text(root, "CPF")) or None
    emit_nome = cs._text(root, "xNome")
    if emit_nome:
        emit_nome = emit_nome[:160]
    valor_total = cs._text(root, "vNF")

    # cSitNFe: 1=autorizada, 2=denegada, 3=cancelada.
    csit = cs._text(root, "cSitNFe")
    situacao = {"1": "autorizado", "2": "denegada", "3": "cancelada"}.get(csit, "autorizado")

    return {
        "chave": chave, "tipo": "NFe", "numero": numero, "serie": serie,
        "modelo": modelo, "dh_txt": dh_txt, "ano": ano, "mes": mes,
        "emit_cnpj": emit_cnpj, "emit_nome": emit_nome,
        "valor_total": valor_total, "situacao": situacao,
    }


# ==========================================================================
# De-para ANP -> produto_id: NAO ha tabela-fonte dedicada (produto so tem
# id/nome/descricao). Reaproveita mapeamentos JA resolvidos em vendas_xml_itens
# e dfe_itens. Retorna None se nao houver de-para conhecido (deixa NULL).
# ==========================================================================
def resolver_produto_id(cur, cod_anp):
    if not cod_anp:
        return None
    cur.execute(
        "SELECT produto_id FROM vendas_xml_itens "
        "WHERE cod_anp = %s AND produto_id IS NOT NULL "
        "GROUP BY produto_id ORDER BY COUNT(*) DESC LIMIT 1",
        (cod_anp,),
    )
    row = cur.fetchone()
    if row and row.get("produto_id"):
        return row["produto_id"]
    cur.execute(
        "SELECT produto_id FROM dfe_itens "
        "WHERE cod_anp = %s AND produto_id IS NOT NULL "
        "GROUP BY produto_id ORDER BY COUNT(*) DESC LIMIT 1",
        (cod_anp,),
    )
    row = cur.fetchone()
    return row["produto_id"] if (row and row.get("produto_id")) else None


# ==========================================================================
# SQLs (parametrizados).
# ==========================================================================
SQL_DOC_UPSERT = (
    "INSERT INTO dfe_documentos "
    "(cliente_id, chave, tipo, nsu, schema_dfe, resumo, numero, serie, modelo, "
    " dh_emissao, emit_cnpj, emit_nome, dest_cnpj, valor_total, situacao, "
    " xml_caminho, xml_expira_em) "
    "VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  nsu=VALUES(nsu), schema_dfe=VALUES(schema_dfe), numero=VALUES(numero), "
    "  serie=VALUES(serie), modelo=VALUES(modelo), dh_emissao=VALUES(dh_emissao), "
    "  emit_cnpj=VALUES(emit_cnpj), emit_nome=VALUES(emit_nome), "
    "  dest_cnpj=VALUES(dest_cnpj), valor_total=VALUES(valor_total), "
    "  xml_caminho=VALUES(xml_caminho), xml_expira_em=VALUES(xml_expira_em), "
    "  resumo=VALUES(resumo)"   # nota COMPLETA chegou: se a linha era resumo(1), vira 0
    # NAO mexe em situacao no UPDATE: preserva 'cancelada' setada por evento.
)

# Upsert de RESUMO de nota (resNFe). Grava resumo=1 com os poucos campos que o
# resNFe traz (chave, emitente, valor, data). Se a chave JA existe (nota completa
# ou outro resumo), NAO sobrescreve nada -- uma nota completa vale mais que um
# resumo. Assim a nota de compra aparece em /dfe/compras mesmo sem o XML cheio.
SQL_RESUMO_UPSERT = (
    "INSERT INTO dfe_documentos "
    "(cliente_id, chave, tipo, nsu, schema_dfe, resumo, numero, serie, modelo, "
    " dh_emissao, emit_cnpj, emit_nome, dest_cnpj, valor_total, situacao, "
    " xml_caminho, xml_expira_em) "
    "VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL) "
    "ON DUPLICATE KEY UPDATE chave=chave"   # no-op: nunca rebaixa nota completa
)

SQL_DOC_ID = "SELECT id FROM dfe_documentos WHERE chave = %s"

SQL_ITEM_UPSERT = (
    "INSERT INTO dfe_itens "
    "(documento_id, n_item, produto_xml, cprod_fornecedor, cean, cod_anp, "
    " produto_id, ncm, unidade, quantidade, valor_unitario, valor_total) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  produto_xml=VALUES(produto_xml), cprod_fornecedor=VALUES(cprod_fornecedor), "
    "  cean=VALUES(cean), cod_anp=VALUES(cod_anp), produto_id=VALUES(produto_id), "
    "  ncm=VALUES(ncm), unidade=VALUES(unidade), quantidade=VALUES(quantidade), "
    "  valor_unitario=VALUES(valor_unitario), valor_total=VALUES(valor_total)"
)

SQL_EVENTO_UPSERT = (
    "INSERT INTO dfe_eventos "
    "(cliente_id, chave_evento, ch_nfe, tp_evento, n_seq, descricao, dh_evento, "
    " nsu, schema_dfe, org_cnpj, xml_caminho, xml_expira_em) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  descricao=VALUES(descricao), dh_evento=VALUES(dh_evento), nsu=VALUES(nsu), "
    "  schema_dfe=VALUES(schema_dfe), org_cnpj=VALUES(org_cnpj), "
    "  xml_caminho=VALUES(xml_caminho), xml_expira_em=VALUES(xml_expira_em)"
)

SQL_CANCELA_NOTA = (
    "UPDATE dfe_documentos SET situacao='cancelada' WHERE chave = %s"
)

# IMPORTANTE (timezone): ult_consulta e proximo_permitido usam SEMPRE o relogio
# do BANCO (NOW()), nunca datetime.now() do processo. Assim a cota funciona igual
# rodando aqui no Windows (horario local) ou no container do Railway (UTC) -- os
# dois leem/gravam no mesmo relogio, sem divergencia de fuso.
#
# SQL_NSU_OK   : sucesso/normal -> limpa a espera (proximo_permitido = NULL)
# SQL_NSU_656  : consumo indevido -> agenda espera de 1h a partir de NOW()
# Ambos com a MESMA assinatura de 5 parametros:
#   (cliente_id, cnpj, ult_nsu, max_nsu, ult_status)
SQL_NSU_OK = (
    "INSERT INTO dfe_nsu "
    "(cliente_id, cnpj, ult_nsu, max_nsu, ult_consulta, proximo_permitido, ult_status) "
    "VALUES (%s,%s,%s,%s,NOW(),NULL,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  ult_nsu=VALUES(ult_nsu), max_nsu=VALUES(max_nsu), "
    "  ult_consulta=NOW(), proximo_permitido=NULL, ult_status=VALUES(ult_status)"
)

SQL_NSU_656 = (
    "INSERT INTO dfe_nsu "
    "(cliente_id, cnpj, ult_nsu, max_nsu, ult_consulta, proximo_permitido, ult_status) "
    "VALUES (%s,%s,%s,%s,NOW(),NOW() + INTERVAL 1 HOUR,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  ult_nsu=VALUES(ult_nsu), max_nsu=VALUES(max_nsu), "
    "  ult_consulta=NOW(), proximo_permitido=NOW() + INTERVAL 1 HOUR, "
    "  ult_status=VALUES(ult_status)"
)


def bloqueado_por_cota(cliente_id):
    """
    Retorna o proximo_permitido (datetime) se a SEFAZ ainda pediu para aguardar,
    ou None se a janela esta aberta. Compara SEMPRE no relogio do BANCO (NOW()),
    evitando divergencia de timezone entre quem gravou e quem le.
    """
    con = pymysql.connect(**cs.CONN)
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT proximo_permitido FROM dfe_nsu "
                "WHERE cliente_id = %s AND proximo_permitido IS NOT NULL "
                "AND proximo_permitido > NOW() LIMIT 1",
                (cliente_id,),
            )
            row = cur.fetchone()
    finally:
        con.close()
    return row["proximo_permitido"] if row else None


# ==========================================================================
# Gravacao de UMA nota (Dropbox + banco). Transacao propria.
# ==========================================================================
def gravar_nota(conn, cur, cliente_id, cnpj_cert, nota, xml_bytes, nsu, schema,
                agora, expira):
    ano = nota["ano"] or agora.year
    mes = nota["mes"] or agora.month
    caminho = montar_caminho(cnpj_cert, ano, mes, nota["chave"])
    upload_xml(caminho, xml_bytes)  # sobe ANTES de gravar; falha aqui aborta o doc

    cur.execute(SQL_DOC_UPSERT, (
        cliente_id, nota["chave"], nota["tipo"], nsu, schema,
        nota["numero"], nota["serie"], nota["modelo"], nota["dh_txt"],
        nota["emit_cnpj"], nota["emit_nome"], nota["dest_cnpj"],
        nota["valor_total"], nota["situacao"], caminho, expira,
    ))
    cur.execute(SQL_DOC_ID, (nota["chave"],))
    row = cur.fetchone()
    documento_id = row["id"] if row else None
    if not documento_id:
        raise RuntimeError("nao recuperou documento_id apos upsert")

    n_itens = 0
    for it in nota["itens"]:
        produto_id = resolver_produto_id(cur, it["cod_anp"])
        cur.execute(SQL_ITEM_UPSERT, (
            documento_id, it["n_item"], it["produto_xml"],
            it["cprod_fornecedor"], it["cean"], it["cod_anp"],
            produto_id, it["ncm"], it["unidade"], it["quantidade"],
            it["valor_unitario"], it["valor_total"],
        ))
        n_itens += 1

    conn.commit()
    return n_itens


# ==========================================================================
# Gravacao de UM evento (Dropbox + banco). Transacao propria.
# ==========================================================================
def gravar_evento(conn, cur, cliente_id, cnpj_cert, ev, xml_bytes, nsu, schema,
                  agora, expira):
    ano = ev["ano"] or agora.year
    mes = ev["mes"] or agora.month
    # Arquiva pelo Id do evento (nao pela chNFe, para nao colidir com a nota).
    caminho = montar_caminho(cnpj_cert, ano, mes, ev["chave_evento"])
    upload_xml(caminho, xml_bytes)

    cur.execute(SQL_EVENTO_UPSERT, (
        cliente_id, ev["chave_evento"], ev["ch_nfe"], ev["tp_evento"],
        ev["n_seq"], ev["descricao"], ev["dh_txt"], nsu, schema,
        ev["org_cnpj"], caminho, expira,
    ))

    cancelou = False
    if ev["tp_evento"] == TP_CANCELAMENTO and ev["ch_nfe"]:
        cur.execute(SQL_CANCELA_NOTA, (ev["ch_nfe"],))
        cancelou = cur.rowcount and cur.rowcount > 0

    conn.commit()
    return bool(cancelou)


# ==========================================================================
# Gravacao de UM resumo de nota (resNFe). So banco (sem Dropbox: o resNFe nao e
# o XML da nota). resumo=1. Idempotente e nao rebaixa nota completa (SQL_RESUMO_UPSERT).
# ==========================================================================
def gravar_resumo_nota(conn, cur, cliente_id, cnpj_cert, res, nsu, schema):
    cur.execute(SQL_RESUMO_UPSERT, (
        cliente_id, res["chave"], res["tipo"], nsu, schema,
        res["numero"], res["serie"], res["modelo"], res["dh_txt"],
        res["emit_cnpj"], res["emit_nome"], cnpj_cert,   # dest = o proprio interessado
        res["valor_total"], res["situacao"],
    ))
    conn.commit()


# ==========================================================================
# Processa e SALVA um UNICO docZip. Este e o ponto onde o "salvar" acontece;
# quem chama usa o retorno para so avancar o ult_nsu ATE o ultimo NSU salvo.
#
#   nfeProc       -> nota completa (resumo=0)
#   procEventoNFe -> evento (dfe_eventos); cancelamento marca a nota
#   resNFe        -> RESUMO de nota (resumo=1) -> aparece em /dfe/compras
#   resEvento / cteProc / outros -> tipos que NAO modelamos: conta e SEGUE
#                    (nao levanta -- nao pode travar a fila de NSU eternamente)
#
# LEVANTA excecao se falhar ao descompactar/parsear OU ao gravar o que DEVE ser
# gravado (nota/evento/resumo). Nesse caso quem chama NAO deve avancar o ult_nsu
# alem deste NSU: na proxima consulta a SEFAZ o servico volta e tenta de novo.
#
# Retorna (kind, n_itens, cancelou) com kind in
# {"nota","evento","resumo","outro"}.
# ==========================================================================
def processar_um_doc(conn, cur, cliente_id, cnpj_cert, d, agora, expira):
    schema = d.get("schema") or None
    nsu = _to_int(d.get("NSU"))
    b64 = d.text or ""

    # Falha aqui (base64/gzip/XML corrompido) PROPAGA: nao avanca o ponteiro.
    xml_bytes = gzip.decompress(base64.b64decode(b64))
    root = ET.fromstring(xml_bytes)
    raiz = cs._local(root.tag)

    if raiz == "nfeProc":
        nota = extrair_nota(root)
        ni = gravar_nota(conn, cur, cliente_id, cnpj_cert, nota,
                         xml_bytes, nsu, schema, agora, expira)
        return "nota", ni, False

    if raiz == "procEventoNFe":
        ev = extrair_evento(root)
        canc = gravar_evento(conn, cur, cliente_id, cnpj_cert, ev,
                             xml_bytes, nsu, schema, agora, expira)
        return "evento", 0, bool(canc)

    if raiz == "resNFe":
        res = extrair_resumo_nota(root)
        gravar_resumo_nota(conn, cur, cliente_id, cnpj_cert, res, nsu, schema)
        return "resumo", 0, False

    # resEvento, cteProc, resCTe etc.: nao modelamos. Nao levanta (nao trava a
    # fila); quem chama loga e segue. Nenhuma NOTA se perde por isto.
    return "outro", 0, False


# ==========================================================================
# MAIN
# ==========================================================================
def main():
    print("=" * 74)
    print("PROCESSA distDFeInt - SEFAZ (PRODUCAO, tpAmb=1) - UM lote, salva e encerra")
    print("SO CONSULTA E SALVA. NAO manifesta. NAO faz loop.")
    print("=" * 74)

    agora = datetime.now()
    expira = (agora + timedelta(days=DIAS_RETENCAO)).date()

    # 1) Certificado (mesma cadeia validada).
    print("\n[1] Abrindo o certificado A1 (banco -> dropbox -> senha -> PFX)...")
    cliente_id, cnpj_cert, cert, chave_priv, cadeia = cs.abrir_certificado()
    print(f"    OK: cliente_id={cliente_id} cnpj={cnpj_cert} cadeia_extra={len(cadeia)}")

    # 2) ult_nsu atual + respeita proximo_permitido (comparado no relogio do BANCO).
    print("\n[2] Lendo ult_nsu (dfe_nsu)...")
    ult_nsu, _proximo = cs.ler_ult_nsu(cliente_id)
    print(f"    ult_nsu = {ult_nsu}" + ("  (sem linha; comeca do 0)" if ult_nsu == 0 else ""))
    bloqueio = bloqueado_por_cota(cliente_id)
    if bloqueio:
        print(f"    ATENCAO: proximo_permitido = {bloqueio} (relogio do banco) ainda no "
              "futuro. A SEFAZ pediu para aguardar. Encerrando sem consultar.")
        return

    # 3) Garante a tabela NOVA de eventos (idempotente, isolada).
    print("\n[3] Garantindo tabela dfe_eventos (CREATE TABLE IF NOT EXISTS)...")
    con0 = pymysql.connect(**cs.CONN)
    try:
        with con0.cursor() as c0:
            c0.execute(DDL_EVENTOS)
        con0.commit()
    finally:
        con0.close()
    print("    OK.")

    # 4) mTLS + UMA requisicao.
    print("\n[4] mTLS em memoria + UMA consulta...")
    sess = cs.montar_sessao_mtls(cert, chave_priv, cadeia)
    soap, ult_nsu_fmt = cs.montar_soap(cnpj_cert, ult_nsu)
    headers = {
        "Content-Type": (
            'application/soap+xml; charset=utf-8; '
            f'action="{cs.NS_WSDL}/nfeDistDFeInteresse"'
        ),
        "User-Agent": "nh-transportes/processa-dfe (uma consulta)",
    }
    r = sess.post(cs.ENDPOINT, data=soap.encode("utf-8"), headers=headers,
                  timeout=cs.TIMEOUT)
    print(f"    HTTP {r.status_code} ({len(r.content)} bytes) | distNSU={ult_nsu_fmt}")
    if r.status_code != 200:
        cs.falhar("4 (HTTP != 200)", f"status {r.status_code}")

    env = ET.fromstring(r.content)
    ret = cs._find(env, "retDistDFeInt")
    if ret is None:
        cs.falhar("5 (sem retDistDFeInt)", "resposta inesperada da SEFAZ.")

    cStat = cs._text(ret, "cStat")
    xMotivo = cs._text(ret, "xMotivo")
    ret_ult = cs._text(ret, "ultNSU")
    ret_max = cs._text(ret, "maxNSU")
    print(f"    cStat/xMotivo : {cStat}  {xMotivo}")
    print(f"    ultNSU        : {ret_ult}")
    print(f"    maxNSU        : {ret_max}")

    status_txt = f"{cStat} {xMotivo}"[:60]

    # 656 = Consumo Indevido: nao e erro; aguardar ~1h.
    # A SEFAZ devolve, MESMO no 656, o ultNSU ate onde ela ja entregou
    # ("use o ultNSU nas solicitacoes subsequentes"). Se vier ultNSU > 0,
    # AVANCA o ponteiro para ele -> a proxima consulta parte dali, nao do 0
    # (recomecar do 0 e justamente o que dispara o 656). A espera (+1h) e o
    # ult_consulta sao gravados no relogio do BANCO (SQL_NSU_656).
    if cStat == "656":
        ret_ult_int = _to_int(ret_ult) or 0
        nsu_gravar = max(ult_nsu, ret_ult_int)   # nunca regride o ponteiro
        if nsu_gravar > ult_nsu:
            print(f"    >>> 656 CONSUMO INDEVIDO: avancando ult_nsu {ult_nsu} -> "
                  f"{nsu_gravar} (ultNSU indicado pela SEFAZ). Aguardar ~1h.")
        else:
            print("    >>> 656 CONSUMO INDEVIDO: aguardar ~1h "
                  "(sem ultNSU novo para avancar).")
        con1 = pymysql.connect(**cs.CONN)
        try:
            with con1.cursor() as c1:
                c1.execute(SQL_NSU_656, (
                    cliente_id, cnpj_cert, nsu_gravar, _to_int(ret_max) or 0,
                    status_txt,
                ))
            con1.commit()
        finally:
            con1.close()
        print("\n" + "=" * 74)
        print(f"FIM - 656, nada gravado. ult_nsu agora = {nsu_gravar}, "
              "proximo_permitido = agora + 1h (relogio do banco).")
        print("=" * 74)
        return

    # 138 = Documento(s) localizado(s). Processa o lote.
    lote = cs._find(ret, "loteDistDFeInt")
    docs = [e for e in (lote.iter() if lote is not None else [])
            if cs._local(e.tag) == "docZip"]
    print(f"\n[5] Documentos no lote: {len(docs)} -- processando...")

    n_nota = n_evento = n_resumo = n_outro = n_itens = n_cancel = 0

    # ATOMICIDADE do ponteiro: processa os docs EM ORDEM DE NSU e so avanca a
    # "marca-d'agua" (nsu_ok) APOS cada gravacao bem-sucedida. Se um doc falha,
    # PARA o lote ali -> o ult_nsu nao passa dele -> na proxima consulta a SEFAZ
    # o servico volta e tenta de novo. Nunca mais pula nota.
    docs.sort(key=lambda e: _to_int(e.get("NSU")) or 0)
    nsu_ok = ult_nsu
    houve_falha = False

    conn = pymysql.connect(**cs.CONN)
    try:
        cur = conn.cursor()
        for d in docs:
            nsu = _to_int(d.get("NSU"))
            try:
                kind, ni, canc = processar_um_doc(
                    conn, cur, cliente_id, cnpj_cert, d, agora, expira)
            except Exception as exc:
                conn.rollback()
                houve_falha = True
                print(f"    [NSU {nsu}] FALHA ao salvar: {exc}")
                print(f"    >>> PARANDO o lote. ult_nsu NAO avanca alem de {nsu_ok} "
                      "(retenta na proxima consulta).")
                break

            if kind == "nota":
                n_nota += 1
                n_itens += ni
                print(f"    [NSU {nsu}] NOTA completa ({ni} item(ns))")
            elif kind == "evento":
                n_evento += 1
                if canc:
                    n_cancel += 1
                print(f"    [NSU {nsu}] EVENTO{' -> nota CANCELADA' if canc else ''}")
            elif kind == "resumo":
                n_resumo += 1
                print(f"    [NSU {nsu}] RESUMO de nota (resNFe) gravado (resumo=1)")
            else:
                n_outro += 1
                print(f"    [NSU {nsu}] tipo nao modelado (CTe/resEvento) -- seguindo.")

            nsu_ok = nsu   # so avanca a marca APOS salvar com sucesso

        # 6) Avanca ult_nsu SO ate o ultimo NSU salvo com sucesso (nsu_ok).
        cur.execute(SQL_NSU_OK, (
            cliente_id, cnpj_cert, nsu_ok, _to_int(ret_max) or 0, status_txt,
        ))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    # 7) Resumo.
    print("\n" + "-" * 74)
    print("RESUMO DO LOTE:")
    print(f"    docs recebidos      : {len(docs)}")
    print(f"    notas completas     : {n_nota}   (itens: {n_itens})")
    print(f"    resumos de nota     : {n_resumo}   (resNFe -> aparecem em /dfe/compras)")
    print(f"    eventos gravados    : {n_evento}   (cancelamentos aplicados: {n_cancel})")
    print(f"    outros (nao modelados): {n_outro}")
    print(f"    ult_nsu final       : {nsu_ok}" + ("  (PAROU por falha)" if houve_falha else ""))
    if ret_ult and ret_max and ret_ult != ret_max:
        print(f"\n    ultNSU ({ret_ult}) < maxNSU ({ret_max}) -> HA MAIS documentos.")
        print("    (este script NAO faz loop; rodar de novo pega o proximo lote)")
    else:
        print(f"\n    ultNSU == maxNSU ({ret_ult}) -> lote final por enquanto.")
    print("=" * 74)
    print("FIM - um lote processado. Nada foi manifestado.")
    print("=" * 74)


if __name__ == "__main__":
    main()
