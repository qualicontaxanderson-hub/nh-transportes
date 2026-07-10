# -*- coding: utf-8 -*-
"""
Conciliação de depósitos EM LOTE (tela isolada).

NÃO altera a tela /depositos (routes/depositos.py). Adiciona só:
  GET  /depositos/conciliar-lote           – tela com 2 grupos
  POST /depositos/conciliar-lote/executar  – grava o lote (AJAX/JSON)

Regra central: só entram no lote os pares com VALOR IDÊNTICO (Decimal, centavo
por centavo) dentro de ±3 dias. Pares com qualquer diferença de valor vão para a
seção "Divergentes" (resolução 1-a-1, reaproveitando depositos.vincular).

Gravação: EXATAMENTE a mesma de depositos.vincular:
  - lancamentos_caixa_comprovacao.bank_transaction_id = <bt>
  - bank_transactions -> status='conciliado', tipo_conciliacao='deposito'
Cada par é validado e gravado INDIVIDUALMENTE: grava os válidos, pula os
inválidos e devolve a lista dos pulados. Idempotente: revalida no momento de
gravar (não religa um depósito já conciliado nem um crédito já usado).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request, jsonify, url_for
from flask_login import login_required, current_user

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('depositos_lote', __name__, url_prefix='/depositos')

_DEPOSIT_TIPOS = ('DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO')
_TIPO_LABEL = {
    'DEPOSITO_ESPECIE':      'Espécie',
    'DEPOSITO_CHEQUE_VISTA': 'Cheque à Vista',
    'DEPOSITO_CHEQUE_PRAZO': 'Cheque a Prazo',
}
_TIPO_GRUPO = {
    'DEPOSITO_ESPECIE':      'ESPECIE',
    'DEPOSITO_CHEQUE_VISTA': 'CHEQUE',
    'DEPOSITO_CHEQUE_PRAZO': 'CHEQUE',
}
_TIPO_CSS = {
    'DEPOSITO_ESPECIE':      'tipo-especie',       # verde
    'DEPOSITO_CHEQUE_VISTA': 'tipo-cheque-vista',  # amarelo
    'DEPOSITO_CHEQUE_PRAZO': 'tipo-cheque-prazo',  # roxo claro
}
WINDOW_DAYS = 3  # janela de data para considerar o mesmo depósito
# Marco de corte fixo: a tela de conciliação em lote esconde depósitos com data do
# depósito feito (COALESCE(data_deposito, data_caixa)) anterior a esta data.
# NÃO apaga nem altera nada no banco — apenas filtra a exibição desta tela.
DATA_CORTE_CONCILIACAO = '2026-06-01'


# ─────────────────────────────── helpers ────────────────────────────────────

def _default_period():
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _fmt_br(d):
    if not d:
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


def _col_exists(cur, table, col):
    cur.execute(
        """SELECT COUNT(*) AS c FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s""",
        (table, col),
    )
    r = cur.fetchone()
    return bool(r and (r.get('c') if isinstance(r, dict) else r[0]))


def _get_contas(conn):
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


def _deposit_forma_sets(conn):
    """
    (formas cheque, formas dinheiro/espécie). Mesma lógica de tipo usada em
    depositos.api_candidatos: conf_depositos_vinculos.tipo_deposito, com fallback
    por nome da forma_recebimento.
    """
    cur = conn.cursor(dictionary=True)
    cheque, dinheiro = set(), set()
    try:
        cur.execute(
            "SELECT forma_recebimento_id, tipo_deposito FROM conf_depositos_vinculos"
        )
        for r in cur.fetchall():
            if (r['tipo_deposito'] or 'DINHEIRO') == 'CHEQUE':
                cheque.add(r['forma_recebimento_id'])
            else:
                dinheiro.add(r['forma_recebimento_id'])
    except Exception:
        pass
    if not cheque and not dinheiro:  # fallback por nome
        try:
            cur.execute("SELECT id, nome FROM formas_recebimento WHERE ativo = 1")
            for r in cur.fetchall():
                n = (r['nome'] or '').upper()
                if 'CHEQUE' in n:
                    cheque.add(r['id'])
                elif any(k in n for k in ('DINHEIRO', 'ESPECIE', 'ESPÉCIE',
                                          'DEPOSITO', 'DEPÓSITO')):
                    dinheiro.add(r['id'])
        except Exception:
            pass
    cur.close()
    return cheque, dinheiro


def _fetch_pending_deposits(conn, di, df):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""
        SELECT lcc.id, lcc.valor, lcc.descricao,
               lc.data AS data_caixa, lc.cliente_id, lc.id AS lancamento_caixa_id,
               fpc.tipo AS forma_tipo,
               COALESCE(cl.nome_fantasia, cl.razao_social) AS cliente_nome
          FROM lancamentos_caixa_comprovacao lcc
          JOIN lancamentos_caixa       lc  ON lc.id  = lcc.lancamento_caixa_id
          JOIN clientes                cl  ON cl.id  = lc.cliente_id
          JOIN formas_pagamento_caixa  fpc ON fpc.id = lcc.forma_pagamento_id
         WHERE fpc.tipo IN {_DEPOSIT_TIPOS}
           AND lcc.bank_transaction_id IS NULL
           AND lcc.valor > 0
           AND lc.data BETWEEN %s AND %s
           AND COALESCE(lcc.data_deposito, lc.data) >= %s
           AND NOT EXISTS (SELECT 1 FROM troco_pix tp
                            WHERE tp.lancamento_caixa_id = lc.id)
         ORDER BY lc.data, lcc.id
        """,
        (di, df, DATA_CORTE_CONCILIACAO),
    )
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        r['tipo_grupo'] = _TIPO_GRUPO.get(r['forma_tipo'], 'ESPECIE')
    return rows


