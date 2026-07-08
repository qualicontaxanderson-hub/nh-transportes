# -*- coding: utf-8 -*-
# ============================================================================
#  CONSULTA CRUA ao distDFeInt da SEFAZ (NFeDistribuicaoDFe) - PRODUCAO
#
#  ISOLADO. SO CONSULTA E LE. NUNCA manifesta (nenhum evento / ciencia /
#  confirmacao). Faz UMA unica requisicao, mostra o que voltou e ENCERRA.
#
#  NAO grava no banco. NAO sobe nada no Dropbox. NAO faz loop.
#
#  Reaproveita a cadeia ja validada em scripts/testa_certificado.py:
#      dfe_certificados -> Dropbox (.pfx) -> decifra senha -> abre o PFX (A1).
#  mTLS com o A1 em memoria (converte PFX->PEM em RAM; NAO grava PEM em disco).
# ============================================================================
import os
import ssl
import sys
import gzip
import base64
import xml.etree.ElementTree as ET

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import pymysql
import requests
from requests.adapters import HTTPAdapter
from urllib3.contrib.pyopenssl import PyOpenSSLContext
from OpenSSL import crypto as ossl
import certifi

from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption,
)

# --------------------------------------------------------------------------
# Parametros fixos deste ambiente
# --------------------------------------------------------------------------
CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV", database="railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=30,
)
CNPJ_PREFERIDO = "33503987000116"   # POSTO NOVO HORIZONTE GOIATUBA
C_UF_AUTOR     = "52"               # GO
TP_AMB         = "1"                # 1 = PRODUCAO

# Webservice NACIONAL de Distribuicao de DFe (producao).
ENDPOINT = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
NS_WSDL  = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
NS_NFE   = "http://www.portalfiscal.inf.br/nfe"
VERSAO   = "1.35"                   # layout do distDFeInt

TIMEOUT = 60


def _so_digitos(v):
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def falhar(etapa, erro):
    print()
    print("!" * 74)
    print(f"FALHOU NA ETAPA: {etapa}")
    print(f"ERRO: {erro}")
    print("!" * 74)
    sys.exit(1)


# ==========================================================================
# ETAPA 1 - Abrir o certificado A1 (mesma cadeia do teste que passou)
# ==========================================================================
def abrir_certificado():
    """
    Retorna (cliente_id, cnpj, cert, chave_priv, cadeia).
    Repete a cadeia validada: banco -> Dropbox -> decifra -> abre PFX.
    """
    # -- 1a) registro ativo no banco -------------------------------------
    con = pymysql.connect(**CONN)
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT id, cliente_id, cnpj, pfx_caminho, senha_cifrada "
                "FROM dfe_certificados WHERE ativo = 1"
            )
            regs = cur.fetchall()
    finally:
        con.close()

    if not regs:
        falhar("1 (banco)", "nenhum certificado ATIVO em dfe_certificados.")
    if len(regs) == 1:
        reg = regs[0]
    else:
        pref = [r for r in regs if _so_digitos(r["cnpj"]) == CNPJ_PREFERIDO]
        reg = pref[0] if pref else regs[0]

    if not reg["pfx_caminho"]:
        falhar("1 (banco)", "registro sem pfx_caminho (PFX deveria estar no Dropbox).")
    if not reg["senha_cifrada"]:
        falhar("1 (banco)", "registro sem senha_cifrada.")

    # -- 1b) baixa o .pfx do Dropbox -------------------------------------
    #    Mesma autenticacao/normalizacao usadas no teste que passou.
    try:
        from integrations.dropbox_ofx import _criar_dbx, _normalizar_caminho
        caminho = _normalizar_caminho(reg["pfx_caminho"])
        dbx = _criar_dbx()
        _meta, resp = dbx.files_download(caminho)
        pfx_bytes = resp.content
    except Exception as exc:
        falhar("1 (download do PFX no Dropbox)", exc)
    if not pfx_bytes:
        falhar("1 (download do PFX)", "arquivo vazio (0 bytes).")

    # -- 1c) decifra a senha ---------------------------------------------
    try:
        from integrations.cripto_dfe import decifrar_senha
        senha = decifrar_senha(reg["senha_cifrada"])
    except Exception as exc:
        falhar("1 (decifrar senha)", exc)

    # -- 1d) abre o PFX (A1) ---------------------------------------------
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        chave_priv, cert, cadeia = pkcs12.load_key_and_certificates(
            pfx_bytes, senha.encode("utf-8")
        )
    except Exception as exc:
        falhar("1 (abrir o PFX)", f"senha incorreta ou PFX invalido -> {exc}")
    if cert is None or chave_priv is None:
        falhar("1 (abrir o PFX)", "PFX sem certificado ou sem chave privada.")

    return reg["cliente_id"], _so_digitos(reg["cnpj"]), cert, chave_priv, (cadeia or [])


