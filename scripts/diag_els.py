"""
scripts/diag_els.py
===================

Diagnostico READ-ONLY do porque a Etapa B "marcou lido mas nao gravou".
NAO grava nada (faz rollback) e NAO marca e-mail como lido.

Faz:
  1) Mostra a estrutura REAL de leitura_tanque_diaria e descargas_pendentes
     (colunas/tipos) + contagem de linhas. Se 'titulo' faltar ou data_leitura
     for DATE, a migration nao foi aplicada -> INSERT com 'titulo' falha.
  2) Le os e-mails do ELS dos ultimos 10 dias (LIDOS e nao-lidos), sem marcar.
  3) Para cada e-mail: detecta o tipo, mostra o que o parser extraiu e TENTA
     a gravacao dentro de uma transacao que sofre ROLLBACK no fim -> revela o
     erro REAL do INSERT (ex.: Unknown column 'titulo') sem persistir nada.

Como rodar (PowerShell, com DB_* + ELS_MAIL_* + ELS_CLIENTE_ID no ambiente):

    python scripts/diag_els.py
"""

import os
import sys
import traceback

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from config import Config
from utils.db import get_db_connection
from integrations import els_email as E


def mostrar_estrutura():
    db = Config.DB_NAME
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for tab in ("leitura_tanque_diaria", "descargas_pendentes"):
            print(f"\n=== {tab} ===")
            cur.execute(
                """SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION""",
                (db, tab),
            )
            cols = cur.fetchall()
            if not cols:
                print("   (tabela NAO existe)")
                continue
            for nome, tipo in cols:
                print(f"   {nome}: {tipo}")
            cur.execute(f"SELECT COUNT(*) FROM {tab}")
            print(f"   -> linhas: {cur.fetchone()[0]}")
    finally:
        cur.close()
        conn.close()


def diagnosticar_emails():
    cliente_id = E._cliente_id()
    print(f"\nELS_CLIENTE_ID = {cliente_id}")
    if cliente_id is None:
        print("ELS_CLIENTE_ID ausente; configure para testar a gravacao.")

    # LIDOS e nao-lidos (_buscar nunca marca); retorna (uid, assunto, texto)
    msgs = E._buscar(cfg_dias=10, apenas_nao_lidos=False)
    print(f"\n{len(msgs)} e-mail(s) do ELS nos ultimos 10 dias:\n")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        for i, (uid, assunto, texto) in enumerate(msgs, 1):
            tipo = E.detectar_tipo(assunto, texto)
            print(f"[{i}] tipo={tipo} | {assunto[:60]}")
            try:
                if tipo == "ABERTURA":
                    ab = E.parse_abertura(texto)
                    print(f"     titulo={ab.titulo!r} data_hora={ab.data_hora} "
                          f"tanques_parseados={len(ab.tanques)}")
                    if ab.tanques:
                        t0 = ab.tanques[0]
                        print(f"     ex tanque {t0.tanque}: {t0.produto} "
                              f"vol_atual={t0.volume_atual_l}")
                    # tenta gravar e DESFAZ (rollback) -> revela erro de INSERT
                    E.gravar_abertura(cur, ab, cliente_id)
                    conn.rollback()
                    print("     INSERT abertura: OK (rollback feito, nada persistido)")
                elif tipo == "DESCARGA":
                    dc = E.parse_descarga(texto)
                    print(f"     descarga parseada={bool(dc)}"
                          + (f" tanque={dc.tanque} total={dc.total_descarga_l} "
                             f"data_final={dc.data_final}" if dc else ""))
                    if dc:
                        E.gravar_descarga(cur, dc, cliente_id)
                        conn.rollback()
                        print("     INSERT descarga: OK (rollback feito)")
                else:
                    print("     (ignorado: tipo nao reconhecido)")
            except Exception:
                conn.rollback()
                print("     >>> ERRO na gravacao (esta e a causa raiz):")
                traceback.print_exc()
            print()
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("1) Estrutura real das tabelas")
    print("=" * 60)
    mostrar_estrutura()
    print("\n" + "=" * 60)
    print("2) Parse + tentativa de gravacao (com rollback)")
    print("=" * 60)
    diagnosticar_emails()
