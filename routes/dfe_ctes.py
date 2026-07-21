"""
Tela CT-e MIGRADOS: listagem + detalhe dos CT-e capturados do DFe da SEFAZ.
ISOLADA, aditiva, SOMENTE VISUALIZACAO.

Rotas:
  GET /dfe/ctes         -> lista paginada (100/pag) com filtros e totais
  GET /dfe/ctes/<id>    -> detalhe (modal via ?partial=1; pagina cheia sem o param)

Le dfe_documentos WHERE tipo='CTe' + LEFT JOIN dfe_cte (specifics) + dfe_cte_nfe
(NF-e vinculadas). Resumos (resCTe) tambem aparecem (ainda sem specifics -> LEFT JOIN).

Padroes do app: blueprint *_bp (auto-registro), @login_required,
get_db_connection() + cursor(dictionary=True), SQL 100% parametrizado (%s).
NAO altera nada existente; NAO toca na captura nem nas tabelas.
"""
import math
from datetime import date, timedelta
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, abort
from flask_login import login_required

from utils.db import get_db_connection

dfe_ctes_bp = Blueprint('dfe_ctes', __name__, url_prefix='/dfe')

POR_PAGINA = 100


def _janela_paginas(pagina, total_paginas, raio=2):
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


@dfe_ctes_bp.route('/ctes', methods=['GET'])
@login_required
def index():
    f = {
        'data_ini':       (request.args.get('data_ini') or '').strip(),
        'data_fim':       (request.args.get('data_fim') or '').strip(),
        'transportadora': (request.args.get('transportadora') or '').strip(),
        'tomador':        (request.args.get('tomador') or '').strip(),
    }
    try:
        pagina = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        pagina = 1

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        where = ["d.tipo = 'CTe'"]
        params = []
        if f['data_ini']:
            where.append("d.dh_emissao >= %s"); params.append(f['data_ini'] + " 00:00:00")
        if f['data_fim']:
            where.append("d.dh_emissao <= %s"); params.append(f['data_fim'] + " 23:59:59")
        if f['transportadora']:
            where.append("d.emit_nome LIKE %s"); params.append(f"%{f['transportadora']}%")
        if f['tomador']:
            where.append("c.toma_nome LIKE %s"); params.append(f"%{f['tomador']}%")
        where_sql = " WHERE " + " AND ".join(where)

        # ---------- Totais (qtd + soma do frete) ----------
        cur.execute(
            f"""
            SELECT COUNT(*) AS total_ctes,
                   COALESCE(SUM(COALESCE(c.vprest, d.valor_total)), 0) AS total_frete
            FROM dfe_documentos d
            LEFT JOIN dfe_cte c ON c.documento_id = d.id
            {where_sql}
            """,
            params,
        )
        agg = cur.fetchone() or {}
        totais = {'ctes': agg.get('total_ctes') or 0, 'frete': agg.get('total_frete') or 0}

        total_ctes = totais['ctes'] or 0
        total_paginas = max(1, math.ceil(total_ctes / POR_PAGINA))
        if pagina > total_paginas:
            pagina = total_paginas
        offset = (pagina - 1) * POR_PAGINA

        # ---------- CT-e da pagina ----------
        cur.execute(
            f"""
            SELECT d.id, d.chave, d.numero, d.serie, d.dh_emissao, d.emit_cnpj,
                   d.emit_nome, d.valor_total, d.situacao, d.resumo,
                   c.mun_ini, c.uf_ini, c.mun_fim, c.uf_fim, c.vprest,
                   c.toma_nome, c.toma_cnpj,
                   COALESCE(c.vprest, d.valor_total) AS frete,
                   (SELECT COUNT(*) FROM dfe_cte_nfe n WHERE n.documento_id = d.id) AS qt_nfe
            FROM dfe_documentos d
            LEFT JOIN dfe_cte c ON c.documento_id = d.id
            {where_sql}
            ORDER BY d.dh_emissao DESC, d.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [POR_PAGINA, offset],
        )
        ctes = cur.fetchall()

        hoje = date.today()
        data_ini_default = f['data_ini'] or (hoje - timedelta(days=90)).strftime('%Y-%m-%d')
        data_fim_default = f['data_fim'] or hoje.strftime('%Y-%m-%d')
        qs_filtros = urlencode({k: v for k, v in f.items() if v})

        return render_template(
            'dfe_ctes/index.html',
            ctes=ctes, totais=totais, filtros=f,
            data_ini_default=data_ini_default, data_fim_default=data_fim_default,
            pagina=pagina, total_paginas=total_paginas, por_pagina=POR_PAGINA,
            paginas=_janela_paginas(pagina, total_paginas), qs_filtros=qs_filtros,
        )
    finally:
        cur.close()
        conn.close()


@dfe_ctes_bp.route('/ctes/<int:cte_id>', methods=['GET'])
@login_required
def detalhe(cte_id):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM dfe_documentos WHERE id = %s AND tipo = 'CTe'", (cte_id,))
        doc = cur.fetchone()
        if not doc:
            abort(404)
        cur.execute("SELECT * FROM dfe_cte WHERE documento_id = %s", (cte_id,))
        cte = cur.fetchone()   # None se for resumo (resCTe ainda sem specifics)
        cur.execute(
            """
            SELECT n.chave_nfe, dd.id AS nfe_doc_id, dd.numero AS nfe_numero,
                   dd.emit_nome AS nfe_emit, dd.valor_total AS nfe_valor
            FROM dfe_cte_nfe n
            LEFT JOIN dfe_documentos dd
                   ON dd.chave = n.chave_nfe AND dd.tipo = 'NFe'
            WHERE n.documento_id = %s
            ORDER BY n.id
            """,
            (cte_id,),
        )
        nfes = cur.fetchall()
        template = ('dfe_ctes/_detalhe_conteudo.html'
                    if request.args.get('partial') else 'dfe_ctes/detalhe.html')
        return render_template(template, doc=doc, cte=cte, nfes=nfes)
    finally:
        cur.close()
        conn.close()
