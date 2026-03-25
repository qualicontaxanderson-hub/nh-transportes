# -*- coding: utf-8 -*-
"""
Módulo de Gerenciamento de Depósitos.

Lista os depósitos registrados nos Fechamentos de Caixa
(lancamentos_caixa_comprovacao cujo tipo de forma de pagamento é
DEPOSITO_ESPECIE, DEPOSITO_CHEQUE_VISTA ou DEPOSITO_CHEQUE_PRAZO) e permite
conciliá-los com as transações bancárias importadas via OFX.

Regras:
  - Depósitos em espécie  (DEPOSITO_ESPECIE)          → tipo_grupo = 'ESPECIE'
  - Depósitos em cheque   (DEPOSITO_CHEQUE_VISTA /
                           DEPOSITO_CHEQUE_PRAZO)      → tipo_grupo = 'CHEQUE'
  - Agrupamento N:1: vários depósitos podem ser vinculados a UMA transação
    bancária (quando o banco consolida vários cheques num só lançamento).
  - Restrição de tipo: espécie só com espécie, cheque só com cheque.

Rotas:
  GET  /depositos/                         – lista com filtros
  GET  /depositos/api/candidatos/<id>      – API: sugestões de match bancário
  POST /depositos/vincular                 – vincula deposito(s) a bank_tx
  POST /depositos/desvincular/<id>         – desvincula
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('depositos', __name__, url_prefix='/depositos')

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_DEPOSIT_TIPOS = ('DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')

_TIPO_LABEL = {
    'DEPOSITO_ESPECIE':       'Espécie',
    'DEPOSITO_CHEQUE_VISTA':  'Cheque à Vista',
    'DEPOSITO_CHEQUE_PRAZO':  'Cheque a Prazo',
}

_TIPO_GRUPO = {
    'DEPOSITO_ESPECIE':       'ESPECIE',
    'DEPOSITO_CHEQUE_VISTA':  'CHEQUE',
    'DEPOSITO_CHEQUE_PRAZO':  'CHEQUE',
}

# Janela de busca de matches bancários (dias antes/depois da data do caixa)
_MATCH_WINDOW_DAYS = 5

# ──────────────────────────────────────────────────────────────────────────────
# DB migration
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_bank_tx_col(conn):
    """
    Adiciona bank_transaction_id à lancamentos_caixa_comprovacao se ainda não
    existir.  Usa INFORMATION_SCHEMA para evitar erros na migration idempotente.
    """
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'lancamentos_caixa_comprovacao'
               AND COLUMN_NAME  = 'bank_transaction_id'
            """
        )
        row = cur.fetchone()
        if not (row and row[0]):
            cur.execute(
                """ALTER TABLE lancamentos_caixa_comprovacao
                   ADD COLUMN bank_transaction_id INT NULL DEFAULT NULL"""
            )
            conn.commit()
        cur.close()
    except Exception:
        pass  # Não crítico


def _reset_orphaned_deposit_transactions(conn):
    """
    Corrige bank_transactions que estão marcadas como status='conciliado' /
    tipo_conciliacao='deposito' mas cujo depósito foi removido ou re-criado
    (por edição do Fechamento de Caixa) — deixando a transação bancária sem
    nenhum lancamentos_caixa_comprovacao vinculado.

    Essas transações "órfãs" ficam invisíveis no fluxo de conciliação porque o
    filtro padrão exclui conciliado+deposito.  Este helper as devolve ao estado
    'pendente' para que voltem a aparecer como candidatos.
    """
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """UPDATE bank_transactions bt
                      SET bt.status            = 'pendente',
                          bt.conciliado_em     = NULL,
                          bt.conciliado_por    = NULL,
                          bt.tipo_conciliacao  = NULL
                    WHERE bt.tipo_conciliacao = 'deposito'
                      AND bt.status           = 'conciliado'
                      AND NOT EXISTS (
                            SELECT 1
                              FROM lancamentos_caixa_comprovacao lcc
                             WHERE lcc.bank_transaction_id = bt.id
                          )"""
            )
        except Exception:
            # Fallback for DB schemas without tipo_conciliacao column
            cur.execute(
                """UPDATE bank_transactions bt
                      SET bt.status         = 'pendente',
                          bt.conciliado_em  = NULL,
                          bt.conciliado_por = NULL
                    WHERE bt.status = 'conciliado'
                      AND NOT EXISTS (
                            SELECT 1
                              FROM lancamentos_caixa_comprovacao lcc
                             WHERE lcc.bank_transaction_id = bt.id
                          )"""
            )
        conn.commit()
        cur.close()
    except Exception:
        pass  # Não crítico

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hoje():
    return date.today()


