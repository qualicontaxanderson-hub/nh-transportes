"""
Tela ESTOQUE MIGRADOS: leituras de tanque (medicoes/estoque) + descargas
capturadas do ELS por e-mail. ISOLADA, aditiva, SOMENTE VISUALIZACAO.

Rota:
  GET /estoque -> uma pagina, duas abas (Leituras / Descargas), filtros e totais

Le leitura_tanque_diaria e descargas_pendentes. Padroes do app: blueprint *_bp
(auto-registro), @login_required, get_db_connection() + cursor(dictionary=True),
SQL 100% parametrizado (%s). NAO altera nada existente.

Terreno para as PROXIMAS camadas (ainda NAO implementadas aqui):
  - aba Descargas tem uma coluna "Acoes" e uma toolbar reservadas para os botoes
    "Vincular nota" (por linha pendente), "Lancar descarga manual" e
    "Inserir/editar estoque manual". A regra de negocio e que toda descarga
    acabe vinculada a uma nota de compra (por e-mail ou manual).
"""
import math
from datetime import date, timedelta
from urllib.parse import urlencode

from flask import Blueprint, render_template, request
from flask_login import login_required

from utils.db import get_db_connection

estoque_bp = Blueprint('estoque', __name__)

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


@estoque_bp.route('/estoque', methods=['GET'])
@login_required
def index():
    f = {
        'empresa':  (request.args.get('empresa') or '').strip(),
        'data_ini': (request.args.get('data_ini') or '').strip(),
        'data_fim': (request.args.get('data_fim') or '').strip(),
    }
    tab = (request.args.get('tab') or 'leituras').strip()
    if tab not in ('leituras', 'descargas'):
        tab = 'leituras'
    try:
        page_l = max(1, int(request.args.get('page_l', 1)))
    except (TypeError, ValueError):
        page_l = 1
    try:
        page_d = max(1, int(request.args.get('page_d', 1)))
    except (TypeError, ValueError):
        page_d = 1

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # -------- WHERE compartilhado (empresa + datas) --------
        w_l, p_l, w_d, p_d = [], [], [], []
        if f['empresa']:
            w_l.append("l.cliente_id = %s"); p_l.append(f['empresa'])
            w_d.append("d.cliente_id = %s"); p_d.append(f['empresa'])
        if f['data_ini']:
            w_l.append("l.data_leitura >= %s"); p_l.append(f['data_ini'] + " 00:00:00")
            w_d.append("COALESCE(d.data_final, d.data_inicial, d.data_descarga) >= %s")
            p_d.append(f['data_ini'] + " 00:00:00")
        if f['data_fim']:
            w_l.append("l.data_leitura <= %s"); p_l.append(f['data_fim'] + " 23:59:59")
            w_d.append("COALESCE(d.data_final, d.data_inicial, d.data_descarga) <= %s")
            p_d.append(f['data_fim'] + " 23:59:59")
        where_l = (" WHERE " + " AND ".join(w_l)) if w_l else ""
        where_d = (" WHERE " + " AND ".join(w_d)) if w_d else ""

        # -------- Totais --------
        cur.execute(f"SELECT COUNT(*) AS n FROM leitura_tanque_diaria l{where_l}", p_l)
        total_leituras = (cur.fetchone() or {}).get('n') or 0
        cur.execute(
            f"""SELECT COUNT(*) AS n, COALESCE(SUM(d.total_descarga), 0) AS litros
                FROM descargas_pendentes d{where_d}""",
            p_d,
        )
        agg_d = cur.fetchone() or {}
        totais = {
            'leituras':  total_leituras,
            'descargas': agg_d.get('n') or 0,
            'litros':    agg_d.get('litros') or 0,
        }

        # -------- Leituras (paginada) --------
        tp_l = max(1, math.ceil(total_leituras / POR_PAGINA))
        page_l = min(page_l, tp_l)
        cur.execute(
            f"""
            SELECT l.id, l.data_leitura, l.titulo, l.tanque, l.produto_nome,
                   l.volume_atual, l.volume_20c, l.capacidade, l.temperatura,
                   COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
            FROM leitura_tanque_diaria l
            LEFT JOIN clientes emp ON emp.id = l.cliente_id
            {where_l}
            ORDER BY l.data_leitura DESC, l.tanque ASC
            LIMIT %s OFFSET %s
            """,
            p_l + [POR_PAGINA, (page_l - 1) * POR_PAGINA],
        )
        leituras = cur.fetchall()

        # -------- Descargas (paginada) --------
        tp_d = max(1, math.ceil(totais['descargas'] / POR_PAGINA))
        page_d = min(page_d, tp_d)
        cur.execute(
            f"""
            SELECT d.id, d.data_final, d.data_inicial, d.data_descarga, d.tanque,
                   d.produto_nome, d.total_descarga, d.total_descarga_20c,
                   d.status, d.frete_id,
                   COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome
            FROM descargas_pendentes d
            LEFT JOIN clientes emp ON emp.id = d.cliente_id
            {where_d}
            ORDER BY COALESCE(d.data_final, d.data_inicial, d.data_descarga) DESC, d.id DESC
            LIMIT %s OFFSET %s
            """,
            p_d + [POR_PAGINA, (page_d - 1) * POR_PAGINA],
        )
        descargas = cur.fetchall()

        # -------- Empresas p/ dropdown (uniao dos dois) --------
        cur.execute(
            """
            SELECT DISTINCT c.id, COALESCE(c.nome_fantasia, c.razao_social) AS nome
            FROM clientes c
            WHERE c.id IN (
                SELECT cliente_id FROM leitura_tanque_diaria WHERE cliente_id IS NOT NULL
                UNION
                SELECT cliente_id FROM descargas_pendentes  WHERE cliente_id IS NOT NULL
            )
            ORDER BY nome
            """
        )
        empresas = cur.fetchall()

        hoje = date.today()
        data_ini_default = f['data_ini'] or (hoje - timedelta(days=90)).strftime('%Y-%m-%d')
        data_fim_default = f['data_fim'] or hoje.strftime('%Y-%m-%d')
        qs_filtros = urlencode({k: v for k, v in f.items() if v})

        return render_template(
            'estoque/index.html',
            leituras=leituras, descargas=descargas, totais=totais,
            filtros=f, empresas=empresas, tab=tab,
            data_ini_default=data_ini_default, data_fim_default=data_fim_default,
            page_l=page_l, tp_l=tp_l, paginas_l=_janela_paginas(page_l, tp_l),
            page_d=page_d, tp_d=tp_d, paginas_d=_janela_paginas(page_d, tp_d),
            qs_filtros=qs_filtros,
        )
    finally:
        cur.close()
        conn.close()
