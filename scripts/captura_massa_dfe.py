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
from integrations.dfe_classificacao import aplicar_regras

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
def _processar_docs(conn, cur, ret, cliente_id, cnpj_cert, agora, expira, ult_nsu):
    """Processa os docZip de UMA resposta 138, EM ORDEM DE NSU, avancando a
    marca-d'agua (nsu_ok) so APOS cada gravacao bem-sucedida. Se um doc falha,
    PARA na hora e devolve houve_falha=True: o chamador NAO deve avancar o
    ult_nsu alem de nsu_ok. Retorna (contagens, nsu_ok, houve_falha)."""
    lote = cs._find(ret, "loteDistDFeInt")
    docs = [e for e in (lote.iter() if lote is not None else [])
            if cs._local(e.tag) == "docZip"]
    docs.sort(key=lambda e: pd._to_int(e.get("NSU")) or 0)
    c = dict(docs=len(docs), n_nota=0, n_evento=0, n_resumo=0, n_outro=0,
             n_itens=0, n_cancel=0)

    nsu_ok = ult_nsu
    houve_falha = False
    for d in docs:
        nsu = pd._to_int(d.get("NSU"))
        try:
            kind, ni, canc = pd.processar_um_doc(
                conn, cur, cliente_id, cnpj_cert, d, agora, expira)
        except Exception as exc:
            conn.rollback()
            houve_falha = True
            print(f"      [NSU {nsu}] FALHA ao salvar: {exc}")
            print(f"      >>> PARANDO o lote; ult_nsu nao avanca alem de {nsu_ok} "
                  "(retenta no proximo ciclo).")
            break

        if kind == "nota":
            c["n_nota"] += 1
            c["n_itens"] += ni
        elif kind == "evento":
            c["n_evento"] += 1
            if canc:
                c["n_cancel"] += 1
        elif kind == "resumo":
            c["n_resumo"] += 1
        else:
            c["n_outro"] += 1
            print(f"      [NSU {nsu}] tipo nao modelado (CTe/resEvento) -- seguindo.")

        nsu_ok = nsu   # so avanca a marca APOS salvar com sucesso

    return c, nsu_ok, houve_falha


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
    tot_nota = tot_evento = tot_itens = tot_cancel = tot_resumo = tot_outro = 0
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

            # ----- 656: consumo indevido -> para na hora, SEM mexer no cursor -----
            # O 656 NAO traz documento. Avancar o cursor aqui PULA notas ainda
            # nao baixadas (foi o que sumiu com as de 11/07). Mantem ult_nsu
            # exatamente onde esta: NAO regride (nao volta pra 0, que e o que
            # dispara o 656) e NAO avanca. So agenda a espera de 1h e para; o
            # proximo ciclo retoma exatamente deste ponto.
            if cStat == "656":
                cur.execute(pd.SQL_NSU_656, (
                    cliente_id, cnpj_cert, ult_nsu, ret_max or max_nsu or 0,
                    status_txt,
                ))
                conn.commit()
                motivo_fim = "656"
                print(f"    >>> 656 CONSUMO INDEVIDO. Parando SEM avancar o cursor "
                      f"(ult_nsu={ult_nsu}); proximo_permitido = agora + 1h "
                      "(relogio do banco). Espere ~1h e rode de novo -- "
                      "continua exatamente daqui.")
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

            # ----- 138: processa o lote e avanca SO ate o ultimo NSU salvo -----
            c, novo_ult, houve_falha = _processar_docs(
                conn, cur, ret, cliente_id, cnpj_cert, agora, expira, ult_nsu)
            cur.execute(pd.SQL_NSU_OK, (
                cliente_id, cnpj_cert, novo_ult, ret_max or 0, status_txt,
            ))
            conn.commit()

            # Classificacao automatica dos itens novos que ja tem regra memorizada
            # (emit_cnpj + cprod). Best-effort e ISOLADO: se falhar, so faz rollback
            # dela -- a nota ja esta salva e o ult_nsu ja avancou.
            try:
                n_cls = aplicar_regras(cur)
                if n_cls:
                    conn.commit()
                    print(f"    (auto-classificacao: {n_cls} item(ns) por regra)")
            except Exception as exc:
                conn.rollback()
                print(f"    (aviso: auto-classificacao falhou: {exc})")

            lotes += 1
            max_nsu = ret_max or max_nsu
            tot_nota += c["n_nota"]
            tot_evento += c["n_evento"]
            tot_itens += c["n_itens"]
            tot_cancel += c["n_cancel"]
            tot_resumo += c["n_resumo"]
            tot_outro += c["n_outro"]
            ult_nsu = novo_ult
            falta = max(0, (max_nsu or 0) - novo_ult)

            print(f"Lote {lotes}: +{c['n_nota']} notas, +{c['n_resumo']} resumos, "
                  f"+{c['n_evento']} eventos, +{c['n_itens']} itens "
                  f"(outros {c['n_outro']}) | NSU agora={novo_ult} (falta {falta})")

            # ----- um doc falhou ao salvar: nao insiste agora; ult_nsu preservado -----
            if houve_falha:
                motivo_fim = "falha_doc"
                print("    >>> Parou por FALHA ao salvar um doc. ult_nsu preservado "
                      "no ultimo salvo; o proximo ciclo retenta a partir dele.")
                break

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
    print(f"    notas completas     : {tot_nota}   (itens: {tot_itens})")
    print(f"    resumos de nota     : {tot_resumo}   (resNFe -> aparecem em /dfe/compras)")
    print(f"    eventos gravados    : {tot_evento}   (cancelamentos: {tot_cancel})")
    print(f"    outros (nao modelados): {tot_outro}")
    print(f"    NSU final           : {ult_nsu}  (maxNSU visto: {max_nsu})")

    if motivo_fim == "completo":
        print("\n    >>> TERMINOU: pegou tudo (ult_nsu >= maxNSU).")
    elif motivo_fim == "fim137":
        print("\n    >>> TERMINOU: SEFAZ sem documentos novos (137, em dia).")
    elif motivo_fim == "falha_doc":
        print(f"\n    >>> PAROU por FALHA ao salvar um doc. ult_nsu preservado no "
              f"ultimo salvo ({ult_nsu}); faltam ~{falta_final} NSU. O proximo "
              "ciclo retenta a partir dali (nada foi pulado).")
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
