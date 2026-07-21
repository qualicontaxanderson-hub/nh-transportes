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
import consulta_sefaz_cte as cte
import processa_dfe as pd
from integrations.dfe_classificacao import aplicar_regras
from integrations import dfe_log

# --------------------------------------------------------------------------
# Parametros de seguranca desta captura em massa.
# --------------------------------------------------------------------------
PAUSA_SEGUNDOS = 20   # pausa entre lotes (comeca conservador; pode subir depois)
MAX_LOTES = 40        # teto de lotes por execucao (nao roda infinito nem abusa)
MAX_LOTES_CTE = 15    # teto MENOR da Fase B (CT-e): a 1a consulta vem cheia (ate 3
                      # meses de historico) e nao pode estourar o timeout de 20 min
                      # do subprocess; o resto vem nas proximas rodadas.

# Quem disparou esta rodada. O agendador injeta DFE_ORIGEM no subprocess
# ('agendador' ou 'manual'); rodando na mao pelo terminal fica 'cli'. So rotula
# o log -- nao muda nenhum comportamento da captura.
ORIGEM = os.environ.get('DFE_ORIGEM', 'cli')
if ORIGEM not in dfe_log.ORIGENS:
    ORIGEM = 'cli'


def _log_avulso(cliente_id, cnpj, evento, **kw):
    """Grava UMA linha do log com conexao propria. Para os pontos FORA do loop
    principal (ex.: rodada pulada pela cota), onde ainda nao ha conexao aberta.
    Best-effort: log nunca derruba a captura."""
    try:
        con = pymysql.connect(**cs.CONN)
        try:
            with con.cursor() as c:
                dfe_log.garantir_tabela(c)
                dfe_log.registrar(c, ORIGEM, evento, cliente_id=cliente_id,
                                  cnpj=cnpj, **kw)
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


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
             n_itens=0, n_cancel=0, n_cte=0, n_resumo_cte=0)

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
        elif kind == "cte":
            c["n_cte"] += 1
            c["n_itens"] += ni   # ni = qtd de NF-e vinculadas
        elif kind == "resumo_cte":
            c["n_resumo_cte"] += 1
        else:
            c["n_outro"] += 1
            print(f"      [NSU {nsu}] tipo nao modelado (resEvento) -- seguindo.")

        nsu_ok = nsu   # so avanca a marca APOS salvar com sucesso

    return c, nsu_ok, houve_falha


def _consultar_cte(sess, cnpj_cert, ult_nsu):
    """Espelho de _consultar(), no endpoint do CTeDistribuicaoDFe. MESMA sessao
    mTLS (o cert serve os dois hosts). Retorna (ret_element, bytes)."""
    soap, _ult_fmt = cte.montar_soap_cte(cnpj_cert, ult_nsu)
    headers = {
        "Content-Type": (
            'application/soap+xml; charset=utf-8; '
            f'action="{cte.ACTION_CTE}"'
        ),
        "User-Agent": "nh-transportes/captura-massa-cte (loop)",
    }
    r = sess.post(cte.ENDPOINT_CTE, data=soap.encode("utf-8"), headers=headers,
                  timeout=cs.TIMEOUT)
    if r.status_code != 200:
        cs.falhar("HTTP != 200 (CTe)", f"status {r.status_code}")
    env = ET.fromstring(r.content)
    ret = cs._find(env, "retDistDFeInt")   # resposta tem a MESMA estrutura da NF-e
    if ret is None:
        cs.falhar("sem retDistDFeInt (CTe)", "resposta inesperada da SEFAZ.")
    return ret, len(r.content)


