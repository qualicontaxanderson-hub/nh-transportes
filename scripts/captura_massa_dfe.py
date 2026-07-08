# -*- coding: utf-8 -*-
# ============================================================================
#  CAPTURA EM MASSA de DFe (distDFeInt) - VARIOS lotes seguidos ate pegar tudo
#  que esta na janela da SEFAZ (do ult_nsu ate o maxNSU), respeitando a cota.
#
#  SO CONSULTA E SALVA -- NUNCA manifesta. Reaproveita TODA a logica ja validada
#  em processa_dfe.py (extracao, gravacao, Dropbox, idempotencia) e em
#  consulta_sefaz.py (certificado A1, mTLS em memoria, SOAP). Aqui so mora o
#  LOOP de lotes + o dispatch fino por documento.
#
#  Comportamento por lote:
#    - consulta a partir do ult_nsu atual
#    - 138 (documentos)  -> processa/salva, avanca ult_nsu, pausa e continua
#    - 137 (nada, em dia) -> chegou ao fim, PARA com sucesso
#    - 656 (consumo indev)-> PARA na hora, grava proximo_permitido=agora+1h,
#                            avanca ult_nsu para o ultNSU indicado, NAO insiste
#    - para tambem quando ult_nsu >= max_nsu (pegou tudo) ou ao bater o limite
#      de seguranca de lotes por execucao.
#
#  Idempotente (UNIQUE na chave): rodar de novo NUNCA duplica. Se parar por 656,
#  espere ~1h e rode de novo -- ele continua de onde parou (ult_nsu).
# ============================================================================
import os
import sys
import time
import gzip
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Raiz do projeto E pasta scripts/ no sys.path (para importar os modulos irmaos).
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

# Reaproveita TUDO: consulta_sefaz (cert/mTLS/SOAP) e processa_dfe (extrai/grava).
import consulta_sefaz as cs
import processa_dfe as pd

# --------------------------------------------------------------------------
# Parametros de seguranca desta captura em massa.
# --------------------------------------------------------------------------
PAUSA_SEGUNDOS = 20   # pausa entre lotes (comeca conservador; pode subir depois)
MAX_LOTES = 40        # teto de lotes por execucao (nao roda infinito nem abusa)


# ==========================================================================
# UMA requisicao distDFeInt (mecanica identica a de processa_dfe/consulta_sefaz).
# Retorna (ret_element, bytes_resposta).
# ==========================================================================
def _consultar(sess, cnpj_cert, ult_nsu):
    soap, _ult_fmt = cs.montar_soap(cnpj_cert, ult_nsu)
    headers = {
        "Content-Type": (
            'application/soap+xml; charset=utf-8; '
            f'action="{cs.NS_WSDL}/nfeDistDFeInteresse"'
        ),
        "User-Agent": "nh-transportes/captura-massa-dfe (loop)",
    }
    r = sess.post(cs.ENDPOINT, data=soap.encode("utf-8"), headers=headers,
                  timeout=cs.TIMEOUT)
    if r.status_code != 200:
        cs.falhar("HTTP != 200", f"status {r.status_code}")
    env = ET.fromstring(r.content)
    ret = cs._find(env, "retDistDFeInt")
    if ret is None:
        cs.falhar("sem retDistDFeInt", "resposta inesperada da SEFAZ.")
    return ret, len(r.content)


