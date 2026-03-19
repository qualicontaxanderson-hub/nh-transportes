"""
Relatório de Conferência de Cartões.

Cruza vendas de cartão (lancamentos_caixa_comprovacao com bandeira_cartao_id)
com recebimentos bancários (bank_transactions CREDIT vinculados a
formas_recebimento com eh_cartao=1), usando a tabela de vinculação
conf_cartoes_vinculos para saber qual bandeira corresponde a qual
forma de recebimento. Cada bandeira pode ter até 2 formas vinculadas
(ex: regular + antecipado para cartão de crédito).

Rota:
  GET  /relatorios/conf_cartoes         – relatório
  POST /relatorios/conf_cartoes/vincular – salva vinculação
  POST /relatorios/conf_cartoes/desvincular – remove vinculação específica
"""
from datetime import date, datetime
from collections import defaultdict

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_cartoes', __name__, url_prefix='/relatorios')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _default_period():
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _ensure_vinculos_table(conn):
    """Cria a tabela de vinculações se ainda não existir e migra a chave única."""
    cur = conn.cursor()
    # Cria a tabela com a chave composta (bandeira + forma) – permite múltiplos vínculos
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS conf_cartoes_vinculos (
            id                   INT AUTO_INCREMENT PRIMARY KEY,
            bandeira_cartao_id   INT NOT NULL,
            forma_recebimento_id INT NOT NULL,
            criado_em            DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_bandeira_forma (bandeira_cartao_id, forma_recebimento_id)
        )
        """
    )
    conn.commit()
    # Migração: se a tabela foi criada com a chave antiga (uk_bandeira apenas em
    # bandeira_cartao_id), dropar e recriar com a chave composta.
    try:
        cur.execute(
            "ALTER TABLE conf_cartoes_vinculos "
            "DROP INDEX uk_bandeira"
        )
        conn.commit()
    except Exception:
        pass  # índice já não existe ou já foi migrado
    try:
        cur.execute(
            "ALTER TABLE conf_cartoes_vinculos "
            "ADD UNIQUE KEY uk_bandeira_forma (bandeira_cartao_id, forma_recebimento_id)"
        )
        conn.commit()
    except Exception:
        pass  # índice já existe
    cur.close()


def _get_empresas(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT DISTINCT c.id,
               COALESCE(c.nome_fantasia, c.razao_social) AS nome
          FROM clientes c
          INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
         ORDER BY nome
        """
    )
    rows = cur.fetchall()
    cur.close()
    return rows


def _get_bandeiras(conn):
    """Retorna todas as bandeiras de cartão ativas com a lista de vínculos (0, 1 ou 2)."""
    cur = conn.cursor(dictionary=True)
    # Busca as bandeiras
    cur.execute(
        """
        SELECT bc.id, bc.nome, bc.tipo
          FROM bandeiras_cartao bc
         WHERE bc.ativo = 1
         ORDER BY bc.tipo, bc.nome
        """
    )
    bandeiras = cur.fetchall()

    # Busca todos os vínculos existentes
    cur.execute(
        """
        SELECT v.bandeira_cartao_id, v.forma_recebimento_id, fr.nome AS forma_recebimento_nome
          FROM conf_cartoes_vinculos v
          JOIN formas_recebimento fr ON fr.id = v.forma_recebimento_id
         ORDER BY v.id
        """
    )
    vinculo_rows = cur.fetchall()
    cur.close()

    # Agrupa vínculos por bandeira
    vinculos_by_band = defaultdict(list)
    for v in vinculo_rows:
        vinculos_by_band[v['bandeira_cartao_id']].append({
            'forma_recebimento_id': v['forma_recebimento_id'],
            'forma_recebimento_nome': v['forma_recebimento_nome'],
        })

    for b in bandeiras:
        b['vinculos'] = vinculos_by_band.get(b['id'], [])
        # Compatibilidade: mantém campos simples para o primeiro vínculo
        b['forma_recebimento_id'] = b['vinculos'][0]['forma_recebimento_id'] if b['vinculos'] else None
        b['forma_recebimento_nome'] = b['vinculos'][0]['forma_recebimento_nome'] if b['vinculos'] else None

    return bandeiras


