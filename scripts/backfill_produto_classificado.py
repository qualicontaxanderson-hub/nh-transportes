# -*- coding: utf-8 -*-
# ============================================================================
#  PASSIVO: a classificacao que o usuario fez nunca chegou em dfe_itens.produto_id
#
#  Ate 16/09/2026 havia duas colunas dizendo a mesma coisa em dfe_itens:
#
#     produto_id                 preenchido na CAPTURA, por um chute no cod_anp
#     classificado_produto_id    preenchido pelo USUARIO, na tela Classificar
#
#  Os relatorios leem a primeira. A tela escreve na segunda. Resultado: item
#  classificado a mao continuava invisivel em /relatorios/fornecedores_migrados
#  -> Por produto. Nao era falta de classificar: ja estava classificado.
#
#  O chute pelo ANP saiu (o ANP identifica familia, nao produto: o 620505001
#  cobre 37 itens do posto, de ARLA a tacografo) e a regra memorizada passou a
#  escrever nas duas colunas. Falta so o passivo -- e o que este script resolve.
#
#  Copia classificado_produto_id -> produto_id SO onde produto_id esta NULL.
#  Nunca sobrescreve um produto_id que ja existe.
#
#  SOMENTE LEITURA por padrao (mostra o que faria). So grava com --apply.
#
#  Uso (PowerShell):
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/backfill_produto_classificado.py            # preview
#     python scripts/backfill_produto_classificado.py --apply    # grava
# ============================================================================
import os
import sys

import pymysql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONN = dict(
    host=os.environ.get("DB_HOST") or "centerbeam.proxy.rlwy.net",
    port=int(os.environ.get("DB_PORT") or 56026),
    user=os.environ.get("DB_USER") or "root",
    password=os.environ.get("DB_PASSWORD") or "",
    database=os.environ.get("DB_NAME") or "railway",
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    read_timeout=60, connect_timeout=15,
)
if not CONN["password"]:
    sys.exit('DB_PASSWORD nao definido. Rode: $env:DB_PASSWORD = "<senha>"')

APLICAR = ("--apply" in sys.argv) or ("--aplicar" in sys.argv)
SEP = "=" * 78


def main():
    con = pymysql.connect(**CONN)
    try:
        cur = con.cursor()
        cur.execute("SELECT DATABASE() AS db")
        print("Banco:", cur.fetchone()["db"])
        print("Modo :", "APLICAR (vai gravar)" if APLICAR else "PREVIEW (nada muda)")

        # ---- 1) o que esta parado: classificado, mas invisivel ----
        print("\n" + SEP)
        print("ITENS CLASSIFICADOS QUE O RELATORIO NAO VE (produto_id NULL):")
        print(SEP)
        cur.execute(
            """
            SELECT p.nome, i.categoria, COUNT(*) AS itens,
                   ROUND(SUM(i.quantidade), 0) AS qtd,
                   MIN(DATE(d.dh_emissao)) AS de, MAX(DATE(d.dh_emissao)) AS ate
              FROM dfe_itens i
              JOIN dfe_documentos d ON d.id = i.documento_id
              LEFT JOIN produto p ON p.id = i.classificado_produto_id
             WHERE i.produto_id IS NULL
               AND i.classificado_produto_id IS NOT NULL
             GROUP BY p.nome, i.categoria
             ORDER BY itens DESC
            """
        )
        linhas = cur.fetchall()
        if not linhas:
            print("  (nada parado -- o passivo ja foi resolvido)")
        for r in linhas:
            print("  %-10s %-12s %4d itens  %12s  de %s a %s"
                  % (r["nome"] or "?", r["categoria"] or "-", r["itens"],
                     "{:,.0f}".format(r["qtd"] or 0).replace(",", "."),
                     r["de"], r["ate"]))
        total = sum(r["itens"] for r in linhas)

        # ---- 2) o que o relatorio Por produto mostra hoje, e mostraria depois ----
        print("\n" + SEP)
        print("O RELATORIO 'Por produto' (so combustivel), ANTES x DEPOIS:")
        print(SEP)
        cur.execute(
            """
            SELECT p.nome,
                   SUM(i.produto_id IS NOT NULL) AS itens_hoje,
                   ROUND(SUM(CASE WHEN i.produto_id IS NOT NULL
                                  THEN i.quantidade END), 0) AS qtd_hoje,
                   COUNT(*) AS itens_dep,
                   ROUND(SUM(i.quantidade), 0) AS qtd_dep
              FROM dfe_itens i
              LEFT JOIN produto p
                     ON p.id = COALESCE(i.produto_id, i.classificado_produto_id)
             WHERE i.categoria = 'combustivel'
               AND COALESCE(i.produto_id, i.classificado_produto_id) IS NOT NULL
             GROUP BY p.nome
             ORDER BY qtd_dep DESC
            """
        )
        print("  produto    |     itens hoje ->  depois |        litros hoje ->        depois")
        print("  -----------+---------------------------+-----------------------------------")
        t_ih = t_id = 0
        t_qh = t_qd = 0.0
        for r in cur.fetchall():
            ih, idp = int(r["itens_hoje"] or 0), int(r["itens_dep"] or 0)
            qh, qd = float(r["qtd_hoje"] or 0), float(r["qtd_dep"] or 0)
            t_ih += ih; t_id += idp; t_qh += qh; t_qd += qd
            print("  %-10s | %9d -> %9d | %13s -> %13s"
                  % (r["nome"] or "?", ih, idp,
                     "{:,.0f}".format(qh).replace(",", "."),
                     "{:,.0f}".format(qd).replace(",", ".")))
        print("  -----------+---------------------------+-----------------------------------")
        print("  TOTAL      | %9d -> %9d | %13s -> %13s"
              % (t_ih, t_id,
                 "{:,.0f}".format(t_qh).replace(",", "."),
                 "{:,.0f}".format(t_qd).replace(",", ".")))

        # ---- 3) trava: nunca sobrescrever um produto_id que ja existe ----
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM dfe_itens
             WHERE produto_id IS NOT NULL
               AND classificado_produto_id IS NOT NULL
               AND produto_id <> classificado_produto_id
            """
        )
        conflitos = cur.fetchone()["n"]
        print("\n" + SEP)
        print("CONFERENCIA: itens onde as duas colunas DISCORDAM: %d" % conflitos)
        print("  (este script nao toca neles -- so preenche o que esta NULL)")
        print(SEP)
        print("RESUMO: %d item(ns) seriam preenchidos." % total)
        print(SEP)

        if not APLICAR:
            print("\nNada foi alterado. Para gravar:")
            print('   $env:DB_PASSWORD = "<senha>"; '
                  'python scripts/backfill_produto_classificado.py --apply')
            return

        cur.execute(
            """
            UPDATE dfe_itens
               SET produto_id = classificado_produto_id
             WHERE produto_id IS NULL
               AND classificado_produto_id IS NOT NULL
            """
        )
        afetados = cur.rowcount
        con.commit()
        print("\nAPLICADO: %d item(ns) atualizados." % afetados)

        cur.execute(
            """
            SELECT SUM(produto_id IS NULL AND classificado_produto_id IS NOT NULL) AS parados,
                   SUM(produto_id IS NULL) AS sem_produto, COUNT(*) AS total
              FROM dfe_itens
            """
        )
        r = cur.fetchone()
        print("  ainda parados (classificados e invisiveis): %s" % r["parados"])
        print("  sem produto nenhum (a classificar): %s de %s"
              % (r["sem_produto"], r["total"]))
    finally:
        con.close()
    print("\nFIM")


if __name__ == "__main__":
    main()