def _default_period():
    hoje = _hoje()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _fmt_br(d):
    if d is None:
        return ''
    if isinstance(d, str):
        try:
            d = datetime.strptime(d, '%Y-%m-%d').date()
        except Exception:
            return d
    try:
        return d.strftime('%d/%m/%Y')
    except Exception:
        return str(d)


def _get_clientes(conn):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT DISTINCT c.id,
                   COALESCE(c.nome_fantasia, c.razao_social) AS nome
              FROM clientes c
             INNER JOIN lancamentos_caixa lc ON lc.cliente_id = c.id
             ORDER BY nome
            """
        )
        return cur.fetchall()
    except Exception:
        return []
    finally:
        cur.close()


def _fetch_depositos(conn, data_inicio, data_fim, cliente_ids=None,
                     tipo_grupo=None, status=None):
    """
    Retorna depósitos do caixa para o período, com dados de conciliação bancária.

    tipo_grupo: 'ESPECIE' | 'CHEQUE' | None (todos)
    status:     'pendente' | 'conciliado' | None (todos)
    """
    where = ["lc.data BETWEEN %s AND %s",
             "fpc.tipo IN ('DEPOSITO_ESPECIE','DEPOSITO_CHEQUE_VISTA','DEPOSITO_CHEQUE_PRAZO')",
             # Exclui caixas gerados automaticamente pelo módulo Troco PIX:
             # sua data é a data da transação (não de um fechamento real), o que
             # causaria DATA CAIXA incorreta na listagem de depósitos.
             "NOT EXISTS (SELECT 1 FROM troco_pix tp WHERE tp.lancamento_caixa_id = lc.id)"]
    params = [data_inicio, data_fim]

    if cliente_ids:
        placeholders = ','.join(['%s'] * len(cliente_ids))
        where.append(f"lc.cliente_id IN ({placeholders})")
        params.extend(int(x) for x in cliente_ids)

    if tipo_grupo == 'ESPECIE':
        where.append("fpc.tipo = 'DEPOSITO_ESPECIE'")
    elif tipo_grupo == 'CHEQUE':
        where.append("fpc.tipo IN ('DEPOSITO_CHEQUE_VISTA','DEPOSITO_CHEQUE_PRAZO')")

    if status == 'conciliado':
        where.append("lcc.bank_transaction_id IS NOT NULL")
    elif status == 'pendente':
        where.append("lcc.bank_transaction_id IS NULL")

    sql = f"""
        SELECT
            lcc.id,
            lcc.lancamento_caixa_id,
            lcc.forma_pagamento_id,
            lcc.descricao,
            lcc.valor,
            lcc.data_deposito,
            lcc.bank_transaction_id,
            lc.data                         AS data_caixa,
            lc.cliente_id,
            COALESCE(cl.nome_fantasia, cl.razao_social) AS cliente_nome,
            fpc.tipo                        AS forma_tipo,
            fpc.nome                        AS forma_nome,
            bt.data_transacao               AS banco_data,
            bt.valor                        AS banco_valor,
            bt.descricao                    AS banco_descricao,
            ba.apelido                      AS banco_conta_apelido,
            ba.banco_nome                   AS banco_nome
        FROM lancamentos_caixa_comprovacao lcc
        INNER JOIN lancamentos_caixa       lc  ON lc.id  = lcc.lancamento_caixa_id
        INNER JOIN clientes                cl  ON cl.id  = lc.cliente_id
        INNER JOIN formas_pagamento_caixa  fpc ON fpc.id = lcc.forma_pagamento_id
        LEFT  JOIN bank_transactions       bt  ON bt.id  = lcc.bank_transaction_id
        LEFT  JOIN bank_accounts           ba  ON ba.id  = bt.account_id
        WHERE {' AND '.join(where)}
        ORDER BY lc.data DESC, lcc.id DESC
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    finally:
        cur.close()

    # Normalise types
    for r in rows:
        for key in ('valor', 'banco_valor'):
            if r.get(key) is not None:
                r[key] = float(r[key])
        for key in ('data_caixa', 'data_deposito', 'banco_data'):
            if r.get(key) and not isinstance(r[key], str):
                r[key] = r[key].isoformat() if hasattr(r[key], 'isoformat') else str(r[key])
        r['forma_tipo_label'] = _TIPO_LABEL.get(r.get('forma_tipo'), r.get('forma_tipo', ''))
        r['tipo_grupo']       = _TIPO_GRUPO.get(r.get('forma_tipo'), 'ESPECIE')
        r['data_caixa_br']    = _fmt_br(r.get('data_caixa'))
        r['data_deposito_br'] = _fmt_br(r.get('data_deposito'))
        r['banco_data_br']    = _fmt_br(r.get('banco_data'))

    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
