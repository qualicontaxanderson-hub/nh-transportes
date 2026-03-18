import csv
import io
import logging
import os
import re
import time
import datetime as _dt
from collections import Counter

import mysql.connector
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from utils.db import get_db_connection

logger = logging.getLogger(__name__)

bp = Blueprint('bank_import', __name__, url_prefix='/banco')

# MySQL error codes used in exception handling throughout this module
_MYSQL_ERRNO_UNKNOWN_COLUMN = 1054   # Unknown column (e.g., descricao_chave not yet added)
_MYSQL_ERRNO_TABLE_NOT_FOUND = 1146  # Table doesn't exist (schema not yet migrated)

# NOTE: this flag is not thread-safe but the underlying operation is idempotent
# (ADD COLUMN IF NOT EXISTS), so a double-run in concurrent requests is harmless.
_ld_bank_tx_id_ready = False
_bsm_descricao_chave_ready = False
# Timestamp-based retry cooldown: after a failed attempt, wait _MIGRATION_RETRY_DELAY
# seconds before retrying.  This avoids hammering the DB on every request but still
# allows recovery from transient errors (e.g., DB temporarily unavailable at startup).
_MIGRATION_RETRY_DELAY = 60  # seconds
_bsm_descricao_chave_retry_after = 0.0   # epoch timestamp; 0 = may run immediately
_ld_bank_tx_id_retry_after       = 0.0


def _ensure_descricao_chave():
    """Garante que bank_supplier_mapping está com o schema completo esperado.

    Aplica todas as migrations opcionais da tabela de forma idempotente:
    - fornecedor_id nullable (necessário para mapeamentos CREDIT sem fornecedor)
    - colunas forma_recebimento_id, titulo_id, categoria_id, subcategoria_id,
      conta_destino_id, tipo_debito (adicionadas em migrations pós-criação)
    - descricao_chave + UNIQUE KEY composta (cnpj_cpf, descricao_chave)
    - tipo_chave ENUM expandido para incluir 'descricao' (transações sem CNPJ)

    Se qualquer coluna estiver ausente, o INSERT de conciliação falha com
    ProgrammingError(1054) e o mapeamento não é salvo — por isso garantimos
    tudo aqui antes da primeira conciliação.
    """
    global _bsm_descricao_chave_ready, _bsm_descricao_chave_retry_after
    if _bsm_descricao_chave_ready:
        return
    if _bsm_descricao_chave_retry_after > time.time():
        return  # em cooldown; tenta novamente após o período de espera
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. fornecedor_id deve ser nullable para mapeamentos CREDIT (sem fornecedor)
        try:
            cursor.execute(
                "ALTER TABLE bank_supplier_mapping MODIFY COLUMN fornecedor_id INT NULL"
            )
            conn.commit()
        except Exception:
            conn.rollback()

        # 2. Colunas opcionais adicionadas em migrations posteriores à criação da tabela.
        #    Sem elas, o INSERT/ON DUPLICATE KEY UPDATE falha com errno=1054 e o
        #    mapeamento é silenciosamente descartado.
        _opt_cols = [
            ('forma_recebimento_id', 'INT NULL'),
            ('titulo_id',            'INT NULL'),
            ('categoria_id',         'INT NULL'),
            ('subcategoria_id',      'INT NULL'),
            ('conta_destino_id',     'INT NULL'),
            ('tipo_debito',          'VARCHAR(20) NULL'),
        ]
        # col/definition são constantes do código acima (não input do usuário),
        # portanto a interpolação direta não cria risco de SQL injection.
        for col, definition in _opt_cols:
            try:
                cursor.execute(
                    f"ALTER TABLE bank_supplier_mapping"
                    f" ADD COLUMN IF NOT EXISTS {col} {definition}"
                )
                conn.commit()
            except Exception:
                conn.rollback()

        # 3. descricao_chave + UNIQUE KEY composta
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'bank_supplier_mapping'"
            " AND COLUMN_NAME = 'descricao_chave'"
        )
        col_exists = cursor.fetchone()[0] > 0
        if not col_exists:
            cursor.execute(
                "ALTER TABLE bank_supplier_mapping"
                " ADD COLUMN descricao_chave VARCHAR(100) NOT NULL DEFAULT ''"
                " COMMENT 'Prefixo normalizado da descrição para diferenciar entradas com mesmo CNPJ'"
            )
            # Remove a constraint única antiga (somente cnpj_cpf) se existir
            try:
                cursor.execute("ALTER TABLE bank_supplier_mapping DROP INDEX uq_bsm_chave")
            except Exception:
                pass
            # Cria nova constraint única composta
            try:
                cursor.execute(
                    "ALTER TABLE bank_supplier_mapping"
                    " ADD UNIQUE KEY uq_bsm_chave (cnpj_cpf, descricao_chave)"
                )
            except Exception:
                pass
            # Remove trigger redundante se existir
            try:
                cursor.execute("DROP TRIGGER IF EXISTS tr_learn_supplier_mapping")
            except Exception:
                pass
            conn.commit()
            logger.info("_ensure_descricao_chave: coluna descricao_chave e índice criados com sucesso")

        # 4. tipo_chave ENUM deve incluir 'descricao' (valor usado para transações sem CNPJ).
        #    O ENUM original tem apenas 'cnpj', 'cpf', 'texto'; inserir 'descricao' em
        #    modo estrito (STRICT_TRANS_TABLES) causa DataError e o mapeamento não é salvo.
        try:
            cursor.execute(
                "ALTER TABLE bank_supplier_mapping"
                " MODIFY COLUMN tipo_chave"
                " ENUM('cnpj','cpf','texto','descricao') NOT NULL DEFAULT 'cnpj'"
            )
            conn.commit()
        except Exception:
            conn.rollback()

        cursor.close()
        _bsm_descricao_chave_ready = True
    except Exception:
        logger.warning("_ensure_descricao_chave: não foi possível aplicar schema de bank_supplier_mapping", exc_info=True)
        _bsm_descricao_chave_retry_after = time.time() + _MIGRATION_RETRY_DELAY  # evita retries imediatos, mas permite recuperação
    finally:
        if conn:
            conn.close()


def _ensure_ld_bank_tx_id():
    """Garante que lancamentos_despesas.bank_transaction_id existe. Idempotente."""
    global _ld_bank_tx_id_ready, _ld_bank_tx_id_retry_after
    if _ld_bank_tx_id_ready:
        return
    if _ld_bank_tx_id_retry_after > time.time():
        return  # em cooldown
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'lancamentos_despesas'"
            " AND COLUMN_NAME = 'bank_transaction_id'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE lancamentos_despesas"
                " ADD COLUMN bank_transaction_id INT NULL"
            )
            conn.commit()
        cursor.close()
        _ld_bank_tx_id_ready = True
    except Exception:
        logger.warning("_ensure_ld_bank_tx_id: não foi possível criar a coluna bank_transaction_id", exc_info=True)
        _ld_bank_tx_id_retry_after = time.time() + _MIGRATION_RETRY_DELAY  # evita retries imediatos, permite recuperação
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------


def _desc_chave(descricao: str) -> str:
    """Normaliza a descrição para chave de memorização: primeiros 100 chars em maiúsculas.

    Usada como parte da chave composta (cnpj_cpf, descricao_chave) na tabela
    bank_supplier_mapping, para diferenciar transações do mesmo CNPJ com tipos
    distintos (ex: mesma empresa pagando por categorias diferentes de despesas).
    """
    return (descricao or '').upper().strip()[:100]


def _get_accounts(cursor, cliente_id=None):
    if cliente_id:
        cursor.execute(
            """SELECT ba.id, ba.banco_nome, ba.agencia, ba.conta, ba.apelido,
                      ba.cliente_id, c.razao_social AS empresa_nome
               FROM bank_accounts ba
               LEFT JOIN clientes c ON c.id = ba.cliente_id
               WHERE ba.ativo = 1 AND ba.cliente_id = %s
               ORDER BY ba.apelido, ba.banco_nome""",
            (cliente_id,),
        )
    else:
        cursor.execute(
            """SELECT ba.id, ba.banco_nome, ba.agencia, ba.conta, ba.apelido,
                      ba.cliente_id, c.razao_social AS empresa_nome
               FROM bank_accounts ba
               LEFT JOIN clientes c ON c.id = ba.cliente_id
               WHERE ba.ativo = 1
               ORDER BY ba.apelido, ba.banco_nome"""
        )
    return cursor.fetchall()


def _get_clientes_com_produtos(cursor):
    """Retorna clientes que possuem ao menos um produto ativo (mesmo padrão das outras rotas)."""
    cursor.execute(
        """SELECT DISTINCT c.id, c.razao_social, c.nome_fantasia
           FROM clientes c
           INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
           WHERE cp.ativo = 1
           ORDER BY c.razao_social"""
    )
    return cursor.fetchall()


def _get_fornecedores(cursor):
    cursor.execute(
        "SELECT id, razao_social, cnpj FROM fornecedores ORDER BY razao_social"
    )
    return cursor.fetchall()