def _get_formas_recebimento_cartao(conn):
    """Retorna formas de recebimento marcadas como cartão (para o select do modal)."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id, nome, tipo_cartao
              FROM formas_recebimento
             WHERE eh_cartao = 1 AND ativo = 1
             ORDER BY nome
            """
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _fetch_vendas(conn, data_inicio, data_fim, empresa_ids):
    """Soma de vendas de cartão por (data, bandeira_cartao_id)."""
    where = ["lc.data BETWEEN %s AND %s", "lcc.bandeira_cartao_id IS NOT NULL"]
    params = [data_inicio, data_fim]

    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        where.append(f"lc.cliente_id IN ({ph})")
        params.extend(empresa_ids)

    sql = f"""
        SELECT
            lc.data                             AS data_venda,
            lcc.bandeira_cartao_id              AS bandeira_id,
            bc.nome                             AS bandeira_nome,
            bc.tipo                             AS tipo_cartao,
            SUM(lcc.valor)                      AS total_venda
          FROM lancamentos_caixa_comprovacao lcc
          JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
          JOIN bandeiras_cartao bc ON bc.id = lcc.bandeira_cartao_id
         WHERE {' AND '.join(where)}
         GROUP BY lc.data, lcc.bandeira_cartao_id
         ORDER BY lc.data, bc.tipo, bc.nome
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetch_recebimentos(conn, data_inicio, data_fim, empresa_ids, forma_ids):
    """Soma de recebimentos bancários por (data_transacao, forma_recebimento_id)."""
    if not forma_ids:
        return []

    ph = ','.join(['%s'] * len(forma_ids))
    where = [
        "bt.tipo = 'CREDIT'",
        f"bt.forma_recebimento_id IN ({ph})",
        "bt.data_transacao BETWEEN %s AND %s",
    ]
    params = list(forma_ids) + [data_inicio, data_fim]

    if empresa_ids:
        ep = ','.join(['%s'] * len(empresa_ids))
        where.append(f"ba.cliente_id IN ({ep})")
        params.extend(empresa_ids)

    sql = f"""
        SELECT
            bt.data_transacao                   AS data_recebimento,
            bt.forma_recebimento_id             AS forma_id,
            fr.nome                             AS forma_nome,
            SUM(bt.valor)                       AS total_recebimento
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
          JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
         WHERE {' AND '.join(where)}
         GROUP BY bt.data_transacao, bt.forma_recebimento_id
         ORDER BY bt.data_transacao
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _fmt_date(d):
    if d is None:
        return ''
    if isinstance(d, str):
        try:
            d = datetime.strptime(d, '%Y-%m-%d').date()
        except Exception:
            return str(d)
    if hasattr(d, 'strftime'):
        return d.strftime('%d/%m/%Y')
    return str(d)


def _build_report(bandeiras, vinculos_map, vendas_rows, recebimentos_rows):
    """
    Para cada bandeira vinculada, produz uma lista de linhas cronológicas
    mostrando vendas x recebimentos com diferença acumulada.

    vinculos_map: dict bandeira_id → [forma_recebimento_id, ...]
    """
    # Index vendas: (bandeira_id, data) → total_venda
    vendas_idx = {}
    for r in vendas_rows:
        d = r['data_venda']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        vendas_idx[(int(r['bandeira_id']), str(d))] = float(r['total_venda'] or 0)

    # Index recebimentos: (forma_id, data) → total_recebimento
    receb_idx = {}
    for r in recebimentos_rows:
        d = r['data_recebimento']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        key = (int(r['forma_id']), str(d))
        receb_idx[key] = float(r['total_recebimento'] or 0)

    # Collect all unique dates per bandeira (from vendas and from all linked formas)
    dates_by_bandeira = defaultdict(set)
    for (bid, d) in vendas_idx:
        dates_by_bandeira[bid].add(d)
    for bid, forma_ids in vinculos_map.items():
        for fid in forma_ids:
            for (fid2, d) in receb_idx:
                if fid2 == fid:
                    dates_by_bandeira[bid].add(d)

    report = []
    grand_total_venda = 0.0
    grand_total_recebimento = 0.0

    for band in bandeiras:
        bid = band['id']
        forma_ids = vinculos_map.get(bid, [])

        all_dates = sorted(dates_by_bandeira.get(bid, set()))

        if not all_dates:
            continue

        saldo = 0.0
        total_venda = 0.0
        total_recebimento = 0.0
        linhas = []

        for d in all_dates:
            venda = vendas_idx.get((bid, d), 0.0)
            # Sum receipts across ALL linked formas for this date
            receb = sum(receb_idx.get((fid, d), 0.0) for fid in forma_ids)

            saldo += receb - venda
            total_venda += venda
            total_recebimento += receb

            pct = (receb / venda * 100) if venda else None

            linhas.append({
                'data_venda': _fmt_date(d) if venda else '',
                'total_venda': venda,
                'data_recebimento': _fmt_date(d) if receb else '',
                'total_recebimento': receb,
                'saldo_acumulado': saldo,
                'porcentagem': pct,
            })

        grand_total_venda += total_venda
        grand_total_recebimento += total_recebimento

        # Build names of linked formas for display
        forma_nomes = [v['forma_recebimento_nome'] for v in band.get('vinculos', [])]

        report.append({
            'bandeira_id': bid,
            'bandeira_nome': band['nome'],
            'tipo_cartao': band['tipo'],
            'forma_recebimento_ids': forma_ids,
            'forma_recebimento_nome': ' + '.join(forma_nomes) if forma_nomes else '',
            'linhas': linhas,
            'total_venda': total_venda,
            'total_recebimento': total_recebimento,
            'saldo_final': saldo,
        })

    grand_saldo = grand_total_recebimento - grand_total_venda

    return report, grand_total_venda, grand_total_recebimento, grand_saldo


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_cartoes', methods=['GET'])
@login_required
@admin_required
def conf_cartoes():
    args = request.args

    data_inicio = args.get('data_inicio', '').strip()
    data_fim = args.get('data_fim', '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]
    bandeira_ids = [b for b in args.getlist('bandeira_ids[]') if b]

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)

        empresas = _get_empresas(conn)
        bandeiras = _get_bandeiras(conn)
        formas_cartao = _get_formas_recebimento_cartao(conn)

        # Apply bandeira filter if selected
        bandeiras_filtered = bandeiras
        if bandeira_ids:
            bandeiras_filtered = [b for b in bandeiras if str(b['id']) in bandeira_ids]

        # Build vinculos map: bandeira_id → [forma_recebimento_id, ...]
        vinculos_map = defaultdict(list)
        for b in bandeiras_filtered:
            for v in b.get('vinculos', []):
                vinculos_map[b['id']].append(v['forma_recebimento_id'])

        # IDs das formas vinculadas (para query de recebimentos)
        forma_ids = list(set(fid for fids in vinculos_map.values() for fid in fids))

        report = []
        grand_total_venda = 0.0
        grand_total_recebimento = 0.0
        grand_saldo = 0.0

        if data_inicio and data_fim:
            vendas_rows = _fetch_vendas(conn, data_inicio, data_fim, empresa_ids)
            receb_rows = _fetch_recebimentos(
                conn, data_inicio, data_fim, empresa_ids, forma_ids
            )
            report, grand_total_venda, grand_total_recebimento, grand_saldo = (
                _build_report(bandeiras_filtered, vinculos_map, vendas_rows, receb_rows)
            )
    finally:
        conn.close()

    return render_template(
        'relatorios/conf_cartoes.html',
        empresas=empresas,
        bandeiras=bandeiras,
        formas_cartao=formas_cartao,
        report=report,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        bandeira_ids=bandeira_ids,
        grand_total_venda=grand_total_venda,
        grand_total_recebimento=grand_total_recebimento,
        grand_saldo=grand_saldo,
    )


