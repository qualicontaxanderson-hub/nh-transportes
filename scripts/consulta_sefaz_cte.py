# -*- coding: utf-8 -*-
# ============================================================================
#  CTeDistribuicaoDFe - canal PROPRIO de CT-e (Ambiente Nacional).
#
#  O NFeDistribuicaoDFe (consulta_sefaz.py) NUNCA traz CT-e; o CT-e do tomador
#  so vem por ESTE servico (endpoint + NSU proprios). Este modulo mora ao lado
#  do de NF-e e REUSA dele: certificado A1 (cs.abrir_certificado), mTLS em
#  memoria (cs.montar_sessao_mtls), parsers (cs._find/_text/_local) e os
#  parametros do interessado (cs.CNPJ_PREFERIDO / C_UF_AUTOR / TP_AMB / CONN).
#  O que muda e SO: endpoint, wrapper SOAP, namespace e a VERSAO do distDFeInt.
#
#  Cursor 100% ISOLADO: tabela propria dfe_nsu_cte (espelho de dfe_nsu). O
#  ult_nsu do CT-e e independente do de NF-e -- um nunca corrompe o outro.
#
#  SO CONSULTA E LE. NUNCA manifesta. Na cota deste servico o SGA NAO entra
#  (SGA nao puxa CT-e); competimos so com o NFStock. A regra do 656 vale igual.
# ============================================================================
import os
import pymysql
import consulta_sefaz as cs   # cert/mTLS/parsers + CONN, CNPJ, C_UF_AUTOR, TP_AMB

# --- Endpoint NACIONAL do CTeDistribuicaoDFe (producao) ---------------------
ENDPOINT_CTE = "https://www1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"
NS_WSDL_CTE  = "http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe"
NS_CTE       = "http://www.portalfiscal.inf.br/cte"
ACTION_CTE   = NS_WSDL_CTE + "/cteDistDFeInteresse"

# VERSAO do distDFeInt do CT-e. ATENCAO (pegadinha): NAO e a "1.35" da NF-e --
# o layout de distribuicao do CT-e tem versao PROPRIA (NT 2015.002). "1.00" e o
# candidato; a 1a consulta em runtime confirma (138/137 = OK; 215/242/versao
# invalida = trocar). Overridavel por env pra ajustar SEM novo deploy.
VERSAO_CTE = os.environ.get("DFE_CTE_VERSAO", "1.00")

def montar_soap_cte(cnpj, ult_nsu):
    """Espelho de cs.montar_soap, trocando wrapper/namespace/versao para o CT-e.
    Consulta por distNSU/ultNSU (distribuicao continua), igual a NF-e -- NAO usa
    consChCTe (por isso a pegadinha do consChNFe/versao 1.01 nao nos afeta)."""
    ult_nsu_fmt = str(int(ult_nsu)).zfill(15)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
        '<soap12:Body>'
        f'<cteDistDFeInteresse xmlns="{NS_WSDL_CTE}">'
        '<cteDadosMsg>'
        f'<distDFeInt xmlns="{NS_CTE}" versao="{VERSAO_CTE}">'
        f'<tpAmb>{cs.TP_AMB}</tpAmb>'
        f'<cUFAutor>{cs.C_UF_AUTOR}</cUFAutor>'
        f'{cs.tag_interessado(cnpj)}'
        f'<distNSU><ultNSU>{ult_nsu_fmt}</ultNSU></distNSU>'
        '</distDFeInt>'
        '</cteDadosMsg>'
        '</cteDistDFeInteresse>'
        '</soap12:Body>'
        '</soap12:Envelope>'
    ), ult_nsu_fmt

# ==========================================================================
# Cursor ISOLADO do CT-e: dfe_nsu_cte (espelho EXATO de dfe_nsu). Criada em
# runtime (idempotente), como DDL_CTE/DDL_CTE_NFE. Zero toque na dfe_nsu.
# ==========================================================================
DDL_NSU_CTE = """
CREATE TABLE IF NOT EXISTS dfe_nsu_cte (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    cliente_id        INT           NOT NULL,
    cnpj              VARCHAR(14)   NOT NULL,
    ult_nsu           BIGINT        NOT NULL DEFAULT 0,
    max_nsu           BIGINT        NOT NULL DEFAULT 0,
    ult_consulta      DATETIME      NULL,
    proximo_permitido DATETIME      NULL,
    ult_status        VARCHAR(255)  NULL,
    atualizado_em     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cliente (cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

def ler_ult_nsu_cte(cliente_id):
    """(ult_nsu:int, proximo_permitido) de dfe_nsu_cte. 0 se nao houver linha."""
    con = pymysql.connect(**cs.CONN)
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT ult_nsu, max_nsu, proximo_permitido "
                "FROM dfe_nsu_cte WHERE cliente_id = %s", (cliente_id,))
            row = cur.fetchone()
    finally:
        con.close()
    if not row:
        return 0, None
    return int(row["ult_nsu"] or 0), row.get("proximo_permitido")

def bloqueado_por_cota_cte(cliente_id):
    """proximo_permitido (datetime) se a SEFAZ ainda pede espera no CT-e; senao
    None. Compara SEMPRE no relogio do BANCO (NOW()), igual a NF-e."""
    con = pymysql.connect(**cs.CONN)
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT proximo_permitido FROM dfe_nsu_cte "
                "WHERE cliente_id = %s AND proximo_permitido IS NOT NULL "
                "AND proximo_permitido > NOW() LIMIT 1", (cliente_id,))
            row = cur.fetchone()
    finally:
        con.close()
    return row["proximo_permitido"] if row else None

# Upserts do cursor de CT-e. Mesma assinatura de 5 params dos de NF-e:
#   (cliente_id, cnpj, ult_nsu, max_nsu, ult_status)
# max_nsu=0 = "SEFAZ nao informou" (656 nao traz maxNSU) -> preserva o atual.
_MAX_NSU_CTE = "max_nsu=IF(VALUES(max_nsu) > 0, VALUES(max_nsu), max_nsu)"

SQL_NSU_CTE_OK = (
    "INSERT INTO dfe_nsu_cte "
    "(cliente_id, cnpj, ult_nsu, max_nsu, ult_consulta, proximo_permitido, ult_status) "
    "VALUES (%s,%s,%s,%s,NOW(),NULL,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  ult_nsu=VALUES(ult_nsu), " + _MAX_NSU_CTE + ", "
    "  ult_consulta=NOW(), proximo_permitido=NULL, ult_status=VALUES(ult_status)"
)
SQL_NSU_CTE_656 = (
    "INSERT INTO dfe_nsu_cte "
    "(cliente_id, cnpj, ult_nsu, max_nsu, ult_consulta, proximo_permitido, ult_status) "
    "VALUES (%s,%s,%s,%s,NOW(),NOW() + INTERVAL 1 HOUR,%s) "
    "ON DUPLICATE KEY UPDATE "
    "  ult_nsu=VALUES(ult_nsu), " + _MAX_NSU_CTE + ", "
    "  ult_consulta=NOW(), proximo_permitido=NOW() + INTERVAL 1 HOUR, "
    "  ult_status=VALUES(ult_status)"
)