# ==========================================================================
# ETAPA 2 - ult_nsu atual (READ-ONLY) em dfe_nsu
# ==========================================================================
def ler_ult_nsu(cliente_id):
    """Retorna (ult_nsu:int, proximo_permitido). Se nao houver linha, ult_nsu=0."""
    con = pymysql.connect(**CONN)
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT ult_nsu, max_nsu, proximo_permitido "
                "FROM dfe_nsu WHERE cliente_id = %s",
                (cliente_id,),
            )
            row = cur.fetchone()
    finally:
        con.close()
    if not row:
        return 0, None
    return int(row["ult_nsu"] or 0), row.get("proximo_permitido")


# ==========================================================================
# ETAPA 3 - mTLS em memoria (PFX -> PEM em RAM; nada em disco)
# ==========================================================================
class AdaptadorCertMemoria(HTTPAdapter):
    """
    HTTPAdapter que faz mTLS com cert+chave carregados de MEMORIA (pyOpenSSL).
    O CA de verificacao do servidor vem do certifi (funciona no Windows tambem).
    """
    def __init__(self, cert_pem, key_pem, chain_pems, **kw):
        self._cert_pem = cert_pem
        self._key_pem = key_pem
        self._chain_pems = chain_pems or []
        super().__init__(**kw)

    def _montar_ctx(self):
        ctx = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
        _c = ctx._ctx
        _c.use_certificate(ossl.load_certificate(ossl.FILETYPE_PEM, self._cert_pem))
        _c.use_privatekey(ossl.load_privatekey(ossl.FILETYPE_PEM, self._key_pem))
        _c.check_privatekey()  # confirma que cert e chave batem
        for extra in self._chain_pems:
            _c.add_extra_chain_cert(ossl.load_certificate(ossl.FILETYPE_PEM, extra))
        # verificacao do servidor
        ctx.load_verify_locations(cafile=certifi.where())
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    def init_poolmanager(self, *a, **kw):
        kw["ssl_context"] = self._montar_ctx()
        return super().init_poolmanager(*a, **kw)

    def proxy_manager_for(self, *a, **kw):
        kw["ssl_context"] = self._montar_ctx()
        return super().proxy_manager_for(*a, **kw)


def montar_sessao_mtls(cert, chave_priv, cadeia):
    cert_pem = cert.public_bytes(Encoding.PEM)
    key_pem = chave_priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    chain_pems = [c.public_bytes(Encoding.PEM) for c in cadeia]
    sess = requests.Session()
    sess.mount("https://", AdaptadorCertMemoria(cert_pem, key_pem, chain_pems))
    return sess


# ==========================================================================
# ETAPA 4 - montar o SOAP e fazer UMA requisicao
# ==========================================================================
def montar_soap(cnpj, ult_nsu):
    ult_nsu_fmt = str(int(ult_nsu)).zfill(15)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
        '<soap12:Body>'
        f'<nfeDistDFeInteresse xmlns="{NS_WSDL}">'
        '<nfeDadosMsg>'
        f'<distDFeInt xmlns="{NS_NFE}" versao="{VERSAO}">'
        f'<tpAmb>{TP_AMB}</tpAmb>'
        f'<cUFAutor>{C_UF_AUTOR}</cUFAutor>'
        f'<CNPJ>{cnpj}</CNPJ>'
        f'<distNSU><ultNSU>{ult_nsu_fmt}</ultNSU></distNSU>'
        '</distDFeInt>'
        '</nfeDadosMsg>'
        '</nfeDistDFeInteresse>'
        '</soap12:Body>'
        '</soap12:Envelope>'
    ), ult_nsu_fmt


# ==========================================================================
# Helpers de parsing (ignora namespaces; busca por nome local)
# ==========================================================================
def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(el, nome):
    for e in el.iter():
        if _local(e.tag) == nome:
            return e
    return None


def _text(el, nome):
    achado = _find(el, nome)
    return achado.text.strip() if (achado is not None and achado.text) else None


def _classifica_schema(schema):
    base = (schema or "").lower()
    if base.startswith("res"):
        return "RESUMO"
    if base.startswith("proc") or base.startswith("nfeproc") or base.startswith("cteproc"):
        return "COMPLETO"
    return "?"


def _peek_doczip(b64):
    """Descompacta o docZip em MEMORIA so para conferencia (tag raiz + chave)."""
    try:
        xml_bytes = gzip.decompress(base64.b64decode(b64))
        root = ET.fromstring(xml_bytes)
        raiz = _local(root.tag)
        chave = None
        for e in root.iter():
            ln = _local(e.tag)
            if ln in ("chNFe", "chCTe", "chDFe") and e.text:
                chave = e.text.strip()
                break
        return raiz, chave
    except Exception:
        return None, None


