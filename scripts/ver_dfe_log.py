# -*- coding: utf-8 -*-
# ============================================================================
#  READ-ONLY - "o que aconteceu em cada rodada?"
#
#  Le dfe_consulta_log e mostra CADA rodada da captura de DFe em horario de
#  BRASILIA (o banco grava em UTC; aqui converte). Mostra tambem as rodadas que
#  NAO consultaram (puladas pela trava de cota / lock), que antes sumiam.
#
#  Uso:
#      python scripts/ver_dfe_log.py           -> ultimas 24h
#      python scripts/ver_dfe_log.py 72        -> ultimas 72h
# ============================================================================
import sys
import pymysql

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV", database="railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=30, connect_timeout=15,
)

HORAS = int(sys.argv[1]) if len(sys.argv) > 1 else 24

# Rotulos curtos por evento (o que a rodada FEZ).
ROTULO = {
    'consulta':    'CONSULTOU',
    'pulado_cota': 'PULADA (cota)',
    'pulado_lock': 'PULADA (lock)',
    'erro':        'ERRO',
}

con = pymysql.connect(**CONN)
try:
    with con.cursor() as cur:
        cur.execute("SELECT NOW() AS utc, CONVERT_TZ(NOW(),'+00:00','-03:00') AS brt")
        r = cur.fetchone()
        print("Agora: %s UTC  =  %s BRT" % (r["utc"], r["brt"]))
        print("Janela: ultimas %sh" % HORAS)
        print("=" * 100)

        cur.execute("""
            SELECT id,
                   CONVERT_TZ(momento,'+00:00','-03:00') AS brt,
                   momento AS utc, origem, evento, ult_nsu_env, c_stat,
                   x_motivo, ret_ult_nsu, ret_max_nsu, docs, notas, eventos,
                   lote, detalhe
              FROM dfe_consulta_log
             WHERE momento >= NOW() - INTERVAL %s HOUR
             ORDER BY momento, id
        """, (HORAS,))
        linhas = cur.fetchall()

        if not linhas:
            print()
            print("  (nenhuma rodada registrada nesta janela)")
            print()
            print("  Se a tabela acabou de ser criada, isso e esperado: ela enche a")
            print("  partir da PROXIMA rodada. Os slots do agendador sao de 3 em 3h")
            print("  no minuto :05 (00:05, 03:05, 06:05... horario de Brasilia).")
        for l in linhas:
            cab = "%s BRT  %-13s  %-9s" % (l["brt"], ROTULO.get(l["evento"], l["evento"]),
                                           l["origem"])
            if l["evento"] == "consulta":
                cab += "  cStat=%-4s  ultNSU_env=%s" % (l["c_stat"], l["ult_nsu_env"])
                if l["docs"]:
                    cab += "  docs=%s (notas=%s, eventos=%s)" % (l["docs"], l["notas"], l["eventos"])
            print(cab)
            if l["x_motivo"]:
                print("      SEFAZ: %s" % l["x_motivo"])
            if l["evento"] == "consulta" and (l["ret_ult_nsu"] or l["ret_max_nsu"]):
                print("      devolveu: ultNSU=%s  maxNSU=%s" % (l["ret_ult_nsu"], l["ret_max_nsu"]))
            if l["detalhe"]:
                print("      -> %s" % l["detalhe"])

        # ---- placar: e SEMPRE 656 ou as vezes funciona? ----
        print("=" * 100)
        print("PLACAR na janela de %sh (a pergunta 'e sempre 656?'):" % HORAS)
        cur.execute("""
            SELECT evento, c_stat, COUNT(*) AS n
              FROM dfe_consulta_log
             WHERE momento >= NOW() - INTERVAL %s HOUR
             GROUP BY evento, c_stat ORDER BY n DESC
        """, (HORAS,))
        placar = cur.fetchall()
        if not placar:
            print("  (sem dados ainda)")
        for p in placar:
            alvo = "%s%s" % (ROTULO.get(p["evento"], p["evento"]),
                             (" cStat=%s" % p["c_stat"]) if p["c_stat"] else "")
            print("  %-28s : %s" % (alvo, p["n"]))

        cur.execute("""
            SELECT SUM(c_stat='656') AS s656, SUM(c_stat='137') AS s137,
                   SUM(c_stat='138') AS s138, COUNT(c_stat) AS tot
              FROM dfe_consulta_log
             WHERE momento >= NOW() - INTERVAL %s HOUR AND evento='consulta'
        """, (HORAS,))
        p = cur.fetchone()
        if p and p["tot"]:
            print()
            print("  De %s consultas que chegaram na SEFAZ: %s deram 656, %s deram 137, "
                  "%s deram 138." % (p["tot"], p["s656"] or 0, p["s137"] or 0, p["s138"] or 0))
            if (p["s656"] or 0) == p["tot"]:
                print("  >>> 100%% 656: NAO e cota compartilhada intermitente -- e algo")
                print("      constante na nossa requisicao. Olhe a mensagem da SEFAZ acima.")
            elif (p["s138"] or 0) > 0:
                print("  >>> Nem sempre 656: a captura FUNCIONA as vezes -> cota/concorrencia.")
        print("=" * 100)
        cur.execute("SELECT COUNT(*) AS n FROM dfe_consulta_log")
        print("Total historico na tabela: %s linha(s)." % cur.fetchone()["n"])
finally:
    con.close()
