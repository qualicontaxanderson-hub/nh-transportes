# -*- coding: utf-8 -*-
"""Fonte UNICA das credenciais do banco.

Existe para que app web e scripts de captura leiam a senha do MESMO lugar.
Antes, o app web lia `DB_PASSWORD` do ambiente e o subprocesso de captura
(`scripts/consulta_sefaz.py`) tinha a senha literal no codigo -- entao a
rotacao de 2026-07-27 derrubou a captura sem derrubar o app, e o sintoma
ficou invisivel (o pai gravava o log, o filho morria com 1045).

De proposito NAO importa Flask nem `config.py`: `config.Config` levanta
RuntimeError quando falta `SECRET_KEY`, e os scripts de captura tambem rodam
por CLI, onde essa variavel nao faz sentido.

NAO existe fallback para senha nenhuma. Se `DB_PASSWORD` faltar, a conexao
falha com mensagem explicita -- e nao silenciosamente com uma senha morta.
"""
import os

DB_HOST = os.environ.get('DB_HOST', 'centerbeam.proxy.rlwy.net')
DB_PORT = int(os.environ.get('DB_PORT', 56026))
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', 'railway')


def exigir_senha():
    """Devolve DB_PASSWORD ou levanta RuntimeError explicando o que falta."""
    if not DB_PASSWORD:
        raise RuntimeError(
            "A variavel de ambiente DB_PASSWORD nao esta definida. "
            "Ela e a senha do MySQL e nao tem valor padrao: sem ela a conexao "
            "falha de proposito, em vez de tentar uma senha antiga. "
            "Defina DB_PASSWORD no servico do Railway (ou no .env local) e "
            "rode de novo."
        )
    return DB_PASSWORD


def pymysql_params(**extra):
    """kwargs prontos para `pymysql.connect()`.

    NAO reaproveita `utils.db.CONNECTION_PARAMS` de proposito: aquele dict e do
    mysql.connector e carrega chaves que o pymysql rejeita (`use_unicode`).
    A fonte dos VALORES e a mesma; so o empacotamento muda por driver.
    """
    import pymysql
    params = dict(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=exigir_senha(),
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    params.update(extra)
    return params
