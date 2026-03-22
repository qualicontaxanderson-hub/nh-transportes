"""
Relatório de Conferência de Cartões.

Cruza vendas de cartão (lancamentos_caixa_comprovacao com bandeira_cartao_id)
com recebimentos bancários (bank_transactions CREDIT vinculados a
formas_recebimento com eh_cartao=1), usando a tabela de vinculação
conf_cartoes_vinculos para saber qual bandeira corresponde a qual
forma de recebimento. Cada bandeira pode ter até 2 formas vinculadas
(ex: regular + antecipado para cartão de crédito).

Rota:
  GET  /relatorios/conf_cartoes               – relatório
  POST /relatorios/conf_cartoes/vincular       – salva vinculação
  POST /relatorios/conf_cartoes/desvincular   – remove vinculação específica
  POST /relatorios/conf_cartoes/prazo_salvar          – salva prazo de compensação
  POST /relatorios/conf_cartoes/saldo_anterior_salvar – salva saldo anterior de vendas pendentes
  POST /relatorios/conf_cartoes/feriado_add           – adiciona feriado
  POST /relatorios/conf_cartoes/feriado_del           – remove feriado
"""
from datetime import date, datetime, timedelta
from collections import defaultdict

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

# Abreviações dos dias da semana em português (weekday() 0=Seg … 6=Dom)
_DIAS_PT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
# Tolerância monetária para comparações de zero (evita erros de ponto flutuante)
_MONETARY_EPSILON = 0.005


def _parse_iso(d):
    """Converte string ISO 'YYYY-MM-DD' ou date para objeto date."""
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(str(d), '%Y-%m-%d').date()
    except Exception:
        return None


def _next_business_day(d, n, feriados_set):
    """Retorna a data que é exatamente n dias úteis após d (pula fins de semana e feriados)."""
    count = 0
    while count < n:
        d = d + timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in feriados_set:
            count += 1
    return d

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
    # Migração: adiciona coluna prazo_compensacao_dias em bandeiras_cartao se não existir
    try:
        cur.execute(
            "ALTER TABLE bandeiras_cartao "
            "ADD COLUMN prazo_compensacao_dias INT NOT NULL DEFAULT 1"
        )
        conn.commit()
    except Exception:
        pass  # coluna já existe
    # Migração: adiciona coluna saldo_anterior em bandeiras_cartao se não existir
    try:
        cur.execute(
            "ALTER TABLE bandeiras_cartao "
            "ADD COLUMN saldo_anterior DECIMAL(12,2) NOT NULL DEFAULT 0"
        )
        conn.commit()
    except Exception:
        pass  # coluna já existe
    cur.close()


def _ensure_feriados_table(conn):
    """Cria a tabela de feriados municipais/estaduais se não existir."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS conf_cartoes_feriados (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            data        DATE NOT NULL,
            descricao   VARCHAR(200) NOT NULL DEFAULT '',
            criado_em   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_feriado_data (data)
        )
        """
    )
    conn.commit()
    cur.close()