def capturar_cte(sess, cliente_id, cnpj_cert):
    """FASE B: mesmo run, mesmo lock, mesma sessao mTLS -- MAS endpoint, cursor
    (dfe_nsu_cte) e cota do CT-e, 100% independentes da NF-e. Se a NF-e estiver
    de castigo por 656, ISTO RODA MESMO ASSIM (cota separada). Reusa _consultar_cte
    e o MESMO _processar_docs (pd.processar_um_doc ja roteia cteProc/resCTe)."""
    print("\n" + "=" * 74)
    print("[FASE B] CAPTURA CT-e -- CTeDistribuicaoDFe (endpoint/cursor proprios)")
    print(f"         versao distDFeInt(CTe) = {cte.VERSAO_CTE}")
    print("=" * 74)
    ult_nsu, _prox = cte.ler_ult_nsu_cte(cliente_id)
    print(f"    ult_nsu (CTe) = {ult_nsu}")
    bloqueio = cte.bloqueado_por_cota_cte(cliente_id)   # cota SEPARADA da NF-e
    if bloqueio:
        print(f"    ATENCAO: proximo_permitido(CTe) = {bloqueio} ainda no futuro. "
              "Pulando Fase B sem consultar.")
        _log_avulso(cliente_id, cnpj_cert, 'pulado_cota', ult_nsu_env=ult_nsu,
                    detalhe=f"CTe: proximo_permitido={bloqueio} no futuro; nao consultou")
        return
    tot_cte = tot_resumo_cte = tot_outro = 0
    lotes = 0
    max_nsu = 0
    motivo_fim = "limite"
    conn = pymysql.connect(**cs.CONN)
    try:
        cur = conn.cursor()
        while lotes < MAX_LOTES_CTE:
            agora = datetime.now()
            expira = (agora + timedelta(days=pd.DIAS_RETENCAO)).date()
            try:
                ret, _nbytes = _consultar_cte(sess, cnpj_cert, ult_nsu)
            except BaseException as exc:
                dfe_log.registrar(
                    cur, ORIGEM, 'erro', cliente_id=cliente_id, cnpj=cnpj_cert,
                    ult_nsu_env=ult_nsu, lote=lotes + 1,
                    detalhe=f"CTe: falha na requisicao -- {type(exc).__name__}: {exc}")
                conn.commit()
                raise
            cStat   = cs._text(ret, "cStat")
            xMotivo = cs._text(ret, "xMotivo")
            ret_ult = pd._to_int(cs._text(ret, "ultNSU")) or 0
            ret_max = pd._to_int(cs._text(ret, "maxNSU")) or 0
            status_txt = f"CTe {cStat} {xMotivo}"[:255]   # prefixo CTe p/ auditar o log
            def _log_consulta(**extra):
                dfe_log.registrar(
                    cur, ORIGEM, 'consulta', cliente_id=cliente_id, cnpj=cnpj_cert,
                    ult_nsu_env=ult_nsu, c_stat=cStat, x_motivo=xMotivo,
                    ret_ult_nsu=ret_ult, ret_max_nsu=ret_max, lote=lotes + 1, **extra)
            # ----- 656: para sem mexer no cursor; +1h na dfe_nsu_cte -----
            if cStat == "656":
                cur.execute(cte.SQL_NSU_CTE_656, (
                    cliente_id, cnpj_cert, ult_nsu, ret_max or max_nsu or 0, status_txt))
                _log_consulta(detalhe="CTe 656: parou sem avancar; proximo_permitido=+1h")
                conn.commit()
                motivo_fim = "656"
                print(f"    >>> [CTe] 656 CONSUMO INDEVIDO. Para SEM avancar "
                      f"(ult_nsu={ult_nsu}); +1h. Continua no proximo ciclo.")
                break
            # ----- 137: em dia -----
            if cStat == "137":
                cur.execute(cte.SQL_NSU_CTE_OK, (
                    cliente_id, cnpj_cert, ult_nsu, ret_max or max_nsu or ult_nsu, status_txt))
                _log_consulta(detalhe="CTe 137: nenhum CT-e novo (em dia)")
                conn.commit()
                motivo_fim = "fim137"
                print("    [CTe] cStat 137: nenhum CT-e novo. Em dia.")
                break
            # ----- qualquer outro != 138 (inclui versao invalida) -----
            if cStat != "138":
                cur.execute(cte.SQL_NSU_CTE_OK, (
                    cliente_id, cnpj_cert, ult_nsu, ret_max or max_nsu or 0, status_txt))
                _log_consulta(detalhe=f"CTe cStat inesperado {cStat}: parou")
                conn.commit()
                motivo_fim = f"cstat_{cStat}"
                print(f"    [CTe] cStat inesperado {cStat} ({xMotivo}). Parando. "
                      "(se for versao invalida, ajuste a env DFE_CTE_VERSAO)")
                break
            # ----- 138: mesmo _processar_docs da NF-e (roteia cteProc/resCTe) -----
            c, novo_ult, houve_falha = _processar_docs(
                conn, cur, ret, cliente_id, cnpj_cert, agora, expira, ult_nsu)
            cur.execute(cte.SQL_NSU_CTE_OK, (
                cliente_id, cnpj_cert, novo_ult, ret_max or 0, status_txt))
            _log_consulta(
                docs=c["docs"],
                detalhe=("CTe 138: %d docs (%d CTe, %d resCTe, %d outros); cursor %d->%d%s"
                         % (c["docs"], c["n_cte"], c["n_resumo_cte"], c["n_outro"],
                            ult_nsu, novo_ult,
                            "; PAROU por falha ao salvar" if houve_falha else "")))
            conn.commit()
            lotes += 1
            max_nsu = ret_max or max_nsu
            tot_cte += c["n_cte"]
            tot_resumo_cte += c["n_resumo_cte"]
            tot_outro += c["n_outro"]
            ult_nsu = novo_ult
            falta = max(0, (max_nsu or 0) - novo_ult)
            print(f"[CTe] Lote {lotes}: +{c['n_cte']} CT-e, +{c['n_resumo_cte']} resCTe "
                  f"(outros {c['n_outro']}) | NSU={novo_ult} (falta {falta})")
            if houve_falha:
                motivo_fim = "falha_doc"
                break
            if max_nsu and novo_ult >= max_nsu:
                motivo_fim = "completo"
                break
            time.sleep(PAUSA_SEGUNDOS)
        cur.close()
    finally:
        conn.close()
    print("\n[FASE B] RESUMO CT-e: %d lote(s), %d CT-e completos, %d resCTe, "
          "%d outros | NSU final=%d (max=%d) | fim=%s"
          % (lotes, tot_cte, tot_resumo_cte, tot_outro, ult_nsu, max_nsu, motivo_fim))


