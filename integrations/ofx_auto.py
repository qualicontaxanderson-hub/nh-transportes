"""
integrations/ofx_auto.py
========================

Importa SOZINHO o extrato OFX que cai em /BANCOS/OFX/NOVO no Dropbox (o NH-Robo
entrega lá, ou alguém larga direto). Antes só entrava pela tela Banco ›
Importar, escolhendo a conta e o arquivo — e o que ninguém escolhia ficava
parado na pasta (três arquivos de ago-out/2026 estavam lá).

A conta sai de DENTRO do arquivo: o <ACCTID> do OFX tem de ser o número de UMA
conta cadastrada (bank_accounts.conta, só os dígitos). Nenhuma ou mais de uma
-> o arquivo fica na pasta e a tela avisa; nunca se chuta a conta.

A importação é a mesma rotina da tela (bank_import._save_transactions): o
hash ignora o que já existe, o lançamento que veio antes pela API é
reconhecido (extrato_grava), e depois vêm Troco PIX, transferências, regras,
despesas e cobranças.

O que já foi importado não volta: só entram os lançamentos a partir da
ultima_data_importacao da conta (o próprio dia incluso — o arquivo do dia pela
metade não pode fazer o resto do dia sumir). Um lançamento antigo que falta no
sistema pode ter sido apagado de propósito (duplicado, espelho); um arquivo
velho largado na pasta não o ressuscita. O que é todo de antes disso vai para
IMPORTADOS com o aviso "período já importado".

Cada arquivo visto fica em ofx_auto_importacoes — é o que a tela mostra. Um
arquivo que não deu (sem conta, erro) não é tentado de novo enquanto não mudar
(mesmo nome e tamanho).

Os arquivos das operadoras de cartão (X7, SIPAG...) na mesma pasta são do
utils/cartao_arquivo — este módulo só olha .ofx.
"""
import logging
import re
from datetime import date, datetime

from utils.db import get_db_connection

