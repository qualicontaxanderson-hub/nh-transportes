"""
Relatório de Conferência de Depósitos.

Cruza depósitos do Fechamento de Caixa (lancamentos_caixa_comprovacao com
tipo DEPOSITO_ESPECIE / DEPOSITO_CHEQUE_VISTA / DEPOSITO_CHEQUE_PRAZO) com
os créditos bancários importados via OFX (bank_transactions CREDIT), usando
a tabela conf_depositos_vinculos para saber qual forma_recebimento de depósito
(ex: "Depósito em Dinheiro", "Depósito em Cheque") corresponde a cada empresa
do fechamento de caixa.

Esse padrão é idêntico ao conf_cartoes:
  conf_cartoes  → bandeira_cartao_id  (caixa)  ↔  forma_recebimento_id (banco)
  conf_depositos→ empresa_id          (caixa)  ↔  forma_recebimento_id (banco)

Uma empresa pode ter N formas vinculadas (ex: dinheiro + cheque = 2 formas).

Colunas do relatório:
  Data Venda | Valor | Data Depósito | Número Depósito | Conta Corrente | Saldo

O Saldo é acumulado: banco – caixa (idêntico à matemática do conf_cartões).

Rotas:
  GET  /relatorios/conf_depositos            – relatório
  POST /relatorios/conf_depositos/vincular   – salva vínculo empresa → forma
  POST /relatorios/conf_depositos/desvincular– remove vínculo
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
# DB setup / migration
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_vinculos_table(conn):
    """
    Cria conf_depositos_vinculos (empresa_id × forma_recebimento_id).
    Se a tabela já existir com o esquema antigo (bank_account_id), dropa e
    recria — os vínculos antigos eram inválidos de qualquer forma.
    """
    cur = conn.cursor()
    # Cria com esquema correto (se já existir nada acontece por enquanto)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS conf_depositos_vinculos (
            id                   INT AUTO_INCREMENT PRIMARY KEY,
            empresa_id           INT NOT NULL,
            forma_recebimento_id INT NOT NULL,
            criado_em            DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_dep_empresa_forma (empresa_id, forma_recebimento_id)
        )
        """
    )
    conn.commit()
    # Migração: se a tabela tem coluna bank_account_id (esquema v1), dropar e recriar.
    try:
        cur.execute("SELECT bank_account_id FROM conf_depositos_vinculos LIMIT 0")
        # Chegou aqui → coluna antiga existe → recriar
        cur.execute("DROP TABLE conf_depositos_vinculos")
        conn.commit()
        cur.execute(
            """
            CREATE TABLE conf_depositos_vinculos (
                id                   INT AUTO_INCREMENT PRIMARY KEY,
                empresa_id           INT NOT NULL,
                forma_recebimento_id INT NOT NULL,
                criado_em            DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_dep_empresa_forma (empresa_id, forma_recebimento_id)
            )
            """
        )
        conn.commit()
    except Exception:
        pass  # Coluna não existe → esquema já correto
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


