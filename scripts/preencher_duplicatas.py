# -*- coding: utf-8 -*-
"""Preenche dfe_duplicatas das notas que ja foram capturadas.

A leitura de <cobr><dup> entrou depois que a captura ja rodava, entao as notas
de agosto estao no banco sem vencimento. O XML de cada uma esta guardado no
Dropbox — da pra reprocessar sem pedir nada a SEFAZ.

PRESSA: a retencao e de 90 dias (processa_dfe.DIAS_RETENCAO). Depois disso o
XML some do Dropbox e o vencimento dessas notas se perde de vez.

So LE o Dropbox e ESCREVE em dfe_duplicatas. Nao altera dfe_documentos, nao
apaga nada, e roda quantas vezes quiser (o upsert e por documento+parcela).

Uso:
    python scripts/preencher_duplicatas.py            # de verdade
    python scripts/preencher_duplicatas.py --simular  # so mostra o que faria
    python scripts/preencher_duplicatas.py --limite 20
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pymysql                                              # noqa: E402
import consulta_sefaz as cs                                 # noqa: E402
import processa_dfe as pd                                   # noqa: E402
from integrations.dropbox_dfe import baixar_xml             # noqa: E402

# Nota de compra com XML guardado e ainda sem nenhuma parcela gravada.
SQL_PENDENTES = """
    SELECT d.id, d.chave, d.numero, d.serie, d.dh_emissao, d.emit_nome,
           d.xml_caminho
      FROM dfe_documentos d
     WHERE d.tipo = 'NFe'
       AND d.resumo = 0
       AND d.xml_caminho IS NOT NULL AND d.xml_caminho <> ''
       AND NOT EXISTS (SELECT 1 FROM dfe_duplicatas x
                        WHERE x.documento_id = d.id)
     ORDER BY d.dh_emissao DESC
     LIMIT %s
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limite', type=int, default=500)
    ap.add_argument('--simular', action='store_true',
                    help='le e mostra, mas nao grava nada')
    args = ap.parse_args()

    con = pymysql.connect(**cs.CONN)
    try:
        with con.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(pd.DDL_DUPLICATAS)
            con.commit()
            cur.execute(SQL_PENDENTES, (args.limite,))
            notas = cur.fetchall()

        print('%d nota(s) sem parcela gravada.\n' % len(notas))
        com, sem, perdidas, erros = 0, 0, 0, 0

        for n in notas:
            rotulo = 'NF %s/%s %s' % (n['numero'], n['serie'],
                                      (n['emit_nome'] or '')[:32])
            try:
                xml = baixar_xml(n['xml_caminho'])
            except Exception as e:                            # noqa: BLE001
                print('  ERRO   %-44s %s' % (rotulo, e))
                erros += 1
                continue

            if xml is None:
                # Passou dos 90 dias de retencao: nao da mais pra recuperar.
                print('  SUMIU  %-44s (XML fora da retencao)' % rotulo)
                perdidas += 1
                continue

            try:
                dups = pd.extrair_duplicatas(ET.fromstring(xml))
                pag = pd.extrair_pagamento(ET.fromstring(xml))
            except Exception as e:                            # noqa: BLE001
                print('  ERRO   %-44s parse: %s' % (rotulo, e))
                erros += 1
                continue

            if not dups:
                # Nota a vista nao tem <cobr> — normal, e nao ha o que gravar.
                print('  A VISTA %-43s ind=%s tPag=%s'
                      % (rotulo, pag['ind'] or '-', pag['tipo'] or '-'))
                sem += 1
                continue

            print('  OK     %-44s %s' % (
                rotulo, ' | '.join('%s: %s R$ %s' % (d['n_dup'], d['vencimento'],
                                                     d['valor']) for d in dups)))
            com += 1
            if args.simular:
                continue

            with con.cursor() as cur:
                for d in dups:
                    cur.execute(pd.SQL_DUP_UPSERT,
                                (n['id'], d['n_dup'], d['vencimento'], d['valor']))
            con.commit()

        print('\ncom vencimento: %d | a vista (sem cobr): %d | XML sumido: %d | erro: %d'
              % (com, sem, perdidas, erros))
        if args.simular:
            print('(--simular: nada foi gravado)')
    finally:
        con.close()


if __name__ == '__main__':
    main()