_log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS `ofx_auto_importacoes` (
    `id`          INT AUTO_INCREMENT PRIMARY KEY,
    `arquivo`     VARCHAR(255) NOT NULL,
    `tamanho`     INT NOT NULL,
    `account_id`  INT NULL,
    `situacao`    VARCHAR(20) NOT NULL COMMENT 'importado | ja_importado | sem_conta | erro',
    `inseridos`   INT NOT NULL DEFAULT 0,
    `duplicados`  INT NOT NULL DEFAULT 0,
    `antigos`     INT NOT NULL DEFAULT 0 COMMENT 'antes da ultima importacao da conta: nao entram',
    `periodo_ini` DATE NULL,
    `periodo_fim` DATE NULL,
    `mensagem`    VARCHAR(500) NULL,
    `criado_em`   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY `ix_arquivo` (`arquivo`, `tamanho`),
    KEY `ix_quando` (`criado_em`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(DDL)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _agora():
    """Hora de Brasília: o servidor roda em UTC e a tela mostra esta hora."""
    try:
        import pytz
        return datetime.now(pytz.timezone('America/Sao_Paulo')).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _digitos(txt):
    return re.sub(r'\D', '', str(txt or ''))


def _tag(conteudo, nome):
    m = re.search(r'<%s>\s*([^\s<]+)' % nome, conteudo, re.IGNORECASE)
    return m.group(1) if m else None


def _data_ofx(valor):
    d = _digitos(valor)[:8]
    try:
        return date(int(d[:4]), int(d[4:6]), int(d[6:8])) if len(d) == 8 else None
    except ValueError:
        return None


def conta_do_arquivo(cursor, conteudo):
    """(account_id, mensagem): a conta cujo número é o <ACCTID> do arquivo.
    Igual nos dígitos; senão, um termina no outro ('148186-0' x '1481860',
    agência colada na frente). Só vale se for UMA conta."""
    acct = _digitos(_tag(conteudo, 'ACCTID'))
    if len(acct) < 5:
        return None, 'o arquivo não traz o número da conta (ACCTID)'
    cursor.execute("SELECT id, conta, apelido FROM bank_accounts WHERE ativo = 1")
    contas = [(r['id'], _digitos(r['conta']), r['apelido']) for r in cursor.fetchall()]
    iguais = [c for c in contas if c[1] and c[1] == acct]
    if not iguais:
        iguais = [c for c in contas if len(c[1]) >= 5 and (acct.endswith(c[1]) or c[1].endswith(acct))]
    if len(iguais) == 1:
        return iguais[0][0], None
    if not iguais:
        return None, f'nenhuma conta cadastrada com o número {acct}'
    return None, f'o número {acct} serve a {len(iguais)} contas: ' + ', '.join(c[2] for c in iguais)


def importar(conteudo, nome):
    """Importa um arquivo. Devolve o dict que vai para ofx_auto_importacoes."""
    from integrations.ofx_parser import OFXParser
    from routes.bank_import import (_atualizar_ultima_data_importacao, _ensure_bank_accounts_ultima_data,
                                    _ensure_descricao_chave, _save_transactions)
    r = {'account_id': None, 'situacao': 'erro', 'inseridos': 0, 'duplicados': 0, 'antigos': 0,
         'periodo_ini': _data_ofx(_tag(conteudo, 'DTSTART')),
         'periodo_fim': _data_ofx(_tag(conteudo, 'DTEND')), 'mensagem': None}
    _ensure_bank_accounts_ultima_data()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conta, erro = conta_do_arquivo(cursor, conteudo)
        if not conta:
            r.update(situacao='sem_conta', mensagem=erro)
            return r
        r['account_id'] = conta
        txs = OFXParser(conteudo).get_transactions()
        if not txs:
            r['mensagem'] = 'nenhum lançamento no arquivo'
            return r
        cursor.execute("SELECT ultima_data_importacao u FROM bank_accounts WHERE id=%s", (conta,))
        ultima = (cursor.fetchone() or {}).get('u')
        novos = [t for t in txs if not ultima or t['data_transacao'] >= ultima]
        r['antigos'] = len(txs) - len(novos)
        fim = max(t['data_transacao'] for t in txs)
        if not novos:
            r.update(situacao='ja_importado',
                     mensagem=f'período já importado (conta importada até {ultima:%d/%m/%Y})')
            return r
        _ensure_descricao_chave()
        ins, dup, _lista = _save_transactions(cursor, conn, conta, novos)
        _atualizar_ultima_data_importacao(cursor, conn, conta, max(fim, r['periodo_fim'] or fim))
        r.update(situacao='importado', inseridos=ins, duplicados=dup)
        if r['antigos']:
            r['mensagem'] = (f"{r['antigos']} lançamento(s) de antes de {ultima:%d/%m/%Y} "
                             f"ignorados (período já importado)")
        return r
    finally:
        cursor.close()
        conn.close()


def processar():
    """Varre a pasta: importa cada .ofx novo e move o que deu para IMPORTADOS.
    Devolve [(arquivo, situação, inseridos, mensagem)]."""
    from integrations.dropbox_ofx import _criar_dbx, _get_config, is_configured
    from utils.cartao_arquivo import operadora_do_nome
    if not is_configured():
        return []
    ensure_tables()
    _, inbox, processed = _get_config()
    dbx = _criar_dbx()
    res = dbx.files_list_folder(inbox)
    entradas = list(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        entradas.extend(res.entries)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    feitos = []
    try:
        for e in entradas:
            if (not hasattr(e, 'size') or not e.name.lower().endswith('.ofx')
                    or operadora_do_nome(e.name)):
                continue
            # Já tentado e não deu: só de novo se o arquivo mudar.
            cur.execute("""SELECT 1 FROM ofx_auto_importacoes WHERE arquivo=%s AND tamanho=%s
                             AND situacao IN ('sem_conta', 'erro') LIMIT 1""", (e.name, e.size))
            if cur.fetchone():
                continue
            try:
                _, resp = dbx.files_download('%s/%s' % (inbox, e.name))
                r = importar(resp.content.decode('latin-1', errors='replace'), e.name)
            except Exception as exc:
                _log.exception('[ofx_auto] %s: falhou', e.name)
                r = {'account_id': None, 'situacao': 'erro', 'inseridos': 0, 'duplicados': 0,
                     'antigos': 0, 'periodo_ini': None, 'periodo_fim': None,
                     'mensagem': str(exc)[:500]}
            cur.execute(
                """INSERT INTO ofx_auto_importacoes
                     (arquivo, tamanho, account_id, situacao, inseridos, duplicados, antigos,
                      periodo_ini, periodo_fim, mensagem, criado_em)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (e.name, e.size, r['account_id'], r['situacao'], r['inseridos'], r['duplicados'],
                 r['antigos'], r['periodo_ini'], r['periodo_fim'], (r['mensagem'] or '')[:500] or None,
                 _agora()))
            conn.commit()
            feitos.append((e.name, r['situacao'], r['inseridos'], r['mensagem']))
            if r['situacao'] in ('importado', 'ja_importado'):
                try:
                    dbx.files_move_v2('%s/%s' % (inbox, e.name), '%s/%s' % (processed, e.name),
                                      autorename=True)
                except Exception:
                    _log.exception('[ofx_auto] %s importado mas não saiu da pasta', e.name)
    finally:
        cur.close()
        conn.close()
    return feitos


def recentes(cursor, dias=7):
    """O que a importação automática fez nos últimos dias — para a tela."""
    try:
        cursor.execute(
            """SELECT o.*, ba.apelido FROM ofx_auto_importacoes o
                 LEFT JOIN bank_accounts ba ON ba.id = o.account_id
                WHERE o.criado_em >= %s - INTERVAL %s DAY
                ORDER BY o.criado_em DESC LIMIT 30""", (_agora(), dias))
        return cursor.fetchall()
    except Exception:           # tabela ainda não criada: nada a mostrar
        return []
