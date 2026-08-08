# -*- coding: utf-8 -*-
# ============================================================================
#  Preenche o produto_id que ficou NULL em descargas_pendentes e
#  leitura_tanque_diaria, usando o matcher NOVO (por slug).
#
#  DEPENDE de o matcher novo ja estar em integrations/els_email.py — ele e
#  importado daqui, nao copiado, para nao existirem duas regras.
#
#  SOMENTE LEITURA por padrao. So grava com --aplicar.
#
#  NAO altera linhas que ja tem produto_id. Se o matcher novo discordar de um
#  produto_id ja gravado (resquicio do bug da chave generica 'DIESEL'), isso e
#  apenas RELATADO — corrigir e decisao separada, porque sobrescrever vinculo
#  de produto ja usado em relatorio e outra conversa.
#
#  Uso:
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/backfill_produto_id.py             # so mostra
#     python scripts/backfill_produto_id.py --aplicar   # grava
# ============================================================================
import os
import sys

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONN = dict(
    host="centerbeam.proxy.rlwy.net", port=56026, user="root",
    password=os.environ.get("DB_PASSWORD") or "",
    database="railway", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    read_timeout=60, connect_timeout=15,
)
if not CONN["password"]:
    sys.exit('DB_PASSWORD nao definido. Rode: $env:DB_PASSWORD = "<senha>"')

from integrations.els_email import resolver_produto_id  # noqa: E402

TABELAS = ("descargas_pendentes", "leitura_tanque_diaria")
APLICAR = "--aplicar" in sys.argv

con = pymysql.connect(**CONN)
try:
    cur = con.cursor()
    cur.execute("SELECT DATABASE() AS db")
    print("Banco:", cur.fetchone()["db"])
    print("Modo :", "APLICAR (vai gravar)" if APLICAR else "SOMENTE LEITURA (nada muda)")

    total_geral = 0
    for tab in TABELAS:
        print("\n" + "=" * 74)
        print(tab)
        print("=" * 74)

        cur.execute(f"""
            SELECT produto_nome, COUNT(*) AS n
            FROM {tab}
            WHERE produto_id IS NULL AND produto_nome IS NOT NULL AND produto_nome <> ''
            GROUP BY produto_nome ORDER BY produto_nome
        """)
        pendentes = cur.fetchall()
        if not pendentes:
            print("  Nenhuma linha com produto_id NULL.")
        else:
            print("  produto_nome              | linhas | vai virar")
            print("  --------------------------+--------+------------------------------")
            for p in pendentes:
                pid, pnome = resolver_produto_id(cur, p["produto_nome"])
                if pid:
                    print("  %-25s | %6d | %s (id %s)"
                          % (p["produto_nome"][:25], p["n"], pnome, pid))
                    total_geral += p["n"]
                    if APLICAR:
                        cur.execute(
                            f"UPDATE {tab} SET produto_id = %s "
                            f"WHERE produto_nome = %s AND produto_id IS NULL",
                            (pid, p["produto_nome"]))
                else:
                    print("  %-25s | %6d | SEM CORRESPONDENTE (fica NULL)"
                          % (p["produto_nome"][:25], p["n"]))

        # Divergencias: produto_id gravado x o que o matcher novo diria.
        cur.execute(f"""
            SELECT produto_nome, produto_id, COUNT(*) AS n
            FROM {tab}
            WHERE produto_id IS NOT NULL AND produto_nome IS NOT NULL
            GROUP BY produto_nome, produto_id ORDER BY produto_nome
        """)
        div = []
        for r in cur.fetchall():
            pid, pnome = resolver_produto_id(cur, r["produto_nome"])
            if pid and pid != r["produto_id"]:
                div.append((r["produto_nome"], r["produto_id"], pid, pnome, r["n"]))
        if div:
            print("\n  ATENCAO — ja tem produto_id, mas o matcher novo discorda")
            print("  (provavel resquicio da chave generica 'DIESEL'). NAO sera alterado:")
            for nome, atual, novo, novo_nome, n in div:
                print("    %-25s id %s -> diria %s (%s)  em %d linha(s)"
                      % (nome[:25], atual, novo, novo_nome, n))
        else:
            print("\n  Nenhuma divergencia nas linhas que ja tem produto_id.")

    if APLICAR:
        con.commit()
        print("\n" + "=" * 74)
        print("APLICADO: %d linha(s) preenchidas." % total_geral)
        for tab in TABELAS:
            cur.execute(f"SELECT COUNT(*) AS n FROM {tab} WHERE produto_id IS NULL")
            print("  %-24s ainda NULL: %d" % (tab, cur.fetchone()["n"]))
    else:
        print("\n" + "=" * 74)
        print("Nada foi alterado. %d linha(s) seriam preenchidas." % total_geral)
        print("Para gravar: python scripts/backfill_produto_id.py --aplicar")

    cur.close()
finally:
    con.close()

print("\nFIM")
