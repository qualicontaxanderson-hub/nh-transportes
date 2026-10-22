# -*- coding: utf-8 -*-
"""Troca da DFE_CRYPTO_KEY sem parar a captura (22/10/2026, incidente da Railway).

A chave cifra a senha dos certificados (dfe_certificados.senha_cifrada). Trocar
só a variável deixaria todos indecifráveis; por isso a troca é em três passos:

  1. Em todos os serviços da Railway que têm a variável:
         DFE_CRYPTO_KEY=<nova>,<velha>
     A primeira cifra, as duas decifram: nada quebra enquanto o banco é recifrado.
  2. Nesta máquina, com a mesma variável no ambiente:
         python scripts/rotacionar_crypto_key.py            # dry-run: só conta
         python scripts/rotacionar_crypto_key.py --apply    # recifra com a <nova>
  3.     python scripts/rotacionar_crypto_key.py --conferir  # tudo abre só com a <nova>?
     Só então DFE_CRYPTO_KEY=<nova> nos serviços.

    python scripts/rotacionar_crypto_key.py --gerar      # imprime uma chave nova

O banco vem do mesmo .cnf do backup (%USERPROFILE%\\.nh-transportes\\mysql_backup.cnf).
Nunca imprime senha: só id e situação. A linha só é regravada se ainda estiver
como foi lida, para não pisar em quem trocou o certificado no meio.
"""
import argparse
import configparser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')

import pymysql                                          # noqa: E402
from cryptography.fernet import Fernet, InvalidToken    # noqa: E402

from integrations.cripto_dfe import _get_fernet         # noqa: E402

CNF = os.path.expanduser(r'~\.nh-transportes\mysql_backup.cnf')


def _conectar():
    cp = configparser.ConfigParser()
    cp.read(CNF)
    s = cp[cp.sections()[0]]
    return pymysql.connect(host=s.get('host'), port=int(s.get('port')), user=s.get('user'),
                           password=s.get('password').strip('"'), database='railway',
                           charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
                           read_timeout=60, connect_timeout=15, autocommit=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--conferir', action='store_true',
                    help='confere que tudo abre só com a PRIMEIRA chave')
    ap.add_argument('--gerar', action='store_true')
    a = ap.parse_args()

    if a.gerar:
        print(Fernet.generate_key().decode())
        return 0

    chaves = [c.strip() for c in os.environ.get('DFE_CRYPTO_KEY', '').split(',') if c.strip()]
    if not chaves:
        print('Ponha DFE_CRYPTO_KEY no ambiente (copie da Railway).')
        return 2
    if not a.conferir and len(chaves) < 2:
        print('DFE_CRYPTO_KEY tem uma chave só. Para recifrar use "<nova>,<velha>".')
        return 2
    nova = Fernet(chaves[0].encode())
    todas = _get_fernet()

    con = _conectar()
    with con.cursor() as cur:
        cur.execute('SELECT id, senha_cifrada AS v FROM dfe_certificados '
                    'WHERE senha_cifrada IS NOT NULL ORDER BY id')
        rows = cur.fetchall()
    ja, mudar, quebradas = 0, [], []
    for r in rows:
        tok = bytes(r['v'])
        try:
            nova.decrypt(tok)
            ja += 1
            continue
        except InvalidToken:
            pass
        if a.conferir:
            quebradas.append(r['id'])
            continue
        try:
            claro = todas.decrypt(tok)
        except InvalidToken:
            quebradas.append(r['id'])
            continue
        novo = todas.rotate(tok)
        if nova.decrypt(novo) != claro:          # paranoia: nunca grava o que não abre
            quebradas.append(r['id'])
            continue
        mudar.append((r, novo))

    print(f'== dfe_certificados.senha_cifrada: {len(rows)} cifradas | {ja} já na chave nova | '
          f'{len(mudar)} a recifrar | {len(quebradas)} não abrem com nenhuma chave')
    if quebradas:
        print(f'   ids que não abrem: {quebradas}')

    if a.apply and mudar:
        feitas = 0
        with con.cursor() as cur:
            for r, novo in mudar:
                feitas += cur.execute('UPDATE dfe_certificados SET senha_cifrada = %s '
                                      'WHERE id = %s AND senha_cifrada = %s',
                                      (novo, r['id'], r['v']))
        print(f'   gravadas: {feitas} de {len(mudar)}'
              + ('' if feitas == len(mudar) else ' — rode de novo: alguém mexeu no meio'))
    con.close()

    if a.conferir:
        print('\nOK: tudo abre só com a chave nova. Pode tirar a velha do ambiente.'
              if not quebradas else
              '\nNÃO tire a chave velha: há linhas que só ela abre (ou nenhuma).')
    elif not a.apply:
        print('\nDRY-RUN: nada gravado. Rode com --apply para recifrar.')
    return 1 if quebradas else 0


if __name__ == '__main__':
    sys.exit(main())
