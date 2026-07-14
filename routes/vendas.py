"""
Tela de LISTAGEM DE VENDAS capturadas de XML (NFe/NFCe do SGAPetro). ISOLADA, aditiva.

Rota: /vendas  (acesso por URL / item de menu)

Lista as notas de `vendas_xml` (cabecalho) com expand dos itens (`vendas_xml_itens`).
Filtros opcionais na query string: data_ini, data_fim (sobre dh_emissao),
vendedor (LIKE em vendedor_raw), produto (LIKE em produto_xml via EXISTS nos itens),
forma_pgto (= forma_pagamento).

Padroes do app: blueprint *_bp (auto-registro), @login_required,
get_db_connection() + cursor(dictionary=True), SQL 100% parametrizado (%s).
NAO altera nada existente; nao toca no robo (vendas_api) nem nas tabelas.
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from utils.db import get_db_connection

vendas_bp = Blueprint('vendas', __name__, url_prefix='/vendas')

# Limite de seguranca para nao estourar a tela.
LIMITE = 500


@vendas_bp.route('', methods=['GET'])
@login_required
def index():
    # ---------- Filtros (todos opcionais) ----------
    f = {
        'data_ini':   (request.args.get('data_ini') or '').strip(),
        'data_fim':   (request.args.get('data_fim') or '').strip(),
        'vendedor':   (request.args.get('vendedor') or '').strip(),
        'produto':    (request.args.get('produto') or '').strip(),
        'forma_pgto': (request.args.get('forma_pgto') or '').strip(),
    }

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        where = []
        params = []
        if f['data_ini']:
            where.append("v.dh_emissao >= %s")
            params.append(f['data_ini'] + " 00:00:00")
        if f['data_fim']:
            where.append("v.dh_emissao <= %s")
            params.append(f['data_fim'] + " 23:59:59")
        if f['vendedor']:
            where.append("v.vendedor_raw LIKE %s")
            params.append(f"%{f['vendedor']}%")
        if f['forma_pgto']:
            where.append("v.forma_pagamento = %s")
            params.append(f['forma_pgto'])
        if f['produto']:
            where.append(
                "EXISTS (SELECT 1 FROM vendas_xml_itens it "
                "WHERE it.venda_id = v.id AND it.produto_xml LIKE %s)"
            )
            params.append(f"%{f['produto']}%")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        # ---------- Totais do filtro (independentes do LIMITE) ----------
        # Canceladas NAO entram na soma de valor.
        cur.execute(
            f"""
            SELECT COUNT(*) AS total_notas,
                   COALESCE(SUM(CASE WHEN v.situacao <> 'cancelada'
                                     THEN v.valor_total ELSE 0 END), 0) AS total_valor,
                   COALESCE(SUM(CASE WHEN v.situacao = 'cancelada'
                                     THEN 1 ELSE 0 END), 0) AS total_canceladas
            FROM vendas_xml v
            {where_sql}
            """,
            params,
        )
        agg = cur.fetchone() or {}
        totais = {
            'notas':      agg.get('total_notas') or 0,
            'valor':      agg.get('total_valor') or 0,
            'canceladas': agg.get('total_canceladas') or 0,
        }

        # ---------- Notas (limitadas) ----------
        cur.execute(
            f"""
            SELECT v.id, v.chave, v.modelo, v.serie, v.numero, v.dh_emissao,
                   v.cnpj_emitente, v.vendedor_raw, v.cliente_doc, v.cliente_nome,
                   v.valor_total, v.forma_pagamento, v.situacao, v.origem
            FROM vendas_xml v
            {where_sql}
            ORDER BY v.dh_emissao DESC, v.id DESC
            LIMIT %s
            """,
            params + [LIMITE],
        )
        notas = cur.fetchall()
        truncado = len(notas) >= LIMITE and (totais['notas'] or 0) > LIMITE

        # ---------- Itens das notas exibidas (1 query, sem N+1) ----------
        itens_por_venda = {}
        ids = [n['id'] for n in notas]
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                SELECT id, venda_id, n_item, produto_xml, cod_anp, eh_combustivel,
                       unidade, quantidade, valor_unitario, valor_total,
                       bico, bomba, tanque, enc_ini, enc_fin
                FROM vendas_xml_itens
                WHERE venda_id IN ({placeholders})
                ORDER BY venda_id, n_item
                """,
                ids,
            )
            for it in cur.fetchall():
                itens_por_venda.setdefault(it['venda_id'], []).append(it)

        # Periodo padrao para o form (ultimos 90 dias, sem forcar filtro).
        hoje = date.today()
        data_ini_default = f['data_ini'] or (hoje - timedelta(days=90)).strftime('%Y-%m-%d')
        data_fim_default = f['data_fim'] or hoje.strftime('%Y-%m-%d')

        return render_template(
            'vendas/index.html',
            notas=notas,
            itens_por_venda=itens_por_venda,
            totais=totais,
            filtros=f,
            truncado=truncado,
            limite=LIMITE,
            data_ini_default=data_ini_default,
            data_fim_default=data_fim_default,
        )
    finally:
        cur.close()
        conn.close()
