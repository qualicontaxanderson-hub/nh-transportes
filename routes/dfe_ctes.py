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
        'empresa':        (request.args.get('empresa') or '').strip(),
        'data_ini':       (request.args.get('data_ini') or '').strip(),
        'data_fim':       (request.args.get('data_fim') or '').strip(),
        'transportadora': (request.args.get('transportadora') or '').strip(),
        'tomador':        (request.args.get('tomador') or '').strip(),
    }
    # Filtros em LISTA da gaveta em passos; os de texto continuam validos.
    f_emp = [v for v in request.args.getlist('emp') if v.strip().isdigit()]
    f_transp = [v for v in request.args.getlist('transp') if v.strip()]
    f_toma = [v for v in request.args.getlist('toma') if v.strip()]
    try:
        pagina = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        pagina = 1

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        where = ["d.tipo = 'CTe'"]
        params = []
        if f['empresa']:
            where.append("d.cliente_id = %s"); params.append(f['empresa'])
        if f['data_ini']:
            where.append("d.dh_emissao >= %s"); params.append(f['data_ini'] + " 00:00:00")
        if f['data_fim']:
            where.append("d.dh_emissao <= %s"); params.append(f['data_fim'] + " 23:59:59")
        if f['transportadora']:
            where.append("d.emit_nome LIKE %s"); params.append(f"%{f['transportadora']}%")
        if f['tomador']:
            where.append("c.toma_nome LIKE %s"); params.append(f"%{f['tomador']}%")
        if f_emp:
            ph = ",".join(["%s"] * len(f_emp))
            where.append(f"d.cliente_id IN ({ph})"); params.extend(f_emp)
        if f_transp:
            ph = ",".join(["%s"] * len(f_transp))
            where.append(f"d.emit_cnpj IN ({ph})"); params.extend(f_transp)
        if f_toma:
            ph = ",".join(["%s"] * len(f_toma))
            where.append(f"c.toma_cnpj IN ({ph})"); params.extend(f_toma)
        where_sql = " WHERE " + " AND ".join(where)

        # ---------- Totais (qtd + soma do frete) ----------
        cur.execute(
            f"""
            SELECT COUNT(*) AS total_ctes,
                   COALESCE(SUM(COALESCE(c.vprest, d.valor_total)), 0) AS total_frete,
                   COALESCE(SUM(CASE WHEN d.situacao IN ('cancelada', 'denegada')
                                     THEN 1 ELSE 0 END), 0) AS cancelados
            FROM dfe_documentos d
            LEFT JOIN dfe_cte c ON c.documento_id = d.id
            {where_sql}
            """,
            params,
        )
        agg = cur.fetchone() or {}
        totais = {'ctes': agg.get('total_ctes') or 0,
                  'frete': agg.get('total_frete') or 0,
                  'cancelados': int(agg.get('cancelados') or 0)}
        totais['medio'] = (float(totais['frete']) / totais['ctes']
                           if totais['ctes'] else 0)

        # Faixas por dia (cabecalho dos grupos da lista).
        _DIAS_SEM = ('Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta',
                     'Sábado', 'Domingo')
        cur.execute(
            f"""
            SELECT DATE(d.dh_emissao) AS dia, COUNT(*) AS n,
                   COALESCE(SUM(COALESCE(c.vprest, d.valor_total)), 0) AS frete
            FROM dfe_documentos d
            LEFT JOIN dfe_cte c ON c.documento_id = d.id
            {where_sql}
            GROUP BY dia
            """,
            params,
        )
        dias = {}
        for r in cur.fetchall():
            d2 = r['dia']
            dias[d2] = {'rot': _DIAS_SEM[d2.weekday()] + ' · ' + d2.strftime('%d/%m'),
                        'n': r['n'], 'frete': float(r['frete'] or 0)}

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
                   c.toma_nome, c.toma_cnpj, c.motorista_nome, c.placa,
                   COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome,
                   COALESCE(c.vprest, d.valor_total) AS frete,
                   (SELECT COUNT(*) FROM dfe_cte_nfe n WHERE n.documento_id = d.id) AS qt_nfe
            FROM dfe_documentos d
            LEFT JOIN dfe_cte c ON c.documento_id = d.id
            LEFT JOIN clientes emp ON emp.id = d.cliente_id
            {where_sql}
            ORDER BY d.dh_emissao DESC, d.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [POR_PAGINA, offset],
        )
        ctes = cur.fetchall()

        # Empresas que TEM CT-e (para o dropdown de filtro por empresa).
        cur.execute(
            """SELECT DISTINCT d.cliente_id AS id,
                      COALESCE(emp.nome_fantasia, emp.razao_social) AS nome
                 FROM dfe_documentos d
                 JOIN clientes emp ON emp.id = d.cliente_id
                WHERE d.tipo = 'CTe'
                ORDER BY nome"""
        )
        empresas = cur.fetchall()

        # Opcoes da gaveta (contagens globais de CT-e).
        cur.execute(
            """SELECT d.emit_cnpj AS cnpj,
                      SUBSTRING_INDEX(GROUP_CONCAT(d.emit_nome SEPARATOR '||'), '||', 1) AS nome,
                      COUNT(*) AS n
                 FROM dfe_documentos d
                WHERE d.tipo = 'CTe' AND d.emit_cnpj <> ''
                GROUP BY d.emit_cnpj ORDER BY n DESC"""
        )
        op_transp = cur.fetchall()
        cur.execute(
            """SELECT c.toma_cnpj AS cnpj,
                      SUBSTRING_INDEX(GROUP_CONCAT(c.toma_nome SEPARATOR '||'), '||', 1) AS nome,
                      COUNT(*) AS n
                 FROM dfe_documentos d
                 JOIN dfe_cte c ON c.documento_id = d.id
                WHERE d.tipo = 'CTe' AND c.toma_cnpj IS NOT NULL AND c.toma_cnpj <> ''
                GROUP BY c.toma_cnpj ORDER BY n DESC"""
        )
        op_toma = cur.fetchall()
        cur.execute(
            """SELECT d.cliente_id AS id, COUNT(*) AS n
                 FROM dfe_documentos d
                WHERE d.tipo = 'CTe' AND d.cliente_id IS NOT NULL
                GROUP BY d.cliente_id"""
        )
        emp_n = {r['id']: r['n'] for r in cur.fetchall()}

        n_filtros = (sum(1 for k in f if f[k])
                     + (1 if f_emp else 0) + (1 if f_transp else 0)
                     + (1 if f_toma else 0))

        hoje = date.today()
        data_ini_default = f['data_ini'] or (hoje - timedelta(days=90)).strftime('%Y-%m-%d')
        data_fim_default = f['data_fim'] or hoje.strftime('%Y-%m-%d')
        qs_filtros = urlencode(
            [(k, v) for k, v in f.items() if v]
            + [('emp', v) for v in f_emp]
            + [('transp', v) for v in f_transp]
            + [('toma', v) for v in f_toma]
        )

        return render_template(
            'dfe_ctes/index.html',
            ctes=ctes, totais=totais, filtros=f, empresas=empresas,
            dias=dias, op_transp=op_transp, op_toma=op_toma, emp_n=emp_n,
            f_emp=f_emp, f_transp=f_transp, f_toma=f_toma, n_filtros=n_filtros,
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