# ==========================================================================
# FASE A - NF-e (NFeDistribuicaoDFe). Cursor/cota em dfe_nsu. Corpo extraido do
# antigo main(): recebe sess/cliente_id/cnpj_cert por PARAMETRO (cert/sessao/DDLs
# agora moram no main orquestrador). No ramo de cota bloqueada faz return DA
# FUNCAO (nao do processo), pra a Fase B rodar mesmo se a NF-e estiver de 656.
# ==========================================================================
def capturar_nfe(sess, cliente_id, cnpj_cert):
    # 2) ult_nsu atual + respeita proximo_permitido (comparado no relogio do BANCO).
    print("\n[2] Lendo ult_nsu (dfe_nsu)...")
    ult_nsu, _proximo = cs.ler_ult_nsu(cliente_id)
    print(f"    ult_nsu = {ult_nsu}")
    bloqueio = pd.bloqueado_por_cota(cliente_id)
    if bloqueio:
        print(f"    ATENCAO: proximo_permitido = {bloqueio} (relogio do banco) ainda no "
              "futuro. A SEFAZ pediu para aguardar (656 recente). Encerrando sem consultar.")
        _log_avulso(cliente_id, cnpj_cert, 'pulado_cota', ult_nsu_env=ult_nsu,
                    detalhe=f"proximo_permitido={bloqueio} ainda no futuro; "
                            "encerrou sem consultar a SEFAZ")
        return

    # 4) Loop de lotes.
    tot_nota = tot_evento = tot_itens = tot_cancel = tot_resumo = tot_outro = 0
    tot_cte = tot_resumo_cte = 0
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

            # A requisicao em si pode morrer (rede/cert/timeout) ou chamar
            # cs.falhar() -> SystemExit. Nos dois casos o log fica: sem isso a
            # rodada some sem deixar rastro, que e o problema que este log existe
            # para resolver.
            try:
                ret, _nbytes = _consultar(sess, cnpj_cert, ult_nsu)
            except BaseException as exc:
                dfe_log.registrar(
                    cur, ORIGEM, 'erro', cliente_id=cliente_id, cnpj=cnpj_cert,
                    ult_nsu_env=ult_nsu, lote=lotes + 1,
                    detalhe=f"falha na requisicao a SEFAZ -- {type(exc).__name__}: {exc}",
                )
                conn.commit()
                raise

            cStat = cs._text(ret, "cStat")
            xMotivo = cs._text(ret, "xMotivo")
            ret_ult = pd._to_int(cs._text(ret, "ultNSU")) or 0
            ret_max = pd._to_int(cs._text(ret, "maxNSU")) or 0
            status_txt = f"{cStat} {xMotivo}"[:255]

            # Log da consulta CRUA, antes de qualquer decisao: e a unica coisa
            # que sobrevive para responder "o que a SEFAZ respondeu as 03:05?".
            # docs/notas/eventos sao completados adiante no ramo 138.
            def _log_consulta(**extra):
                dfe_log.registrar(
                    cur, ORIGEM, 'consulta', cliente_id=cliente_id, cnpj=cnpj_cert,
                    ult_nsu_env=ult_nsu, c_stat=cStat, x_motivo=xMotivo,
                    ret_ult_nsu=ret_ult, ret_max_nsu=ret_max, lote=lotes + 1,
                    **extra
                )

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
                _log_consulta(detalhe="656: parou sem avancar o cursor; "
                                      "proximo_permitido = agora + 1h")
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
                _log_consulta(detalhe="137: nenhum documento novo (em dia)")
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
                _log_consulta(detalhe=f"cStat inesperado {cStat}: parou")
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
            _log_consulta(
                docs=c["docs"], notas=c["n_nota"], eventos=c["n_evento"],
                detalhe=("138: %d docs (%d notas, %d resumos, %d CTe, %d resCTe, "
                         "%d eventos, %d outros); cursor %d -> %d%s"
                         % (c["docs"], c["n_nota"], c["n_resumo"], c["n_cte"],
                            c["n_resumo_cte"], c["n_evento"], c["n_outro"],
                            ult_nsu, novo_ult,
                            "; PAROU por falha ao salvar" if houve_falha else "")),
            )
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
            tot_cte += c["n_cte"]
            tot_resumo_cte += c["n_resumo_cte"]
            ult_nsu = novo_ult
            falta = max(0, (max_nsu or 0) - novo_ult)

            print(f"Lote {lotes}: +{c['n_nota']} notas, +{c['n_resumo']} resumos, "
                  f"+{c['n_cte']} CT-e, +{c['n_evento']} eventos, +{c['n_itens']} itens "
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
    print(f"    CT-e completos      : {tot_cte}")
    print(f"    resumos de CT-e     : {tot_resumo_cte}   (resCTe)")
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


# ==========================================================================
# MAIN - orquestrador das 2 fases (A: NF-e / B: CT-e), mesmo run e mesmo lock.
# ==========================================================================
def main():
    print("=" * 74)
    print("CAPTURA EM MASSA DFe - FASE A (NF-e) + FASE B (CT-e), mesmo run/lock")
    print("SO CONSULTA E SALVA. NAO manifesta.")
    print("=" * 74)
    # 1) Certificado (uma vez; serve os dois endpoints).
    cliente_id, cnpj_cert, cert, chave_priv, cadeia = cs.abrir_certificado()
    print(f"[1] cert OK: cliente_id={cliente_id} cnpj={cnpj_cert}")
    # 2) DDLs idempotentes (+ dfe_nsu_cte) e sessao mTLS unica.
    con0 = pymysql.connect(**cs.CONN)
    try:
        with con0.cursor() as c0:
            c0.execute(pd.DDL_EVENTOS)
            c0.execute(pd.DDL_CTE)
            c0.execute(pd.DDL_CTE_NFE)
            c0.execute(cte.DDL_NSU_CTE)     # <-- cursor CT-e
            dfe_log.garantir_tabela(c0)
        con0.commit()
    finally:
        con0.close()
    sess = cs.montar_sessao_mtls(cert, chave_priv, cadeia)
    # FASE A: NF-e (cota/cursor dfe_nsu) -- corpo atual, so vira funcao.
    capturar_nfe(sess, cliente_id, cnpj_cert)
    # FASE B: CT-e (cota/cursor dfe_nsu_cte) -- roda mesmo se A estiver bloqueada.
    capturar_cte(sess, cliente_id, cnpj_cert)
    print("\nFIM - captura A+B concluida. Nada foi manifestado.")


if __name__ == "__main__":
    main()