@admin_required
def listar():
    args = request.args

    data_inicio  = args.get('data_inicio', '').strip()
    data_fim     = args.get('data_fim',    '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    cliente_ids = [c for c in args.getlist('cliente_ids[]') if c]
    tipo_grupo  = args.get('tipo_grupo', '').strip() or None
    status      = args.get('status',    '').strip() or None

    conn = get_db_connection()
    try:
        _ensure_bank_tx_col(conn)
        _reset_orphaned_deposit_transactions(conn)
        clientes   = _get_clientes(conn)
        depositos  = _fetch_depositos(
            conn, data_inicio, data_fim,
            cliente_ids=cliente_ids,
            tipo_grupo=tipo_grupo,
            status=status,
        )
    finally:
        conn.close()

    total_pendente    = sum(d['valor'] for d in depositos if not d.get('bank_transaction_id'))
    total_conciliado  = sum(d['valor'] for d in depositos if d.get('bank_transaction_id'))
    total_geral       = sum(d['valor'] for d in depositos)
    qtd_pendente      = sum(1 for d in depositos if not d.get('bank_transaction_id'))
    qtd_conciliado    = sum(1 for d in depositos if d.get('bank_transaction_id'))

    return render_template(
        'depositos/listar.html',
        depositos=depositos,
        clientes=clientes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        tipo_grupo=tipo_grupo or '',
        status=status or '',
        cliente_ids=cliente_ids,
        total_pendente=total_pendente,
        total_conciliado=total_conciliado,
        total_geral=total_geral,
        qtd_pendente=qtd_pendente,
        qtd_conciliado=qtd_conciliado,
    )


@bp.route('/api/candidatos/<int:comprovacao_id>')
@login_required
def api_candidatos(comprovacao_id):
    """
    API: retorna transações bancárias CREDIT que podem ser matches para o
    depósito informado.

    Busca transações dentro de ±MATCH_WINDOW_DAYS da data do caixa.
    Filtra por tipo de depósito (CHEQUE ou ESPÉCIE) usando conf_depositos_vinculos;
    quando não configurado, cai no fallback por nome de formas_recebimento.
    Inclui transações pendentes e conciliadas para recebimento (que ainda não
    foram vinculadas como depósito).
    Ordenado por proximidade de valor e data.
    """
    conn = get_db_connection()
    cur  = conn.cursor(dictionary=True)
    try:
        # Carrega o depósito (inclui cliente_id para filtrar por tipo)
        cur.execute(
            """
            SELECT lcc.id, lcc.valor, lcc.bank_transaction_id,
                   lc.data AS data_caixa,
                   lc.cliente_id,
                   fpc.tipo AS forma_tipo
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa      lc  ON lc.id  = lcc.lancamento_caixa_id
              JOIN formas_pagamento_caixa fpc ON fpc.id = lcc.forma_pagamento_id
             WHERE lcc.id = %s
            """,
            (comprovacao_id,),
        )
        dep = cur.fetchone()
        if not dep:
            return jsonify([])

        valor      = float(dep['valor'] or 0)
        data_ref   = dep['data_caixa']
        cliente_id = dep.get('cliente_id')
        if hasattr(data_ref, 'isoformat'):
            data_ref = data_ref.isoformat()

        data_ini = (datetime.strptime(data_ref, '%Y-%m-%d').date()
                    - timedelta(days=_MATCH_WINDOW_DAYS)).isoformat()
        data_fim = (datetime.strptime(data_ref, '%Y-%m-%d').date()
                    + timedelta(days=_MATCH_WINDOW_DAYS)).isoformat()

        dep_tipo_grupo   = _TIPO_GRUPO.get(dep['forma_tipo'], 'ESPECIE')
        tipo_dep_vinculo = 'CHEQUE' if dep_tipo_grupo == 'CHEQUE' else 'DINHEIRO'

        # Resolve formas_recebimento_ids que correspondem ao tipo de depósito
        # 1) via conf_depositos_vinculos (configuração explícita por empresa)
        forma_ids = []
        if cliente_id:
            try:
                cur.execute(
                    """
                    SELECT forma_recebimento_id
                      FROM conf_depositos_vinculos
                     WHERE empresa_id = %s AND tipo_deposito = %s
                    """,
                    (cliente_id, tipo_dep_vinculo),
                )
                forma_ids = [r['forma_recebimento_id'] for r in cur.fetchall()]
            except Exception:
                forma_ids = []

        # 2) fallback: busca por nome da forma_recebimento
        if not forma_ids:
            try:
                if dep_tipo_grupo == 'CHEQUE':
                    cur.execute(
                        "SELECT id FROM formas_recebimento WHERE nome LIKE %s AND ativo = 1",
                        ('%CHEQUE%',),
                    )
                else:
                    cur.execute(
                        "SELECT id FROM formas_recebimento WHERE (nome LIKE %s OR nome LIKE %s OR nome LIKE %s) AND ativo = 1",
                        ('%DINHEIRO%', '%ESPÉCIE%', '%ESPECIE%'),
                    )
                forma_ids = [r['id'] for r in cur.fetchall()]
            except Exception:
                forma_ids = []

        # Monta filtro de forma_recebimento (se encontrado algum)
        forma_filter = ''
        forma_params = []
        if forma_ids:
            ph = ','.join(['%s'] * len(forma_ids))
            forma_filter = f'AND bt.forma_recebimento_id IN ({ph})'
            forma_params = forma_ids

        # Inclui: pendente OU conciliado-para-recebimento (ainda não vinculado como depósito)
        # Também inclui conciliado+deposito sem nenhum comprovacao vinculado
        # (transações "órfãs" que perderam o vínculo por edição do Fechamento de Caixa)
        status_filter = (
            "(bt.status = 'pendente' OR "
            "(bt.status = 'conciliado' AND "
            " (bt.tipo_conciliacao IS NULL OR "
            "  bt.tipo_conciliacao NOT IN ('deposito','transferencia','troco_pix') OR "
            "  (bt.tipo_conciliacao = 'deposito' AND "
            "   NOT EXISTS (SELECT 1 FROM lancamentos_caixa_comprovacao lcc_chk "
            "               WHERE lcc_chk.bank_transaction_id = bt.id)))))"
        )

        cur.execute(
            f"""
            SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao,
                   ba.apelido AS conta_apelido, ba.banco_nome,
                   fr.nome    AS forma_recebimento_nome
              FROM bank_transactions bt
              JOIN bank_accounts     ba ON ba.id  = bt.account_id
              LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
             WHERE bt.tipo = 'CREDIT'
               AND {status_filter}
               AND bt.data_transacao BETWEEN %s AND %s
               {forma_filter}
             ORDER BY ABS(bt.valor - %s), ABS(DATEDIFF(bt.data_transacao, %s))
             LIMIT 30
            """,
            [data_ini, data_fim] + forma_params + [valor, data_ref],
        )
        rows = cur.fetchall()
        for r in rows:
            if r.get('data_transacao'):
                r['data_transacao'] = str(r['data_transacao'])
            if r.get('valor') is not None:
                r['valor'] = float(r['valor'])
        return jsonify(rows)
    finally:
        cur.close()
        conn.close()


@bp.route('/vincular', methods=['POST'])
@login_required
@admin_required
def vincular():
    """
    Vincula um ou mais depósitos (lancamentos_caixa_comprovacao) a uma
    transação bancária CREDIT.

    POST params:
      bank_transaction_id  – ID da bank_transaction
      comprovacao_ids[]    – lista de IDs de lancamentos_caixa_comprovacao
    """
    bank_tx_id       = request.form.get('bank_transaction_id', '').strip()
    comprovacao_ids  = [x for x in request.form.getlist('comprovacao_ids[]') if x]

    if not bank_tx_id or not comprovacao_ids:
        flash('Selecione a transação bancária e pelo menos um depósito.', 'warning')
        return redirect(url_for('depositos.listar'))

    conn = get_db_connection()
    cur  = conn.cursor(dictionary=True)
    try:
        # Validate type consistency (no mixing espécie with cheque)
        placeholders = ','.join(['%s'] * len(comprovacao_ids))
        cur.execute(
            f"""
            SELECT fpc.tipo
              FROM lancamentos_caixa_comprovacao lcc
              JOIN formas_pagamento_caixa fpc ON fpc.id = lcc.forma_pagamento_id
             WHERE lcc.id IN ({placeholders})
            """,
            [int(x) for x in comprovacao_ids],
        )
        tipos = {_TIPO_GRUPO.get(r['tipo'], 'ESPECIE') for r in cur.fetchall()}
        if len(tipos) > 1:
            flash('Não é possível juntar depósitos em espécie com depósitos em cheque.', 'danger')
            return redirect(url_for('depositos.listar'))

        agora   = datetime.now()
        usuario = current_user.email if hasattr(current_user, 'email') else str(current_user.id)

        # Link all selected comprovacos to the bank transaction
        cur.execute(
            f"""
            UPDATE lancamentos_caixa_comprovacao
               SET bank_transaction_id = %s
             WHERE id IN ({placeholders})
            """,
            [int(bank_tx_id)] + [int(x) for x in comprovacao_ids],
        )

        # Mark bank transaction as conciliado
        try:
            cur.execute(
                """UPDATE bank_transactions
                      SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                          tipo_conciliacao='deposito'
                    WHERE id=%s""",
                (agora, usuario, int(bank_tx_id)),
            )
        except Exception:
            conn.rollback()
            cur.execute(
                """UPDATE bank_transactions
                      SET status='conciliado', conciliado_em=%s, conciliado_por=%s
                    WHERE id=%s""",
                (agora, usuario, int(bank_tx_id)),
            )

        conn.commit()
        flash('Depósito(s) vinculado(s) com sucesso!', 'success')
    except Exception as exc:
        conn.rollback()
        flash(f'Erro ao vincular: {exc}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('depositos.listar'))


@bp.route('/desvincular/<int:comprovacao_id>', methods=['POST'])
@login_required
@admin_required
def desvincular(comprovacao_id):
    """
    Remove o vínculo entre um depósito e a transação bancária.
    Se nenhum outro depósito estiver vinculado à mesma bank_transaction,
    a transação volta ao status 'pendente'.
    """
    conn = get_db_connection()
    cur  = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT bank_transaction_id FROM lancamentos_caixa_comprovacao WHERE id=%s",
            (comprovacao_id,),
        )
        row = cur.fetchone()
        if not row or not row.get('bank_transaction_id'):
            flash('Nenhum vínculo bancário encontrado.', 'warning')
            return redirect(url_for('depositos.listar'))

        bank_tx_id = row['bank_transaction_id']

        # Unlink this deposit
        cur.execute(
            "UPDATE lancamentos_caixa_comprovacao SET bank_transaction_id=NULL WHERE id=%s",
            (comprovacao_id,),
        )

        # Check if any other deposits still reference this bank_transaction
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM lancamentos_caixa_comprovacao WHERE bank_transaction_id=%s",
            (bank_tx_id,),
        )
        remaining = (cur.fetchone() or {}).get('cnt', 0)

        if not remaining:
            # No more deposits linked — revert bank_transaction to pendente
            try:
                cur.execute(
                    """UPDATE bank_transactions
                          SET status='pendente', conciliado_em=NULL, conciliado_por=NULL,
                              tipo_conciliacao=NULL
                        WHERE id=%s""",
                    (bank_tx_id,),
                )
            except Exception:
                conn.rollback()
                cur.execute(
                    """UPDATE bank_transactions
                          SET status='pendente', conciliado_em=NULL, conciliado_por=NULL
                        WHERE id=%s""",
                    (bank_tx_id,),
                )

        conn.commit()
        flash('Vínculo removido com sucesso!', 'success')
    except Exception as exc:
        conn.rollback()
        flash(f'Erro ao desvincular: {exc}', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('depositos.listar'))