@bp.route('/conf_cartoes/vincular', methods=['POST'])
@login_required
@admin_required
def vincular_cartao():
    """Adiciona uma vinculação bandeira_cartao ↔ forma_recebimento (máximo 2 por bandeira)."""
    data = request.get_json(silent=True) or {}
    bandeira_id = data.get('bandeira_cartao_id')
    forma_id = data.get('forma_recebimento_id')

    if not bandeira_id or not forma_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)
        cur = conn.cursor()
        # Verifica quantas vinculações já existem para esta bandeira
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM conf_cartoes_vinculos WHERE bandeira_cartao_id = %s",
            (bandeira_id,),
        )
        row = cur.fetchone()
        count = row[0] if row else 0

        # Verifica se essa combinação exata já existe
        cur.execute(
            "SELECT id FROM conf_cartoes_vinculos WHERE bandeira_cartao_id = %s AND forma_recebimento_id = %s",
            (bandeira_id, forma_id),
        )
        exists = cur.fetchone()

        if exists:
            cur.close()
            return jsonify({'success': True, 'message': 'Vínculo já existente.'})

        if count >= 2:
            cur.close()
            return jsonify({
                'success': False,
                'message': 'Máximo de 2 formas de recebimento por bandeira atingido. Remova uma antes de adicionar.'
            }), 400

        cur.execute(
            """
            INSERT INTO conf_cartoes_vinculos (bandeira_cartao_id, forma_recebimento_id)
            VALUES (%s, %s)
            """,
            (bandeira_id, forma_id),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Vinculação salva com sucesso.'})


@bp.route('/conf_cartoes/desvincular', methods=['POST'])
@login_required
@admin_required
def desvincular_cartao():
    """Remove uma vinculação específica de bandeira ↔ forma_recebimento."""
    data = request.get_json(silent=True) or {}
    bandeira_id = data.get('bandeira_cartao_id')
    forma_id = data.get('forma_recebimento_id')

    if not bandeira_id:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    conn = get_db_connection()
    try:
        _ensure_vinculos_table(conn)
        cur = conn.cursor()
        if forma_id:
            # Remove vinculação específica
            cur.execute(
                "DELETE FROM conf_cartoes_vinculos WHERE bandeira_cartao_id = %s AND forma_recebimento_id = %s",
                (bandeira_id, forma_id),
            )
        else:
            # Remove todas as vinculações da bandeira
            cur.execute(
                "DELETE FROM conf_cartoes_vinculos WHERE bandeira_cartao_id = %s",
                (bandeira_id,),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Vinculação removida.'})
