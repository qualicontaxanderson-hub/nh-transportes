"""
Relatório de Conferência de Depósitos.

Cruza depósitos do Fechamento de Caixa (lancamentos_caixa_comprovacao com
tipo DEPOSITO_ESPECIE / DEPOSITO_CHEQUE_VISTA / DEPOSITO_CHEQUE_PRAZO) com
os créditos bancários importados via OFX (bank_transactions CREDIT), usando
a tabela conf_depositos_vinculos para saber qual empresa corresponde a qual
conta corrente bancária.

Colunas do relatório:
  Data Venda | Valor | Data Depósito | Número Depósito | Conta Corrente | Saldo

O Saldo é acumulado: banco – caixa (igual à matemática do conf_cartões).

Rotas:
  GET  /relatorios/conf_depositos          – relatório
  POST /relatorios/conf_depositos/vincular    – salva vínculo empresa → conta
  POST /relatorios/conf_depositos/desvincular – remove vínculo
"""
from datetime import date, datetime
from collections import defaultdict

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_depositos', __name__, url_prefix='/relatorios')

_DIAS_PT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']


# ──────────────────────────────────────────────────────────────────────────────
# Helpers – DB setup
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_vinculos_table(conn):
    """Cria conf_depositos_vinculos se ainda não existir."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS conf_depositos_vinculos (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            empresa_id      INT NOT NULL,
            bank_account_id INT NOT NULL,
            criado_em       DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_dep_empresa_conta (empresa_id, bank_account_id)
        )
        """
    )
    conn.commit()
    cur.close()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers – data
# ──────────────────────────────────────────────────────────────────────────────

def _default_period():
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _parse_iso(d):
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(str(d), '%Y-%m-%d').date()
    except Exception:
        return None


def _fmt_date(d):
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