def _get_deposit_formas(conn):
    """
    Formas de recebimento NÃO-cartão ativas — são os candidatos a vínculos de
    depósito (ex: Depósito em Dinheiro, Depósito em Cheque, Recebimento Pix…).
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id, nome
              FROM formas_recebimento
             WHERE eh_cartao = 0 AND ativo = 1
             ORDER BY nome
            """
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _get_vinculos_list(conn):
    """Retorna todos os vínculos empresa → forma com nomes."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT v.id,
                   v.empresa_id,
                   v.forma_recebimento_id,
                   fr.nome                                           AS forma_nome,
                   COALESCE(c.nome_fantasia, c.razao_social)        AS empresa_nome
              FROM conf_depositos_vinculos v
              JOIN formas_recebimento fr ON fr.id = v.forma_recebimento_id
              JOIN clientes c            ON c.id  = v.empresa_id
             ORDER BY empresa_nome, forma_nome
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
    Inclui DEPOSITO_ESPECIE + DEPOSITO_CHEQUE_VISTA + DEPOSITO_CHEQUE_PRAZO.
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
          JOIN lancamentos_caixa lc      ON lc.id  = lcc.lancamento_caixa_id
          JOIN formas_pagamento_caixa fp ON fp.id  = lcc.forma_pagamento_id
         WHERE fp.tipo IN ('DEPOSITO_ESPECIE','DEPOSITO_CHEQUE_VISTA','DEPOSITO_CHEQUE_PRAZO')
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


def _fetch_bank_deposits(conn, data_inicio, data_fim, forma_ids):
    """
    Créditos bancários individuais onde forma_recebimento_id é um dos
    IDs vinculados (ex: "Depósito em Dinheiro" ou "Depósito em Cheque").
    Retorna uma linha por transação para mostrar Número Depósito e Conta Corrente.
    """
    if not forma_ids:
        return []
    cur = conn.cursor(dictionary=True)
    ph = ','.join(['%s'] * len(forma_ids))
    try:
        cur.execute(
            f"""
            SELECT bt.id,
                   bt.data_transacao,
                   bt.valor,
                   bt.descricao,
                   bt.forma_recebimento_id,
                   COALESCE(ba.apelido, ba.banco_nome) AS conta_nome,
                   ba.cliente_id                       AS banco_empresa_id
              FROM bank_transactions bt
              JOIN bank_accounts ba ON ba.id = bt.account_id
             WHERE bt.tipo = 'CREDIT'
               AND bt.data_transacao BETWEEN %s AND %s
               AND bt.forma_recebimento_id IN ({ph})
             ORDER BY bt.data_transacao, bt.id
            """,
            [data_inicio, data_fim] + list(forma_ids),
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
    com saldo acumulado (banco − caixa), idêntico ao conf_cartoes.

    vinculos_list: lista de {empresa_id, forma_recebimento_id, empresa_nome, forma_nome}

    Estrutura de cada linha:
      tipo           : 'caixa' | 'banco'
      data_venda     : DD/MM/YYYY  (linha caixa)
      dia_semana     : str
      valor          : float
      data_deposito  : DD/MM/YYYY  (linha banco)
      num_deposito   : str         (descricao da transação)
      conta_corrente : str         (apelido/banco_nome da conta bancária)
      saldo          : float acumulado
      saldo_pos/neg  : bool
    """
    # ── índice caixa: (empresa_id, 'YYYY-MM-DD') → total
    caixa_idx = {}
    for r in caixa_rows:
        d = r['data_venda']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        caixa_idx[(int(r['empresa_id']), str(d))] = float(r['total_caixa'] or 0)

    # ── índice banco: forma_recebimento_id → lista de transações
    bank_by_forma = defaultdict(list)
    for r in bank_rows:
        d = r['data_transacao']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        bank_by_forma[int(r['forma_recebimento_id'])].append({
            'data':       str(d),
            'valor':      float(r['valor'] or 0),
            'descricao':  r.get('descricao') or '',
            'conta_nome': r.get('conta_nome') or '',
        })

    # ── agrupar vínculos por empresa
    vinculos_by_empresa = defaultdict(list)
    for v in vinculos_list:
        vinculos_by_empresa[int(v['empresa_id'])].append(v)

    sections = []

    for empresa_id, vincs in vinculos_by_empresa.items():
        empresa_nome = vincs[0]['empresa_nome']
        forma_ids    = [int(v['forma_recebimento_id']) for v in vincs]
        forma_nomes  = [v['forma_nome'] for v in vincs]

        # Datas com atividade no caixa para esta empresa
        all_dates = set()
        for (eid, d) in caixa_idx:
            if eid == empresa_id:
                all_dates.add(d)

        # Datas com atividade nas formas vinculadas
        for fid in forma_ids:
            for tx in bank_by_forma.get(fid, []):
                all_dates.add(tx['data'])

        if not all_dates:
            sections.append({
                'empresa_id':   empresa_id,
                'empresa_nome': empresa_nome,
                'formas':       forma_nomes,
                'linhas':       [],
                'total_caixa':  0.0,
                'total_banco':  0.0,
                'saldo_final':  0.0,
            })
            continue

        all_dates   = sorted(all_dates)
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
                d_obj       = _parse_iso(d)
                dia_semana  = _DIAS_PT[d_obj.weekday()] if d_obj else ''
                linhas.append({
                    'tipo':           'caixa',
                    'data_venda':     _fmt_date(d),
                    'dia_semana':     dia_semana,
                    'valor':          caixa_val,
                    'data_deposito':  '',
                    'num_deposito':   '',
                    'conta_corrente': '',
                    'saldo':          saldo,
                    'saldo_pos':      saldo > 0.005,
                    'saldo_neg':      saldo < -0.005,
                })

            # ── linhas BANCO (somam ao saldo), uma por transação
            for fid in forma_ids:
                for tx in bank_by_forma.get(fid, []):
                    if tx['data'] == d:
                        saldo       += tx['valor']
                        total_banco += tx['valor']
                        linhas.append({
                            'tipo':           'banco',
                            'data_venda':     '',
                            'dia_semana':     '',
                            'valor':          tx['valor'],
                            'data_deposito':  _fmt_date(tx['data']),
                            'num_deposito':   tx['descricao'],
                            'conta_corrente': tx['conta_nome'],
                            'saldo':          saldo,
                            'saldo_pos':      saldo > 0.005,
                            'saldo_neg':      saldo < -0.005,
                        })

        sections.append({
            'empresa_id':   empresa_id,
            'empresa_nome': empresa_nome,
            'formas':       forma_nomes,
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

        empresas       = _get_empresas_caixa(conn)
        deposit_formas = _get_deposit_formas(conn)
        vinculos_list  = _get_vinculos_list(conn)

        # Empresas com pelo menos um vínculo
        linked_empresa_ids = list({int(v['empresa_id']) for v in vinculos_list})

        # Se filtro de empresa aplicado, restringe; senão usa todas as vinculadas
        active_empresa_ids = (
            [int(e) for e in empresa_ids if int(e) in linked_empresa_ids]
            if empresa_ids
            else linked_empresa_ids
        )

        vinculos_filtered = [
            v for v in vinculos_list
            if int(v['empresa_id']) in (active_empresa_ids or linked_empresa_ids)
        ]

        # Formas vinculadas às empresas ativas
        linked_forma_ids = list({
            int(v['forma_recebimento_id'])
            for v in vinculos_filtered
        })

        caixa_rows = _fetch_caixa_deposits(
            conn, data_inicio, data_fim,
            active_empresa_ids or linked_empresa_ids or [0],
        )
        bank_rows = _fetch_bank_deposits(
            conn, data_inicio, data_fim,
            linked_forma_ids or [0],
        )

        sections = _build_report(vinculos_filtered, caixa_rows, bank_rows)

    finally:
        conn.close()

    return render_template(
        'relatorios/conf_depositos.html',
        sections=sections,
        empresas=empresas,
        deposit_formas=deposit_formas,
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
    empresa_id           = data.get('empresa_id')
    forma_recebimento_id = data.get('forma_recebimento_id')
    if not empresa_id or not forma_recebimento_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT IGNORE INTO conf_depositos_vinculos (empresa_id, forma_recebimento_id)
            VALUES (%s, %s)
            """,
            (int(empresa_id), int(forma_recebimento_id)),
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
    empresa_id           = data.get('empresa_id')
    forma_recebimento_id = data.get('forma_recebimento_id')
    if not empresa_id or not forma_recebimento_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM conf_depositos_vinculos
             WHERE empresa_id = %s AND forma_recebimento_id = %s
            """,
            (int(empresa_id), int(forma_recebimento_id)),
        )
        conn.commit()
        cur.close()
    except Exception:
        pass
    finally:
        conn.close()
    return jsonify({'success': True})