# ==========================================================================
# Processa os docZip de UMA resposta 138. Mesmo dispatch de processa_dfe.main(),
# chamando as funcoes IMPORTADAS de processa_dfe (extrai/grava/Dropbox).
# Grava por documento (commit/rollback dentro de gravar_*). Retorna contagens.
# ==========================================================================
def _processar_docs(conn, cur, ret, cliente_id, cnpj_cert, agora, expira):
    lote = cs._find(ret, "loteDistDFeInt")
    docs = [e for e in (lote.iter() if lote is not None else [])
            if cs._local(e.tag) == "docZip"]
    c = dict(docs=len(docs), n_nota=0, n_evento=0, n_resumo=0, n_outro=0,
             n_itens=0, n_cancel=0, n_erro=0)

    for d in docs:
        schema = d.get("schema") or None
        nsu = pd._to_int(d.get("NSU"))
        b64 = d.text or ""
        try:
            xml_bytes = gzip.decompress(base64.b64decode(b64))
            root = ET.fromstring(xml_bytes)
            raiz = cs._local(root.tag)
        except Exception as exc:
            c["n_erro"] += 1
            print(f"      [NSU {nsu}] ERRO descompactar/parsear: {exc}")
            continue

        try:
            if raiz == "nfeProc":
                nota = pd.extrair_nota(root)
                ni = pd.gravar_nota(conn, cur, cliente_id, cnpj_cert, nota,
                                    xml_bytes, nsu, schema, agora, expira)
                c["n_nota"] += 1
                c["n_itens"] += ni
            elif raiz == "procEventoNFe":
                ev = pd.extrair_evento(root)
                canc = pd.gravar_evento(conn, cur, cliente_id, cnpj_cert, ev,
                                        xml_bytes, nsu, schema, agora, expira)
                c["n_evento"] += 1
                if canc:
                    c["n_cancel"] += 1
            elif raiz in ("resNFe", "resEvento"):
                c["n_resumo"] += 1       # resumo redundante: so conta
            else:
                c["n_outro"] += 1
                print(f"      [NSU {nsu}] IGNORADO (raiz desconhecida: {raiz})")
        except Exception as exc:
            conn.rollback()
            c["n_erro"] += 1
            print(f"      [NSU {nsu}] ERRO gravar ({raiz}): {exc}")

    return c