def _save_transactions(cursor, conn, account_id, transactions):
    """
    Insere em lote as *transactions* (saída de OFXParser.get_transactions()) na tabela
    bank_transactions para o *account_id* informado.

    Estratégia:
      1. Verificação de duplicatas em lote por hash_dedup (sha256 de fitid+data+valor+desc).
      1b. Verificação secundária por conteúdo (data+tipo+valor+cnpj+desc) para detectar a
          mesma transação re-exportada com um FITID diferente pelo banco.
      2. Busca de mapeamento de fornecedores em lote – uma query IN para todos os CNPJs.
      3. INSERT único com executemany para todas as novas linhas.
      4. Até 3 tentativas em caso de deadlock MySQL (errno 1213).

    Retorna (inseridos, duplicados_count, duplicados_lista) onde duplicados_lista é uma
    lista de dicts com os dados das transações duplicadas e o status do registro existente.
    """
    if not transactions:
        return 0, 0, []

    # 1. Verificação de duplicatas em lote por hash_dedup
    hashes = [tx['hash_dedup'] for tx in transactions]
    placeholders = ','.join(['%s'] * len(hashes))
    cursor.execute(
        f'SELECT hash_dedup FROM bank_transactions WHERE hash_dedup IN ({placeholders})',
        hashes,
    )
    existing_hashes = {row['hash_dedup'] for row in cursor.fetchall()}

    # 1b. Deduplicação secundária por conteúdo: evita "lançamentos pendentes fantasmas"
    # quando o banco re-exporta o mesmo extrato com FITIDs diferentes a cada download.
    # A chave é: (data_transacao, tipo, valor, cnpj_cpf, primeiros 255 chars da descrição)
    # - Para CREDIT com CPF: a combinação conta+data+tipo+valor+CPF é praticamente única.
    # - Incluímos a descrição normalizada para lidar com transações sem CPF/CNPJ.
    # Transações candidatas (que passaram no hash check) são filtradas por este critério.
    candidate_dates = [
        tx['data_transacao']
        for tx in transactions
        if tx['hash_dedup'] not in existing_hashes
    ]
    existing_content_keys: set = set()
    if candidate_dates:
        min_date = min(candidate_dates)
        max_date = max(candidate_dates)
        cursor.execute(
            """SELECT CONCAT(data_transacao, '|', tipo, '|',
                             CAST(valor AS CHAR), '|',
                             COALESCE(cnpj_cpf,''), '|',
                             UPPER(TRIM(LEFT(COALESCE(descricao,''), 255)))) AS ck
               FROM bank_transactions
               WHERE account_id = %s AND data_transacao BETWEEN %s AND %s""",
            (account_id, min_date, max_date),
        )
        existing_content_keys = {row['ck'] for row in cursor.fetchall()}

    # 2. Busca de mapeamento de fornecedores/formas/despesas em lote (por CNPJ)
    cnpj_list = list({tx['cnpj_cpf'] for tx in transactions if tx.get('cnpj_cpf')})
    mapping = {}  # (cnpj_cpf, descricao_chave) -> row
    if cnpj_list:
        ph2 = ','.join(['%s'] * len(cnpj_list))
        try:
            cursor.execute(
                f'SELECT cnpj_cpf, descricao_chave, fornecedor_id, forma_recebimento_id, titulo_id, categoria_id, subcategoria_id '
                f'FROM bank_supplier_mapping WHERE cnpj_cpf IN ({ph2})',
                cnpj_list,
            )
        except mysql.connector.errors.ProgrammingError:
            # Coluna descricao_chave pode ainda não existir (migration pendente)
            cursor.execute(
                f"SELECT cnpj_cpf, '' AS descricao_chave, fornecedor_id, forma_recebimento_id, titulo_id, categoria_id, subcategoria_id "
                f'FROM bank_supplier_mapping WHERE cnpj_cpf IN ({ph2})',
                cnpj_list,
            )
        for row in cursor.fetchall():
            mapping[(row['cnpj_cpf'], row['descricao_chave'])] = row

    now = _dt.datetime.now()
    rows = []
    duplicados = 0
    duplicados_lista = []
    for tx in transactions:
        if tx['hash_dedup'] in existing_hashes:
            duplicados += 1
            duplicados_lista.append({
                'data_transacao': str(tx['data_transacao']),
                'tipo': tx.get('tipo', ''),
                'valor': round(float(tx.get('valor', 0)), 2),
                'descricao': (tx.get('descricao') or '')[:120],
                'cnpj_cpf': tx.get('cnpj_cpf') or '',
                'hash_dedup': tx['hash_dedup'],
                'por_hash': True,
            })
            continue
        # Secondary content-based dedup.
        # Key format must match the SQL CONCAT in the DB query above:
        #   CONCAT(data_transacao, '|', tipo, '|', CAST(valor AS CHAR), '|', ...)
        # MySQL DECIMAL(15,2) CAST returns exactly 2 decimal places (e.g., '79.20').
        # round() prevents floating-point imprecision before {:.2f} formatting.
        _ck = '{}|{}|{:.2f}|{}|{}'.format(
            tx['data_transacao'],
            tx.get('tipo', ''),
            round(float(tx.get('valor', 0)), 2),
            tx.get('cnpj_cpf') or '',
            (tx.get('descricao') or '')[:255].upper().strip(),
        )
        if _ck in existing_content_keys:
            duplicados += 1
            duplicados_lista.append({
                'data_transacao': str(tx['data_transacao']),
                'tipo': tx.get('tipo', ''),
                'valor': round(float(tx.get('valor', 0)), 2),
                'descricao': (tx.get('descricao') or '')[:120],
                'cnpj_cpf': tx.get('cnpj_cpf') or '',
                'hash_dedup': tx.get('hash_dedup'),
                'por_hash': False,
            })
            continue
        # Add to existing_content_keys to catch duplicates within the same batch
        existing_content_keys.add(_ck)
        cnpj = tx.get('cnpj_cpf') or ''
        desc = _desc_chave(tx.get('descricao') or '')
        m = mapping.get((cnpj, desc)) or mapping.get((cnpj, ''))
        if tx['tipo'] == 'CREDIT':
            frec_id = m['forma_recebimento_id'] if m else None
            forn_id = None
            status = 'conciliado' if frec_id else 'pendente'
            conciliado_em = now if frec_id else None
            conciliado_por = 'auto' if frec_id else None
        else:
            forn_id = m['fornecedor_id'] if m else None
            frec_id = None
            # Débitos com mapeamento de despesa ficam pendentes (auto-conciliados após INSERT)
            has_despesa_mapping = bool(m and m.get('titulo_id'))
            status = 'conciliado' if forn_id else 'pendente'
            conciliado_em = now if forn_id else None
            conciliado_por = 'auto' if forn_id else None
        rows.append((
            account_id,
            tx['hash_dedup'],
            tx['data_transacao'],
            tx['tipo'],
            tx['valor'],
            tx['descricao'],
            tx.get('cnpj_cpf'),
            tx.get('memo'),
            tx.get('fitid'),
            status,
            forn_id,
            frec_id,
            conciliado_em,
            conciliado_por,
        ))

    inseridos = len(rows)
    if rows:
        for attempt in range(3):
            try:
                cursor.executemany(
                    """INSERT INTO bank_transactions
                       (account_id, hash_dedup, data_transacao, tipo, valor, descricao,
                        cnpj_cpf, memo, fitid, status, fornecedor_id, forma_recebimento_id,
                        conciliado_em, conciliado_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    rows,
                )
                conn.commit()
                break
            except mysql.connector.errors.InternalError as exc:
                if getattr(exc, 'errno', None) == 1213 and attempt < 2:
                    conn.rollback()
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise
    # 4. Auto-conciliação imediata por regras de descrição (para os que ficaram pendentes)
    _auto_conciliar_por_regras(cursor, conn, account_id)
    # 5. Auto-conciliação de despesas por CNPJ (cria lancamentos_despesas automaticamente)
    _auto_conciliar_despesas_por_cnpj(cursor, conn, account_id, mapping)
    # 6. Auto-conciliação de créditos EFI por charge_id (Recebimento de cobrança: XXXXXXXXX)
    _auto_conciliar_cobrancas(cursor, conn, account_id)

    # Enriquece duplicados_lista com informações do registro existente (id, status)
    if duplicados_lista:
        hash_only = [d['hash_dedup'] for d in duplicados_lista if d.get('por_hash') and d.get('hash_dedup')]
        if hash_only:
            ph = ','.join(['%s'] * len(hash_only))
            cursor.execute(
                f"SELECT id, hash_dedup, status FROM bank_transactions WHERE hash_dedup IN ({ph})",
                hash_only,
            )
            hash_to_info = {r['hash_dedup']: r for r in cursor.fetchall()}
            for d in duplicados_lista:
                if d.get('por_hash') and d.get('hash_dedup') in hash_to_info:
                    info = hash_to_info[d['hash_dedup']]
                    d['existing_id'] = info['id']
                    d['existing_status'] = info['status']
        # Para duplicatas por conteúdo, busca o registro existente individualmente
        for d in duplicados_lista:
            if not d.get('por_hash') and 'existing_id' not in d:
                try:
                    cursor.execute(
                        """SELECT id, status FROM bank_transactions
                           WHERE account_id = %s AND data_transacao = %s
                             AND tipo = %s AND valor = %s
                             AND COALESCE(cnpj_cpf,'') = %s
                             AND UPPER(TRIM(LEFT(COALESCE(descricao,''),255))) = %s
                           LIMIT 1""",
                        (account_id, d['data_transacao'], d['tipo'], d['valor'],
                         d.get('cnpj_cpf') or '',
                         (d.get('descricao') or '')[:255].upper().strip()),
                    )
                    row = cursor.fetchone()
                    if row:
                        d['existing_id'] = row['id']
                        d['existing_status'] = row['status']
                except Exception:
                    pass

    return inseridos, duplicados, duplicados_lista


def _get_or_create_forma_compensacao_cobranca(cursor, conn):
    """Retorna o id de formas_recebimento para 'Compensação Cobrança', criando se não existir."""
    try:
        cursor.execute(
            "SELECT id FROM formas_recebimento WHERE nome = 'Compensação Cobrança' LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return row['id']
        cursor.execute(
            "INSERT INTO formas_recebimento (nome, ativo) VALUES ('Compensação Cobrança', 1)"
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as _e:
        logger.warning("_get_or_create_forma_compensacao_cobranca: %s", _e)
        return None


def _auto_conciliar_cobrancas(cursor, conn, account_id=None):
    """
    Auto-concilia créditos do banco EFI com cobranças emitidas.

    O extrato EFI produz descrições no formato:
        "Recebimento de cobrança: 979319884 de AUTO POSTO SCARPIM LTDA"
    O número (charge_id) é idêntico ao campo `cobrancas.charge_id`.

    Para cada transação CREDIT pendente cujo texto contiver esse padrão:
    1. Extrai o charge_id numérico.
    2. Localiza a cobrança correspondente na tabela `cobrancas`.
    3. Marca a cobrança como paga (status='pago', pago_via_provedor=1).
    4. Marca a transação bancária como conciliada com forma 'Compensação Cobrança'.

    Retorna o número de pares conciliados.
    """
    import re as _re

    # Aceita tanto a codificação correta (cobrança) quanto a dupla-codificação
    # que ocorre quando arquivos OFX em UTF-8 são lidos como Latin-1 (cobranÃ§a).
    _CHARGE_RE = _re.compile(
        r'cobran(?:ça|Ã§a|ca)[:\s]+(\d{6,12})',
        _re.IGNORECASE,
    )

    forma_id = _get_or_create_forma_compensacao_cobranca(cursor, conn)

    # Busca créditos pendentes (ou já conciliados por outras regras mas sem cobranca linkada)
    if account_id:
        cursor.execute(
            """SELECT id, descricao, valor, data_transacao
               FROM bank_transactions
               WHERE account_id = %s AND tipo = 'CREDIT' AND status = 'pendente'""",
            (account_id,),
        )
    else:
        cursor.execute(
            """SELECT id, descricao, valor, data_transacao
               FROM bank_transactions
               WHERE tipo = 'CREDIT' AND status = 'pendente'"""
        )
    pendentes = cursor.fetchall()
    if not pendentes:
        return 0

    agora = _dt.datetime.now()
    count = 0
    for tx in pendentes:
        descricao = tx.get('descricao') or ''
        m = _CHARGE_RE.search(descricao)
        if not m:
            continue
        charge_id = m.group(1)

        # Verifica se a cobrança existe e ainda não está paga/cancelada
        cursor.execute(
            """SELECT id, status, pago_via_provedor
               FROM cobrancas
               WHERE charge_id = %s LIMIT 1""",
            (charge_id,),
        )
        cobr = cursor.fetchone()
        if not cobr:
            continue
        status_cobr = (cobr.get('status') or '').lower()
        if status_cobr in ('pago', 'cancelado'):
            # Mesmo que a cobrança já esteja paga, concilia a transação bancária
            _update_bank_tx_conciliada(cursor, tx['id'], forma_id, agora)
            count += 1
            continue

        # Marca cobrança como paga via provedor
        data_pagamento = tx.get('data_transacao')
        cursor.execute(
            """UPDATE cobrancas
               SET status = 'pago',
                   pago_via_provedor = 1,
                   data_pagamento = %s
               WHERE id = %s""",
            (data_pagamento, cobr['id']),
        )
        # Marca transação bancária como conciliada com forma 'Compensação Cobrança'
        _update_bank_tx_conciliada(cursor, tx['id'], forma_id, agora)
        count += 1

    if count:
        conn.commit()
        logger.info("_auto_conciliar_cobrancas: %d transação(ões) conciliada(s) por charge_id", count)
    return count


def _update_bank_tx_conciliada(cursor, tx_id, forma_id, agora):
    """Marca uma bank_transaction como conciliada com a forma 'Compensação Cobrança'."""
    if forma_id:
        try:
            cursor.execute(
                """UPDATE bank_transactions
                   SET status = 'conciliado',
                       forma_recebimento_id = %s,
                       conciliado_em = %s,
                       conciliado_por = 'auto-efi'
                   WHERE id = %s""",
                (forma_id, agora, tx_id),
            )
            return
        except Exception:
            pass
    cursor.execute(
        """UPDATE bank_transactions
           SET status = 'conciliado',
               conciliado_em = %s,
               conciliado_por = 'auto-efi'
           WHERE id = %s""",
        (agora, tx_id),
    )


def _auto_conciliar_despesas_por_cnpj(cursor, conn, account_id, mapping):
    """
    Cria lancamentos_despesas automaticamente para débitos pendentes cujo CNPJ
    tem mapeamento de despesa integral (titulo_id+categoria_id) em bank_supplier_mapping.
    Débitos divididos (split) nunca são auto-conciliados — ficam para o usuário.
    """
    # mapping é indexado por (cnpj_cpf, descricao_chave); filtra os que têm despesa
    despesa_mappings = {key: m for key, m in mapping.items() if m.get('titulo_id')}
    if not despesa_mappings:
        return 0

    # Busca cliente_id da conta
    cursor.execute("SELECT cliente_id FROM bank_accounts WHERE id=%s", (account_id,))
    acc = cursor.fetchone()
    cliente_id = acc['cliente_id'] if acc else None

    cnpj_list = list({key[0] for key in despesa_mappings.keys()})
    ph = ','.join(['%s'] * len(cnpj_list))
    cursor.execute(
        f"""SELECT id, data_transacao, descricao, cnpj_cpf, valor
            FROM bank_transactions
            WHERE account_id=%s AND tipo='DEBIT' AND status='pendente' AND cnpj_cpf IN ({ph})""",
        [account_id] + cnpj_list,
    )
    pendentes = cursor.fetchall()
    if not pendentes:
        return 0

    agora = _dt.datetime.now()
    count = 0
    for tx in pendentes:
        cnpj = tx['cnpj_cpf']
        desc = _desc_chave(tx.get('descricao') or '')
        m = despesa_mappings.get((cnpj, desc)) or despesa_mappings.get((cnpj, ''))
        if not m:
            continue
        descricao = (tx.get('descricao') or '')
        cursor.execute(
            """INSERT INTO lancamentos_despesas
               (data, cliente_id, titulo_id, categoria_id, subcategoria_id,
                valor, fornecedor, observacao, bank_transaction_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (tx['data_transacao'], cliente_id, m['titulo_id'], m['categoria_id'],
             m.get('subcategoria_id'), tx['valor'], descricao[:255], descricao, tx['id']),
        )
        cursor.execute(
            """UPDATE bank_transactions
               SET status='conciliado', conciliado_em=%s, conciliado_por='auto'
               WHERE id=%s""",
            (agora, tx['id']),
        )
        count += 1
    if count:
        conn.commit()
    return count


def _auto_conciliar_por_regras(cursor, conn, account_id=None):
    """
    Aplica bank_conciliacao_regras às transações pendentes do account_id (ou todas).
    Suporta:
      - Match simples (padrao_descricao contém ou é exato)
      - Match composto (padrao_descricao + padrao_secundario: ambos devem estar na descrição)
      - Regras de despesa (titulo_id + categoria_id → cria lancamentos_despesas)
      - Regras de cliente (cliente_id para créditos de cobrança)
    Retorna quantas foram auto-conciliadas.

    Performance: todo o matching é feito em Python (memória); as escritas no BD são
    feitas em lote com executemany() para evitar timeouts quando há muitas transações.
    """
    # Carrega regras ativas ordenadas por especificidade:
    # 1. Regras vinculadas a uma conta específica (account_id) antes das genéricas
    # 2. Regras com padrão secundário (mais específicas) antes das que só têm padrão principal
    # Isso garante que "DEP + DINHEIRO" é avaliada antes de "DEP" sozinho,
    # evitando que uma regra genérica capture transações que deveriam ir para uma regra específica.
    cursor.execute(
        """SELECT * FROM bank_conciliacao_regras WHERE ativo=1
           ORDER BY
               (account_id IS NOT NULL) DESC,
               (padrao_secundario IS NOT NULL AND padrao_secundario <> '') DESC,
               id"""
    )
    regras = cursor.fetchall()
    if not regras:
        logger.info("_auto_conciliar_por_regras: nenhuma regra ativa encontrada")
        return 0

    # Busca transações ainda pendentes com dados da conta
    if account_id:
        cursor.execute(
            """SELECT bt.id, bt.descricao, bt.tipo, bt.cnpj_cpf,
                      bt.data_transacao, bt.valor, bt.account_id,
                      ba.cliente_id AS conta_cliente_id
               FROM bank_transactions bt
               INNER JOIN bank_accounts ba ON ba.id = bt.account_id
               WHERE (bt.status='pendente' OR (bt.status='conciliado' AND bt.conciliado_por='auto'))
                 AND bt.account_id=%s""",
            (account_id,),
        )
    else:
        cursor.execute(
            """SELECT bt.id, bt.descricao, bt.tipo, bt.cnpj_cpf,
                      bt.data_transacao, bt.valor, bt.account_id,
                      ba.cliente_id AS conta_cliente_id
               FROM bank_transactions bt
               INNER JOIN bank_accounts ba ON ba.id = bt.account_id
               WHERE bt.status='pendente' OR (bt.status='conciliado' AND bt.conciliado_por='auto')"""
        )
    pendentes = cursor.fetchall()
    if not pendentes:
        logger.info("_auto_conciliar_por_regras: nenhuma transação pendente encontrada (account_id=%s)", account_id)
        return 0

    logger.info("_auto_conciliar_por_regras: %d regra(s) ativa(s), %d transação(ões) pendente(s)", len(regras), len(pendentes))
    agora = _dt.datetime.now()

    # ------------------------------------------------------------------ #
    # Fase 1: matching em memória — zero round-trips ao BD por transação  #
    # ------------------------------------------------------------------ #
    # batch_simples: linhas para UPDATE bank_transactions (forma/fornecedor)
    batch_simples = []
    # batch_despesa_insert: linhas para INSERT lancamentos_despesas
    batch_despesa_insert = []
    # batch_despesa_update: linhas para UPDATE bank_transactions (despesa)
    batch_despesa_update = []
    # rule_hits: contador de quantas vezes cada regra foi aplicada
    rule_hits: Counter = Counter()

    for tx in pendentes:
        descricao = (tx.get('descricao') or '').upper()
        tipo = tx.get('tipo') or ''
        for regra in regras:
            # Filtra por conta bancária: se a regra for específica para uma conta,
            # só aplica a transações dessa conta
            regra_account_id = regra.get('account_id')
            if regra_account_id and int(regra_account_id) != int(tx['account_id']):
                continue
            # Filtra por tipo de transação
            tipo_regra = regra.get('tipo_transacao', 'AMBOS')
            if tipo_regra != 'AMBOS' and tipo_regra != tipo:
                continue
            # Match principal
            padrao = (regra.get('padrao_descricao') or '').upper()
            tipo_match = regra.get('tipo_match', 'contem')
            if tipo_match == 'exato':
                match = descricao == padrao
            else:
                match = padrao in descricao
            if not match:
                continue
            # Match secundário (composto): ex: "LIQ.COBRANCA SIMPLES" + "TRANSPORTES TREMEA"
            padrao2 = (regra.get('padrao_secundario') or '').upper()
            if padrao2 and padrao2 not in descricao:
                continue

            # Determina o que vincular
            forma_id     = regra.get('forma_recebimento_id')
            forn_id      = regra.get('fornecedor_id')
            titulo_id    = regra.get('titulo_id')
            categoria_id = regra.get('categoria_id')

            if titulo_id and categoria_id and tipo == 'DEBIT':
                # Regra de despesa → acumula INSERT lancamentos_despesas
                conta_cliente_id = tx.get('conta_cliente_id')
                batch_despesa_insert.append((
                    tx['data_transacao'],
                    conta_cliente_id,
                    titulo_id, categoria_id,
                    tx['valor'],
                    (tx.get('descricao') or '')[:255],
                    tx.get('descricao') or '',
                    tx['id'],
                ))
                batch_despesa_update.append((agora, tx['id']))
            else:
                batch_simples.append((forma_id, forn_id, agora, tx['id']))

            rule_hits[regra['id']] += 1
            break  # primeira regra que bate

    aplicadas = len(batch_simples) + len(batch_despesa_insert)
    if not aplicadas:
        return 0

    # ------------------------------------------------------------------ #
    # Fase 2: escritas em lote — poucos round-trips independente do volume #
    # ------------------------------------------------------------------ #
    if batch_simples:
        cursor.executemany(
            """UPDATE bank_transactions
               SET status='conciliado',
                   forma_recebimento_id=%s,
                   fornecedor_id=%s,
                   conciliado_em=%s,
                   conciliado_por='auto-regra'
               WHERE id=%s""",
            batch_simples,
        )
    if batch_despesa_insert:
        cursor.executemany(
            """INSERT INTO lancamentos_despesas
               (data, cliente_id, titulo_id, categoria_id, valor,
                fornecedor, observacao, bank_transaction_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            batch_despesa_insert,
        )
        cursor.executemany(
            """UPDATE bank_transactions
               SET status='conciliado', conciliado_em=%s, conciliado_por='auto-regra'
               WHERE id=%s""",
            batch_despesa_update,
        )
    if rule_hits:
        cursor.executemany(
            """UPDATE bank_conciliacao_regras
               SET total_aplicacoes=total_aplicacoes+%s WHERE id=%s""",
            [(cnt, rid) for rid, cnt in rule_hits.items()],
        )

    conn.commit()
    return aplicadas

# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

@bp.route('/')
@login_required
def index():
    """Página principal – dashboard de importação bancária."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Apenas empresas com produtos ativos
    clientes = _get_clientes_com_produtos(cursor)

    # Filtro opcional: contas por empresa selecionada
    cliente_id_filter = request.args.get('empresa_id', type=int)
    contas = _get_accounts(cursor, cliente_id=cliente_id_filter)

    # Contadores do resumo
    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions WHERE status = 'pendente'")
    pendentes = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions WHERE status = 'conciliado'")
    conciliados = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions")
    total = cursor.fetchone()['total']

    cursor.close()
    conn.close()

    _ofx_dir_env = os.environ.get('OFX_INBOX_DIR', '')

    # Detecta tipo de caminho configurado
    # Caminho Windows: contém \ ou letra de unidade (ex: C:\Users\ ou Dropbox\...)
    _is_windows_path = bool(_ofx_dir_env) and (
        '\\' in _ofx_dir_env
        or (len(_ofx_dir_env) >= 2 and _ofx_dir_env[1] == ':')
    )
    # Caminho /tmp ou sem configuração → usar upload direto
    _is_tmp_or_unset = not _ofx_dir_env or _ofx_dir_env.startswith('/tmp')
    # Caminho Linux válido (ex: /data/ofx_inbox)
    _is_valid_linux_path = bool(_ofx_dir_env) and not _is_windows_path and not _is_tmp_or_unset
    # Verifica se o diretório já existe no servidor
    _inbox_dir_exists = _is_valid_linux_path and os.path.isdir(_ofx_dir_env)

    # inbox_is_tmp=True → oculta UI de pasta, mostra card de "use upload direto"
    inbox_is_tmp = _is_tmp_or_unset or _is_windows_path
    # inbox_dir_missing=True → caminho Linux válido mas diretório ainda não existe
    #   (ex: /data/ofx_inbox precisa de um Render Disk montado em /data)
    inbox_dir_missing = _is_valid_linux_path and not _inbox_dir_exists

    # Verifica se a integração Dropbox está configurada
    from integrations.dropbox_ofx import (
        is_configured as dropbox_is_configured,
        get_inbox_paths as dropbox_paths,
        usa_oauth2 as dropbox_usa_oauth2,
    )
    _dropbox_ok = dropbox_is_configured()
    _dbx_inbox, _dbx_processed = dropbox_paths()
    _dropbox_oauth2 = dropbox_usa_oauth2()

    return render_template(
        'bank_import/index.html',
        contas=contas,
        clientes=clientes,
        cliente_id_filter=cliente_id_filter,
        pendentes=pendentes,
        conciliados=conciliados,
        total=total,
        inbox_is_tmp=inbox_is_tmp,
        inbox_dir_missing=inbox_dir_missing,
        ofx_dir_configured=_ofx_dir_env,
        is_windows_path=_is_windows_path,
        dropbox_configured=_dropbox_ok,
        dropbox_oauth2=_dropbox_oauth2,
        dropbox_inbox=_dbx_inbox,
        dropbox_processed=_dbx_processed,
    )


@bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """Upload e importação de arquivo OFX."""
    if request.method == 'GET':
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        contas = _get_accounts(cursor)
        cursor.close()
        conn.close()
        return render_template('bank_import/index.html',
                               contas=contas, pendentes=0, conciliados=0, total=0)

    # POST – processa o arquivo enviado
    arquivo = request.files.get('ofx_file')
    account_id = request.form.get('account_id')

    if not arquivo or not arquivo.filename:
        flash('Nenhum arquivo selecionado.', 'warning')
        return redirect(url_for('bank_import.index'))

    if not account_id:
        flash('Selecione uma conta bancária.', 'warning')
        return redirect(url_for('bank_import.index'))

    try:
        content = arquivo.read().decode('latin-1', errors='replace')
    except Exception as exc:
        flash(f'Erro ao ler arquivo: {exc}', 'danger')
        return redirect(url_for('bank_import.index'))

    from integrations.ofx_parser import OFXParser
    parser = OFXParser(content)
    transactions = parser.get_transactions()

    if not transactions:
        flash('Nenhuma transação encontrada no arquivo OFX.', 'warning')
        return redirect(url_for('bank_import.index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    _ensure_descricao_chave()
    inseridos, duplicados, duplicados_lista = _save_transactions(cursor, conn, account_id, transactions)

    cursor.close()
    conn.close()

    msg = f'Importação concluída: {inseridos} transação(ões) importada(s), {duplicados} duplicata(s) ignorada(s).'
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if wants_json:
        return jsonify({
            'success': True,
            'message': msg,
            'inseridos': inseridos,
            'duplicados': duplicados,
            'duplicados_lista': duplicados_lista,
        })
    flash(msg, 'success')
    return redirect(url_for('bank_import.index'))


def _extrair_padrao_descricao(descricao):
    """Extrai prefixo significativo da descrição até o primeiro CPF (11 dígitos) ou
    CNPJ (14 dígitos). Usado para gerar regras de conciliação por padrão de descrição,
    evitando que a forma de recebimento fique vinculada ao CPF/CNPJ do remetente
    (o mesmo CPF pode aparecer em PIX, depósito em dinheiro, cheque, etc.).
    """
    # Mínimo de 5 caracteres antes do CPF/CNPJ para garantir prefixo significativo
    _MIN_PREFIX = 5
    # Limite do valor armazenável na coluna padrao_descricao (VARCHAR(200)); usamos 100
    # para deixar margem e cobrir variações de maiúsculas/espaços durante o matching.
    _MAX_PADRAO = 100
    desc = (descricao or '').strip()
    if not desc:
        return ''
    # Prioriza CPF (11 dígitos) antes de CNPJ (14 dígitos); ambos isolados por lookahead
    m = re.search(r'(?<!\d)(\d{11}|\d{14})(?!\d)', desc)
    if m and m.start() > _MIN_PREFIX:
        padrao = desc[:m.start()].rstrip(' -_/')
    else:
        padrao = desc[:50]  # fallback: primeiros 50 chars quando não há CPF/CNPJ
    return padrao.strip()[:_MAX_PADRAO]


def _get_formas_recebimento(cursor):
    """Retorna formas de recebimento ativas para uso na conciliação.
    Inclui registros com ativo IS NULL para compatibilidade com tabelas
    criadas antes da migração que adicionou o campo com DEFAULT 1.
    """
    cursor.execute(
        "SELECT id, nome FROM formas_recebimento WHERE ativo = 1 OR ativo IS NULL ORDER BY nome"
    )
    return cursor.fetchall()


def _get_titulos_despesas(cursor):
    """Retorna títulos de despesas ativos com suas categorias e subcategorias."""
    cursor.execute(
        """SELECT t.id AS titulo_id, t.nome AS titulo_nome,
                  c.id AS categoria_id, c.nome AS categoria_nome,
                  s.id AS sub_id, s.nome AS sub_nome
           FROM titulos_despesas t
           INNER JOIN categorias_despesas c ON c.titulo_id = t.id AND c.ativo = 1
           LEFT JOIN subcategorias_despesas s ON s.categoria_id = c.id AND s.ativo = 1
           WHERE t.ativo = 1
           ORDER BY t.ordem, t.nome, c.ordem, c.nome, s.ordem, s.nome"""
    )
    rows = cursor.fetchall()
    # Agrupa: { titulo_id: {nome, categorias: { cat_id: {nome, subcategorias:[]} }} }
    titulos = {}
    for r in rows:
        tid = r['titulo_id']
        if tid not in titulos:
            titulos[tid] = {'id': tid, 'nome': r['titulo_nome'], 'categorias': {}}
        cats = titulos[tid]['categorias']
        cid = r['categoria_id']
        if cid not in cats:
            cats[cid] = {'id': cid, 'nome': r['categoria_nome'], 'subcategorias': []}
        if r['sub_id']:
            cats[cid]['subcategorias'].append({'id': r['sub_id'], 'nome': r['sub_nome']})
    result = []
    for t in titulos.values():
        result.append({'id': t['id'], 'nome': t['nome'],
                       'categorias': list(t['categorias'].values())})
    return result


def _conciliar_transferencia(cursor, conn, tx_id, conta_destino_id, usuario,
                             salvar_mapeamento=True):
    """Registra transferência entre contas: concilia a origem e cria um CREDIT na conta destino.
    Salva mapeamento CNPJ→conta_destino apenas se salvar_mapeamento=True.
    """
    agora = _dt.datetime.now()
    cursor.execute(
        """SELECT id, data_transacao, valor, descricao, hash_dedup, cnpj_cpf, account_id
           FROM bank_transactions WHERE id=%s""",
        (tx_id,),
    )
    tx = cursor.fetchone()
    if not tx:
        return
    # Marca a tx de origem como conciliada.
    # Tenta com tipo_conciliacao (coluna nova); se não existir usa UPDATE básico.
    try:
        cursor.execute(
            """UPDATE bank_transactions
               SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                   tipo_conciliacao='transferencia'
               WHERE id=%s""",
            (agora, usuario, tx_id),
        )
    except Exception:
        conn.rollback()
        cursor.execute(
            """UPDATE bank_transactions
               SET status='conciliado', conciliado_em=%s, conciliado_por=%s
               WHERE id=%s""",
            (agora, usuario, tx_id),
        )
    # Cria CREDIT na conta destino. Usa TRANSFER_<id> para garantir que cabe
    # em VARCHAR(64) (SHA-256 = 64 chars; '_transfer' causaria overflow).
    # Cria como 'pendente' para que apareça na fila de conciliação da conta destino.
    hash_destino = f'TRANSFER_{tx_id}'
    descricao_dest = f"TRANSFERENCIA RECEBIDA - {tx.get('descricao') or ''}"[:500]
    try:
        cursor.execute(
            """INSERT INTO bank_transactions
                   (account_id, data_transacao, tipo, valor, descricao, hash_dedup,
                    status, tipo_conciliacao)
               VALUES (%s, %s, 'CREDIT', %s, %s, %s, 'pendente', 'transferencia')""",
            (conta_destino_id, tx['data_transacao'], tx['valor'],
             descricao_dest, hash_destino),
        )
    except Exception:
        # tipo_conciliacao não existe ainda — INSERT sem a coluna
        cursor.execute(
            """INSERT INTO bank_transactions
                   (account_id, data_transacao, tipo, valor, descricao, hash_dedup,
                    status)
               VALUES (%s, %s, 'CREDIT', %s, %s, %s, 'pendente')""",
            (conta_destino_id, tx['data_transacao'], tx['valor'],
             descricao_dest, hash_destino),
        )
    # Auto-aprender: salva CNPJ+descrição→conta_destino para sugestão nas próximas importações.
    # Quando não há CNPJ, usa cnpj_cpf='' com descricao_chave como chave de match — isso
    # permite que transações sem CPF/CNPJ (ex: Pix sem identificação) recebam sugestão de
    # transferência na próxima vez que o mesmo texto de descrição aparecer.
    cnpj = tx.get('cnpj_cpf') or ''
    desc_chave = _desc_chave(tx.get('descricao') or '')
    if salvar_mapeamento and (cnpj or desc_chave):
        try:
            cursor.execute(
                """INSERT INTO bank_supplier_mapping (cnpj_cpf, descricao_chave, conta_destino_id, tipo_debito)
                   VALUES (%s, %s, %s, 'transferencia')
                   ON DUPLICATE KEY UPDATE conta_destino_id=%s, tipo_debito='transferencia'""",
                (cnpj, desc_chave, conta_destino_id, conta_destino_id),
            )
        except mysql.connector.errors.ProgrammingError:
            # Coluna pode não existir ainda (migration pendente) — ignora silenciosamente
            pass
    conn.commit()


def _conciliar_tx(cursor, conn, tx_id, acao, tipo_tx,
                  fornecedor_id, forma_recebimento_id, usuario,
                  tipo_debito=None, despesas=None, troco_pix_id=None,
                  salvar_mapeamento=True, conta_origem_id=None):
    """Concilia (ou ignora) uma única transação e aprende mapeamentos.

    Para débitos com tipo_debito='despesa', *despesas* é uma lista de dicts:
        [{'titulo_id': int, 'categoria_id': int, 'valor': float, 'observacao': str}]
    Para débitos com tipo_debito='troco_pix', *troco_pix_id* deve ser informado.
    Se salvar_mapeamento=False, a conciliação ocorre normalmente mas os dados NÃO
    são salvos no bank_supplier_mapping (Lançamento Único / sem aprendizado).
    """
    if acao == 'ignorar':
        cursor.execute(
            "UPDATE bank_transactions SET status='ignorado' WHERE id=%s", (tx_id,)
        )
        conn.commit()
        return

    agora = _dt.datetime.now()

    if tipo_tx == 'CREDIT':
        if tipo_debito == 'transferencia':
            # Crédito de transferência recebida — confirma a entrada e marca como conciliado
            try:
                cursor.execute(
                    """UPDATE bank_transactions
                       SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                           tipo_conciliacao='transferencia'
                       WHERE id=%s""",
                    (agora, usuario, tx_id),
                )
            except Exception:
                conn.rollback()
                cursor.execute(
                    """UPDATE bank_transactions
                       SET status='conciliado', conciliado_em=%s, conciliado_por=%s
                       WHERE id=%s""",
                    (agora, usuario, tx_id),
                )
            # Armazena conta de origem (referência cruzada) se fornecida pelo usuário
            if conta_origem_id:
                try:
                    cursor.execute(
                        "UPDATE bank_transactions SET conta_origem_id=%s WHERE id=%s",
                        (conta_origem_id, tx_id),
                    )
                except mysql.connector.errors.ProgrammingError:
                    # Coluna pode não existir ainda (migration pendente) — ignora
                    logger.debug("conta_origem_id column not yet available; skipping")
        else:
            # Crédito → Forma de Recebimento
            if not forma_recebimento_id:
                raise ValueError("Selecione uma forma de recebimento para conciliar este crédito.")
            cursor.execute(
                """UPDATE bank_transactions
                   SET status='conciliado', forma_recebimento_id=%s,
                       conciliado_em=%s, conciliado_por=%s
                   WHERE id=%s""",
                (forma_recebimento_id, agora, usuario, tx_id),
            )
            # Marca duplicatas pendentes com o mesmo conteúdo como 'ignorado'.
            # Transações duplicadas podem existir quando o banco re-exportou o extrato OFX
            # com FITIDs diferentes antes da deduplicação por conteúdo ser implementada.
            # Usar um cursor separado para evitar conflito de result-set com o cursor principal.
            try:
                # dictionary=True necessário para acessar campos por nome no fetchone()
                with conn.cursor(dictionary=True) as _dup_cur:
                    _dup_cur.execute(
                        "SELECT account_id, tipo, data_transacao, valor, "
                        "COALESCE(cnpj_cpf,'') AS cnpj_cpf, "
                        "UPPER(TRIM(LEFT(COALESCE(descricao,''),255))) AS desc_norm "
                        "FROM bank_transactions WHERE id=%s",
                        (tx_id,),
                    )
                    _tx_info = _dup_cur.fetchone()
                if _tx_info:
                    with conn.cursor() as _dup_upd:
                        _dup_upd.execute(
                            """UPDATE bank_transactions
                               SET status='ignorado'
                               WHERE id <> %s
                                 AND account_id = %s
                                 AND status = 'pendente'
                                 AND tipo = %s
                                 AND data_transacao = %s
                                 AND valor = %s
                                 AND COALESCE(cnpj_cpf,'') = %s
                                 AND UPPER(TRIM(LEFT(COALESCE(descricao,''),255))) = %s""",
                            (
                                tx_id,
                                _tx_info['account_id'],
                                _tx_info['tipo'],
                                _tx_info['data_transacao'],
                                _tx_info['valor'],
                                _tx_info['cnpj_cpf'],
                                _tx_info['desc_norm'],
                            ),
                        )
                        if _dup_upd.rowcount:
                            logger.info(
                                "_conciliar_tx: %d duplicata(s) pendente(s) marcadas como"
                                " ignorado para tx_id=%s", _dup_upd.rowcount, tx_id
                            )
            except Exception as _dup_exc:
                # Falha na deduplicação não impede a conciliação principal
                logger.warning(
                    "_conciliar_tx: erro ao marcar duplicatas, ignorando: %s", _dup_exc
                )
            # Auto-aprender: salva CNPJ+Descrição → forma_recebimento para sugestões e
            # auto-conciliação em importações futuras com a mesma transação.
            # Qualquer falha aqui é recuperável — a conciliação principal já foi executada
            # e será commitada independentemente do resultado do mapeamento.
            if salvar_mapeamento:
                try:
                    with conn.cursor(dictionary=True) as _map_cur:
                        _map_cur.execute(
                            "SELECT cnpj_cpf, descricao FROM bank_transactions WHERE id=%s",
                            (tx_id,),
                        )
                        row_cr = _map_cur.fetchone()
                    desc_chave = _desc_chave(row_cr.get('descricao') or '') if row_cr else ''
                    if row_cr and (row_cr.get('cnpj_cpf') or desc_chave):
                        cnpj_save = row_cr.get('cnpj_cpf') or ''
                        tipo_chave_save = 'cnpj' if cnpj_save else 'texto'
                        try:
                            with conn.cursor() as _ins_cur:
                                _ins_cur.execute(
                                    """INSERT INTO bank_supplier_mapping
                                           (cnpj_cpf, descricao_chave, tipo_chave,
                                            total_conciliacoes, forma_recebimento_id)
                                       VALUES (%s, %s, %s, 1, %s)
                                       ON DUPLICATE KEY UPDATE
                                           forma_recebimento_id=%s,
                                           fornecedor_id=NULL, titulo_id=NULL,
                                           categoria_id=NULL, subcategoria_id=NULL,
                                           total_conciliacoes=total_conciliacoes+1,
                                           atualizado_em=NOW()""",
                                    (cnpj_save, desc_chave, tipo_chave_save,
                                     forma_recebimento_id, forma_recebimento_id),
                                )
                        except mysql.connector.errors.ProgrammingError as _pe:
                            if _pe.errno == 1054:
                                logger.warning(
                                    "_conciliar_tx CREDIT: coluna descricao_chave ausente em"
                                    " bank_supplier_mapping — migration pendente, mapeamento ignorado."
                                    " Execute migrations/20260318_fix_banco_sugestoes_sem_cnpj.sql no Railway."
                                )
                            else:
                                logger.warning(
                                    "_conciliar_tx CREDIT: erro ao salvar mapeamento"
                                    " (ProgrammingError %s), ignorando: %s", _pe.errno, _pe
                                )
                        except Exception as _map_e:
                            _errno = getattr(_map_e, 'errno', None)
                            if _errno in (1364, 1048):
                                # 1364: Field has no default value (fornecedor_id NOT NULL)
                                # 1048: Column cannot be null
                                logger.warning(
                                    "_conciliar_tx CREDIT: fornecedor_id NOT NULL impede salvar"
                                    " mapeamento (errno=%s) — execute migration"
                                    " 20260318_fix_banco_sugestoes_sem_cnpj.sql no Railway.",
                                    _errno,
                                )
                            else:
                                logger.warning(
                                    "_conciliar_tx CREDIT: erro ao salvar mapeamento, ignorando: %s",
                                    _map_e,
                                )
                except Exception as _outer_map_e:
                    logger.warning(
                        "_conciliar_tx CREDIT: erro ao buscar dados para mapeamento,"
                        " ignorando: %s", _outer_map_e
                    )

    elif tipo_debito == 'troco_pix' and troco_pix_id:
        # Débito → Troco PIX: vincula a transação bancária ao registro de troco_pix
        try:
            cursor.execute(
                """UPDATE bank_transactions
                   SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                       tipo_conciliacao='troco_pix'
                   WHERE id=%s""",
                (agora, usuario, tx_id),
            )
        except Exception:
            conn.rollback()
            cursor.execute(
                """UPDATE bank_transactions
                   SET status='conciliado', conciliado_em=%s, conciliado_por=%s
                   WHERE id=%s""",
                (agora, usuario, tx_id),
            )
        # Vincula o troco_pix à transação bancária (graceful: ignora se coluna não existir)
        try:
            cursor.execute(
                "UPDATE troco_pix SET bank_transaction_id=%s WHERE id=%s",
                (tx_id, troco_pix_id),
            )
        except Exception:
            pass
    elif tipo_debito == 'despesa' and despesas:
        # Débito → uma ou mais Despesas (lançamentos_despesas)
        cursor.execute(
            """SELECT bt.data_transacao, bt.descricao, bt.cnpj_cpf,
                      bt.valor AS tx_valor,
                      ba.cliente_id
               FROM bank_transactions bt
               INNER JOIN bank_accounts ba ON ba.id = bt.account_id
               WHERE bt.id = %s""",
            (tx_id,),
        )
        tx = cursor.fetchone()
        if not tx:
            raise ValueError(f"Transação bancária #{tx_id} não encontrada.")
        data_tx    = tx['data_transacao']
        descricao  = tx.get('descricao') or ''
        cliente_id = tx.get('cliente_id')
        inseridos = 0
        for desp in despesas:
            titulo_id      = desp.get('titulo_id')
            categoria_id   = desp.get('categoria_id')
            subcategoria_id = desp.get('subcategoria_id') or None
            fornecedor_txt = (desp.get('fornecedor') or descricao)[:255]
            # Usa o valor especificado ou, se ausente, o valor total da transação (modo lote)
            valor          = desp.get('valor') or tx.get('tx_valor')
            observacao     = desp.get('observacao') or descricao
            if not titulo_id or not categoria_id or not valor:
                continue
            cursor.execute(
                """INSERT INTO lancamentos_despesas
                       (data, cliente_id, titulo_id, categoria_id, subcategoria_id,
                        valor, fornecedor, observacao, bank_transaction_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (data_tx, cliente_id, titulo_id, categoria_id, subcategoria_id,
                 valor, fornecedor_txt, observacao, tx_id),
            )
            inseridos += 1
        if not inseridos:
            raise ValueError(
                "Preencha os campos obrigatórios da despesa (Título, Categoria e Valor) "
                "antes de conciliar."
            )
        cursor.execute(
            """UPDATE bank_transactions
               SET status='conciliado', conciliado_em=%s, conciliado_por=%s
               WHERE id=%s""",
            (agora, usuario, tx_id),
        )
        # Auto-aprender: despesa INTEGRAL (não dividida) salva mapeamento para próxima importação
        desc_chave_desp = _desc_chave(descricao)
        if salvar_mapeamento and len(despesas) == 1 and (tx.get('cnpj_cpf') or desc_chave_desp):
            d = despesas[0]
            cnpj_save_desp = tx.get('cnpj_cpf') or ''
            tipo_chave_desp = 'cnpj' if cnpj_save_desp else 'texto'
            desc_chave = desc_chave_desp
            cursor.execute(
                """INSERT INTO bank_supplier_mapping
                       (cnpj_cpf, descricao_chave, tipo_chave, total_conciliacoes, titulo_id, categoria_id, subcategoria_id)
                   VALUES (%s, %s, %s, 1, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       titulo_id=%s, categoria_id=%s, subcategoria_id=%s,
                       fornecedor_id=NULL, forma_recebimento_id=NULL,
                       total_conciliacoes=total_conciliacoes+1, atualizado_em=NOW()""",
                (cnpj_save_desp, desc_chave, tipo_chave_desp,
                 d['titulo_id'], d['categoria_id'], d.get('subcategoria_id'),
                 d['titulo_id'], d['categoria_id'], d.get('subcategoria_id')),
            )
    else:
        # Débito → Fornecedor
        if tipo_debito == 'despesa':
            raise ValueError(
                "Preencha os campos obrigatórios da despesa (Título, Categoria e Valor) "
                "antes de conciliar."
            )
        if not fornecedor_id:
            raise ValueError("Selecione um fornecedor para conciliar este débito.")
        cursor.execute(
            """UPDATE bank_transactions
               SET status='conciliado', fornecedor_id=%s,
                   conciliado_em=%s, conciliado_por=%s
               WHERE id=%s""",
            (fornecedor_id, agora, usuario, tx_id),
        )
        cursor.execute("SELECT cnpj_cpf, descricao FROM bank_transactions WHERE id=%s", (tx_id,))
        row = cursor.fetchone()
        desc_chave_row = _desc_chave(row.get('descricao') or '') if row else ''
        if salvar_mapeamento and row and (row.get('cnpj_cpf') or desc_chave_row):
            cnpj_save = row.get('cnpj_cpf') or ''
            tipo_chave_save = 'cnpj' if cnpj_save else 'texto'
            desc_chave = desc_chave_row
            cursor.execute(
                """INSERT INTO bank_supplier_mapping
                       (fornecedor_id, cnpj_cpf, descricao_chave, tipo_chave, total_conciliacoes)
                   VALUES (%s, %s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE
                       fornecedor_id=%s,
                       total_conciliacoes=total_conciliacoes+1,
                       atualizado_em=NOW()""",
                (fornecedor_id, cnpj_save, desc_chave, tipo_chave_save, fornecedor_id),
            )

    conn.commit()


def _get_troco_pix_sem_banco():
    """Retorna Troco PIX que ainda não foram vinculados a transações bancárias.
    Graceful: se a coluna bank_transaction_id não existir ainda, retorna lista vazia.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT tp.id, tp.data, tp.troco_pix AS valor_pix,
                      tp.numero_sequencial,
                      c.razao_social AS posto_nome,
                      tpc.nome_completo AS cliente_nome
               FROM troco_pix tp
               LEFT JOIN clientes c ON c.id = tp.cliente_id
               LEFT JOIN troco_pix_clientes tpc ON tpc.id = tp.troco_pix_cliente_id
               WHERE tp.bank_transaction_id IS NULL AND tp.troco_pix > 0
               ORDER BY tp.data DESC
               LIMIT 200"""
        )
        rows = cursor.fetchall()
        return rows
    except Exception:
        # Coluna bank_transaction_id ainda não existe (migration pendente)
        return []
    finally:
        cursor.close()
        conn.close()


@bp.route('/conciliar', methods=['GET', 'POST'])
@login_required
def conciliar():
    """Interface de conciliação manual com filtros, multi-seleção e memória."""
    _ensure_ld_bank_tx_id()
    _ensure_descricao_chave()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _db_closed = False

    def _close_db():
        """Fecha cursor e conn de forma idempotente (seguro chamar múltiplas vezes)."""
        nonlocal _db_closed
        if not _db_closed:
            _db_closed = True
            try:
                cursor.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    usuario = current_user.email if hasattr(current_user, 'email') else 'manual'

    # ------------------------------------------------------------------
    # POST: processa conciliação (individual ou em lote)
    # ------------------------------------------------------------------
    if request.method == 'POST':
        acao = request.form.get('acao', 'conciliar')
        # Multi-seleção: tx_ids é lista separada por vírgula ou campo repetido
        tx_ids_raw = request.form.getlist('transaction_id') or []
        if not tx_ids_raw:
            tx_ids_raw = [request.form.get('transaction_id', '')]
        tx_ids = [t for t in tx_ids_raw if t]

        fornecedor_id        = request.form.get('fornecedor_id') or None
        forma_recebimento_id = request.form.get('forma_recebimento_id') or None
        tipo_tx              = request.form.get('tipo_tx', 'DEBIT')
        tipo_debito          = request.form.get('tipo_debito', 'fornecedor')  # 'fornecedor' | 'despesa' | 'transferencia'

        # Despesas (até 3 linhas de split)
        despesas = []
        for i in range(1, 4):  # suporta até 3 linhas de split
            tid  = request.form.get(f'desp_{i}_titulo_id') or None
            cid  = request.form.get(f'desp_{i}_categoria_id') or None
            scid = request.form.get(f'desp_{i}_subcategoria_id') or None
            val  = request.form.get(f'desp_{i}_valor') or None
            obs  = request.form.get(f'desp_{i}_observacao') or None
            forn = request.form.get(f'desp_{i}_fornecedor') or None
            if tid and cid:
                try:
                    # val can be None in batch mode → _conciliar_tx uses the transaction's own value
                    val_f = float(val.replace(',', '.')) if val else None
                    despesas.append({'titulo_id': int(tid), 'categoria_id': int(cid),
                                     'subcategoria_id': int(scid) if scid else None,
                                     'valor': val_f, 'observacao': obs, 'fornecedor': forn})
                except (ValueError, TypeError):
                    pass

        conta_destino_id = request.form.get('conta_destino_id') or None
        conta_origem_id  = request.form.get('conta_origem_id') or None
        troco_pix_id     = request.form.get('troco_pix_id') or None

        ok = 0

        if acao == 'aprovar_sugestoes_pagina':
            # Aprovação em lote das sugestões visíveis na página corrente.
            # O frontend envia campos tx_N_id, tx_N_tipo_tx, tx_N_tipo_debito,
            # tx_N_forma_recebimento_id, tx_N_fornecedor_id, tx_N_conta_destino_id,
            # tx_N_titulo_id, tx_N_categoria_id, tx_N_subcategoria_id, tx_N_valor
            # para N = 0, 1, 2, ... enquanto tx_N_id estiver presente.
            try:
                n = 0
                while True:
                    tid = request.form.get(f'tx_{n}_id', '').strip()
                    if not tid:
                        break
                    t_tipo_tx  = request.form.get(f'tx_{n}_tipo_tx', 'DEBIT')
                    t_tipo_deb = request.form.get(f'tx_{n}_tipo_debito', '')
                    t_forma    = request.form.get(f'tx_{n}_forma_recebimento_id') or None
                    t_forn     = request.form.get(f'tx_{n}_fornecedor_id') or None
                    t_conta    = request.form.get(f'tx_{n}_conta_destino_id') or None
                    t_titulo   = request.form.get(f'tx_{n}_titulo_id') or None
                    t_categ    = request.form.get(f'tx_{n}_categoria_id') or None
                    t_sub      = request.form.get(f'tx_{n}_subcategoria_id') or None
                    t_valor    = request.form.get(f'tx_{n}_valor') or None
                    if t_tipo_deb == 'transferencia' and t_conta:
                        _conciliar_transferencia(cursor, conn, tid, t_conta, usuario,
                                                 salvar_mapeamento=True)
                    elif t_tipo_deb == 'transferencia_recebida':
                        _conciliar_tx(cursor, conn, tid, 'conciliar', 'CREDIT',
                                      None, None, usuario, tipo_debito='transferencia',
                                      salvar_mapeamento=True)
                    elif t_tipo_deb == 'despesa' and t_titulo and t_categ and t_valor:
                        try:
                            val_f = float(str(t_valor).replace(',', '.'))
                        except (ValueError, TypeError):
                            n += 1
                            continue
                        desp = [{'titulo_id': int(t_titulo), 'categoria_id': int(t_categ),
                                  'subcategoria_id': int(t_sub) if t_sub else None,
                                  'valor': val_f, 'observacao': None, 'fornecedor': None}]
                        _conciliar_tx(cursor, conn, tid, 'conciliar', 'DEBIT',
                                      None, None, usuario, tipo_debito='despesa',
                                      despesas=desp, salvar_mapeamento=True)
                    elif t_forn or t_forma:
                        try:
                            _conciliar_tx(cursor, conn, tid, 'conciliar', t_tipo_tx,
                                          t_forn, t_forma, usuario,
                                          tipo_debito=t_tipo_deb or 'fornecedor',
                                          salvar_mapeamento=True)
                        except ValueError as ve:
                            logger.debug("aprovar_sugestoes_pagina: ignorando tx %s — %s", tid, ve)
                            n += 1
                            continue
                    else:
                        # Sugestão sem dados suficientes — ignora silenciosamente
                        n += 1
                        continue
                    ok += 1
                    n += 1
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                _close_db()
                logger.exception("Erro ao aprovar sugestões em lote: %s", exc)
                flash('Erro ao aprovar sugestões. Tente novamente ou contacte o suporte.', 'danger')
                return redirect(request.url)
            flash(f'{ok} sugestão(ões) aprovada(s) com sucesso!', 'success')
            _close_db()
            return redirect(request.url)

        salvar_mapeamento = (acao != 'lancamento_unico')
        # Lançamento Único usa a mesma lógica de conciliação, apenas sem salvar mapeamento
        acao_conciliar = 'conciliar' if acao == 'lancamento_unico' else acao
        try:
            for tx_id in tx_ids:
                if tipo_debito == 'transferencia' and conta_destino_id:
                    _conciliar_transferencia(cursor, conn, tx_id, conta_destino_id, usuario,
                                             salvar_mapeamento=salvar_mapeamento)
                else:
                    _conciliar_tx(cursor, conn, tx_id, acao_conciliar, tipo_tx,
                                  fornecedor_id, forma_recebimento_id, usuario,
                                  tipo_debito=tipo_debito, despesas=despesas or None,
                                  troco_pix_id=troco_pix_id,
                                  salvar_mapeamento=salvar_mapeamento,
                                  conta_origem_id=conta_origem_id)
                ok += 1
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            _close_db()
            logger.exception("Erro ao conciliar transação: %s", exc)
            flash(f'Erro ao conciliar: {exc}', 'danger')
            return redirect(request.url)

        if acao == 'ignorar':
            flash(f'{ok} transação(ões) ignorada(s).', 'info')
        else:
            flash(f'{ok} transação(ões) conciliada(s) com sucesso!', 'success')

        _close_db()
        # Mantém filtros após POST
        return redirect(request.url)

    # ------------------------------------------------------------------
    # GET: filtros
    # ------------------------------------------------------------------
    # Inicia uma transação limpa para garantir que o SELECT enxergue os dados
    # mais recentes já commitados (snapshot MVCC atualizado).  Mesmo com
    # pool_reset_session=True, conexões de fallback direto e casos extremos
    # podem herdar um snapshot antigo; este rollback explícito garante que a
    # leitura use sempre o snapshot mais recente do InnoDB (REPEATABLE READ).
    try:
        conn.rollback()
    except Exception:
        pass

    f_clientes  = [int(c) for c in request.args.getlist('cliente_id') if c and c.isdigit()]
    f_tipo      = request.args.get('tipo', '')           # CREDIT / DEBIT
    f_data_ini  = request.args.get('data_ini', '')
    f_data_fim  = request.args.get('data_fim', '')
    f_descricao = request.args.get('descricao', '')
    f_cnpj      = request.args.get('cnpj_cpf', '')
    f_contas    = [c for c in request.args.getlist('account_id') if c]

    page     = request.args.get('page', 1, type=int)
    per_page = 50
    offset   = (page - 1) * per_page

    _TIPOS_OK = {'CREDIT', 'DEBIT'}
    where  = ["bt.status = 'pendente'"]
    params = []

    if f_clientes:
        ph = ','.join(['%s'] * len(f_clientes))
        where.append(f"ba.cliente_id IN ({ph})")
        params.extend(f_clientes)
    if f_tipo and f_tipo in _TIPOS_OK:
        where.append("bt.tipo = %s")
        params.append(f_tipo)
    if f_data_ini:
        where.append("bt.data_transacao >= %s")
        params.append(f_data_ini)
    if f_data_fim:
        where.append("bt.data_transacao <= %s")
        params.append(f_data_fim)
    if f_descricao:
        where.append("bt.descricao LIKE %s")
        params.append(f'%{f_descricao}%')
    if f_cnpj:
        where.append("bt.cnpj_cpf LIKE %s")
        params.append(f'%{f_cnpj}%')
    if f_contas:
        ph = ','.join(['%s'] * len(f_contas))
        where.append(f"bt.account_id IN ({ph})")
        params.extend(f_contas)

    where_sql = 'WHERE ' + ' AND '.join(where)

    # When no company is selected yet, skip expensive queries and show nothing.
    try:
        transacoes = []
        total = 0

        if f_clientes:
            # ------------------------------------------------------------------
            # Busca transações sem N+1 query: sem correlated subquery do BSM
            # ------------------------------------------------------------------
            cursor.execute(
                f"""SELECT bt.*, ba.apelido AS conta_apelido, ba.banco_nome
                    FROM bank_transactions bt
                    INNER JOIN bank_accounts ba ON bt.account_id = ba.id
                    {where_sql}
                    ORDER BY bt.data_transacao DESC, bt.id DESC
                    LIMIT %s OFFSET %s""",
                params + [per_page, offset],
            )
            transacoes = cursor.fetchall()

            # ------------------------------------------------------------------
            # Batch lookup: bank_supplier_mapping para todos os CNPJs distintos
            # Substitui o N+1 correlated subquery por uma única consulta em lote
            # ------------------------------------------------------------------
            for tx in transacoes:
                tx['sugestao_fornecedor_id']       = None
                tx['sugestao_forma_id']            = None
                tx['sugestao_titulo_id']           = None
                tx['sugestao_categoria_id']        = None
                tx['sugestao_subcategoria_id']     = None
                tx['sugestao_conta_destino_id']    = None
                tx['sugestao_tipo_debito']         = None
                tx['sugestao_bsm_descricao_chave'] = None
                tx['sugestao_forma_nome']          = None
                tx['sugestao_fornecedor_nome']     = None
                tx['sugestao_titulo_nome']         = None
                tx['sugestao_categoria_nome']      = None

            cnpjs = list({tx['cnpj_cpf'] for tx in transacoes if tx.get('cnpj_cpf')})
            if cnpjs:
                ph = ','.join(['%s'] * len(cnpjs))
                try:
                    cursor.execute(
                        f"""SELECT bsm.cnpj_cpf, bsm.descricao_chave,
                                   bsm.fornecedor_id, bsm.forma_recebimento_id,
                                   bsm.titulo_id, bsm.categoria_id, bsm.subcategoria_id,
                                   bsm.conta_destino_id, bsm.tipo_debito,
                                   fr.nome AS sugestao_forma_nome,
                                   fs.razao_social AS sugestao_fornecedor_nome,
                                   td.nome AS sugestao_titulo_nome,
                                   cd.nome AS sugestao_categoria_nome
                            FROM bank_supplier_mapping bsm
                            LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id
                            LEFT JOIN fornecedores fs ON fs.id = bsm.fornecedor_id
                            LEFT JOIN titulos_despesas td ON td.id = bsm.titulo_id
                            LEFT JOIN categorias_despesas cd ON cd.id = bsm.categoria_id
                            WHERE bsm.cnpj_cpf IN ({ph})""",
                        cnpjs,
                    )
                    bsm_rows = cursor.fetchall()
                except mysql.connector.errors.ProgrammingError as e:
                    if e.errno == _MYSQL_ERRNO_UNKNOWN_COLUMN:
                        # descricao_chave column not yet created — use legacy fallback without it.
                        logger.warning("conciliar: descricao_chave column missing, using batch fallback")
                        try:
                            cursor.execute(
                                f"""SELECT bsm.cnpj_cpf, '' AS descricao_chave,
                                           bsm.fornecedor_id, bsm.forma_recebimento_id,
                                           bsm.titulo_id, bsm.categoria_id, bsm.subcategoria_id,
                                           bsm.conta_destino_id, bsm.tipo_debito,
                                           fr.nome AS sugestao_forma_nome,
                                           fs.razao_social AS sugestao_fornecedor_nome,
                                           td.nome AS sugestao_titulo_nome,
                                           cd.nome AS sugestao_categoria_nome
                                    FROM bank_supplier_mapping bsm
                                    LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id
                                    LEFT JOIN fornecedores fs ON fs.id = bsm.fornecedor_id
                                    LEFT JOIN titulos_despesas td ON td.id = bsm.titulo_id
                                    LEFT JOIN categorias_despesas cd ON cd.id = bsm.categoria_id
                                    WHERE bsm.cnpj_cpf IN ({ph})""",
                                cnpjs,
                            )
                            bsm_rows = cursor.fetchall()
                        except Exception:
                            logger.warning("conciliar: BSM fallback query also failed, skipping suggestions", exc_info=True)
                            bsm_rows = []
                    else:
                        # Other MySQL error (e.g., errno=1146 table not found) — degrade gracefully.
                        logger.warning("conciliar: BSM lookup failed (errno=%s), skipping suggestions", e.errno)
                        bsm_rows = []
                except Exception:
                    logger.warning("conciliar: BSM lookup failed unexpectedly, skipping suggestions", exc_info=True)
                    bsm_rows = []

                # Índice: (cnpj_cpf, descricao_chave) → row
                bsm_index = {}
                for row in bsm_rows:
                    bsm_index[(row['cnpj_cpf'], row['descricao_chave'])] = row

                # Aplica o mapeamento a cada transação (match específico > genérico)
                for tx in transacoes:
                    cnpj = tx.get('cnpj_cpf') or ''
                    if not cnpj:
                        continue
                    desc_key = _desc_chave(tx.get('descricao') or '')
                    bsm = bsm_index.get((cnpj, desc_key)) or bsm_index.get((cnpj, ''))
                    if bsm:
                        tx['sugestao_fornecedor_id']       = bsm.get('fornecedor_id')
                        tx['sugestao_forma_id']            = bsm.get('forma_recebimento_id')
                        tx['sugestao_titulo_id']           = bsm.get('titulo_id')
                        tx['sugestao_categoria_id']        = bsm.get('categoria_id')
                        tx['sugestao_subcategoria_id']     = bsm.get('subcategoria_id')
                        tx['sugestao_conta_destino_id']    = bsm.get('conta_destino_id')
                        tx['sugestao_tipo_debito']         = bsm.get('tipo_debito')
                        tx['sugestao_bsm_descricao_chave'] = bsm.get('descricao_chave', '')
                        tx['sugestao_forma_nome']          = bsm.get('sugestao_forma_nome')
                        tx['sugestao_fornecedor_nome']     = bsm.get('sugestao_fornecedor_nome')
                        tx['sugestao_titulo_nome']         = bsm.get('sugestao_titulo_nome')
                        tx['sugestao_categoria_nome']      = bsm.get('sugestao_categoria_nome')

            # ------------------------------------------------------------------
            # Sugestões para transações SEM CNPJ: match por descricao_chave
            # (ex: transferências Pix que não têm CPF/CNPJ no extrato OFX)
            # ------------------------------------------------------------------
            desc_chaves_sem_cnpj = list({
                _desc_chave(tx.get('descricao') or '')
                for tx in transacoes
                if not tx.get('cnpj_cpf') and (tx.get('descricao') or '')
            })
            if desc_chaves_sem_cnpj:
                ph_desc = ','.join(['%s'] * len(desc_chaves_sem_cnpj))
                try:
                    cursor.execute(
                        f"""SELECT bsm.descricao_chave,
                                   bsm.fornecedor_id, bsm.forma_recebimento_id,
                                   bsm.titulo_id, bsm.categoria_id, bsm.subcategoria_id,
                                   bsm.conta_destino_id, bsm.tipo_debito,
                                   fr.nome AS sugestao_forma_nome,
                                   fs.razao_social AS sugestao_fornecedor_nome,
                                   td.nome AS sugestao_titulo_nome,
                                   cd.nome AS sugestao_categoria_nome
                            FROM bank_supplier_mapping bsm
                            LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id
                            LEFT JOIN fornecedores fs ON fs.id = bsm.fornecedor_id
                            LEFT JOIN titulos_despesas td ON td.id = bsm.titulo_id
                            LEFT JOIN categorias_despesas cd ON cd.id = bsm.categoria_id
                            WHERE bsm.cnpj_cpf = '' AND bsm.descricao_chave IN ({ph_desc})""",
                        desc_chaves_sem_cnpj,
                    )
                    desc_bsm_rows = cursor.fetchall()
                    desc_bsm_index = {row['descricao_chave']: row for row in desc_bsm_rows}
                    for tx in transacoes:
                        if tx.get('cnpj_cpf'):
                            continue
                        desc_key = _desc_chave(tx.get('descricao') or '')
                        bsm = desc_bsm_index.get(desc_key)
                        if bsm:
                            tx['sugestao_fornecedor_id']       = bsm.get('fornecedor_id')
                            tx['sugestao_forma_id']            = bsm.get('forma_recebimento_id')
                            tx['sugestao_titulo_id']           = bsm.get('titulo_id')
                            tx['sugestao_categoria_id']        = bsm.get('categoria_id')
                            tx['sugestao_subcategoria_id']     = bsm.get('subcategoria_id')
                            tx['sugestao_conta_destino_id']    = bsm.get('conta_destino_id')
                            tx['sugestao_tipo_debito']         = bsm.get('tipo_debito')
                            tx['sugestao_bsm_descricao_chave'] = bsm.get('descricao_chave', '')
                            tx['sugestao_forma_nome']          = bsm.get('sugestao_forma_nome')
                            tx['sugestao_fornecedor_nome']     = bsm.get('sugestao_fornecedor_nome')
                            tx['sugestao_titulo_nome']         = bsm.get('sugestao_titulo_nome')
                            tx['sugestao_categoria_nome']      = bsm.get('sugestao_categoria_nome')
                except Exception:
                    logger.warning("conciliar: description-only BSM lookup failed", exc_info=True)

            # -----------------------------------------------------------------------
            # Aplicar regras por padrão de descrição a transações sem sugestão de CNPJ
            # -----------------------------------------------------------------------
            try:
                cursor.execute(
                    """SELECT r.id, r.padrao_descricao, r.padrao_secundario, r.tipo_match,
                              r.tipo_transacao, r.account_id,
                              r.forma_recebimento_id, fr.nome AS forma_nome,
                              r.fornecedor_id, f.razao_social AS fornecedor_nome
                       FROM bank_conciliacao_regras r
                       LEFT JOIN formas_recebimento fr ON fr.id = r.forma_recebimento_id
                       LEFT JOIN fornecedores f ON f.id = r.fornecedor_id
                       WHERE r.ativo = 1
                       ORDER BY
                           (r.account_id IS NOT NULL) DESC,
                           (r.padrao_secundario IS NOT NULL AND r.padrao_secundario <> '') DESC,
                           r.id"""
                )
                regras_padrao = cursor.fetchall()
            except Exception:
                logger.warning("conciliar: bank_conciliacao_regras query failed, skipping rules", exc_info=True)
                regras_padrao = []

            for tx in transacoes:
                descricao = (tx.get('descricao') or '').upper()
                tipo_tx_r = tx.get('tipo', '')
                for regra in regras_padrao:
                    # Filtra por conta bancária
                    regra_account_id = regra.get('account_id')
                    if regra_account_id and int(regra_account_id) != int(tx['account_id']):
                        continue
                    if regra['tipo_transacao'] != 'AMBOS' and regra['tipo_transacao'] != tipo_tx_r:
                        continue
                    padrao = (regra['padrao_descricao'] or '').upper()
                    if regra['tipo_match'] == 'exato':
                        bate = descricao == padrao
                    else:
                        bate = padrao in descricao
                    if not bate:
                        continue
                    # Match secundário
                    padrao2 = (regra.get('padrao_secundario') or '').upper()
                    if padrao2 and padrao2 not in descricao:
                        continue
                    # Regras de descrição têm prioridade sobre mapeamento por CNPJ
                    if regra['forma_recebimento_id']:
                        tx['sugestao_forma_id']   = regra['forma_recebimento_id']
                        tx['sugestao_forma_nome'] = regra['forma_nome']
                        tx['sugestao_regra']      = True
                    if regra['fornecedor_id']:
                        tx['sugestao_fornecedor_id']   = regra['fornecedor_id']
                        tx['sugestao_fornecedor_nome'] = regra['fornecedor_nome']
                        tx['sugestao_regra']           = True
                    break  # primeira regra que bate vence

            # Para créditos sem regra de descrição correspondente: remove a sugestão de forma
            # que veio do bank_supplier_mapping por CNPJ/CPF genérico (sem descrição específica).
            # O mesmo CPF pode aparecer em transações de tipos distintos (PIX, depósito, cheque…),
            # tornando a sugestão por CNPJ não confiável para créditos.
            # Exceção: mapeamentos com descricao_chave específica são confiáveis e mantidos.
            for tx in transacoes:
                if tx.get('tipo') == 'CREDIT' and not tx.get('sugestao_regra'):
                    # Preserve a sugestão se veio de memorização específica (descricao_chave não vazia)
                    if not tx.get('sugestao_bsm_descricao_chave'):
                        tx['sugestao_forma_id']   = None
                        tx['sugestao_forma_nome'] = None

            # Sugestão 'Compensação Cobrança' para créditos EFI sem outra sugestão de forma.
            # Detecta o padrão do extrato EFI: "Recebimento de cobrança: <charge_id> de ..."
            # Aceita tanto a codificação correta (cobrança) quanto a dupla-codificação
            # que ocorre quando OFX UTF-8 é lido como Latin-1 (cobranÃ§a).
            _efi_charge_re = re.compile(
                r'cobran(?:ça|Ã§a|ca)[:\s]+\d{6,12}',
                re.IGNORECASE,
            )
            _forma_comp_id   = None
            _forma_comp_nome = None
            try:
                cursor.execute(
                    "SELECT id, nome FROM formas_recebimento WHERE nome = 'Compensação Cobrança' LIMIT 1"
                )
                _fr = cursor.fetchone()
                if _fr:
                    _forma_comp_id   = _fr['id']
                    _forma_comp_nome = _fr['nome']
            except Exception:
                pass
            if _forma_comp_id:
                for tx in transacoes:
                    if (tx.get('tipo') == 'CREDIT'
                            and not tx.get('sugestao_forma_id')
                            and _efi_charge_re.search(tx.get('descricao') or '')):
                        tx['sugestao_forma_id']   = _forma_comp_id
                        tx['sugestao_forma_nome'] = _forma_comp_nome
                        tx['sugestao_regra']      = True

            # Enriquece badge de sugestão de despesa (CNPJ → título/categoria)
            for tx in transacoes:
                if tx.get('sugestao_titulo_id') and not tx.get('sugestao_forma_id') and not tx.get('sugestao_fornecedor_id'):
                    tx['sugestao_despesa_label'] = (
                        (tx.get('sugestao_titulo_nome') or '') + ' › ' + (tx.get('sugestao_categoria_nome') or '')
                    )

            # Marca CREDITs que são transferências recebidas (sintéticas ou por CNPJ aprendido)
            for tx in transacoes:
                if tx.get('tipo') == 'CREDIT':
                    tipo_conc    = tx.get('tipo_conciliacao') or ''
                    sugestao_tip = tx.get('sugestao_tipo_debito') or ''
                    if tipo_conc == 'transferencia' or sugestao_tip == 'transferencia':
                        tx['sugestao_transferencia_recebida'] = True

            # Reordena: dentro de cada data, lançamentos com sugestão aparecem primeiro
            def _tem_sugestao(tx):
                return bool(
                    tx.get('sugestao_forma_id') or
                    tx.get('sugestao_fornecedor_id') or
                    tx.get('sugestao_titulo_id') or
                    tx.get('sugestao_transferencia_recebida')
                )
            transacoes = sorted(
                transacoes,
                key=lambda tx: (tx.get('data_transacao'), _tem_sugestao(tx)),
                reverse=True,
            )

            cursor.execute(
                f"SELECT COUNT(*) AS total FROM bank_transactions bt "
                f"INNER JOIN bank_accounts ba ON bt.account_id = ba.id "
                f"{where_sql}",
                params,
            )
            total = cursor.fetchone()['total']

        fornecedores       = _get_fornecedores(cursor)
        formas_recebimento = _get_formas_recebimento(cursor)
        titulos_despesas   = _get_titulos_despesas(cursor)
        contas             = _get_accounts(cursor)
        clientes           = _get_clientes_com_produtos(cursor)

        # Todas as contas de todas as empresas (para transferência entre contas e filtro JS)
        cursor.execute(
            """SELECT ba.id, ba.apelido, ba.banco_nome, ba.cliente_id,
                      c.nome_fantasia AS empresa_nome
               FROM bank_accounts ba
               LEFT JOIN clientes c ON c.id = ba.cliente_id
               WHERE ba.ativo = 1
               ORDER BY empresa_nome, ba.banco_nome, ba.apelido"""
        )
        todas_contas = cursor.fetchall()
        # Mapa id→label para exibir nome da conta sugerida no badge de transferência
        todas_contas_map = {c['id']: f"{c.get('empresa_nome') or ''} — {c['banco_nome']} {c['apelido']}"
                            for c in todas_contas}

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        _close_db()
        logger.exception("Erro ao carregar página de conciliação: %s", exc)
        flash('Erro ao carregar a página de conciliação. Tente novamente.', 'danger')
        return redirect(url_for('bank_import.index'))
    finally:
        _close_db()

    total_pages = max(1, (total + per_page - 1) // per_page)

    # Busca Troco PIX pendentes de conciliação bancária para o modal de débitos.
    # Graceful: se a coluna bank_transaction_id não existir ainda, retorna lista vazia.
    troco_pix_pendentes = _get_troco_pix_sem_banco()

    return render_template(
        'bank_import/conciliar.html',
        transacoes=transacoes,
        fornecedores=fornecedores,
        formas_recebimento=formas_recebimento,
        titulos_despesas=titulos_despesas,
        contas=contas,
        clientes=clientes,
        todas_contas=todas_contas,
        todas_contas_map=todas_contas_map,
        troco_pix_pendentes=troco_pix_pendentes,
        page=page,
        total_pages=total_pages,
        total=total,
        # filtros atuais para manter na paginação
        f_clientes=f_clientes,
        f_tipo=f_tipo,
        f_data_ini=f_data_ini,
        f_data_fim=f_data_fim,
        f_descricao=f_descricao,
        f_cnpj=f_cnpj,
        f_contas=f_contas,
    )


@bp.route('/relatorio')
@login_required
def relatorio():
    """Relatório completo de transações — ferramenta de auditoria."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    contas   = _get_accounts(cursor)
    clientes = _get_clientes_com_produtos(cursor)

    # Filtros
    account_id = request.args.get('account_id', '')
    empresa_id = request.args.get('empresa_id', '')
    status     = request.args.get('status', '')
    tipo       = request.args.get('tipo', '')
    data_ini   = request.args.get('data_ini', '')
    data_fim   = request.args.get('data_fim', '')

    # Paginação (page >= 1 sempre)
    page     = max(1, request.args.get('page', 1, type=int))
    per_page = 100
    offset   = (page - 1) * per_page

    # Monta filtros seguros
    _ALLOWED_STATUSES = {'pendente', 'conciliado', 'ignorado'}
    _ALLOWED_TIPOS    = {'CREDIT', 'DEBIT'}
    where_parts = []
    params      = []

    if account_id:
        where_parts.append('bt.account_id = %s')
        params.append(account_id)
    if empresa_id:
        where_parts.append('ba.cliente_id = %s')
        params.append(empresa_id)
    if status and status in _ALLOWED_STATUSES:
        where_parts.append('bt.status = %s')
        params.append(status)
    if tipo and tipo in _ALLOWED_TIPOS:
        where_parts.append('bt.tipo = %s')
        params.append(tipo)
    if data_ini:
        where_parts.append('bt.data_transacao >= %s')
        params.append(data_ini)
    if data_fim:
        where_parts.append('bt.data_transacao <= %s')
        params.append(data_fim)

    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    # Query principal: traz formas_recebimento + empresa + indica vínculos via LEFT JOIN
    cursor.execute(
        """SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao,
                  bt.cnpj_cpf, bt.status, bt.conciliado_em, bt.conciliado_por,
                  bt.tipo_conciliacao,
                  ba.apelido AS conta_apelido, ba.banco_nome,
                  c.razao_social AS empresa_nome,
                  f.razao_social  AS fornecedor_nome,
                  fr.nome         AS forma_recebimento_nome,
                  CASE WHEN ld.bt_id IS NOT NULL THEN 1 ELSE 0 END AS tem_lancamento_despesa,
                  CASE WHEN tp.bt_id IS NOT NULL THEN 1 ELSE 0 END AS tem_troco_pix
           FROM bank_transactions bt
           INNER JOIN bank_accounts ba ON bt.account_id = ba.id
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           LEFT JOIN fornecedores f ON f.id = bt.fornecedor_id
           LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
           LEFT JOIN (SELECT DISTINCT bank_transaction_id AS bt_id
                      FROM lancamentos_despesas
                      WHERE bank_transaction_id IS NOT NULL) ld ON ld.bt_id = bt.id
           LEFT JOIN (SELECT DISTINCT bank_transaction_id AS bt_id
                      FROM troco_pix
                      WHERE bank_transaction_id IS NOT NULL) tp ON tp.bt_id = bt.id
           """
        + where_sql
        + ' ORDER BY bt.data_transacao DESC, bt.id DESC'
        + ' LIMIT %s OFFSET %s',
        params + [per_page, offset],
    )
    transacoes = cursor.fetchall()

    # Totais (sem paginação)
    cursor.execute(
        """SELECT
               COUNT(*) AS total_transacoes,
               SUM(CASE WHEN bt.tipo='DEBIT'  THEN bt.valor ELSE 0 END) AS total_debitos,
               SUM(CASE WHEN bt.tipo='CREDIT' THEN bt.valor ELSE 0 END) AS total_creditos,
               SUM(CASE WHEN bt.status='pendente'   THEN 1 ELSE 0 END) AS total_pendentes,
               SUM(CASE WHEN bt.status='conciliado' THEN 1 ELSE 0 END) AS total_conciliados
           FROM bank_transactions bt
           INNER JOIN bank_accounts ba ON bt.account_id = ba.id
           """
        + where_sql,
        params,
    )
    totais = cursor.fetchone()
    total_rows = totais['total_transacoes'] or 0

    cursor.close()
    conn.close()

    total_pages = max(1, (total_rows + per_page - 1) // per_page)

    return render_template(
        'bank_import/relatorio.html',
        transacoes=transacoes,
        contas=contas,
        clientes=clientes,
        totais=totais,
        total_rows=total_rows,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        filtros={
            'account_id': account_id,
            'empresa_id': empresa_id,
            'status':     status,
            'tipo':       tipo,
            'data_ini':   data_ini,
            'data_fim':   data_fim,
        },
    )


@bp.route('/relatorio/exportar-csv')
@login_required
def relatorio_exportar_csv():
    """Exporta o relatório completo de transações como CSV (sem limite de linhas)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    account_id = request.args.get('account_id', '')
    empresa_id = request.args.get('empresa_id', '')
    status     = request.args.get('status', '')
    tipo       = request.args.get('tipo', '')
    data_ini   = request.args.get('data_ini', '')
    data_fim   = request.args.get('data_fim', '')

    _ALLOWED_STATUSES = {'pendente', 'conciliado', 'ignorado'}
    _ALLOWED_TIPOS    = {'CREDIT', 'DEBIT'}
    where_parts = []
    params      = []

    if account_id:
        where_parts.append('bt.account_id = %s')
        params.append(account_id)
    if empresa_id:
        where_parts.append('ba.cliente_id = %s')
        params.append(empresa_id)
    if status and status in _ALLOWED_STATUSES:
        where_parts.append('bt.status = %s')
        params.append(status)
    if tipo and tipo in _ALLOWED_TIPOS:
        where_parts.append('bt.tipo = %s')
        params.append(tipo)
    if data_ini:
        where_parts.append('bt.data_transacao >= %s')
        params.append(data_ini)
    if data_fim:
        where_parts.append('bt.data_transacao <= %s')
        params.append(data_fim)

    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    cursor.execute(
        """SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao,
                  bt.cnpj_cpf, bt.status, bt.conciliado_em, bt.conciliado_por,
                  bt.tipo_conciliacao,
                  ba.apelido AS conta_apelido, ba.banco_nome,
                  c.razao_social AS empresa_nome,
                  f.razao_social  AS fornecedor_nome,
                  fr.nome         AS forma_recebimento_nome,
                  CASE WHEN ld.bt_id IS NOT NULL THEN 1 ELSE 0 END AS tem_lancamento_despesa,
                  CASE WHEN tp.bt_id IS NOT NULL THEN 1 ELSE 0 END AS tem_troco_pix
           FROM bank_transactions bt
           INNER JOIN bank_accounts ba ON bt.account_id = ba.id
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           LEFT JOIN fornecedores f ON f.id = bt.fornecedor_id
           LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
           LEFT JOIN (SELECT DISTINCT bank_transaction_id AS bt_id
                      FROM lancamentos_despesas
                      WHERE bank_transaction_id IS NOT NULL) ld ON ld.bt_id = bt.id
           LEFT JOIN (SELECT DISTINCT bank_transaction_id AS bt_id
                      FROM troco_pix
                      WHERE bank_transaction_id IS NOT NULL) tp ON tp.bt_id = bt.id
           """
        + where_sql
        + ' ORDER BY bt.data_transacao DESC, bt.id DESC',
        params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'ID', 'Data', 'Tipo', 'Valor', 'Descrição', 'CNPJ/CPF',
        'Status', 'Tipo Conciliação', 'Fornecedor', 'Forma Recebimento',
        'Conta', 'Empresa', 'Conciliado Em', 'Conciliado Por',
        'Tem Lançamento Despesa', 'Tem Troco PIX',
    ])
    for r in rows:
        valor = r['valor']
        writer.writerow([
            r['id'],
            r['data_transacao'].strftime('%d/%m/%Y') if r['data_transacao'] else '',
            'Débito' if r['tipo'] == 'DEBIT' else 'Crédito',
            str(valor).replace('.', ',') if valor is not None else '',
            r['descricao'] or '',
            r['cnpj_cpf'] or '',
            r['status'] or '',
            r['tipo_conciliacao'] or '',
            r['fornecedor_nome'] or '',
            r['forma_recebimento_nome'] or '',
            r['conta_apelido'] or r['banco_nome'] or '',
            r['empresa_nome'] or '',
            r['conciliado_em'].strftime('%d/%m/%Y %H:%M') if r['conciliado_em'] else '',
            r['conciliado_por'] or '',
            'Sim' if r['tem_lancamento_despesa'] else 'Não',
            'Sim' if r['tem_troco_pix'] else 'Não',
        ])

    output.seek(0)
    return Response(
        '\ufeff' + output.getvalue(),   # BOM para Excel abrir UTF-8 corretamente
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="transacoes_bancarias.csv"'},
    )


# ---------------------------------------------------------------------------
# Endpoints da API REST
# ---------------------------------------------------------------------------

@bp.route('/api/transacoes-pendentes')
@login_required
def api_transacoes_pendentes():
    """API: retorna lista JSON de transações pendentes."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao,
                  bt.cnpj_cpf, bt.status, ba.apelido AS conta_apelido
           FROM bank_transactions bt
           INNER JOIN bank_accounts ba ON bt.account_id = ba.id
           WHERE bt.status = 'pendente'
           ORDER BY bt.data_transacao DESC
           LIMIT 200"""
    )
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # Converte objetos de data para strings ISO para serialização JSON
    for row in rows:
        if row.get('data_transacao'):
            row['data_transacao'] = str(row['data_transacao'])
        if row.get('valor') is not None:
            row['valor'] = float(row['valor'])

    return jsonify(rows)


@bp.route('/api/auto-reconcile', methods=['POST'])
def api_auto_reconcile():
    """API: força a auto-conciliação de transações pendentes (por CNPJ e por regras)."""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'erro': 'Sessão expirada. Por favor, recarregue a página e faça login novamente.', 'conciliados': 0}), 401
    _ensure_ld_bank_tx_id()
    _ensure_descricao_chave()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # 1. Auto-conciliação por regras de descrição (regras têm prioridade sobre CNPJ)
        por_regras = _auto_conciliar_por_regras(cursor, conn)
        logger.info("api_auto_reconcile: por_regras=%d", por_regras)

        # 2. Auto-conciliação por CNPJ (apenas para os que ficaram pendentes após as regras)
        try:
            cursor.execute(
                """SELECT bt.id, bt.tipo, bsm.fornecedor_id, bsm.forma_recebimento_id
                   FROM bank_transactions bt
                   INNER JOIN bank_supplier_mapping bsm ON bsm.id = (
                       SELECT s.id FROM bank_supplier_mapping s
                       WHERE s.cnpj_cpf = bt.cnpj_cpf
                         AND s.descricao_chave IN ('', LEFT(UPPER(TRIM(bt.descricao)), 100))
                       ORDER BY LENGTH(s.descricao_chave) DESC
                       LIMIT 1
                   )
                   WHERE bt.status = 'pendente' AND bt.cnpj_cpf IS NOT NULL AND bt.cnpj_cpf != ''"""
            )
        except mysql.connector.errors.ProgrammingError as _e:
            if _e.errno != 1054:
                raise
            # Fallback when descricao_chave column does not yet exist in the DB
            logger.warning("api_auto_reconcile: descricao_chave column missing, using simple join fallback")
            cursor.execute(
                """SELECT bt.id, bt.tipo, bsm.fornecedor_id, bsm.forma_recebimento_id
                   FROM bank_transactions bt
                   INNER JOIN bank_supplier_mapping bsm ON bsm.cnpj_cpf = bt.cnpj_cpf
                   WHERE bt.status = 'pendente' AND bt.cnpj_cpf IS NOT NULL AND bt.cnpj_cpf != ''"""
            )
        rows = cursor.fetchall()

        agora = _dt.datetime.now()
        batch_credit = []
        batch_debit  = []
        for row in rows:
            if row['tipo'] == 'CREDIT':
                batch_credit.append((row['forma_recebimento_id'], agora, row['id']))
            else:
                batch_debit.append((row['fornecedor_id'], agora, row['id']))
        if batch_credit:
            cursor.executemany(
                """UPDATE bank_transactions
                   SET status='conciliado', forma_recebimento_id=%s,
                       conciliado_em=%s, conciliado_por='auto'
                   WHERE id=%s""",
                batch_credit,
            )
        if batch_debit:
            cursor.executemany(
                """UPDATE bank_transactions
                   SET status='conciliado', fornecedor_id=%s,
                       conciliado_em=%s, conciliado_por='auto'
                   WHERE id=%s""",
                batch_debit,
            )
        updated = len(batch_credit) + len(batch_debit)

        conn.commit()

        # 3. Auto-conciliação por charge_id EFI
        por_efi = _auto_conciliar_cobrancas(cursor, conn)

        cursor.close()
        conn.close()
        logger.info("api_auto_reconcile: por_cnpj=%d por_efi=%d total=%d", updated, por_efi, updated + por_regras + por_efi)
        return jsonify({'success': True, 'conciliados': updated + por_regras + por_efi,
                        'por_cnpj': updated, 'por_regras': por_regras, 'por_efi': por_efi})
    except Exception as e:
        logger.exception("Erro em api_auto_reconcile: %s", e)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        try:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        except Exception:
            pass
        return jsonify({'success': False, 'erro': str(e), 'conciliados': 0}), 200


@bp.route('/api/diagnostico-regras')
@login_required
def api_diagnostico_regras():
    """Diagnóstico: mostra regras e o que cada uma encontraria (sem fazer alterações)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT * FROM bank_conciliacao_regras WHERE ativo=1
               ORDER BY
                   (account_id IS NOT NULL) DESC,
                   (padrao_secundario IS NOT NULL AND padrao_secundario <> '') DESC,
                   id"""
        )
        regras = cursor.fetchall()

        cursor.execute(
            """SELECT bt.id, bt.descricao, bt.tipo, bt.cnpj_cpf,
                      bt.data_transacao, bt.valor, bt.account_id
               FROM bank_transactions bt
               WHERE bt.status='pendente'
               LIMIT 200"""
        )
        pendentes = cursor.fetchall()

        resultado = {
            'total_regras': len(regras),
            'total_pendentes': len(pendentes),
            'regras': [],
            'matches': []
        }

        for r in regras:
            resultado['regras'].append({
                'id': r['id'],
                'padrao': r.get('padrao_descricao'),
                'padrao2': r.get('padrao_secundario'),
                'tipo_match': r.get('tipo_match'),
                'tipo_transacao': r.get('tipo_transacao'),
                'titulo_id': r.get('titulo_id'),
                'categoria_id': r.get('categoria_id'),
                'forma_id': r.get('forma_recebimento_id'),
                'forn_id': r.get('fornecedor_id'),
            })

        for tx in pendentes:
            descricao = (tx.get('descricao') or '').upper()
            tipo = tx.get('tipo') or ''
            for regra in regras:
                regra_account_id = regra.get('account_id')
                if regra_account_id and int(regra_account_id) != int(tx['account_id']):
                    continue
                tipo_regra = regra.get('tipo_transacao', 'AMBOS')
                if tipo_regra != 'AMBOS' and tipo_regra != tipo:
                    continue
                padrao = (regra.get('padrao_descricao') or '').upper()
                tipo_match = regra.get('tipo_match', 'contem')
                match = (descricao == padrao) if tipo_match == 'exato' else (padrao in descricao)
                if not match:
                    continue
                padrao2 = (regra.get('padrao_secundario') or '').upper()
                if padrao2 and padrao2 not in descricao:
                    continue
                resultado['matches'].append({
                    'tx_id': tx['id'],
                    'tx_descricao': tx.get('descricao'),
                    'tx_tipo': tipo,
                    'tx_valor': str(tx.get('valor')),
                    'regra_id': regra['id'],
                    'regra_padrao': regra.get('padrao_descricao'),
                    'titulo_id': regra.get('titulo_id'),
                    'categoria_id': regra.get('categoria_id'),
                })
                break

        cursor.close()
        conn.close()
        return jsonify(resultado)
    except Exception as e:
        logger.exception("Erro em diagnostico_regras: %s", e)
        return jsonify({'erro': str(e)}), 500


@bp.route('/api/debug-transferencias')
@login_required
def api_debug_transferencias():
    """Debug: mostra o estado real das transferências no banco."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Verifica se coluna tipo_conciliacao existe
        cursor.execute(
            """SELECT COUNT(*) AS existe FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE()
                 AND TABLE_NAME='bank_transactions'
                 AND COLUMN_NAME='tipo_conciliacao'""")
        col_existe = cursor.fetchone()['existe'] > 0

        # CREDITs com TRANSFER_
        cursor.execute(
            """SELECT id, account_id, data_transacao, valor, hash_dedup, status, descricao
               FROM bank_transactions
               WHERE hash_dedup LIKE 'TRANSFER_%'
               ORDER BY id DESC LIMIT 20""")
        credits = cursor.fetchall()

        # DEBITs conciliados recentes
        cursor.execute(
            """SELECT id, account_id, data_transacao, valor, status,
                      conciliado_por, descricao
               FROM bank_transactions
               WHERE tipo='DEBIT' AND status='conciliado'
               ORDER BY id DESC LIMIT 20""")
        debits = cursor.fetchall()

        return jsonify({
            'col_tipo_conciliacao_existe': col_existe,
            'credits_transfer': [dict(r) for r in credits],
            'debits_conciliados_recentes': [dict(r) for r in debits],
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/api/contas', methods=['GET'])
@login_required
def api_contas():
    """API: lista contas bancárias cadastradas."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cliente_id = request.args.get('cliente_id', type=int)
    contas = _get_accounts(cursor, cliente_id=cliente_id)
    cursor.close()
    conn.close()
    return jsonify(contas)


@bp.route('/api/contas', methods=['POST'])
@login_required
def api_criar_conta():
    """API: cria uma nova conta bancária vinculada a uma empresa."""
    data = request.get_json() or {}
    banco_nome = (data.get('banco_nome') or '').strip()
    if not banco_nome:
        return jsonify({'success': False, 'message': 'banco_nome é obrigatório'}), 400

    # cliente_id é opcional mas recomendado – vincula a conta a uma empresa com produtos
    cliente_id = data.get('cliente_id') or None
    if cliente_id is not None:
        try:
            cliente_id = int(cliente_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'cliente_id inválido'}), 400

    plano_contas_conta_id = data.get('plano_contas_conta_id') or None
    if plano_contas_conta_id is not None:
        try:
            plano_contas_conta_id = int(plano_contas_conta_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'plano_contas_conta_id inválido'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """INSERT INTO bank_accounts (banco_nome, agencia, conta, apelido, cliente_id, plano_contas_conta_id)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (banco_nome, data.get('agencia'), data.get('conta'), data.get('apelido'),
         cliente_id, plano_contas_conta_id),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()

    return jsonify({'success': True, 'id': new_id}), 201


@bp.route('/contas')
@login_required
def gerenciar_contas():
    """Página de gerenciamento de contas bancárias (lista, edita, exclui)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT ba.id, ba.banco_nome, ba.agencia, ba.conta, ba.apelido,
                  ba.ativo, ba.cliente_id, ba.criado_em,
                  ba.plano_contas_conta_id,
                  c.razao_social AS empresa_nome,
                  pc.codigo AS plano_codigo, pc.nome AS plano_nome,
                  (SELECT COUNT(*) FROM bank_transactions bt WHERE bt.account_id = ba.id) AS total_transacoes
           FROM bank_accounts ba
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           LEFT JOIN plano_contas_contas pc ON pc.id = ba.plano_contas_conta_id
           ORDER BY ba.ativo DESC, ba.apelido, ba.banco_nome"""
    )
    contas = cursor.fetchall()
    clientes = _get_clientes_com_produtos(cursor)
    cursor.execute(
        """SELECT pcc.id, pcc.codigo, pcc.nome, g.nome AS grupo_nome
           FROM plano_contas_contas pcc
           JOIN plano_contas_grupos g ON g.id = pcc.grupo_id
           WHERE pcc.ativo = 1
           ORDER BY pcc.codigo"""
    )
    plano_contas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('bank_import/contas.html', contas=contas, clientes=clientes,
                           plano_contas=plano_contas)


@bp.route('/api/contas/<int:conta_id>', methods=['PUT'])
@login_required
def api_editar_conta(conta_id):
    """API: edita dados de uma conta bancária."""
    data = request.get_json() or {}
    banco_nome = (data.get('banco_nome') or '').strip()
    if not banco_nome:
        return jsonify({'success': False, 'message': 'banco_nome é obrigatório'}), 400

    cliente_id = data.get('cliente_id') or None
    if cliente_id is not None:
        try:
            cliente_id = int(cliente_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'cliente_id inválido'}), 400

    plano_contas_conta_id = data.get('plano_contas_conta_id') or None
    if plano_contas_conta_id is not None:
        try:
            plano_contas_conta_id = int(plano_contas_conta_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'plano_contas_conta_id inválido'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """UPDATE bank_accounts
           SET banco_nome=%s, agencia=%s, conta=%s, apelido=%s,
               cliente_id=%s, plano_contas_conta_id=%s
           WHERE id=%s""",
        (banco_nome, data.get('agencia') or None, data.get('conta') or None,
         data.get('apelido') or None, cliente_id, plano_contas_conta_id, conta_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})


@bp.route('/api/contas/<int:conta_id>/excluir', methods=['POST'])
@login_required
def api_excluir_conta(conta_id):
    """API: desativa (soft-delete) uma conta bancária."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Verifica transações vinculadas antes de desativar
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_transactions WHERE account_id = %s", (conta_id,)
    )
    total = cursor.fetchone()['total']
    if total > 0:
        cursor.close()
        conn.close()
        return jsonify({
            'success': False,
            'message': f'Esta conta possui {total} transação(ões) vinculada(s). Remova as transações antes de desativar.'
        }), 409

    cursor.execute("UPDATE bank_accounts SET ativo = 0 WHERE id = %s", (conta_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})



def _get_inbox_dirs() -> tuple:
    """
    Retorna (inbox_dir, processed_dir), criando ambos se não existirem.

    Usa /tmp/ofx_inbox como fallback quando o caminho configurado não é gravável
    (ex.: diretório da aplicação somente leitura após o build no Render/Railway).

    processed_dir é OFX_PROCESSED_DIR se configurado, caso contrário
    <inbox_dir>/processados/ (padrão compatível com versões anteriores).
    """
    from config import Config
    inbox = Config.OFX_INBOX_DIR
    processed = Config.OFX_PROCESSED_DIR or os.path.join(inbox, 'processados')

    def _try_makedirs(path):
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except OSError:
            return False

    # Tentativa principal
    if _try_makedirs(inbox) and _try_makedirs(processed):
        return inbox, processed

    # Fallback para /tmp – sempre gravável no Render/Railway/Docker
    tmp_inbox = os.path.join('/tmp', 'ofx_inbox')
    tmp_processed = os.path.join(tmp_inbox, 'processados')
    _try_makedirs(tmp_inbox)
    _try_makedirs(tmp_processed)
    return tmp_inbox, tmp_processed


def _get_inbox_dir() -> str:
    """Retorna o diretório de entrada (auxiliar compatível com versões anteriores)."""
    inbox, _ = _get_inbox_dirs()
    return inbox


@bp.route('/api/inbox-files')
@login_required
def api_inbox_files():
    """API: lista arquivos OFX encontrados na pasta de entrada."""
    inbox, processed = _get_inbox_dirs()
    files = []
    try:
        for name in sorted(os.listdir(inbox)):
            if not name.lower().endswith('.ofx'):
                continue
            full = os.path.join(inbox, name)
            if not os.path.isfile(full):
                continue
            stat = os.stat(full)
            files.append({
                'nome': name,
                'tamanho': stat.st_size,
                'modificado': _dt.datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'),
            })
    except OSError as exc:
        return jsonify({'success': False, 'message': str(exc), 'files': []}), 500

    return jsonify({'success': True, 'pasta': inbox, 'pasta_processados': processed, 'files': files})


@bp.route('/api/inbox-upload', methods=['POST'])
@login_required
def api_inbox_upload():
    """
    Salva um arquivo OFX na pasta de entrada SEM processar imediatamente.

    Útil no Railway (container efêmero): o usuário faz upload pelo navegador,
    o arquivo fica na pasta inbox aguardando, e pode ser importado depois
    clicando em "Importar" na seção "Pasta de Entrada OFX".
    """
    arquivo = request.files.get('ofx_file')
    if not arquivo or not arquivo.filename:
        return jsonify({'success': False, 'message': 'Nenhum arquivo enviado'}), 400

    nome = os.path.basename(arquivo.filename)
    if not nome.lower().endswith('.ofx'):
        return jsonify({'success': False, 'message': 'Apenas arquivos .ofx são aceitos'}), 400

    inbox = _get_inbox_dir()
    dest = os.path.join(inbox, nome)

    # Evita sobrescrever arquivo existente – prefixa com timestamp
    if os.path.exists(dest):
        ts = _dt.datetime.now().strftime('%Y%m%d%H%M%S_')
        nome = ts + nome
        dest = os.path.join(inbox, nome)

    try:
        arquivo.save(dest)
    except OSError as exc:
        return jsonify({'success': False, 'message': f'Erro ao salvar arquivo: {exc}'}), 500

    return jsonify({'success': True, 'nome': nome, 'message': f'Arquivo "{nome}" salvo na pasta de entrada.'})


@bp.route('/scan-inbox', methods=['POST'])
@login_required
def scan_inbox():
    """
    Processa um arquivo OFX da pasta de entrada.

    Parâmetros POST (form ou JSON):
        account_id  – ID da conta bancária destino
        nome_arquivo – nome do arquivo dentro da pasta de entrada
    """
    # Aceita form-data e JSON
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form

    account_id = data.get('account_id')
    nome_arquivo = (data.get('nome_arquivo') or '').strip()

    if not account_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'account_id é obrigatório'}), 400
        flash('Selecione uma conta bancária.', 'warning')
        return redirect(url_for('bank_import.index'))

    if not nome_arquivo:
        if request.is_json:
            return jsonify({'success': False, 'message': 'nome_arquivo é obrigatório'}), 400
        flash('Nenhum arquivo especificado.', 'warning')
        return redirect(url_for('bank_import.index'))

    # Segurança: apenas nomes simples de arquivo são aceitos – bloqueia tentativas de path traversal
    if os.sep in nome_arquivo or '/' in nome_arquivo or '\\' in nome_arquivo or '..' in nome_arquivo:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Nome de arquivo inválido'}), 400
        flash('Nome de arquivo inválido.', 'danger')
        return redirect(url_for('bank_import.index'))

    inbox, processed = _get_inbox_dirs()
    filepath = os.path.join(inbox, nome_arquivo)

    if not os.path.isfile(filepath):
        if request.is_json:
            return jsonify({'success': False, 'message': f'Arquivo não encontrado: {nome_arquivo}'}), 404
        flash(f'Arquivo não encontrado: {nome_arquivo}', 'danger')
        return redirect(url_for('bank_import.index'))

    # Leitura e parse do arquivo.
    # Arquivos OFX v1.x (SGML) geralmente usam codificação Latin-1 / ISO-8859-1.
    # Usar 'latin-1' com errors='replace' é a opção mais segura e universal:
    # todos os 256 valores de byte têm mapeamento, portanto nenhum byte causa erro.
    try:
        with open(filepath, 'r', encoding='latin-1', errors='replace') as fh:
            content = fh.read()
    except OSError as exc:
        if request.is_json:
            return jsonify({'success': False, 'message': str(exc)}), 500
        flash(f'Erro ao ler arquivo: {exc}', 'danger')
        return redirect(url_for('bank_import.index'))

    from integrations.ofx_parser import OFXParser
    transactions = OFXParser(content).get_transactions()

    if not transactions:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Nenhuma transação encontrada no arquivo OFX.'}), 422
        flash('Nenhuma transação encontrada no arquivo OFX.', 'warning')
        return redirect(url_for('bank_import.index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    _ensure_descricao_chave()
    inseridos, duplicados, duplicados_lista = _save_transactions(cursor, conn, account_id, transactions)

    cursor.close()
    conn.close()

    # Move o arquivo para o diretório de processados (OFX_PROCESSED_DIR)
    dest = os.path.join(processed, nome_arquivo)
    # Evita colisão: prefixa com timestamp se já existir arquivo com o mesmo nome
    if os.path.exists(dest):
        ts = _dt.datetime.now().strftime('%Y%m%d%H%M%S_')
        dest = os.path.join(processed, ts + nome_arquivo)
    try:
        os.rename(filepath, dest)
    except OSError:
        pass  # Não crítico – arquivo processado mesmo se a movimentação falhar

    msg = f'{nome_arquivo}: {inseridos} transação(ões) importada(s), {duplicados} duplicata(s) ignorada(s).'
    if request.is_json:
        return jsonify({'success': True, 'message': msg, 'inseridos': inseridos, 'duplicados': duplicados, 'duplicados_lista': duplicados_lista})
    flash(msg, 'success')
    return redirect(url_for('bank_import.index'))


# ---------------------------------------------------------------------------
# API: dias importados por conta
# ---------------------------------------------------------------------------

@bp.route('/api/dias-importados')
@login_required
def api_dias_importados():
    """
    Retorna os dias com transações importadas para uma conta (ou empresa).
    GET params:
      - account_id (int, opcional) — filtra por conta específica
      - empresa_id (int, opcional) — filtra por todas as contas de uma empresa
    Retorna lista de datas importadas e lista de datas faltando no intervalo.
    """
    account_id = request.args.get('account_id', type=int)
    empresa_id = request.args.get('empresa_id', type=int)

    if not account_id and not empresa_id:
        return jsonify({'success': False, 'message': 'Informe account_id ou empresa_id'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if account_id:
            # Busca info da conta para o título
            cursor.execute(
                """SELECT ba.id, ba.apelido, ba.banco_nome, ba.agencia, ba.conta,
                          c.razao_social AS empresa_nome
                   FROM bank_accounts ba
                   LEFT JOIN clientes c ON c.id = ba.cliente_id
                   WHERE ba.id = %s""",
                (account_id,),
            )
            conta_info = cursor.fetchone() or {}
            titulo = (
                conta_info.get('apelido') or conta_info.get('banco_nome') or f'Conta #{account_id}'
            )
            if conta_info.get('empresa_nome'):
                titulo += f' – {conta_info["empresa_nome"]}'

            cursor.execute(
                """SELECT DATE(data_transacao) AS dia, COUNT(*) AS qtd
                   FROM bank_transactions
                   WHERE account_id = %s
                   GROUP BY DATE(data_transacao)
                   ORDER BY dia""",
                (account_id,),
            )
        else:
            # Filtra por empresa (todas as contas dela)
            cursor.execute(
                "SELECT razao_social FROM clientes WHERE id = %s", (empresa_id,)
            )
            emp = cursor.fetchone()
            titulo = emp['razao_social'] if emp else f'Empresa #{empresa_id}'

            cursor.execute(
                """SELECT DATE(bt.data_transacao) AS dia, COUNT(*) AS qtd
                   FROM bank_transactions bt
                   INNER JOIN bank_accounts ba ON ba.id = bt.account_id
                   WHERE ba.cliente_id = %s
                   GROUP BY DATE(bt.data_transacao)
                   ORDER BY dia""",
                (empresa_id,),
            )

        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    if not rows:
        return jsonify({'success': True, 'titulo': titulo, 'dias': [], 'faltando': []})

    # Converte para strings YYYY-MM-DD
    dias_importados = [str(r['dia']) for r in rows]
    qtd_por_dia = {str(r['dia']): r['qtd'] for r in rows}

    # Calcula dias faltando (entre o primeiro e hoje, exceto fins de semana)
    data_min = _dt.date.fromisoformat(dias_importados[0])
    data_max = _dt.date.today()
    faltando = []
    cur = data_min
    while cur <= data_max:
        dia_str = cur.isoformat()
        # Pula fins de semana (sábado=5, domingo=6)
        if cur.weekday() < 5 and dia_str not in qtd_por_dia:
            faltando.append(dia_str)
        cur += _dt.timedelta(days=1)

    return jsonify({
        'success': True,
        'titulo': titulo,
        'dias': [{'data': d, 'qtd': qtd_por_dia[d]} for d in dias_importados],
        'faltando': faltando,
    })


# ---------------------------------------------------------------------------
# Integração Dropbox API
# ---------------------------------------------------------------------------

@bp.route('/api/dropbox-files')
@login_required
def api_dropbox_files():
    """
    API: lista arquivos .ofx na pasta Dropbox configurada.
    GET param: account_id (int, opcional) — quando informado, tenta filtrar arquivos cujo nome
    contenha dígitos da conta, agência ou palavras do apelido/banco.
    Se o filtro não encontrar nenhum arquivo, retorna todos os arquivos com
    filtrado_sem_resultado=True para que o front-end exiba todos e permita seleção manual.
    """
    from integrations.dropbox_ofx import listar_arquivos_ofx, get_inbox_paths
    account_id = request.args.get('account_id', type=int)
    try:
        arquivos = listar_arquivos_ofx()
        inbox, processed = get_inbox_paths()
    except RuntimeError as exc:
        return jsonify({'success': False, 'message': str(exc), 'files': []}), 400

    filtrado = False
    filtrado_sem_resultado = False
    if account_id:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT banco_nome, agencia, conta, apelido FROM bank_accounts WHERE id = %s",
            (account_id,),
        )
        acc = cursor.fetchone()
        cursor.close()
        conn.close()
        if acc:
            # Tokens de busca: sinais específicos do BANCO e CONTA para localizar o arquivo.
            # Tokens de dígitos (conta/agência) são altamente confiáveis — match direto.
            # Tokens de texto (banco, apelido) são ambíguos e requerem verificação de ACCTID:
            #   ex: "NH GTBA" é compartilhado entre CORA - NH GTBA e SICREDI - NH GTBA.
            #   A verificação de ACCTID garante que o arquivo corresponde à conta selecionada.
            STOPWORDS = {'banco', 'de', 'do', 'da', 'e', 'em', 'sa', 's/a', 'ltda'}

            def _extrair_palavras(texto):
                """Retorna palavras significativas de um texto (mín. 3 chars, fora de stopwords)."""
                for p in re.split(r'[\W_]+', texto or ''):
                    pl = p.lower()
                    if len(pl) >= 3 and pl not in STOPWORDS:
                        yield pl

            tokens = set()
            conta_digits_full = ''

            # 1. Dígitos do número da conta (com e sem traço).
            if acc.get('conta'):
                conta_digits_full = re.sub(r'\D', '', acc['conta'])
                if len(conta_digits_full) >= 4:
                    tokens.add(conta_digits_full[-6:] if len(conta_digits_full) >= 6 else conta_digits_full)
                    # Sequência completa cobre "27677832" quando a conta é "2767783-2"
                    tokens.add(conta_digits_full)

            # 2. Dígitos da agência (quando tiver 4+ dígitos).
            if acc.get('agencia'):
                ag_digits = re.sub(r'\D', '', acc['agencia'])
                if len(ag_digits) >= 4:
                    tokens.add(ag_digits)

            # 3. Palavras significativas do nome do banco (ex: "SICREDI", "CORA", "EFI").
            tokens.update(_extrair_palavras(acc.get('banco_nome')))

            # 4. Palavras do apelido da conta (ex: "NH GTBA" → token "gtba").
            # Apis bancárias como a CORA nomeiam os arquivos OFX com a slug da empresa
            # (ex: "nh-gtba_...ofx"), sem o nome do banco no nome do arquivo.
            # Quando o nome do banco não aparece no arquivo, sem essa inclusão nenhum
            # token corresponderia e todos os arquivos seriam exibidos como fallback.
            # Como o apelido é compartilhado entre contas de bancos diferentes,
            # os arquivos que só correspondem por esses tokens passam pela verificação
            # de ACCTID (conteúdo do OFX), garantindo que pertencem à conta correta.
            tokens.update(_extrair_palavras(acc.get('apelido')))

            # Remove tokens vazios que possam ter sido gerados.
            tokens.discard('')

            if tokens:
                _usar_digits = bool(conta_digits_full and len(conta_digits_full) >= 4)

                # Tokens numéricos (conta/agência) — altamente específicos.
                # Quando um arquivo corresponde a um desses tokens, não precisa de
                # verificação de conteúdo (o número da conta já está no nome).
                digit_tokens = set()
                if conta_digits_full and len(conta_digits_full) >= 4:
                    digit_tokens.add(conta_digits_full)
                    digit_tokens.add(conta_digits_full[-6:] if len(conta_digits_full) >= 6 else conta_digits_full)
                if acc.get('agencia'):
                    ag_d = re.sub(r'\D', '', acc['agencia'])
                    if len(ag_d) >= 4:
                        digit_tokens.add(ag_d)

                # Tokens de texto do nome do banco (ex: "sicredi") — ambíguos quando
                # várias contas são do mesmo banco. Arquivos que só correspondem por
                # esses tokens precisam de verificação de conteúdo.
                bank_name_tokens = tokens - digit_tokens

                def _arquivo_corresponde_por_digito(nome):
                    """Verdadeiro quando o nome contém dígitos da conta/agência."""
                    nome_lower = nome.lower()
                    if any(t in nome_lower for t in digit_tokens):
                        return True
                    if _usar_digits:
                        nome_digits = re.sub(r'\D', '', nome_lower)
                        if conta_digits_full in nome_digits:
                            return True
                    return False

                def _arquivo_corresponde(nome):
                    nome_lower = nome.lower()
                    if any(t in nome_lower for t in tokens):
                        return True
                    if _usar_digits:
                        nome_digits = re.sub(r'\D', '', nome_lower)
                        if conta_digits_full in nome_digits:
                            return True
                    return False

                matched = [f for f in arquivos if _arquivo_corresponde(f['nome'])]

                if matched:
                    # Para arquivos que correspondem APENAS pelo nome do banco
                    # (sem dígitos da conta no nome), verificamos o conteúdo OFX
                    # para garantir que o ACCTID dentro do arquivo realmente pertence
                    # à conta selecionada. Isso evita que um arquivo de outra empresa
                    # (ex: extrato SICREDI da NH-GTBA) apareça para QUALICONTAX.
                    from integrations.dropbox_ofx import extrair_acctid_ofx
                    verificados = []
                    for f in matched:
                        # Se o nome já contém dígitos da conta → confiável, sem download
                        if _arquivo_corresponde_por_digito(f['nome']):
                            verificados.append(f)
                            continue
                        # Caso contrário (só bateu por nome do banco) → lê o OFX
                        acctid_no_arquivo = extrair_acctid_ofx(f['nome'])
                        if acctid_no_arquivo is None:
                            # Falha ao ler: mantém o arquivo (benefício da dúvida)
                            verificados.append(f)
                            continue
                        # Verifica se os dígitos da conta selecionada correspondem ao ACCTID
                        # do arquivo. Exige que ambos tenham ao menos 4 dígitos para evitar
                        # correspondências acidentais com sequências curtas.
                        if (conta_digits_full and len(acctid_no_arquivo) >= 4 and (
                            acctid_no_arquivo == conta_digits_full
                            or acctid_no_arquivo.endswith(conta_digits_full)
                            or conta_digits_full.endswith(acctid_no_arquivo)
                        )):
                            verificados.append(f)
                    matched = verificados

                if matched:
                    # Arquivos encontrados pelo filtro — retorna apenas os correspondentes.
                    arquivos = matched
                    filtrado = True
                else:
                    # Nenhum arquivo correspondeu ao filtro por nome nem por conteúdo.
                    # Retorna todos os arquivos da pasta com flag especial para que o
                    # front-end informe o usuário e permita selecionar manualmente.
                    filtrado_sem_resultado = True

    return jsonify({
        'success': True,
        'files': arquivos,
        'pasta': inbox,
        'pasta_processados': processed,
        'filtrado': filtrado,
        'filtrado_sem_resultado': filtrado_sem_resultado,
    })


@bp.route('/importar-dropbox', methods=['POST'])
@login_required
def importar_dropbox():
    """
    Baixa um arquivo OFX do Dropbox, importa as transações e move o arquivo
    para a pasta DROPBOX_OFX_PROCESSED.
    """
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form

    account_id = data.get('account_id')
    nome_arquivo = (data.get('nome_arquivo') or '').strip()

    if not account_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'account_id é obrigatório'}), 400
        flash('Selecione uma conta bancária.', 'warning')
        return redirect(url_for('bank_import.index'))

    if not nome_arquivo:
        if request.is_json:
            return jsonify({'success': False, 'message': 'nome_arquivo é obrigatório'}), 400
        flash('Nenhum arquivo especificado.', 'warning')
        return redirect(url_for('bank_import.index'))

    from integrations.dropbox_ofx import baixar_arquivo, mover_para_processados
    try:
        content = baixar_arquivo(nome_arquivo)
    except RuntimeError as exc:
        if request.is_json:
            return jsonify({'success': False, 'message': str(exc)}), 400
        flash(f'Erro ao baixar arquivo do Dropbox: {exc}', 'danger')
        return redirect(url_for('bank_import.index'))

    from integrations.ofx_parser import OFXParser
    transactions = OFXParser(content).get_transactions()

    if not transactions:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Nenhuma transação encontrada no arquivo OFX.'}), 422
        flash('Nenhuma transação encontrada no arquivo OFX.', 'warning')
        return redirect(url_for('bank_import.index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    _ensure_descricao_chave()
    inseridos, duplicados, duplicados_lista = _save_transactions(cursor, conn, account_id, transactions)
    cursor.close()
    conn.close()

    # Move para pasta de processados no Dropbox (não crítico)
    mover_para_processados(nome_arquivo)

    msg = f'Dropbox "{nome_arquivo}": {inseridos} transação(ões) importada(s), {duplicados} duplicata(s) ignorada(s).'
    if request.is_json:
        return jsonify({'success': True, 'message': msg, 'inseridos': inseridos, 'duplicados': duplicados, 'duplicados_lista': duplicados_lista})
    flash(msg, 'success')
    return redirect(url_for('bank_import.index'))


@bp.route('/api/reimportar-duplicatas', methods=['POST'])
@login_required
def api_reimportar_duplicatas():
    """
    Re-ativa transações bancárias duplicadas que foram ignoradas ou estão pendentes,
    resetando seu status para 'pendente' para que possam ser conciliadas novamente.
    """
    data = request.get_json() or {}
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return jsonify({'success': False, 'message': 'Lista de IDs inválida'}), 400
    try:
        ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'IDs devem ser inteiros'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    ph = ','.join(['%s'] * len(ids))
    cursor.execute(
        f"""UPDATE bank_transactions
               SET status='pendente', conciliado_em=NULL, conciliado_por=NULL
             WHERE id IN ({ph})
               AND status IN ('ignorado', 'pendente')""",
        ids,
    )
    reativados = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True, 'reativados': reativados})


# ---------------------------------------------------------------------------
# Dropbox OAuth2 — fluxo de autorização para obter refresh token permanente
# ---------------------------------------------------------------------------

@bp.route('/api/dropbox-oauth-url')
@login_required
def api_dropbox_oauth_url():
    """Gera a URL de autorização Dropbox (OAuth2 offline) para o usuário clicar."""
    try:
        import dropbox
        app_key = os.environ.get('DROPBOX_APP_KEY', '').strip()
        if not app_key:
            return jsonify({'ok': False, 'erro': 'DROPBOX_APP_KEY não configurado no Render.'})

        auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(
            app_key,
            use_pkce=True,
            token_access_type='offline',
        )
        url = auth_flow.start()
        # Guarda o verifier na sessão para usar na troca
        from flask import session
        session['dbx_pkce_verifier'] = auth_flow.flow_result.pkce_verifier
        return jsonify({'ok': True, 'url': url})
    except Exception as exc:
        return jsonify({'ok': False, 'erro': str(exc)})


@bp.route('/api/desfazer-transferencia/<int:tx_id>', methods=['POST'])
@login_required
def api_desfazer_transferencia(tx_id):
    """Desfaz uma transferência entre contas:
    - Remove o CREDIT TRANSFER_<id> se existir
    - Redefine o DEBIT de origem para status='pendente'
    Isso permite que o usuário refaça a conciliação.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Verifica que a transação existe e é um DEBIT conciliado
        cursor.execute(
            "SELECT id, tipo, status FROM bank_transactions WHERE id=%s", (tx_id,)
        )
        tx = cursor.fetchone()
        if not tx:
            return jsonify({'ok': False, 'erro': 'Transação não encontrada.'}), 404
        if tx['tipo'] != 'DEBIT':
            return jsonify({'ok': False, 'erro': 'Apenas débitos podem ser desfeitos.'}), 400

        hash_credit = f'TRANSFER_{tx_id}'

        # Remove o CREDIT correspondente (se existir)
        cursor.execute(
            "DELETE FROM bank_transactions WHERE hash_dedup = %s AND tipo = 'CREDIT'",
            (hash_credit,),
        )
        deletados = cursor.rowcount

        # Reabre o DEBIT para pendente — tenta com tipo_conciliacao (nova coluna)
        try:
            cursor.execute(
                """UPDATE bank_transactions
                   SET status='pendente', conciliado_em=NULL, conciliado_por=NULL,
                       fornecedor_id=NULL, forma_recebimento_id=NULL,
                       tipo_conciliacao=NULL
                   WHERE id=%s""",
                (tx_id,),
            )
        except Exception:
            conn.rollback()
            cursor.execute(
                """UPDATE bank_transactions
                   SET status='pendente', conciliado_em=NULL, conciliado_por=NULL,
                       fornecedor_id=NULL, forma_recebimento_id=NULL
                   WHERE id=%s""",
                (tx_id,),
            )
        conn.commit()
        return jsonify({
            'ok': True,
            'mensagem': f'Conciliação desfeita. CREDIT removido: {deletados}. Transação reaberta para conciliação.',
        })
    except Exception as exc:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(exc)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/api/dropbox-oauth-token')
@login_required
def api_dropbox_oauth_token():
    """
    Troca o código de autorização pelo refresh token permanente.
    Parâmetro GET: code (colado pelo usuário após autorizar no Dropbox).
    """
    try:
        import dropbox
        from flask import session
        code = (request.args.get('code') or '').strip()
        if not code:
            return jsonify({'ok': False, 'erro': 'Parâmetro "code" é obrigatório.'})

        app_key    = os.environ.get('DROPBOX_APP_KEY', '').strip()
        app_secret = os.environ.get('DROPBOX_APP_SECRET', '').strip()
        if not app_key or not app_secret:
            return jsonify({'ok': False, 'erro': 'DROPBOX_APP_KEY e DROPBOX_APP_SECRET devem estar configurados.'})

        pkce_verifier = session.pop('dbx_pkce_verifier', None)
        auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(
            app_key,
            consumer_secret=app_secret,
            use_pkce=True,
            token_access_type='offline',
        )
        if pkce_verifier:
            auth_flow.flow_result.pkce_verifier = pkce_verifier

        oauth_result = auth_flow.finish(code)
        refresh_token = oauth_result.refresh_token

        return jsonify({
            'ok': True,
            'refresh_token': refresh_token,
            'instrucao': (
                f'Copie o valor abaixo e configure como variável de ambiente '
                f'DROPBOX_REFRESH_TOKEN no Render. Depois disso o token nunca mais vai expirar.'
            ),
        })
    except Exception as exc:
        return jsonify({'ok': False, 'erro': f'Erro ao trocar código: {exc}'})

