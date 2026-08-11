# -*- coding: utf-8 -*-
# ============================================================================
#  SEMENTE do de-para de produto da VENDA (vendas_xml_depara_produto).
#
#  Popula o de-para (cnpj_emitente + cprod -> nosso produto_id) e resolve o
#  PASSIVO retroativo: preenche vendas_xml_itens.produto_id SO nos itens que
#  casam no de-para (os 4 combustiveis do posto). O resto (lubrificante, ARLA,
#  odorizante...) fica NULL de proposito -- nao e combustivel de tanque.
#
#  Espelha o de-para da COMPRA (dfe_classificacao_regra). Diferencas: a venda
#  nao tem 'categoria' (venda e sempre produto) e a chave e o cnpj_emitente
#  (a venda nao carrega cliente_id).
#
#  SOMENTE LEITURA por padrao (mostra o que faria). So grava com --apply.
#
#  Uso (PowerShell):
#     $env:DB_PASSWORD = "<senha>"
#     python scripts/semente_depara_venda.py            # preview, nada muda
#     python scripts/semente_depara_venda.py --apply    # grava
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

APLICAR = ("--apply" in sys.argv) or ("--aplicar" in sys.argv)

# ---- Mapeamento do Posto NH (revise antes de aplicar) ----
CNPJ = "33503987000116"
# (cprod no posto, nosso produto_id, rotulo so p/ conferencia visual)
PARES = [
    ("1", 2, "GASOLINA C COMUM        -> Gasolina (id 2)"),
    ("2", 1, "ETANOL HIDRATADO COMUM  -> Etanol   (id 1)"),
    ("3", 4, "OLEO DIESEL B S500      -> S-500    (id 4)"),
    ("4", 5, "OLEO DIESEL B S10       -> S-10     (id 5)"),
]

SEP = "=" * 74


def main():
    con = pymysql.connect(**CONN)
    try:
        cur = con.cursor()
        cur.execute("SELECT DATABASE() AS db")
        print("Banco:", cur.fetchone()["db"])
        print("Modo :", "APLICAR (vai gravar)" if APLICAR else "PREVIEW (nada muda)")
        print("CNPJ :", CNPJ)

        # ---- 0) confere que cada produto_id existe e com que nome ----
        print("\n" + SEP)
        print("PARES A GRAVAR NO DE-PARA (confira nome do produto):")
        print(SEP)
        for cprod, pid, rotulo in PARES:
            cur.execute("SELECT nome FROM produto WHERE id = %s", (pid,))
            row = cur.fetchone()
            nome = row["nome"] if row else "*** produto_id INEXISTENTE ***"
            print("  cprod %-2s -> produto_id %s  [%s]  (%s)" % (cprod, pid, nome, rotulo))

        # ---- 1) itens de venda por (cnpj+cprod): o que casa e o que fica NULL ----
        print("\n" + SEP)
        print("VENDAS DESTE EMITENTE por cprod (o que o de-para vai resolver):")
        print(SEP)
        print("  cprod | xProd (amostra)              | cod_anp    | itens  | prod_id atual -> alvo | muda")
        print("  ------+------------------------------+------------+--------+-----------------------+------")
        alvo = {cprod: pid for cprod, pid, _ in PARES}
        total_mudam = 0
        cur.execute(
            """
            SELECT i.cprod,
                   MAX(i.produto_xml) AS xprod,
                   MAX(i.cod_anp)     AS cod_anp,
                   COUNT(*)           AS itens,
                   SUM(i.produto_id IS NULL) AS n_null
            FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            WHERE v.cnpj_emitente = %s
            GROUP BY i.cprod
            ORDER BY itens DESC
            """,
            (CNPJ,),
        )
        for r in cur.fetchall():
            cprod = r["cprod"]
            pid = alvo.get(cprod)
            if pid is None:
                destino = "(fora do de-para -> fica NULL)"
                muda = "-"
            else:
                # quantos ficariam diferentes do alvo (null-safe)
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM vendas_xml_itens i
                    JOIN vendas_xml v ON v.id = i.venda_id
                    WHERE v.cnpj_emitente = %s AND i.cprod = %s
                      AND NOT (i.produto_id <=> %s)
                    """,
                    (CNPJ, cprod, pid),
                )
                n_muda = cur.fetchone()["n"]
                total_mudam += n_muda
                destino = "NULL/outro -> %s" % pid
                muda = str(n_muda)
            print("  %-5s | %-28s | %-10s | %6d | %-21s | %s"
                  % (cprod, (r["xprod"] or "")[:28], r["cod_anp"] or "", r["itens"], destino, muda))

        # ---- 2) de-para atual deste emitente ----
        print("\n" + SEP)
        print("DE-PARA ATUAL (vendas_xml_depara_produto) deste emitente:")
        print(SEP)
        cur.execute(
            "SELECT cprod, produto_id, ativo FROM vendas_xml_depara_produto "
            "WHERE cnpj_emitente = %s ORDER BY cprod",
            (CNPJ,),
        )
        atuais = cur.fetchall()
        if not atuais:
            print("  (vazio)")
        else:
            for r in atuais:
                print("  cprod %-2s -> produto_id %s (ativo=%s)" % (r["cprod"], r["produto_id"], r["ativo"]))

        # ---- resumo ----
        print("\n" + SEP)
        print("RESUMO: %d item(ns) de venda seriam preenchidos/corrigidos." % total_mudam)
        print(SEP)

        if not APLICAR:
            print("\nNada foi alterado. Para gravar:")
            print('   $env:DB_PASSWORD = "<senha>"; python scripts/semente_depara_venda.py --apply')
            return

        # ================= APLICA =================
        # (a) grava/atualiza os 4 pares no de-para (idempotente).
        for cprod, pid, _ in PARES:
            cur.execute(
                """
                INSERT INTO vendas_xml_depara_produto (cnpj_emitente, cprod, produto_id, ativo)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE produto_id = VALUES(produto_id), ativo = 1
                """,
                (CNPJ, cprod, pid),
            )
        # (b) resolve o passivo: preenche produto_id dos itens que casam no de-para.
        #     null-safe: so toca linhas que ficariam diferentes do de-para.
        cur.execute(
            """
            UPDATE vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            JOIN vendas_xml_depara_produto dp
              ON dp.cnpj_emitente = v.cnpj_emitente
             AND dp.cprod = i.cprod
             AND dp.ativo = 1
            SET i.produto_id = dp.produto_id
            WHERE NOT (i.produto_id <=> dp.produto_id)
            """
        )
        afetados = cur.rowcount
        con.commit()

        print("\nAPLICADO: %d item(ns) atualizados." % afetados)
        cur.execute(
            """
            SELECT SUM(i.produto_id IS NULL) AS ainda_null, COUNT(*) AS total
            FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            WHERE v.cnpj_emitente = %s
            """,
            (CNPJ,),
        )
        r = cur.fetchone()
        print("  itens deste emitente ainda com produto_id NULL: %s de %s "
              "(esperado: nao-combustivel)" % (r["ainda_null"], r["total"]))
    finally:
        con.close()
    print("\nFIM")


if __name__ == "__main__":
    main()
