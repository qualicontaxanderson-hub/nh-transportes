# -*- coding: utf-8 -*-
"""Entrypoint do backup na nuvem: e isto que o servico de cron da Railway roda.

    Custom Start Command: python cron_backup.py
    Cron Schedule:        0 6 * * *      (o campo e UTC = 03:00 em Brasilia)

Fino de proposito -- a logica toda mora em utils/backup_bd.py. Aqui so ficam as
tres coisas que sao do CRON, e nao do backup:

  1. NASCE DESLIGADO. Sem `BACKUP_ATIVO=1` ele sai sem fazer nada, o que permite
     subir o codigo antes de o servico existir (e o codigo tem que subir antes:
     criar o servico apontando para um arquivo que ainda nao esta no GitHub so
     produz uma rodada falhando).
  2. Imprime o resultado, para a aba de logs da Railway contar a mesma historia
     que o card do dashboard.
  3. Devolve `exit 1` na falha -- e por esse codigo, e so por ele, que a Railway
     marca a rodada como falha.
"""
import json
import os
import sys


def principal():
    if (os.environ.get('BACKUP_ATIVO') or '').strip() != '1':
        print('[backup] BACKUP_ATIVO != 1 -- nada a fazer. '
              'Defina BACKUP_ATIVO=1 no servico para ligar.')
        return 0

    from utils import backup_bd

    print('[backup] iniciando...')
    status = backup_bd.executar()
    print('[backup] ' + json.dumps(status, ensure_ascii=False, indent=2))

    if not status.get('ok'):
        print('[backup] FALHOU na etapa "%s".' % status.get('etapa'))
        return 1

    if status.get('aviso'):
        print('[backup] AVISO: %s' % status['aviso'])
    print('[backup] OK: %s -> %s' % (status.get('arquivo'), status.get('destino')))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(principal())
    except Exception:
        # Rede de seguranca: `executar()` ja promete nao levantar, mas se algo
        # escapar (import quebrado, por exemplo) a rodada tem que ficar VERMELHA
        # na Railway, nunca verde por engano.
        import traceback
        traceback.print_exc()
        sys.exit(1)
