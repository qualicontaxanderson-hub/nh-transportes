#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Manutencao do banco Railway: segura o disco antes que ele estoure.

Por que existe: o volume do Railway tem 500 MB e em 21/08/2026 chegou a 90%
com o banco tendo so ~100 MB de dados reais. O resto era gordura que ninguem
recolhe sozinho:
  - redo log preallocado (100 MB -> 32 MB, ja ajustado com SET PERSIST);
  - log de diagnostico da DFe crescendo ~9 MB/mes pra sempre;
  - espaco solto dentro dos arquivos das tabelas (o InnoDB nao devolve ao
    disco o que voce apaga; so um rebuild devolve).

O que ele faz, nesta ordem:
  1. Apaga linhas velhas das tabelas de LOG (nenhuma tela do app le essas
     tabelas; sao diagnostico).
  2. Desfragmenta (OPTIMIZE TABLE) so as tabelas com folga grande, da MENOR
     pra MAIOR. O OPTIMIZE reconstroi a tabela num arquivo novo, entao ele
     PRECISA de espaco livre do tamanho da tabela — comecar pelas pequenas
     vai abrindo espaco pras grandes.
  3. Imprime o antes/depois pra ficar no log do backup.

Uso (o .bat chama assim, depois do dump):
  python manutencao_banco.py --host H --port P --user U --password S \
      [--db railway] [--dias-log 30] [--folga-mb 5] [--so-relatorio]

--so-relatorio mostra o diagnostico sem apagar nem reconstruir nada.

Codigos de saida:
  0 = sucesso (ou nada a fazer)
  2 = falha de conexao
  3 = erro durante a manutencao
"""
import argparse
import sys

import pymysql

# Tabelas de LOG: puro diagnostico, nenhuma tela do app consulta.
# (tabela, coluna de data). Se um dia alguma virar tela, tire daqui.
TABELAS_DE_LOG = [
    ("dfe_consulta_log", "momento"),
]


def mb(v):
    # FILE_SIZE/SUM() voltam Decimal: dividir por float explode. float() antes.
    return round(float(v or 0) / 1048576.0, 1)


def diagnostico(cur, db):
    """Quanto o banco ocupa de arquivo x quanto usa de verdade."""
    cur.execute(
        """SELECT ts.NAME nome,
                  ts.FILE_SIZE arquivo,
                  (t.data_length + t.index_length) usado
             FROM information_schema.INNODB_TABLESPACES ts
             JOIN information_schema.tables t
               ON CONCAT(t.table_schema, '/', t.table_name) = ts.NAME
            WHERE t.table_schema = %s
            ORDER BY ts.FILE_SIZE DESC""",
        (db,),
    )
    linhas = cur.fetchall()
    cur.execute("SELECT COALESCE(SUM(FILE_SIZE),0) FROM information_schema.INNODB_TABLESPACES")
    total = cur.fetchone()[0]
    return linhas, total


def main():
    ap = argparse.ArgumentParser(description="Manutencao de espaco do banco.")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--db", default="railway")
    ap.add_argument("--dias-log", type=int, default=30,
                    help="quantos dias de log de diagnostico manter (padrao 30)")
    ap.add_argument("--folga-mb", type=float, default=5.0,
                    help="so desfragmenta tabela com folga acima disso (padrao 5 MB)")
    ap.add_argument("--so-relatorio", action="store_true",
                    help="mostra o diagnostico sem apagar nem reconstruir")
    a = ap.parse_args()

    try:
        cn = pymysql.connect(host=a.host, port=a.port, user=a.user,
                             password=a.password, database=a.db,
                             autocommit=True, connect_timeout=20)
    except Exception as e:
        print("ERRO de conexao: %s" % e)
        return 2

    try:
        cur = cn.cursor()
        linhas, total_antes = diagnostico(cur, a.db)
        usado = sum(l[2] or 0 for l in linhas)
        print("ANTES: arquivos do InnoDB %.1f MB | dados reais em %s: %.1f MB"
              % (mb(total_antes), a.db, mb(usado)))

        if a.so_relatorio:
            for nome, arq, uso in linhas[:10]:
                print("  %-40s arquivo %7.1f MB | usado %7.1f MB | folga %.1f MB"
                      % (nome, mb(arq), mb(uso), mb((arq or 0) - (uso or 0))))
            return 0

        # 1) log de diagnostico: mantem so a janela recente
        for tabela, col in TABELAS_DE_LOG:
            try:
                cur.execute(
                    "DELETE FROM `%s` WHERE `%s` < NOW() - INTERVAL %%s DAY"
                    % (tabela, col), (a.dias_log,))
                if cur.rowcount:
                    print("LOG: %s — %d linha(s) com mais de %d dias apagada(s)"
                          % (tabela, cur.rowcount, a.dias_log))
            except pymysql.err.ProgrammingError:
                pass          # tabela ainda nao existe neste banco: tudo bem

        # 2) desfragmenta da MENOR pra MAIOR (o rebuild precisa de espaco
        #    livre do tamanho da tabela; as pequenas abrem caminho)
        alvos = [(n, arq, uso) for (n, arq, uso) in linhas
                 if mb((arq or 0) - (uso or 0)) >= a.folga_mb]
        alvos.sort(key=lambda x: x[1] or 0)
        for nome, arq, _uso in alvos:
            tabela = nome.split("/", 1)[1]
            try:
                cur.execute("OPTIMIZE TABLE `%s`" % tabela)
                cur.fetchall()
                cur.execute("""SELECT FILE_SIZE FROM information_schema.INNODB_TABLESPACES
                                WHERE NAME = %s""", (nome,))
                novo = (cur.fetchone() or [arq])[0]
                print("OPTIMIZE: %-32s %7.1f -> %7.1f MB (liberou %.1f MB)"
                      % (tabela, mb(arq), mb(novo), mb((arq or 0) - (novo or 0))))
            except Exception as e:
                print("AVISO: OPTIMIZE %s falhou: %s" % (tabela, e))

        _, total_depois = diagnostico(cur, a.db)
        print("DEPOIS: arquivos do InnoDB %.1f MB (liberado nesta rodada: %.1f MB)"
              % (mb(total_depois), mb((total_antes or 0) - (total_depois or 0))))
        return 0
    except Exception as e:
        print("ERRO na manutencao: %s" % e)
        return 3
    finally:
        try:
            cn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