def _get_feriados(conn):
    """Retorna lista de feriados e um set com as datas ISO."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, DATE_FORMAT(data, '%Y-%m-%d') AS data_iso, descricao "
            "FROM conf_cartoes_feriados ORDER BY data"
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    feriados_set = {r['data_iso'] for r in rows}
    return rows, feriados_set


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
        SELECT bc.id, bc.nome, bc.tipo,
               COALESCE(bc.prazo_compensacao_dias, 1) AS prazo_compensacao_dias,
               COALESCE(bc.saldo_anterior, 0) AS saldo_anterior
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


def _build_report(bandeiras, vinculos_map, vendas_rows, recebimentos_rows, feriados_set=None):
    """
    Para cada bandeira vinculada, organiza as vendas em ciclos de liquidação
    (usando prazo_compensacao_dias e dias úteis).

    Cada venda é mapeada à sua data de recebimento esperada. Vendas com a
    mesma data esperada formam um ciclo. O recebimento real é comparado
    contra a soma das vendas do ciclo (mais saldo_anterior no 1º ciclo).

    Cada linha representa uma data de venda. Na última linha do ciclo são
    exibidos o recebimento, a Dif. Acumulada e a % de taxa cobrada.

    DIF (taxa):  +  = operadora descontou taxa  (venda > recebimento)
                 −  = operadora pagou a mais    (recebimento > venda)
    %  = (vendas_ciclo − recebimento) / vendas_ciclo × 100
    """
    if feriados_set is None:
        feriados_set = set()

    # Index vendas: (bandeira_id, data_iso) → total_venda
    vendas_idx = {}
    for r in vendas_rows:
        d = r['data_venda']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        vendas_idx[(int(r['bandeira_id']), str(d))] = float(r['total_venda'] or 0)

    # Index recebimentos: (forma_id, data_iso) → total_recebimento
    receb_idx = {}
    for r in recebimentos_rows:
        d = r['data_recebimento']
        if hasattr(d, 'isoformat'):
            d = d.isoformat()
        key = (int(r['forma_id']), str(d))
        receb_idx[key] = float(r['total_recebimento'] or 0)

    report = []
    grand_total_venda = 0.0
    grand_total_recebimento = 0.0

    for band in bandeiras:
        bid = band['id']
        prazo = int(band.get('prazo_compensacao_dias', 1))
        forma_ids = vinculos_map.get(bid, [])
        saldo_anterior = float(band.get('saldo_anterior', 0.0))

        # Todas as datas de venda desta bandeira no período
        sale_dates = sorted(d for (b, d) in vendas_idx if b == bid)

        # Todas as datas de recebimento real no período
        all_receipt_dates = set()
        for fid in forma_ids:
            for (fid2, d) in receb_idx:
                if fid2 == fid:
                    all_receipt_dates.add(d)

        if not sale_dates and not all_receipt_dates and saldo_anterior == 0.0:
            continue

        # ── Mapeia cada data de venda → data esperada de recebimento ──────────
        # cycles[receipt_date_iso] = [sale_date_iso, ...]
        cycles = defaultdict(list)
        for sd in sale_dates:
            sd_obj = _parse_iso(sd)
            if sd_obj:
                rd_obj = sd_obj if prazo == 0 else _next_business_day(sd_obj, prazo, feriados_set)
                cycles[rd_obj.isoformat()].append(sd)

        # Recebimentos sem venda correspondente no período (ex: créditos avulsos)
        for rd in all_receipt_dates:
            if rd not in cycles:
                cycles[rd] = []

        sorted_cycle_dates = sorted(cycles.keys())
        if not sorted_cycle_dates:
            continue

        # ── Monta as linhas agrupadas por ciclo ───────────────────────────────
        linhas = []
        total_venda = 0.0
        total_recebimento = 0.0
        saldo = 0.0          # DIF acumulada (sign: negativo = taxas cobradas)
        is_first_cycle = True

        for rd in sorted_cycle_dates:
            cycle_sale_dates = sorted(cycles[rd])
            actual_receipt = sum(receb_idx.get((fid, rd), 0.0) for fid in forma_ids)
            cycle_venda = sum(vendas_idx.get((bid, sd), 0.0) for sd in cycle_sale_dates)

            # No 1º ciclo: saldo_anterior compõe as vendas efetivas
            # (pré-período pendentes de liquidação no primeiro recebimento)
            effective_sales = cycle_venda
            if is_first_cycle and saldo_anterior != 0.0:
                effective_sales += saldo_anterior
            is_first_cycle = False

            # Taxa do ciclo: positivo = operadora descontou; negativo = pagou a mais
            # Só calculamos taxa e DIF quando há recebimento real
            has_receipt = actual_receipt > _MONETARY_EPSILON
            cycle_fee = (effective_sales - actual_receipt) if has_receipt else 0.0
            pct = (cycle_fee / effective_sales * 100) if (has_receipt and effective_sales) else None

            rd_obj = _parse_iso(rd)
            dia_semana_rd = _DIAS_PT[rd_obj.weekday()] if rd_obj else ''
            num_sale_rows = len(cycle_sale_dates)

            if num_sale_rows == 0:
                # Recebimento avulso sem vendas no período
                if has_receipt:
                    saldo += actual_receipt
                is_destaque_rd = (rd_obj is not None and rd_obj.weekday() >= 5) or (rd in feriados_set)
                linhas.append({
                    'data_venda': '',
                    'total_venda': 0.0,
                    'data_recebimento': _fmt_date(rd) if has_receipt else '',
                    'total_recebimento': actual_receipt,
                    'saldo_acumulado': saldo if has_receipt else None,
                    'porcentagem': None,
                    'data_iso': rd,
                    'dia_semana': '',
                    'dia_semana_recebimento': dia_semana_rd,
                    'is_destaque': is_destaque_rd,
                })
            else:
                if has_receipt:
                    saldo -= cycle_fee  # saldo += actual_receipt - effective_sales

                for i, sd in enumerate(cycle_sale_dates):
                    venda = vendas_idx.get((bid, sd), 0.0)
                    is_last = (i == num_sale_rows - 1)

                    sd_obj = _parse_iso(sd)
                    dia_semana_sd = _DIAS_PT[sd_obj.weekday()] if sd_obj else ''
                    is_destaque = (sd_obj is not None and sd_obj.weekday() >= 5) or (sd in feriados_set)

                    if is_last:
                        # Última venda do ciclo: exibe recebimento, DIF e %
                        # Sempre mostra a data de recebimento esperada (mesmo sem recebimento)
                        linhas.append({
                            'data_venda': _fmt_date(sd),
                            'total_venda': venda,
                            'data_recebimento': _fmt_date(rd),
                            'total_recebimento': actual_receipt,
                            'saldo_acumulado': saldo if has_receipt else None,
                            'porcentagem': pct,
                            'data_iso': sd,
                            'dia_semana': dia_semana_sd,
                            'dia_semana_recebimento': dia_semana_rd,
                            'is_destaque': is_destaque,
                        })
                    else:
                        # Linhas intermediárias: mostra data esperada de recebimento, sem valor
                        linhas.append({
                            'data_venda': _fmt_date(sd),
                            'total_venda': venda,
                            'data_recebimento': _fmt_date(rd),
                            'total_recebimento': 0.0,
                            'saldo_acumulado': None,
                            'porcentagem': None,
                            'data_iso': sd,
                            'dia_semana': dia_semana_sd,
                            'dia_semana_recebimento': dia_semana_rd,
                            'is_destaque': is_destaque,
                        })

            total_venda += cycle_venda
            total_recebimento += actual_receipt

        if not linhas:
            continue

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
            'saldo_anterior': saldo_anterior,
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
        _ensure_feriados_table(conn)

        empresas = _get_empresas(conn)
        bandeiras = _get_bandeiras(conn)
        formas_cartao = _get_formas_recebimento_cartao(conn)
        feriados, feriados_set = _get_feriados(conn)

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
                _build_report(bandeiras_filtered, vinculos_map, vendas_rows, receb_rows, feriados_set)
            )
    finally:
        conn.close()

    return render_template(
        'relatorios/conf_cartoes.html',
        empresas=empresas,
        bandeiras=bandeiras,
        formas_cartao=formas_cartao,
        feriados=feriados,
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


@bp.route('/conf_cartoes/prazo_salvar', methods=['POST'])
@login_required
@admin_required
def prazo_salvar():
    """Salva o prazo de compensação (dias úteis) para uma bandeira de cartão."""
    data = request.get_json(silent=True) or {}
    bandeira_id = data.get('bandeira_cartao_id')
    prazo_dias = data.get('prazo_dias')

    if not bandeira_id or prazo_dias is None:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    try:
        prazo_dias = int(prazo_dias)
        if prazo_dias < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Prazo inválido.'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE bandeiras_cartao SET prazo_compensacao_dias = %s WHERE id = %s",
            (prazo_dias, bandeira_id),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Prazo salvo.'})


@bp.route('/conf_cartoes/saldo_anterior_salvar', methods=['POST'])
@login_required
@admin_required
def saldo_anterior_salvar():
    """Salva o saldo anterior de vendas pendentes para uma bandeira de cartão."""
    data = request.get_json(silent=True) or {}
    bandeira_id = data.get('bandeira_cartao_id')
    saldo_anterior = data.get('saldo_anterior')

    if not bandeira_id or 'saldo_anterior' not in data:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos.'}), 400

    try:
        saldo_anterior = float(saldo_anterior)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Saldo inválido.'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE bandeiras_cartao SET saldo_anterior = %s WHERE id = %s",
            (saldo_anterior, bandeira_id),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Saldo anterior salvo.'})


@bp.route('/conf_cartoes/feriado_add', methods=['POST'])
@login_required
@admin_required
def feriado_add():
    """Adiciona um feriado municipal/estadual."""
    data = request.get_json(silent=True) or {}
    data_feriado = (data.get('data') or '').strip()
    descricao = (data.get('descricao') or '').strip()

    if not data_feriado:
        return jsonify({'success': False, 'message': 'Data obrigatória.'}), 400

    # Valida formato da data
    try:
        datetime.strptime(data_feriado, '%Y-%m-%d')
    except ValueError:
        return jsonify({'success': False, 'message': 'Data inválida.'}), 400

    conn = get_db_connection()
    try:
        _ensure_feriados_table(conn)
        cur = conn.cursor(dictionary=True)
        # Verifica se já existe
        cur.execute(
            "SELECT id FROM conf_cartoes_feriados WHERE data = %s",
            (data_feriado,),
        )
        if cur.fetchone():
            cur.close()
            return jsonify({'success': False, 'message': 'Esta data já está cadastrada como feriado.'}), 400
        cur.execute(
            "INSERT INTO conf_cartoes_feriados (data, descricao) VALUES (%s, %s)",
            (data_feriado, descricao),
        )
        new_id = cur.lastrowid
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({'success': True, 'id': new_id, 'message': 'Feriado adicionado.'})


@bp.route('/conf_cartoes/feriado_del', methods=['POST'])
@login_required
@admin_required
def feriado_del():
    """Remove um feriado pelo id."""
    data = request.get_json(silent=True) or {}
    feriado_id = data.get('id')

    if not feriado_id:
        return jsonify({'success': False, 'message': 'ID obrigatório.'}), 400

    conn = get_db_connection()
    try:
        _ensure_feriados_table(conn)
        cur = conn.cursor()
        cur.execute("DELETE FROM conf_cartoes_feriados WHERE id = %s", (feriado_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Feriado removido.'})
