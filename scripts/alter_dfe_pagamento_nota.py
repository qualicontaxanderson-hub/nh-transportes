# -*- coding: utf-8 -*-
"""Cria a tabela dfe_pagamento_nota (vinculo manual pagamento <-> nota).

Ate aqui a conferencia Fornecedores x Compras DFe so tinha alocacao
automatica por data (FIFO), que e leitura e nao fica gravada. Esta tabela
guarda a decisao do usuario: "este pagamento cobre esta nota, neste valor".

Vale para pagamento de QUALQUER data — inclusive anterior ao corte da captura
DFe, que e justamente o caso que o FIFO nao resolve (pagou em julho, a nota
saiu em agosto).

Idempotente: pode rodar quantas vezes quiser.

Uso:
    python scripts/alter_dfe_pagamento_nota.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import get_db_connection  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS dfe_pagamento_nota (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    documento_id  INT            NOT NULL,
    transacao_id  INT            NOT NULL,
    valor         DECIMAL(14,2)  NOT NULL,
    criado_em     TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por    INT            NULL,
    UNIQUE KEY uq_doc_tx (documento_id, transacao_id),
    KEY ix_doc (documento_id),
    KEY ix_tx (transacao_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def main():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(DDL)
        conn.commit()

        cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name = 'dfe_pagamento_nota'""")
        existe = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM dfe_pagamento_nota")
        linhas = cur.fetchone()[0]
        print("dfe_pagamento_nota: %s | %d vinculo(s) gravado(s)"
              % ("OK" if existe else "NAO CRIADA", linhas))
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