# ──────────────────────────────────────────────────────────────────────────────
# Extrato bancário – transações OFX CREDIT com status de vinculação
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_extrato_bancario(conn, data_inicio, data_fim, conta_ids=None):
    """
    Retorna transações bancárias de CRÉDITO importadas via OFX no período.
    Indica para cada transação se já está vinculada a algum depósito do caixa,
    e o total de depósitos vinculados.
    """
    where = ["bt.tipo = 'CREDIT'",
             "bt.data_transacao BETWEEN %s AND %s"]
    params = [data_inicio, data_fim]

    if conta_ids:
        ph = ','.join(['%s'] * len(conta_ids))
        where.append(f"bt.account_id IN ({ph})")
        params.extend(int(x) for x in conta_ids)

    sql = f"""
        SELECT
            bt.id,
            bt.data_transacao,
            bt.valor,
            bt.descricao,
            bt.status,
            bt.tipo_conciliacao,
            ba.apelido                AS conta_apelido,
            ba.banco_nome,
            fr.nome                   AS forma_recebimento_nome,
            (SELECT COUNT(*)
               FROM lancamentos_caixa_comprovacao lcc2
              WHERE lcc2.bank_transaction_id = bt.id) AS qtd_depositos_vinculados,
            (SELECT COALESCE(SUM(lcc2.valor), 0)
               FROM lancamentos_caixa_comprovacao lcc2
              WHERE lcc2.bank_transaction_id = bt.id) AS total_depositos_vinculados
        FROM bank_transactions bt
        JOIN bank_accounts     ba ON ba.id  = bt.account_id
        LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
        WHERE {' AND '.join(where)}
        ORDER BY bt.data_transacao DESC, bt.id DESC
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    finally:
        cur.close()

    for r in rows:
        if r.get('valor') is not None:
            r['valor'] = float(r['valor'])
        if r.get('total_depositos_vinculados') is not None:
            r['total_depositos_vinculados'] = float(r['total_depositos_vinculados'])
        if r.get('data_transacao') and not isinstance(r['data_transacao'], str):
            r['data_transacao'] = (
                r['data_transacao'].isoformat()
                if hasattr(r['data_transacao'], 'isoformat')
                else str(r['data_transacao'])
            )
        r['data_transacao_br'] = _fmt_br(r.get('data_transacao'))
        r['vinculado'] = r.get('qtd_depositos_vinculados', 0) > 0
    return rows


def _get_contas_bancarias(conn):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, COALESCE(apelido, banco_nome) AS nome FROM bank_accounts ORDER BY nome"
        )
        return cur.fetchall()
    except Exception:
        return []
    finally:
        cur.close()


@bp.route('/extrato')
@login_required
@admin_required
def extrato():
    """
    Extrato bancário: mostra as transações CREDIT importadas via OFX no período,
    indicando quais já estão vinculadas a depósitos do Fechamento de Caixa e
    quais ainda estão sem destinação — permitindo ao usuário identificar e
    conciliar transações pendentes.
    """
    args = request.args

    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    conta_ids = [c for c in args.getlist('conta_ids[]') if c]

    conn = get_db_connection()
    try:
        contas     = _get_contas_bancarias(conn)
        transacoes = _fetch_extrato_bancario(conn, data_inicio, data_fim, conta_ids=conta_ids)
    finally:
        conn.close()

    total_vinculado     = sum(t['valor'] for t in transacoes if t['vinculado'])
    total_nao_vinculado = sum(t['valor'] for t in transacoes if not t['vinculado'])
    total_geral         = sum(t['valor'] for t in transacoes)
    qtd_vinculado       = sum(1 for t in transacoes if t['vinculado'])
    qtd_nao_vinculado   = sum(1 for t in transacoes if not t['vinculado'])

    return render_template(
        'depositos/extrato.html',
        transacoes=transacoes,
        contas=contas,
        data_inicio=data_inicio,
        data_fim=data_fim,
        conta_ids=conta_ids,
        total_vinculado=total_vinculado,
        total_nao_vinculado=total_nao_vinculado,
        total_geral=total_geral,
        qtd_vinculado=qtd_vinculado,
        qtd_nao_vinculado=qtd_nao_vinculado,
    )