def _get_empresas_caixa(conn):
    """Empresas que possuem fechamentos de caixa."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT DISTINCT c.id,
               COALESCE(c.nome_fantasia, c.razao_social) AS nome
          FROM clientes c
          INNER JOIN lancamentos_caixa lc ON lc.cliente_id = c.id
         ORDER BY nome
        """
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _get_bank_accounts(conn):
    """Todas as contas bancárias ativas."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT ba.id,
               COALESCE(ba.apelido, ba.banco_nome) AS conta_nome,
               ba.apelido, ba.banco_nome,
               ba.cliente_id,
               COALESCE(c.nome_fantasia, c.razao_social) AS empresa_nome
          FROM bank_accounts ba
          LEFT JOIN clientes c ON c.id = ba.cliente_id
         WHERE ba.ativo = 1
         ORDER BY empresa_nome, conta_nome
        """
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _get_vinculos_list(conn):
    """Retorna todos os vínculos empresa → conta com nomes."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT v.id, v.empresa_id, v.bank_account_id,
                   COALESCE(ba.apelido, ba.banco_nome) AS conta_nome,
                   ba.apelido, ba.banco_nome,
                   COALESCE(c.nome_fantasia, c.razao_social) AS empresa_nome
              FROM conf_depositos_vinculos v
              JOIN bank_accounts ba ON ba.id = v.bank_account_id
              JOIN clientes c ON c.id = v.empresa_id
             ORDER BY empresa_nome, conta_nome
            """
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _fetch_caixa_deposits(conn, data_inicio, data_fim, empresa_ids):
    """
    Soma depósitos do caixa por (empresa_id, data).
    Agrupa DEPOSITO_ESPECIE + DEPOSITO_CHEQUE_VISTA + DEPOSITO_CHEQUE_PRAZO.
    """
    if not empresa_ids:
        return []
    cur = conn.cursor(dictionary=True)
    ph = ','.join(['%s'] * len(empresa_ids))
    cur.execute(
        f"""
        SELECT lc.data         AS data_venda,
               lc.cliente_id   AS empresa_id,
               SUM(lcc.valor)  AS total_caixa
          FROM lancamentos_caixa_comprovacao lcc
          JOIN lancamentos_caixa lc    ON lc.id  = lcc.lancamento_caixa_id
          JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
         WHERE fp.tipo IN ('DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
           AND lc.data BETWEEN %s AND %s
           AND lcc.valor > 0
           AND lc.cliente_id IN ({ph})
         GROUP BY lc.data, lc.cliente_id
         ORDER BY lc.data
        """,
        [data_inicio, data_fim] + list(empresa_ids),
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetch_bank_deposits(conn, data_inicio, data_fim, account_ids):
    """
    Créditos bancários individuais para as contas vinculadas.
    Retorna uma linha por transação (para mostrar Número Depósito).
    """
    if not account_ids:
        return []
    cur = conn.cursor(dictionary=True)
    ph = ','.join(['%s'] * len(account_ids))
    try:
        cur.execute(
            f"""
            SELECT bt.id,
                   bt.data_transacao,
                   bt.valor,
                   bt.descricao,
                   bt.account_id,
                   COALESCE(ba.apelido, ba.banco_nome) AS conta_nome
              FROM bank_transactions bt
              JOIN bank_accounts ba ON ba.id = bt.account_id
             WHERE bt.tipo = 'CREDIT'
               AND bt.data_transacao BETWEEN %s AND %s
               AND bt.account_id IN ({ph})
             ORDER BY bt.data_transacao, bt.id
            """,
            [data_inicio, data_fim] + list(account_ids),
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _build_report(vinculos_list, caixa_rows, bank_rows):
    """
    Para cada empresa com vínculo produz uma lista de linhas cronológicas
    mostrando depósitos do caixa e créditos bancários intercalados,
    com saldo acumulado (banco − caixa).

    Estrutura de cada linha:
      tipo          : 'caixa' | 'banco'
      data_venda    : DD/MM/YYYY (preenchido na linha caixa)
      valor         : float
      data_deposito : DD/MM/YYYY (preenchido na linha banco)
      num_deposito  : str        (descrição da transação bancária)
      conta_corrente: str        (apelido da conta bancária)
      saldo         : float acumulado
      saldo_pos     : bool
      saldo_neg     : bool
    """

    # ── índice caixa: (empresa_id, 'YYYY-MM-DD') → total
    caixa_idx = {}
    for r in caixa_rows:
        d = r['data_venda']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        caixa_idx[(int(r['empresa_id']), str(d))] = float(r['total_caixa'] or 0)

    # ── lista de transações banco por account_id
    bank_by_account = defaultdict(list)
    for r in bank_rows:
        d = r['data_transacao']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        bank_by_account[int(r['account_id'])].append({
            'data':         str(d),
            'valor':        float(r['valor'] or 0),
            'descricao':    r.get('descricao') or '',
            'conta_nome':   r.get('conta_nome') or '',
        })

    # ── agrupar vínculos por empresa
    vinculos_by_empresa = defaultdict(list)
    for v in vinculos_list:
        vinculos_by_empresa[int(v['empresa_id'])].append(v)

    sections = []

    for empresa_id, vincs in vinculos_by_empresa.items():
        empresa_nome = vincs[0]['empresa_nome']
        account_ids  = [int(v['bank_account_id']) for v in vincs]
        conta_nomes  = [v['conta_nome'] or v['banco_nome'] or '' for v in vincs]

        # datas com atividade no caixa para esta empresa
        all_dates = set()
        for (eid, d) in caixa_idx:
            if eid == empresa_id:
                all_dates.add(d)

        # datas com atividade no banco para as contas vinculadas
        for aid in account_ids:
            for tx in bank_by_account.get(aid, []):
                all_dates.add(tx['data'])

        if not all_dates:
            sections.append({
                'empresa_id':   empresa_id,
                'empresa_nome': empresa_nome,
                'contas':       conta_nomes,
                'linhas':       [],
                'total_caixa':  0.0,
                'total_banco':  0.0,
                'saldo_final':  0.0,
            })
            continue

        all_dates = sorted(all_dates)

        saldo       = 0.0
        total_caixa = 0.0
        total_banco = 0.0
        linhas      = []

        for d in all_dates:
            # ── linha CAIXA (subtrai do saldo)
            caixa_val = caixa_idx.get((empresa_id, d), 0.0)
            if caixa_val:
                saldo       -= caixa_val
                total_caixa += caixa_val
                d_obj = _parse_iso(d)
                dia_semana = _DIAS_PT[d_obj.weekday()] if d_obj else ''
                linhas.append({
                    'tipo':          'caixa',
                    'data_venda':    _fmt_date(d),
                    'dia_semana':    dia_semana,
                    'valor':         caixa_val,
                    'data_deposito': '',
                    'num_deposito':  '',
                    'conta_corrente': '',
                    'saldo':         saldo,
                    'saldo_pos':     saldo > 0.005,
                    'saldo_neg':     saldo < -0.005,
                })

            # ── linhas BANCO (somam ao saldo), uma por transação
            for aid in account_ids:
                for tx in bank_by_account.get(aid, []):
                    if tx['data'] == d:
                        saldo       += tx['valor']
                        total_banco += tx['valor']
                        linhas.append({
                            'tipo':          'banco',
                            'data_venda':    '',
                            'dia_semana':    '',
                            'valor':         tx['valor'],
                            'data_deposito': _fmt_date(tx['data']),
                            'num_deposito':  tx['descricao'],
                            'conta_corrente': tx['conta_nome'],
                            'saldo':         saldo,
                            'saldo_pos':     saldo > 0.005,
                            'saldo_neg':     saldo < -0.005,
                        })

        sections.append({
            'empresa_id':   empresa_id,
            'empresa_nome': empresa_nome,
            'contas':       conta_nomes,
            'linhas':       linhas,
            'total_caixa':  total_caixa,
            'total_banco':  total_banco,
            'saldo_final':  saldo,
        })

    return sections


# ──────────────────────────────────────────────────────────────────────────────
# Routes – main report
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_depositos', methods=['GET'])
@login_required
@admin_required
def conf_depositos():
    args = request.args

    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)

        empresas      = _get_empresas_caixa(conn)
        bank_accounts = _get_bank_accounts(conn)
        vinculos_list = _get_vinculos_list(conn)

        # Se filtro de empresa, restringe; caso contrário usa todas as com vínculo
        linked_empresa_ids = list({int(v['empresa_id']) for v in vinculos_list})
        active_empresa_ids = (
            [int(e) for e in empresa_ids if int(e) in linked_empresa_ids]
            if empresa_ids
            else linked_empresa_ids
        )
        linked_account_ids = list({
            int(v['bank_account_id'])
            for v in vinculos_list
            if int(v['empresa_id']) in (active_empresa_ids or linked_empresa_ids)
        })

        vinculos_filtered = [
            v for v in vinculos_list
            if int(v['empresa_id']) in (active_empresa_ids or linked_empresa_ids)
        ]

        caixa_rows = _fetch_caixa_deposits(
            conn, data_inicio, data_fim,
            active_empresa_ids or linked_empresa_ids or [0],
        )
        bank_rows = _fetch_bank_deposits(
            conn, data_inicio, data_fim,
            linked_account_ids or [0],
        )

        sections = _build_report(vinculos_filtered, caixa_rows, bank_rows)

    finally:
        conn.close()

    return render_template(
        'relatorios/conf_depositos.html',
        sections=sections,
        empresas=empresas,
        banco_accounts=bank_accounts,
        vinculos_list=vinculos_list,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes – vinculos management
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_depositos/vincular', methods=['POST'])
@login_required
@admin_required
def vincular_deposito():
    data = request.get_json(force=True) or {}
    empresa_id      = data.get('empresa_id')
    bank_account_id = data.get('bank_account_id')
    if not empresa_id or not bank_account_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT IGNORE INTO conf_depositos_vinculos (empresa_id, bank_account_id)
            VALUES (%s, %s)
            """,
            (int(empresa_id), int(bank_account_id)),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify({'success': True})


@bp.route('/conf_depositos/desvincular', methods=['POST'])
@login_required
@admin_required
def desvincular_deposito():
    data = request.get_json(force=True) or {}
    empresa_id      = data.get('empresa_id')
    bank_account_id = data.get('bank_account_id')
    if not empresa_id or not bank_account_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM conf_depositos_vinculos
             WHERE empresa_id = %s AND bank_account_id = %s
            """,
            (int(empresa_id), int(bank_account_id)),
        )
        conn.commit()
        cur.close()
    except Exception:
        pass
    finally:
        conn.close()
    return jsonify({'success': True})