# ==========================================================================
# MAIN
# ==========================================================================
def main():
    print("=" * 74)
    print("CONSULTA distDFeInt - SEFAZ NFeDistribuicaoDFe (PRODUCAO, tpAmb=1)")
    print("SO CONSULTA. NAO manifesta. NAO grava. UMA requisicao.")
    print("=" * 74)

    # 1) Certificado
    print("\n[1] Abrindo o certificado A1 (banco -> dropbox -> senha -> PFX)...")
    cliente_id, cnpj, cert, chave_priv, cadeia = abrir_certificado()
    print(f"    OK: cliente_id={cliente_id} cnpj={cnpj} cadeia_extra={len(cadeia)} cert(s)")

    # 2) ult_nsu
    print("\n[2] Lendo ult_nsu atual (dfe_nsu, read-only)...")
    ult_nsu, proximo = ler_ult_nsu(cliente_id)
    print(f"    ult_nsu = {ult_nsu}" + ("  (sem linha em dfe_nsu; comecando do 0)"
                                        if ult_nsu == 0 else ""))
    if proximo:
        print(f"    ATENCAO: dfe_nsu.proximo_permitido = {proximo} "
              "(a SEFAZ pediu para so consultar depois desse horario)")

    # 3) sessao mTLS
    print("\n[3] Preparando mTLS em memoria (PFX->PEM em RAM, nada em disco)...")
    try:
        sess = montar_sessao_mtls(cert, chave_priv, cadeia)
    except Exception as exc:
        falhar("3 (mTLS em memoria)", exc)
    print("    OK.")

    # 4) UMA requisicao
    soap, ult_nsu_fmt = montar_soap(cnpj, ult_nsu)
    headers = {
        "Content-Type": (
            'application/soap+xml; charset=utf-8; '
            f'action="{NS_WSDL}/nfeDistDFeInteresse"'
        ),
        "User-Agent": "nh-transportes/consulta-sefaz (diagnostico read-only)",
    }
    print(f"\n[4] Enviando UMA requisicao a {ENDPOINT}")
    print(f"    distNSU/ultNSU = {ult_nsu_fmt} | cUFAutor={C_UF_AUTOR} | tpAmb={TP_AMB}")
    try:
        r = sess.post(ENDPOINT, data=soap.encode("utf-8"), headers=headers, timeout=TIMEOUT)
    except Exception as exc:
        falhar("4 (requisicao HTTPS/mTLS)", exc)

    print(f"    HTTP {r.status_code} ({len(r.content)} bytes)")
    if r.status_code != 200:
        # Mostra um trecho pra diagnostico e encerra.
        print("    Corpo (inicio):")
        print("    " + (r.text[:1500].replace("\n", "\n    ")))
        falhar("4 (HTTP != 200)", f"status {r.status_code}")

    # 5) Parse + impressao (SEM salvar nada)
    print("\n[5] Resposta da SEFAZ:")
    try:
        env = ET.fromstring(r.content)
    except Exception as exc:
        print("    Nao foi possivel parsear XML. Corpo (inicio):")
        print("    " + r.text[:1500].replace("\n", "\n    "))
        falhar("5 (parse XML)", exc)

    ret = _find(env, "retDistDFeInt")
    if ret is None:
        print("    Sem retDistDFeInt no envelope. Corpo (inicio):")
        print("    " + r.text[:1500].replace("\n", "\n    "))
        falhar("5 (sem retDistDFeInt)", "resposta inesperada da SEFAZ.")

    cStat   = _text(ret, "cStat")
    xMotivo = _text(ret, "xMotivo")
    dhResp  = _text(ret, "dhResp")
    ret_ult = _text(ret, "ultNSU")
    ret_max = _text(ret, "maxNSU")
    verAplic = _text(ret, "verAplic")

    print(f"    cStat / xMotivo : {cStat}  {xMotivo}")
    print(f"    verAplic        : {verAplic}")
    print(f"    dhResp          : {dhResp}")
    print(f"    ultNSU (retorno): {ret_ult}")
    print(f"    maxNSU (retorno): {ret_max}")

    # 656 = Consumo Indevido -> nao e erro; e so aguardar.
    if cStat == "656":
        print()
        print("    >>> cStat 656 = CONSUMO INDEVIDO. NAO e erro.")
        print("    >>> A SEFAZ pede para AGUARDAR (tipicamente ~1h) antes de nova consulta.")
        print("    >>> Nada a fazer agora, sem loop.")

    # Documentos do lote
    lote = _find(ret, "loteDistDFeInt")
    docs = [e for e in (lote.iter() if lote is not None else []) if _local(e.tag) == "docZip"]
    print(f"\n    Documentos no lote (docZip): {len(docs)}")
    for i, d in enumerate(docs, 1):
        schema = d.get("schema") or "(sem schema)"
        nsu = d.get("NSU") or "?"
        tipo = _classifica_schema(schema)
        raiz, chave = _peek_doczip(d.text or "")
        extra = ""
        if raiz:
            extra = f" | raiz={raiz}"
        if chave:
            extra += f" | chave={chave}"
        print(f"      [{i:>2}] NSU={nsu:<16} schema={schema:<18} {tipo}{extra}")

    if ret_ult and ret_max and ret_ult != ret_max:
        print(f"\n    Nota: ultNSU ({ret_ult}) < maxNSU ({ret_max}) -> ha MAIS documentos.")
        print("    (este script NAO faz loop; buscar o resto seria outra execucao)")

    print()
    print("=" * 74)
    print("FIM - consulta unica concluida. Nada foi gravado, nada foi manifestado.")
    print("=" * 74)


if __name__ == "__main__":
    main()