def _fetch_free_credits(conn, di, df, forma_ids, conta_ids):
    """
    Créditos OFX 'livres' (não vinculados a nenhum depósito) das formas de
    depósito, na janela [di-3d, df+3d], filtrados por conta se informado.
    """
    if not forma_ids:
        return []
    di_w = (datetime.strptime(di, '%Y-%m-%d').date() - timedelta(days=WINDOW_DAYS)).isoformat()
    df_w = (datetime.strptime(df, '%Y-%m-%d').date() + timedelta(days=WINDOW_DAYS)).isoformat()
    ph = ','.join(['%s'] * len(forma_ids))
    params = [di_w, df_w] + list(forma_ids)
    where_conta = ''
    if conta_ids:
        cph = ','.join(['%s'] * len(conta_ids))
        where_conta = f'AND bt.account_id IN ({cph})'
        params += [int(x) for x in conta_ids]

    dbv_clause = (
        "AND NOT EXISTS (SELECT 1 FROM deposito_bank_vinculos dbv "
        "WHERE dbv.bank_transaction_id = bt.id)"
    )
    sql = f"""
        SELECT bt.id, bt.valor, bt.data_transacao, bt.descricao,
               bt.forma_recebimento_id, bt.account_id, bt.status,
               COALESCE(ba.apelido, ba.banco_nome) AS conta_nome
          FROM bank_transactions bt
          JOIN bank_accounts ba ON ba.id = bt.account_id
         WHERE bt.tipo = 'CREDIT'
           AND bt.status <> 'ignorado'
           AND bt.data_transacao BETWEEN %s AND %s
           AND bt.forma_recebimento_id IN ({ph})
           {where_conta}
           AND NOT EXISTS (SELECT 1 FROM lancamentos_caixa_comprovacao l2
                            WHERE l2.bank_transaction_id = bt.id)
           {dbv_clause}
         ORDER BY bt.data_transacao, bt.id
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        # Ambiente sem deposito_bank_vinculos: repete sem essa cláusula
        cur.execute(sql.replace(dbv_clause, ''), params)
        rows = cur.fetchall()
    finally:
        cur.close()
    return rows


def _grupo_da_transacao(bt, cheque_set, dinheiro_set):
    fid = bt['forma_recebimento_id']
    if fid in cheque_set:
        return 'CHEQUE'
    if fid in dinheiro_set:
        return 'ESPECIE'
    return None


def _parear(depositos, bank_txs, cheque_set, dinheiro_set):
    """
    Greedy 1:1. Cada depósito pega no máximo 1 crédito; cada crédito é usado 1 vez.
    EXATO: mesmo grupo (cheque/espécie), valor Decimal idêntico, ±WINDOW dias
           (empate resolvido pela menor distância de data, depois menor id).
    DIVERGENTE: sem par exato → melhor candidato por proximidade de valor/data
                (pode ser None se não houver crédito livre na janela).
    """
    usados = set()
    exatos, divergentes = [], []

    for d in depositos:
        d_grupo = d['tipo_grupo']
        d_valor = d['valor']          # Decimal
        d_data = d['data_caixa']      # date

        # 1) tenta EXATO
        melhor, melhor_key = None, None
        for bt in bank_txs:
            if bt['id'] in usados:
                continue
            if _grupo_da_transacao(bt, cheque_set, dinheiro_set) != d_grupo:
                continue
            if bt['valor'] != d_valor:            # igualdade Decimal, sem tolerância
                continue
            dist = abs((bt['data_transacao'] - d_data).days)
            if dist > WINDOW_DAYS:
                continue
            key = (dist, bt['id'])
            if melhor_key is None or key < melhor_key:
                melhor_key, melhor = key, bt
        if melhor is not None:
            usados.add(melhor['id'])
            exatos.append((d, melhor))
            continue

        # 2) DIVERGENTE: melhor candidato por proximidade (valor, depois data)
        melhor, melhor_key = None, None
        for bt in bank_txs:
            if bt['id'] in usados:
                continue
            if _grupo_da_transacao(bt, cheque_set, dinheiro_set) != d_grupo:
                continue
            dist = abs((bt['data_transacao'] - d_data).days)
            if dist > WINDOW_DAYS:
                continue
            vdiff = abs(bt['valor'] - d_valor)
            key = (vdiff, dist, bt['id'])
            if melhor_key is None or key < melhor_key:
                melhor_key, melhor = key, bt
        divergentes.append((d, melhor))  # melhor pode ser None
    return exatos, divergentes


def _row_dep(d):
    return {
        'dep_id': d['id'],
        'lancamento_caixa_id': d['lancamento_caixa_id'],
        'cliente': d['cliente_nome'],
        'tipo_label': _TIPO_LABEL.get(d['forma_tipo'], d['forma_tipo']),
        'tipo_css': _TIPO_CSS.get(d['forma_tipo'], 'tipo-especie'),
        'tipo_grupo': d['tipo_grupo'],
        'data_caixa_br': _fmt_br(d['data_caixa']),
        'valor': float(d['valor']),
    }


def _row_bt(bt):
    return {
        'bt_id': bt['id'],
        'bt_data_br': _fmt_br(bt['data_transacao']),
        'bt_valor': float(bt['valor']),
        'bt_desc': bt.get('descricao') or '',
        'conta': bt.get('conta_nome') or '',
    }


# ──────────────────────────────── rotas ─────────────────────────────────────

@bp.route('/conciliar-lote')
@login_required
@admin_required
def conciliar_lote():
    args = request.args
    data_inicio = args.get('data_inicio', '').strip()
    data_fim = args.get('data_fim', '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()
    conta_ids = [c for c in args.getlist('conta_ids[]') if c]

    conn = get_db_connection()
    try:
        contas = _get_contas(conn)
        cheque_set, dinheiro_set = _deposit_forma_sets(conn)
        forma_ids = list(cheque_set | dinheiro_set)
        depositos = _fetch_pending_deposits(conn, data_inicio, data_fim)
        bank_txs = _fetch_free_credits(conn, data_inicio, data_fim, forma_ids, conta_ids)
        exatos, divergentes = _parear(depositos, bank_txs, cheque_set, dinheiro_set)
    finally:
        conn.close()

    exatos_rows = []
    total_exato = 0.0
    for d, bt in exatos:
        row = {**_row_dep(d), **_row_bt(bt)}
        exatos_rows.append(row)
        total_exato += row['valor']

    divergentes_rows = []
    for d, bt in divergentes:
        row = _row_dep(d)
        if bt is not None:
            row.update(_row_bt(bt))
            row['tem_candidato'] = True
            row['diff'] = round(row['bt_valor'] - row['valor'], 2)
        else:
            row['tem_candidato'] = False
            row['diff'] = None
        divergentes_rows.append(row)

    empresas = sorted(
        {r['cliente'] for r in exatos_rows} | {r['cliente'] for r in divergentes_rows}
    )

    return render_template(
        'depositos/conciliar_lote.html',
        contas=contas,
        conta_ids=conta_ids,
        data_inicio=data_inicio,
        data_fim=data_fim,
        window_days=WINDOW_DAYS,
        data_corte_br=_fmt_br(DATA_CORTE_CONCILIACAO),
        empresas=empresas,
        exatos=exatos_rows,
        divergentes=divergentes_rows,
        total_exato=total_exato,
        qtd_exato=len(exatos_rows),
        qtd_divergente=len(divergentes_rows),
    )


@bp.route('/conciliar-lote/executar', methods=['POST'])
@login_required
@admin_required
def conciliar_lote_executar():
    """
    Grava o lote. JSON: {"pares": [{"c": <comprovacao_id>, "b": <bank_tx_id>}, ...]}

    Grava os válidos e PULA os inválidos (não é tudo-ou-nada). Cada par é
    revalidado individualmente no momento de gravar; o que falhar volta em
    'pulados' com o motivo, e o que der certo é comitado.
    """
    payload = request.get_json(silent=True) or {}
    pares = payload.get('pares') or []

    clean, seen_dep, seen_bt, pulados = [], set(), set(), []
    for p in pares:
        try:
            c, b = int(p.get('c')), int(p.get('b'))
        except (TypeError, ValueError):
            continue
        if c in seen_dep or b in seen_bt:  # par repetido no mesmo lote → pula
            pulados.append({'c': c, 'b': b, 'motivo': 'par duplicado no lote'})
            continue
        seen_dep.add(c); seen_bt.add(b)
        clean.append((c, b))

    if not clean:
        return jsonify(success=False, message='Nenhum par informado.',
                       conciliados=[], pulados=pulados, qtd=0,
                       qtd_pulados=len(pulados)), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        agora = datetime.now()
        usuario = current_user.email if hasattr(current_user, 'email') else str(current_user.id)
        has_tipo_concil = _col_exists(cur, 'bank_transactions', 'tipo_conciliacao')

        conciliados = []
        for c, b in clean:
            # ── revalidação individual (idempotência + valor exato) ──
            cur.execute(
                """
                SELECT lcc.valor AS dep_valor, lcc.bank_transaction_id AS cur_link,
                       bt.tipo AS bt_tipo, bt.status AS bt_status, bt.valor AS bt_valor,
                       (SELECT COUNT(*) FROM lancamentos_caixa_comprovacao l2
                         WHERE l2.bank_transaction_id = bt.id) AS used_primary,
                       (SELECT COUNT(*) FROM deposito_bank_vinculos dbv
                         WHERE dbv.bank_transaction_id = bt.id) AS used_extra
                  FROM lancamentos_caixa_comprovacao lcc
                  JOIN bank_transactions bt ON bt.id = %s
                 WHERE lcc.id = %s
                """,
                (b, c),
            )
            row = cur.fetchone()

            motivo = None
            if not row:
                motivo = 'registro inexistente'
            elif row['cur_link'] is not None:
                motivo = 'depósito já conciliado'
            elif row['bt_tipo'] != 'CREDIT':
                motivo = 'transação não é crédito'
            elif row['bt_status'] == 'ignorado':
                motivo = 'transação ignorada'
            elif (row['used_primary'] or 0) + (row['used_extra'] or 0) > 0:
                motivo = 'transação já usada em outro depósito'
            elif row['dep_valor'] != row['bt_valor']:  # igualdade Decimal
                motivo = f"valor diverge ({row['dep_valor']} ≠ {row['bt_valor']})"

            if motivo:
                pulados.append({'c': c, 'b': b, 'motivo': motivo})
                continue

            # ── gravação — idêntica a depositos.vincular ──
            cur.execute(
                """UPDATE lancamentos_caixa_comprovacao
                      SET bank_transaction_id = %s
                    WHERE id = %s AND bank_transaction_id IS NULL""",
                (b, c),
            )
            if cur.rowcount != 1:  # corrida: conciliado nesse meio-tempo → pula
                pulados.append({'c': c, 'b': b, 'motivo': 'conflito de concorrência'})
                continue
            if has_tipo_concil:
                cur.execute(
                    """UPDATE bank_transactions
                          SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                              tipo_conciliacao='deposito'
                        WHERE id=%s""",
                    (agora, usuario, b),
                )
            else:
                cur.execute(
                    """UPDATE bank_transactions
                          SET status='conciliado', conciliado_em=%s, conciliado_por=%s
                        WHERE id=%s""",
                    (agora, usuario, b),
                )
            conciliados.append(c)

        conn.commit()
        return jsonify(
            success=True,
            conciliados=conciliados,
            pulados=pulados,
            qtd=len(conciliados),
            qtd_pulados=len(pulados),
        )

    except Exception as exc:
        conn.rollback()
        return jsonify(success=False, message=f'Erro ao conciliar: {exc}'), 500
    finally:
        cur.close()
        conn.close()


@bp.route('/conciliar-lote/vincular-divergente', methods=['POST'])
@login_required
@admin_required
def conciliar_lote_vincular_divergente():
    """
    Vincula UM par divergente (valor NÃO precisa bater) via AJAX, para o vínculo
    acontecer na própria tela /conciliar-lote sem redirecionar.
    Gravação idêntica a depositos.vincular; só o retorno é JSON.
    """
    payload = request.get_json(silent=True) or {}
    try:
        c, b = int(payload.get('c')), int(payload.get('b'))
    except (TypeError, ValueError):
        return jsonify(success=False, message='Par inválido.'), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        agora = datetime.now()
        usuario = current_user.email if hasattr(current_user, 'email') else str(current_user.id)
        has_tipo_concil = _col_exists(cur, 'bank_transactions', 'tipo_conciliacao')

        cur.execute(
            """
            SELECT lcc.bank_transaction_id AS cur_link,
                   bt.tipo AS bt_tipo, bt.status AS bt_status,
                   (SELECT COUNT(*) FROM lancamentos_caixa_comprovacao l2
                     WHERE l2.bank_transaction_id = bt.id) AS used_primary,
                   (SELECT COUNT(*) FROM deposito_bank_vinculos dbv
                     WHERE dbv.bank_transaction_id = bt.id) AS used_extra
              FROM lancamentos_caixa_comprovacao lcc
              JOIN bank_transactions bt ON bt.id = %s
             WHERE lcc.id = %s
            """,
            (b, c),
        )
        row = cur.fetchone()

        motivo = None
        if not row:
            motivo = 'registro inexistente'
        elif row['cur_link'] is not None:
            motivo = 'depósito já conciliado'
        elif row['bt_tipo'] != 'CREDIT':
            motivo = 'transação não é crédito'
        elif row['bt_status'] == 'ignorado':
            motivo = 'transação ignorada'
        elif (row['used_primary'] or 0) + (row['used_extra'] or 0) > 0:
            motivo = 'transação já usada em outro depósito'
        if motivo:
            conn.rollback()
            return jsonify(success=False, message=motivo), 409

        cur.execute(
            """UPDATE lancamentos_caixa_comprovacao
                  SET bank_transaction_id = %s
                WHERE id = %s AND bank_transaction_id IS NULL""",
            (b, c),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return jsonify(success=False, message='conflito de concorrência'), 409
        if has_tipo_concil:
            cur.execute(
                """UPDATE bank_transactions
                      SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                          tipo_conciliacao='deposito'
                    WHERE id=%s""",
                (agora, usuario, b),
            )
        else:
            cur.execute(
                """UPDATE bank_transactions
                      SET status='conciliado', conciliado_em=%s, conciliado_por=%s
                    WHERE id=%s""",
                (agora, usuario, b),
            )
        conn.commit()
        return jsonify(success=True, conciliado=c)
    except Exception as exc:
        conn.rollback()
        return jsonify(success=False, message=f'Erro ao vincular: {exc}'), 500
    finally:
        cur.close()
        conn.close()


@bp.route('/conciliar-lote/candidatos/<int:comprovacao_id>')
@login_required
@admin_required
def conciliar_lote_candidatos(comprovacao_id):
    """
    Lista transações CRÉDITO LIVRES (não usadas por depósito) na janela de
    ±WINDOW_DAYS da DATA DO DEPÓSITO FEITO (COALESCE(data_deposito, data_caixa)),
    do mesmo tipo (cheque/espécie) do depósito. Só SUGERE — nada é gravado.
    Usado pelo modal "Juntar transações" (banco dividiu o depósito).
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT lcc.id, lcc.valor, lcc.bank_transaction_id,
                   COALESCE(lcc.data_deposito, lc.data) AS data_ref,
                   fpc.tipo AS forma_tipo
              FROM lancamentos_caixa_comprovacao lcc
              JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
              JOIN formas_pagamento_caixa fpc ON fpc.id = lcc.forma_pagamento_id
             WHERE lcc.id = %s
            """,
            (comprovacao_id,),
        )
        dep = cur.fetchone()
        if not dep:
            return jsonify(success=False, message='Depósito inexistente.'), 404
        if dep['bank_transaction_id'] is not None:
            return jsonify(success=False, message='Depósito já conciliado.'), 409

        cheque_set, dinheiro_set = _deposit_forma_sets(conn)
        grupo = _TIPO_GRUPO.get(dep['forma_tipo'], 'ESPECIE')
        forma_ids = list(cheque_set if grupo == 'CHEQUE' else dinheiro_set)

        dep_out = {
            'id': dep['id'], 'valor': float(dep['valor']),
            'tipo': _TIPO_LABEL.get(dep['forma_tipo'], dep['forma_tipo']),
            'data_ref_br': _fmt_br(dep['data_ref']),
        }
        if not forma_ids:
            return jsonify(success=True, dep=dep_out, candidatos=[])

        data_ref = dep['data_ref']
        di = (data_ref - timedelta(days=WINDOW_DAYS)).isoformat()
        df = (data_ref + timedelta(days=WINDOW_DAYS)).isoformat()
        ph = ','.join(['%s'] * len(forma_ids))
        dbv_clause = ("AND NOT EXISTS (SELECT 1 FROM deposito_bank_vinculos dbv "
                      "WHERE dbv.bank_transaction_id = bt.id)")
        sql = f"""
            SELECT bt.id, bt.valor, bt.data_transacao, bt.descricao,
                   COALESCE(ba.apelido, ba.banco_nome) AS conta_nome
              FROM bank_transactions bt
              JOIN bank_accounts ba ON ba.id = bt.account_id
             WHERE bt.tipo = 'CREDIT'
               AND bt.status <> 'ignorado'
               AND bt.data_transacao BETWEEN %s AND %s
               AND bt.forma_recebimento_id IN ({ph})
               AND NOT EXISTS (SELECT 1 FROM lancamentos_caixa_comprovacao l2
                                WHERE l2.bank_transaction_id = bt.id)
               {dbv_clause}
             ORDER BY bt.data_transacao, bt.id
        """
        params = [di, df] + forma_ids
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        except Exception:
            cur.execute(sql.replace(dbv_clause, ''), params)
            rows = cur.fetchall()

        candidatos = [{
            'id': r['id'], 'valor': float(r['valor']),
            'data_br': _fmt_br(r['data_transacao']),
            'desc': r.get('descricao') or '', 'conta': r.get('conta_nome') or '',
        } for r in rows]
        return jsonify(success=True, dep=dep_out, candidatos=candidatos)
    finally:
        cur.close()
        conn.close()


@bp.route('/conciliar-lote/vincular-multiplo', methods=['POST'])
@login_required
@admin_required
def conciliar_lote_vincular_multiplo():
    """
    Vincula 1 depósito a N transações (banco dividiu o depósito). Exige soma EXATA.
    Gravação IDÊNTICA à tela antiga depositos.vincular:
      - primária em lancamentos_caixa_comprovacao.bank_transaction_id
      - extras em deposito_bank_vinculos
      - cada bt marcada status='conciliado', tipo_conciliacao='deposito'
    Revalida na hora (idempotente): depósito livre + todas as bts livres + soma exata.
    """
    payload = request.get_json(silent=True) or {}
    try:
        c = int(payload.get('c'))
    except (TypeError, ValueError):
        return jsonify(success=False, message='Depósito inválido.'), 400
    bts, seen = [], set()
    for x in (payload.get('bts') or []):
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v not in seen:
            seen.add(v); bts.append(v)
    if len(bts) < 2:
        return jsonify(success=False, message='Selecione ao menos 2 transações.'), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        agora = datetime.now()
        usuario = current_user.email if hasattr(current_user, 'email') else str(current_user.id)
        has_tipo_concil = _col_exists(cur, 'bank_transactions', 'tipo_conciliacao')

        cur.execute(
            "SELECT valor, bank_transaction_id FROM lancamentos_caixa_comprovacao WHERE id=%s",
            (c,),
        )
        dep = cur.fetchone()
        if not dep:
            conn.rollback()
            return jsonify(success=False, message='Depósito inexistente.'), 404
        if dep['bank_transaction_id'] is not None:
            conn.rollback()
            return jsonify(success=False, message='Depósito já conciliado.'), 409

        ph = ','.join(['%s'] * len(bts))
        cur.execute(
            f"""
            SELECT bt.id, bt.valor, bt.tipo, bt.status,
                   (SELECT COUNT(*) FROM lancamentos_caixa_comprovacao l2
                     WHERE l2.bank_transaction_id = bt.id) AS up,
                   (SELECT COUNT(*) FROM deposito_bank_vinculos dbv
                     WHERE dbv.bank_transaction_id = bt.id) AS ue
              FROM bank_transactions bt
             WHERE bt.id IN ({ph})
            """,
            bts,
        )
        found = {r['id']: r for r in cur.fetchall()}
        if len(found) != len(bts):
            conn.rollback()
            return jsonify(success=False, message='Alguma transação não existe mais.'), 409

        soma = Decimal('0')
        for bid in bts:
            r = found[bid]
            if r['tipo'] != 'CREDIT':
                conn.rollback()
                return jsonify(success=False, message=f'Transação #{bid} não é crédito.'), 409
            if r['status'] == 'ignorado':
                conn.rollback()
                return jsonify(success=False, message=f'Transação #{bid} está ignorada.'), 409
            if (r['up'] or 0) + (r['ue'] or 0) > 0:
                conn.rollback()
                return jsonify(success=False, message=f'Transação #{bid} já foi usada em outro depósito.'), 409
            soma += r['valor']
        if soma != dep['valor']:   # igualdade Decimal, sem tolerância
            conn.rollback()
            return jsonify(success=False, message=f'Soma não confere ({soma} ≠ {dep["valor"]}).'), 409

        # ── gravação idêntica à tela antiga (primária + extras + marcação) ──
        primary, extras = bts[0], bts[1:]
        cur.execute(
            """UPDATE lancamentos_caixa_comprovacao
                  SET bank_transaction_id = %s
                WHERE id = %s AND bank_transaction_id IS NULL""",
            (primary, c),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return jsonify(success=False, message='conflito de concorrência'), 409
        for btx in extras:
            cur.execute(
                """INSERT IGNORE INTO deposito_bank_vinculos
                       (comprovacao_id, bank_transaction_id, vinculado_em, vinculado_por)
                   VALUES (%s, %s, %s, %s)""",
                (c, btx, agora, usuario),
            )
        for btx in [primary] + extras:
            if has_tipo_concil:
                cur.execute(
                    """UPDATE bank_transactions
                          SET status='conciliado', conciliado_em=%s, conciliado_por=%s,
                              tipo_conciliacao='deposito'
                        WHERE id=%s""",
                    (agora, usuario, btx),
                )
            else:
                cur.execute(
                    """UPDATE bank_transactions
                          SET status='conciliado', conciliado_em=%s, conciliado_por=%s
                        WHERE id=%s""",
                    (agora, usuario, btx),
                )
        conn.commit()
        return jsonify(success=True, conciliado=c, qtd_transacoes=len(bts))
    except Exception as exc:
        conn.rollback()
        return jsonify(success=False, message=f'Erro ao vincular: {exc}'), 500
    finally:
        cur.close()
        conn.close()
