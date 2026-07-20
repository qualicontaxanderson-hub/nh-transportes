"""
Tela de LISTAGEM + DETALHE de VENDAS capturadas de XML (NFe/NFCe do SGAPetro).
ISOLADA, aditiva. SOMENTE VISUALIZACAO.

Rotas:
  GET /vendas        -> lista paginada (100/pagina) com filtros e totais
  GET /vendas/<id>   -> detalhe no layout de nota (modelo 65 = cupom, 55 = DANFE)

Filtros (query string): data_ini, data_fim, vendedor, produto (LIKE nos itens),
forma_pgto. A paginacao (param `page`) PRESERVA os filtros na URL.

Padroes do app: blueprint *_bp (auto-registro), @login_required,
get_db_connection() + cursor(dictionary=True), SQL 100% parametrizado (%s).
NAO altera nada existente; NAO toca no robo (vendas_api) nem nas tabelas.
"""
import math
from datetime import date, timedelta
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, abort
from flask_login import login_required

from utils.db import get_db_connection

vendas_bp = Blueprint('vendas', __name__, url_prefix='/vendas')

# Notas por pagina.
POR_PAGINA = 100


def _janela_paginas(pagina, total_paginas, raio=2):
    """Paginas a exibir: 1 ... (janela em torno da atual) ... N. None = reticencias."""
    marcadas = {1, total_paginas}
    for p in range(pagina - raio, pagina + raio + 1):
        if 1 <= p <= total_paginas:
            marcadas.add(p)
    saida, anterior = [], 0
    for p in sorted(marcadas):
        if p - anterior > 1:
            saida.append(None)
        saida.append(p)
        anterior = p
    return saida


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
    try:
        pagina = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        pagina = 1

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

        # ---------- Totais do filtro (INALTERADO: sobre TODO o filtro) ----------
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

        # ---------- Paginacao ----------
        total_notas = totais['notas'] or 0
        total_paginas = max(1, math.ceil(total_notas / POR_PAGINA))
        if pagina > total_paginas:
            pagina = total_paginas
        offset = (pagina - 1) * POR_PAGINA

        # ---------- Notas da pagina ----------
        cur.execute(
            f"""
            SELECT v.id, v.chave, v.modelo, v.serie, v.numero, v.dh_emissao,
                   v.cnpj_emitente, v.vendedor_raw, v.cliente_doc, v.cliente_nome,
                   v.valor_total, v.forma_pagamento, v.situacao, v.origem
            FROM vendas_xml v
            {where_sql}
            ORDER BY v.dh_emissao DESC, v.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [POR_PAGINA, offset],
        )
        notas = cur.fetchall()

        # ---------- Itens das notas exibidas (1 query, sem N+1) — p/ cards mobile ----------
        itens_por_venda = {}
        ids = [n['id'] for n in notas]
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                SELECT venda_id, n_item, produto_xml, cod_anp,
                       unidade, quantidade, valor_unitario, valor_total
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

        # Querystring dos filtros (sem 'page') para os links de paginacao.
        qs_filtros = urlencode({k: v for k, v in f.items() if v})

        return render_template(
            'vendas/index.html',
            notas=notas,
            itens_por_venda=itens_por_venda,
            totais=totais,
            filtros=f,
            data_ini_default=data_ini_default,
            data_fim_default=data_fim_default,
            pagina=pagina,
            total_paginas=total_paginas,
            por_pagina=POR_PAGINA,
            paginas=_janela_paginas(pagina, total_paginas),
            qs_filtros=qs_filtros,
        )
    finally:
        cur.close()
        conn.close()


@vendas_bp.route('/<int:venda_id>', methods=['GET'])
@login_required
def detalhe(venda_id):
    """Detalhe SOMENTE-LEITURA de uma venda, no layout de nota."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM vendas_xml WHERE id = %s", (venda_id,))
        nota = cur.fetchone()
        if not nota:
            abort(404)
        cur.execute(
            "SELECT * FROM vendas_xml_itens WHERE venda_id = %s ORDER BY n_item",
            (venda_id,),
        )
        itens = cur.fetchall()
        return render_template('vendas/detalhe.html', nota=nota, itens=itens)
    finally:
        cur.close()
        conn.close()
