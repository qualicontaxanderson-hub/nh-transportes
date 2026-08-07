"""
scripts/alter_leitura_tanque_datetime.py
========================================

Migration idempotente e ADITIVA da tabela `leitura_tanque_diaria`:

  1) data_leitura: DATE -> DATETIME  (para guardar a HORA exata da leitura:
     05:00, 12:30, 23:30... e nao apenas o dia).
  2) adiciona a coluna `titulo` VARCHAR(40) (ex.: 'ABERTURA'), usada pela
     conciliacao para saber qual e a leitura de abertura do dia.

A chave UNIQUE (cliente_id, data_leitura, tanque) NAO muda: como data_leitura
passa a carregar hora, a mesma UNIQUE ja discrimina por segundo -> cada medicao
de horario diferente vira um registro novo, sem sobrescrever.

Idempotente: checa o information_schema antes de cada ALTER (MySQL nao tem
ADD COLUMN IF NOT EXISTS). Rodar quantas vezes quiser.

Como rodar (PowerShell, com os DB_* que voce ja usa):

    $env:DB_HOST="<host do banco Railway>"; $env:DB_PORT="<porta>"
    $env:DB_USER="root"; $env:DB_PASSWORD="<senha do banco>"; $env:DB_NAME="railway"
    python scripts\alter_leitura_tanque_datetime.py
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from config import Config
from utils.db import get_db_connection
from integrations import els_email


def migrar():
    # Garante a tabela. Se nao existir, ja nasce no formato NOVO (DATETIME +
    # titulo) pelo DDL atualizado em els_email.py. Se existir no formato antigo,
    # o CREATE IF NOT EXISTS e no-op e os ALTERs abaixo corrigem.
    els_email.ensure_tables()

    db = Config.DB_NAME
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1) data_leitura: DATE -> DATETIME
        cur.execute(
            """SELECT DATA_TYPE FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME='leitura_tanque_diaria'
                 AND COLUMN_NAME='data_leitura'""",
            (db,),
        )
        row = cur.fetchone()
        if row and str(row[0]).lower() == "date":
            cur.execute(
                "ALTER TABLE leitura_tanque_diaria "
                "MODIFY `data_leitura` DATETIME NOT NULL"
            )
            print("data_leitura: DATE -> DATETIME (ok)")
        else:
            atual = row[0] if row else "(tabela nova / coluna ausente)"
            print(f"data_leitura ja e {atual}; nada a fazer")

        # 2) coluna titulo (MySQL nao tem ADD COLUMN IF NOT EXISTS)
        cur.execute(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME='leitura_tanque_diaria'
                 AND COLUMN_NAME='titulo'""",
            (db,),
        )
        if not cur.fetchone():
            cur.execute(
                "ALTER TABLE leitura_tanque_diaria "
                "ADD COLUMN `titulo` VARCHAR(40) NULL AFTER `data_leitura`"
            )
            print("coluna titulo adicionada (ok)")
        else:
            print("coluna titulo ja existe; nada a fazer")

        conn.commit()

        # Confirmacao final: mostra a estrutura relevante
        print("\nEstrutura atual de leitura_tanque_diaria:")
        cur.execute(
            """SELECT COLUMN_NAME, COLUMN_TYPE
               FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME='leitura_tanque_diaria'
                 AND COLUMN_NAME IN ('data_leitura','titulo')
               ORDER BY ORDINAL_POSITION""",
            (db,),
        )
        for nome, tipo in cur.fetchall():
            print(f"   {nome}: {tipo}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    migrar()
