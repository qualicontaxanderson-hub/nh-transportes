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
    Cria conf_depositos_vinculos (empresa_id × forma_recebimento_id × tipo_deposito).
    Se a tabela já existir com o esquema antigo (bank_account_id), dropa e
    recria — os vínculos antigos eram inválidos de qualquer forma.
    Se a tabela existir mas sem a coluna tipo_deposito, adiciona via ALTER TABLE.

    Usa INFORMATION_SCHEMA.COLUMNS para detectar o schema antigo sem disparar
    um ProgrammingError de "coluna desconhecida" que poderia corromper o estado
    do cursor/conexão no mysql.connector.
    """
    _NEW_DDL = """
        CREATE TABLE IF NOT EXISTS conf_depositos_vinculos (
            id                   INT AUTO_INCREMENT PRIMARY KEY,
            empresa_id           INT NOT NULL,
            forma_recebimento_id INT NOT NULL,
            tipo_deposito        ENUM('DINHEIRO','CHEQUE') NOT NULL DEFAULT 'DINHEIRO',
            criado_em            DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_dep_empresa_forma (empresa_id, forma_recebimento_id)
        )
    """
    try:
        cur = conn.cursor()
        # 1. Garante que a tabela exista (com o esquema correto se for nova)
        cur.execute(_NEW_DDL)
        conn.commit()

        # 2. Verifica via INFORMATION_SCHEMA se ainda existe a coluna antiga
        #    (nunca falha por "Unknown column"; apenas retorna 0 ou 1)
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
              FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = 'conf_depositos_vinculos'
               AND COLUMN_NAME  = 'bank_account_id'
            """
        )
        row = cur.fetchone()
        has_old_col = bool(row and row[0])

        if has_old_col:
            # 3. Esquema v1 detectado: a coluna bank_account_id nunca foi usada em
            #    produção de forma válida, portanto é seguro dropar e recriar a tabela
            #    (ALTER TABLE também funcionaria, mas a tabela estava vazia na prática).
            cur.execute("DROP TABLE conf_depositos_vinculos")
            conn.commit()
            cur.execute(_NEW_DDL.replace("IF NOT EXISTS ", ""))
            conn.commit()
        else:
            # 4. Verifica se a coluna tipo_deposito já existe; se não, adiciona
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                  FROM INFORMATION_SCHEMA.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE()
                   AND TABLE_NAME   = 'conf_depositos_vinculos'
                   AND COLUMN_NAME  = 'tipo_deposito'
                """
            )
            row2 = cur.fetchone()
            if not (row2 and row2[0]):
                cur.execute(
                    """ALTER TABLE conf_depositos_vinculos
                       ADD COLUMN tipo_deposito ENUM('DINHEIRO','CHEQUE') NOT NULL DEFAULT 'DINHEIRO'"""
                )
                conn.commit()

        cur.close()
    except Exception:
        pass  # Não crítico — a tabela pode já estar correta


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
        rows = cur.fetchall()
    except Exception:
        rows = []
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
                   COALESCE(v.tipo_deposito, 'DINHEIRO')              AS tipo_deposito,
                   fr.nome                                           AS forma_nome,
                   COALESCE(c.nome_fantasia, c.razao_social)        AS empresa_nome
              FROM conf_depositos_vinculos v
              JOIN formas_recebimento fr ON fr.id = v.forma_recebimento_id
              JOIN clientes c            ON c.id  = v.empresa_id
             ORDER BY empresa_nome, tipo_deposito, forma_nome
            """
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _fetch_caixa_deposits(conn, data_inicio, data_fim, empresa_ids):
    """
    Soma depósitos do caixa por (empresa_id, data, tipo_deposito).
    DEPOSITO_ESPECIE         → tipo_deposito = 'DINHEIRO'
    DEPOSITO_CHEQUE_VISTA    → tipo_deposito = 'CHEQUE'
    DEPOSITO_CHEQUE_PRAZO    → tipo_deposito = 'CHEQUE'
    """
    if not empresa_ids:
        return []
    cur = conn.cursor(dictionary=True)
    ph = ','.join(['%s'] * len(empresa_ids))
    try:
        cur.execute(
            f"""
            SELECT lc.data         AS data_venda,
                   lc.cliente_id   AS empresa_id,
                   CASE fp.tipo
                     WHEN 'DEPOSITO_ESPECIE' THEN 'DINHEIRO'
                     ELSE 'CHEQUE'
                   END             AS tipo_deposito,
                   SUM(lcc.valor)  AS total_caixa
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa lc      ON lc.id  = lcc.lancamento_caixa_id
              JOIN formas_pagamento_caixa fp ON fp.id  = lcc.forma_pagamento_id
             WHERE fp.tipo IN ('DEPOSITO_ESPECIE','DEPOSITO_CHEQUE_VISTA','DEPOSITO_CHEQUE_PRAZO')
               AND lc.data BETWEEN %s AND %s
               AND lcc.valor > 0
               AND lc.cliente_id IN ({ph})
             GROUP BY lc.data, lc.cliente_id, tipo_deposito
             ORDER BY lc.data
            """,
            [data_inicio, data_fim] + list(empresa_ids),
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _get_contas_bancarias(conn, forma_ids):
    """
    Contas bancárias (bank_accounts) que têm créditos OFX classificados
    com uma das formas de depósito vinculadas. Usado para popular o filtro de conta.
    """
    if not forma_ids:
        return []
    cur = conn.cursor(dictionary=True)
    ph = ','.join(['%s'] * len(forma_ids))
    try:
        cur.execute(
            f"""
            SELECT DISTINCT ba.id,
                   COALESCE(ba.apelido, ba.banco_nome) AS nome
              FROM bank_accounts ba
              JOIN bank_transactions bt ON bt.account_id = ba.id
             WHERE bt.tipo = 'CREDIT'
               AND bt.forma_recebimento_id IN ({ph})
             ORDER BY nome
            """,
            list(forma_ids),
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _fetch_bank_deposits(conn, data_inicio, data_fim, forma_ids):
    """
    Créditos bancários individuais onde forma_recebimento_id é um dos
    IDs vinculados (ex: "Depósito em Dinheiro" ou "Depósito em Cheque").
    Retorna uma linha por transação incluindo account_id para filtro de conta.
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
                   bt.account_id,
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


def _build_report(vinculos_list, caixa_rows, bank_rows, conta_ids=None):
    """
    Para cada empresa com vínculo produz seções por tipo_deposito (DINHEIRO / CHEQUE).
    Cada linha pode ser do tipo 'caixa' (valor lançado no fechamento) ou 'banco'
    (crédito OFX individual), com saldo acumulado corrente.

    conta_ids: set/list de account_id para filtrar créditos bancários (None = todos).

    Estrutura de cada linha:
      tipo_row      : 'caixa' | 'banco'
      data          : DD/MM/YYYY
      dia_semana    : str  (preenchido apenas em linhas caixa)
      val_sistema   : float  (> 0 em linhas caixa)
      conta         : str    (preenchido em linhas banco)
      val_deposito  : float  (> 0 em linhas banco)
      saldo         : float acumulado (banco − caixa)
      saldo_pos/neg : bool
    """
    conta_ids_set = set(int(c) for c in conta_ids) if conta_ids else None

    # ── índice caixa: (empresa_id, tipo_deposito, 'YYYY-MM-DD') → total
    caixa_idx = {}
    for r in caixa_rows:
        d = r['data_venda']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        tipo = r.get('tipo_deposito', 'DINHEIRO')
        caixa_idx[(int(r['empresa_id']), tipo, str(d))] = float(r['total_caixa'] or 0)

    # ── índice banco: forma_recebimento_id → date → list of transactions
    bank_by_forma = defaultdict(lambda: defaultdict(list))
    for r in bank_rows:
        # Apply conta filter if set
        if conta_ids_set and int(r.get('account_id') or 0) not in conta_ids_set:
            continue
        d = r['data_transacao']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        bank_by_forma[int(r['forma_recebimento_id'])][str(d)].append({
            'valor':      float(r['valor'] or 0),
            'conta_nome': r.get('conta_nome') or '',
            'account_id': r.get('account_id'),
        })

    # ── agrupar vínculos por (empresa_id, tipo_deposito)
    vinculos_by_empresa_tipo = defaultdict(list)
    for v in vinculos_list:
        key = (int(v['empresa_id']), v.get('tipo_deposito', 'DINHEIRO'))
        vinculos_by_empresa_tipo[key].append(v)

    # ── agrupar por empresa para construir as seções
    empresas_vistas = {}
    for (empresa_id, tipo), vincs in vinculos_by_empresa_tipo.items():
        if empresa_id not in empresas_vistas:
            empresas_vistas[empresa_id] = vincs[0]['empresa_nome']

    sections = []

    for empresa_id, empresa_nome in sorted(empresas_vistas.items(), key=lambda x: x[1]):
        sub_sections = []
        empresa_total_caixa = 0.0
        empresa_total_banco = 0.0

        for tipo in ('DINHEIRO', 'CHEQUE'):
            vincs = vinculos_by_empresa_tipo.get((empresa_id, tipo), [])

            forma_ids   = [int(v['forma_recebimento_id']) for v in vincs]
            forma_nomes = [v['forma_nome'] for v in vincs]

            # Datas com atividade no caixa para este empresa+tipo
            all_dates = set()
            for (eid, tp, d) in caixa_idx:
                if eid == empresa_id and tp == tipo:
                    all_dates.add(d)
            # Datas com atividade nas formas bancárias vinculadas
            for fid in forma_ids:
                for d in bank_by_forma.get(fid, {}):
                    all_dates.add(d)

            if not all_dates:
                sub_sections.append({
                    'tipo':        tipo,
                    'tipo_label':  'Dinheiro' if tipo == 'DINHEIRO' else 'Cheque',
                    'formas':      forma_nomes,
                    'linhas':      [],
                    'total_caixa': 0.0,
                    'total_banco': 0.0,
                    'saldo_final': 0.0,
                })
                continue

            all_dates   = sorted(all_dates)
            saldo       = 0.0
            total_caixa = 0.0
            total_banco = 0.0
            linhas      = []

            for d in all_dates:
                d_obj      = _parse_iso(d)
                dia_semana = _DIAS_PT[d_obj.weekday()] if d_obj else ''

                # ── linha CAIXA (subtrai do saldo)
                val_sistema = caixa_idx.get((empresa_id, tipo, d), 0.0)
                if val_sistema:
                    saldo       -= val_sistema
                    total_caixa += val_sistema
                    linhas.append({
                        'tipo_row':    'caixa',
                        'data':        _fmt_date(d),
                        'dia_semana':  dia_semana,
                        'val_sistema': val_sistema,
                        'conta':       '',
                        'val_deposito': 0.0,
                        'saldo':       saldo,
                        'saldo_pos':   saldo > 0.005,
                        'saldo_neg':   saldo < -0.005,
                    })

                # ── linhas BANCO (somam ao saldo), uma por transação
                for fid in forma_ids:
                    for tx in bank_by_forma.get(fid, {}).get(d, []):
                        saldo       += tx['valor']
                        total_banco += tx['valor']
                        linhas.append({
                            'tipo_row':    'banco',
                            'data':        _fmt_date(d),
                            'dia_semana':  '',
                            'val_sistema': 0.0,
                            'conta':       tx['conta_nome'],
                            'val_deposito': tx['valor'],
                            'saldo':       saldo,
                            'saldo_pos':   saldo > 0.005,
                            'saldo_neg':   saldo < -0.005,
                        })

            empresa_total_caixa += total_caixa
            empresa_total_banco += total_banco

            sub_sections.append({
                'tipo':        tipo,
                'tipo_label':  'Dinheiro' if tipo == 'DINHEIRO' else 'Cheque',
                'formas':      forma_nomes,
                'linhas':      linhas,
                'total_caixa': total_caixa,
                'total_banco': total_banco,
                'saldo_final': saldo if linhas else 0.0,
            })

        if sub_sections:
            sections.append({
                'empresa_id':   empresa_id,
                'empresa_nome': empresa_nome,
                'sub_sections': sub_sections,
                'total_caixa':  empresa_total_caixa,
                'total_banco':  empresa_total_banco,
                'saldo_final':  empresa_total_banco - empresa_total_caixa,
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
    conta_ids   = [c for c in args.getlist('conta_ids[]')   if c]

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

        # Contas bancárias disponíveis para filtro (baseado nas formas vinculadas)
        contas_bancarias = _get_contas_bancarias(conn, linked_forma_ids or [0])

        caixa_rows = _fetch_caixa_deposits(
            conn, data_inicio, data_fim,
            active_empresa_ids or linked_empresa_ids or [0],
        )
        bank_rows = _fetch_bank_deposits(
            conn, data_inicio, data_fim,
            linked_forma_ids or [0],
        )

        sections = _build_report(
            vinculos_filtered, caixa_rows, bank_rows,
            conta_ids=conta_ids or None,
        )

    finally:
        conn.close()

    return render_template(
        'relatorios/conf_depositos.html',
        sections=sections,
        empresas=empresas,
        deposit_formas=deposit_formas,
        vinculos_list=vinculos_list,
        contas_bancarias=contas_bancarias,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        conta_ids=conta_ids,
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
    tipo_deposito        = data.get('tipo_deposito', 'DINHEIRO')
    if tipo_deposito not in ('DINHEIRO', 'CHEQUE'):
        tipo_deposito = 'DINHEIRO'
    if not empresa_id or not forma_recebimento_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO conf_depositos_vinculos (empresa_id, forma_recebimento_id, tipo_deposito)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE tipo_deposito = VALUES(tipo_deposito)
            """,
            (int(empresa_id), int(forma_recebimento_id), tipo_deposito),
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