# ==========================================================================
# MAIN - loop de lotes.
# ==========================================================================
def main():
    print("=" * 74)
    print("CAPTURA EM MASSA distDFeInt - SEFAZ (PRODUCAO, tpAmb=1)")
    print(f"Loop ate pegar tudo (ate {MAX_LOTES} lotes), pausa {PAUSA_SEGUNDOS}s "
          "entre lotes. SO CONSULTA E SALVA. NAO manifesta.")
    print("=" * 74)

    # 1) Certificado (mesma cadeia validada).
    print("\n[1] Abrindo o certificado A1 (banco -> dropbox -> senha -> PFX)...")
    cliente_id, cnpj_cert, cert, chave_priv, cadeia = cs.abrir_certificado()
    print(f"    OK: cliente_id={cliente_id} cnpj={cnpj_cert} cadeia_extra={len(cadeia)}")

    # 2) ult_nsu atual + respeita proximo_permitido (comparado no relogio do BANCO).
    print("\n[2] Lendo ult_nsu (dfe_nsu)...")
    ult_nsu, _proximo = cs.ler_ult_nsu(cliente_id)
    print(f"    ult_nsu = {ult_nsu}")
    bloqueio = pd.bloqueado_por_cota(cliente_id)
    if bloqueio:
        print(f"    ATENCAO: proximo_permitido = {bloqueio} (relogio do banco) ainda no "
              "futuro. A SEFAZ pediu para aguardar (656 recente). Encerrando sem consultar.")
        return

    # 3) Garante a tabela de eventos (idempotente) e monta a sessao mTLS uma vez.
    print("\n[3] Garantindo dfe_eventos + mTLS em memoria...")
    con0 = pymysql.connect(**cs.CONN)
    try:
        with con0.cursor() as c0:
            c0.execute(pd.DDL_EVENTOS)
        con0.commit()
    finally:
        con0.close()
    sess = cs.montar_sessao_mtls(cert, chave_priv, cadeia)
    print("    OK.")

    # 4) Loop de lotes.
    tot_nota = tot_evento = tot_itens = tot_cancel = tot_resumo = tot_outro = tot_erro = 0
    lotes = 0
    max_nsu = 0
    motivo_fim = "limite"   # default se sair pelo teto

    print(f"\n[4] Iniciando loop a partir do NSU {ult_nsu}...\n")
    conn = pymysql.connect(**cs.CONN)
    try:
        cur = conn.cursor()
        while lotes < MAX_LOTES:
            agora = datetime.now()
            expira = (agora + timedelta(days=pd.DIAS_RETENCAO)).date()

            ret, _nbytes = _consultar(sess, cnpj_cert, ult_nsu)
            cStat = cs._text(ret, "cStat")
            xMotivo = cs._text(ret, "xMotivo")
            ret_ult = pd._to_int(cs._text(ret, "ultNSU")) or 0
            ret_max = pd._to_int(cs._text(ret, "maxNSU")) or 0
            status_txt = f"{cStat} {xMotivo}"[:60]

            # ----- 656: consumo indevido -> para na hora -----
            if cStat == "656":
                nsu_grav = max(ult_nsu, ret_ult)   # nunca regride
                cur.execute(pd.SQL_NSU_656, (
                    cliente_id, cnpj_cert, nsu_grav, ret_max or max_nsu or 0,
                    status_txt,
                ))
                conn.commit()
                ult_nsu = nsu_grav
                motivo_fim = "656"
                print(f"    >>> 656 CONSUMO INDEVIDO. Parando. ult_nsu={ult_nsu}, "
                      "proximo_permitido = agora + 1h (relogio do banco); "
                      "espere ~1h e rode de novo.")
                break

            # ----- 137: nada localizado (em dia) -> fim com sucesso -----
            if cStat == "137":
                cur.execute(pd.SQL_NSU_OK, (
                    cliente_id, cnpj_cert, ult_nsu, ret_max or max_nsu or ult_nsu,
                    status_txt,
                ))
                conn.commit()
                motivo_fim = "fim137"
                print("    cStat 137: nenhum documento novo. Em dia.")
                break

            # ----- qualquer outro cStat != 138 -> para com aviso -----
            if cStat != "138":
                cur.execute(pd.SQL_NSU_OK, (
                    cliente_id, cnpj_cert, ult_nsu, ret_max or max_nsu or 0,
                    status_txt,
                ))
                conn.commit()
                motivo_fim = f"cstat_{cStat}"
                print(f"    cStat inesperado {cStat} ({xMotivo}). Parando.")
                break

            # ----- 138: processa o lote e avanca -----
            c = _processar_docs(conn, cur, ret, cliente_id, cnpj_cert, agora, expira)
            novo_ult = ret_ult or ult_nsu
            cur.execute(pd.SQL_NSU_OK, (
                cliente_id, cnpj_cert, novo_ult, ret_max or 0, status_txt,
            ))
            conn.commit()

            lotes += 1
            max_nsu = ret_max or max_nsu
            tot_nota += c["n_nota"]
            tot_evento += c["n_evento"]
            tot_itens += c["n_itens"]
            tot_cancel += c["n_cancel"]
            tot_resumo += c["n_resumo"]
            tot_outro += c["n_outro"]
            tot_erro += c["n_erro"]
            ult_nsu = novo_ult
            falta = max(0, (max_nsu or 0) - novo_ult)

            print(f"Lote {lotes}: +{c['n_nota']} notas, +{c['n_evento']} eventos, "
                  f"+{c['n_itens']} itens ({c['n_resumo']} resumos, {c['n_erro']} erros) "
                  f"| NSU agora={novo_ult} (falta {falta})")

            # ----- chegou ao fim da janela? -----
            if max_nsu and novo_ult >= max_nsu:
                motivo_fim = "completo"
                break

            # ----- pausa de seguranca antes do proximo lote -----
            time.sleep(PAUSA_SEGUNDOS)

        cur.close()
    finally:
        conn.close()

    # 5) Resumo final.
    falta_final = max(0, (max_nsu or 0) - ult_nsu)
    print("\n" + "-" * 74)
    print("RESUMO DA CAPTURA EM MASSA:")
    print(f"    lotes processados   : {lotes}")
    print(f"    notas gravadas      : {tot_nota}   (itens: {tot_itens})")
    print(f"    eventos gravados    : {tot_evento}   (cancelamentos: {tot_cancel})")
    print(f"    resumos ignorados   : {tot_resumo}")
    print(f"    outros ignorados    : {tot_outro}")
    print(f"    erros (doc a doc)   : {tot_erro}")
    print(f"    NSU final           : {ult_nsu}  (maxNSU visto: {max_nsu})")

    if motivo_fim == "completo":
        print("\n    >>> TERMINOU: pegou tudo (ult_nsu >= maxNSU).")
    elif motivo_fim == "fim137":
        print("\n    >>> TERMINOU: SEFAZ sem documentos novos (137, em dia).")
    elif motivo_fim == "656":
        print(f"\n    >>> PAROU por 656 (consumo indevido). Faltam ~{falta_final} NSU. "
              "Espere ~1h e rode de novo -- continua de onde parou.")
    elif motivo_fim == "limite":
        print(f"\n    >>> PAROU no limite de {MAX_LOTES} lotes. Faltam ~{falta_final} NSU. "
              "Rode de novo pra continuar.")
    else:
        print(f"\n    >>> PAROU por cStat inesperado ({motivo_fim}). "
              f"Faltam ~{falta_final} NSU.")

    print("=" * 74)
    print("FIM - captura em massa concluida. Nada foi manifestado.")
    print("=" * 74)


if __name__ == "__main__":
    main()
