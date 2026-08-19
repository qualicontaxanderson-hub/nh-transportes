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

from flask import Blueprint, render_template, request, abort, jsonify
from flask_login import login_required

from utils.db import get_db_connection
from utils.pagamentos import classificar_recebimento

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
        autorizadas = totais['notas'] - totais['canceladas']
        totais['ticket'] = (float(totais['valor']) / autorizadas
                            if autorizadas > 0 else 0)

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
                   v.valor_total, v.forma_pagamento, v.situacao, v.origem,
                   v.card_bandeira, v.card_credenciadora, v.card_autorizacao, v.tef_terminal
            FROM vendas_xml v
            {where_sql}
            ORDER BY v.dh_emissao DESC, v.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [POR_PAGINA, offset],
        )
        notas = cur.fetchall()

        # Classe de RECEBIMENTO (coluna nova; NAO altera forma_pagamento cru nem o filtro).
        for n in notas:
            n['recebimento'] = classificar_recebimento(
                n.get('forma_pagamento'), n.get('card_bandeira'),
                n.get('card_credenciadora'), n.get('card_autorizacao'),
                n.get('tef_terminal'), n.get('cliente_doc'))

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

        # ---------- Faixas por dia (cabecalho de cada grupo da lista) ----
        # Conta sobre TODO o filtro, nao so a pagina: se um dia quebra entre
        # paginas, a faixa ainda mostra o total do dia inteiro.
        _DIAS_SEM = ('Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta',
                     'Sábado', 'Domingo')
        dias = {}
        dias_pg = sorted({n['dh_emissao'].date() for n in notas
                          if n.get('dh_emissao')})
        if dias_pg:
            ph = ",".join(["%s"] * len(dias_pg))
            cond = where + [f"DATE(v.dh_emissao) IN ({ph})"]
            cur.execute(
                f"""
                SELECT DATE(v.dh_emissao) AS dia, COUNT(*) AS n,
                       COALESCE(SUM(CASE WHEN v.situacao <> 'cancelada'
                                         THEN v.valor_total ELSE 0 END), 0) AS valor
                FROM vendas_xml v
                WHERE {" AND ".join(cond)}
                GROUP BY dia
                """,
                params + dias_pg,
            )
            for r in cur.fetchall():
                d = r['dia']
                dias[d] = {'rot': _DIAS_SEM[d.weekday()] + ' · '
                                  + d.strftime('%d/%m'),
                           'n': r['n'], 'valor': float(r['valor'] or 0)}

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
            dias=dias,
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
    """Detalhe SOMENTE-LEITURA de uma venda, no layout de nota.

    ?partial=1 -> retorna apenas o fragmento (para carregar no modal via fetch).
    Sem o parametro -> pagina completa (link direto / fallback).
    """
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
        template = ('vendas/_detalhe_conteudo.html'
                    if request.args.get('partial') else 'vendas/detalhe.html')
        return render_template(template, nota=nota, itens=itens)
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# CLASSIFICAR: de-para de produto da venda (cnpj_emitente + cprod -> produto_id).
# Espelha a Classificar de COMPRAS (routes/dfe_compras), SEM categoria (venda e
# sempre produto) e com chave = cnpj_emitente (a venda nao tem cliente_id).
#   AREA 1 "Classificar" -> cprods SEM regra no de-para, agrupados por
#                           cnpj_emitente + cprod.  Memorizar / So desta vez.
#   AREA 2 "Regras"       -> de-para memorizado (ver/editar/apagar).
# ==========================================================================
@vendas_bp.route('/classificar', methods=['GET'])
@login_required
def classificar():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos = cur.fetchall()

        # ---------- AREA 1: cprods SEM regra no de-para ----------
        cur.execute(
            """
            SELECT v.cnpj_emitente,
                   i.cprod,
                   MAX(i.produto_xml) AS xprod,
                   MAX(i.cod_anp)     AS cod_anp,
                   COUNT(*)           AS itens,
                   ROUND(SUM(CASE WHEN i.unidade = 'L'
                                  THEN i.quantidade ELSE 0 END), 0) AS litros,
                   MAX(COALESCE(cl.nome_fantasia, cl.razao_social,
                                v.cnpj_emitente)) AS emitente_nome
            FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            LEFT JOIN vendas_xml_depara_produto dp
                   ON dp.cnpj_emitente = v.cnpj_emitente
                  AND dp.cprod = i.cprod
                  AND dp.ativo = 1
            LEFT JOIN clientes cl
                   ON REPLACE(REPLACE(REPLACE(cl.cnpj, '.', ''), '/', ''), '-', '')
                      = v.cnpj_emitente
            WHERE dp.id IS NULL
              AND i.cprod IS NOT NULL AND i.cprod <> ''
            GROUP BY v.cnpj_emitente, i.cprod
            ORDER BY litros DESC, itens DESC
            """
        )
        pendentes = cur.fetchall()

        # ---------- AREA 2: regras memorizadas (de-para) ----------
        cur.execute(
            """
            SELECT dp.id, dp.cnpj_emitente, dp.cprod, dp.produto_id, dp.ativo,
                   p.nome AS produto_nome,
                   MAX(COALESCE(cl.nome_fantasia, cl.razao_social,
                                dp.cnpj_emitente)) AS emitente_nome,
                   (SELECT i.produto_xml
                      FROM vendas_xml_itens i
                      JOIN vendas_xml v ON v.id = i.venda_id
                     WHERE v.cnpj_emitente = dp.cnpj_emitente
                       AND i.cprod = dp.cprod
                       AND i.produto_xml IS NOT NULL
                     ORDER BY i.id DESC LIMIT 1) AS xprod
            FROM vendas_xml_depara_produto dp
            LEFT JOIN produto p ON p.id = dp.produto_id
            LEFT JOIN clientes cl
                   ON REPLACE(REPLACE(REPLACE(cl.cnpj, '.', ''), '/', ''), '-', '')
                      = dp.cnpj_emitente
            GROUP BY dp.id, dp.cnpj_emitente, dp.cprod, dp.produto_id, dp.ativo, p.nome
            ORDER BY emitente_nome, dp.cprod
            """
        )
        regras = cur.fetchall()

        # Agrupa regras por emitente (accordion), preservando a ordem.
        emitentes_regras = []
        _idx = {}
        for r in regras:
            ck = r['cnpj_emitente'] or ''
            if ck not in _idx:
                _idx[ck] = len(emitentes_regras)
                emitentes_regras.append({
                    'cnpj_emitente': r['cnpj_emitente'],
                    'nome': r['emitente_nome'],
                    'regras': [],
                })
            emitentes_regras[_idx[ck]]['regras'].append(r)

        litros_pend = sum(float(p['litros'] or 0) for p in pendentes)
        itens_pend = sum(int(p['itens'] or 0) for p in pendentes)

        return render_template(
            'vendas/classificar.html',
            produtos=produtos,
            pendentes=pendentes,
            regras=regras,
            emitentes_regras=emitentes_regras,
            litros_pend=litros_pend,
            itens_pend=itens_pend,
        )
    finally:
        cur.close()
        conn.close()


def _produto_valido(cur, produto_id):
    """produto_id inteiro que existe em `produto`, ou None."""
    try:
        pid = int(produto_id) if produto_id not in (None, '', '0') else None
    except (TypeError, ValueError):
        return None
    if not pid:
        return None
    cur.execute("SELECT id FROM produto WHERE id = %s", (pid,))
    return pid if cur.fetchone() else None


@vendas_bp.route('/classificar', methods=['POST'])
@login_required
def classificar_gravar():
    """Memorizar (grava regra + retroativo) ou So-desta-vez (so retroativo).
    Chave = cnpj_emitente + cprod (o grupo listado na aba)."""
    dados = request.get_json(silent=True) or {}
    cnpj = (dados.get('cnpj_emitente') or '').strip()
    cprod = (dados.get('cprod') or '').strip()
    modo = (dados.get('modo') or '').strip()  # 'memorizar' | 'so_desta_vez'

    if not cnpj or not cprod:
        return jsonify({'ok': False, 'erro': 'cnpj_emitente/cprod ausente'}), 400
    if modo not in ('memorizar', 'so_desta_vez'):
        return jsonify({'ok': False, 'erro': 'modo inválido'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        produto_id = _produto_valido(cur, dados.get('produto_id'))
        if not produto_id:
            return jsonify({'ok': False, 'erro': 'escolha um produto válido'}), 400

        # Trava: o par (cnpj_emitente, cprod) precisa existir nas vendas.
        cur.execute(
            """
            SELECT 1 FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            WHERE v.cnpj_emitente = %s AND i.cprod = %s LIMIT 1
            """,
            (cnpj, cprod),
        )
        if not cur.fetchone():
            return jsonify({'ok': False, 'erro': 'cprod não encontrado nas vendas'}), 404

        regra_gravada = False
        if modo == 'memorizar':
            cur.execute(
                """
                INSERT INTO vendas_xml_depara_produto (cnpj_emitente, cprod, produto_id, ativo)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE produto_id = VALUES(produto_id), ativo = 1
                """,
                (cnpj, cprod, produto_id),
            )
            regra_gravada = True

        # Retroativo: preenche os itens iguais (null-safe -> so o que muda).
        cur.execute(
            """
            UPDATE vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
               SET i.produto_id = %s
             WHERE v.cnpj_emitente = %s AND i.cprod = %s
               AND NOT (i.produto_id <=> %s)
            """,
            (produto_id, cnpj, cprod, produto_id),
        )
        tambem = cur.rowcount or 0
        conn.commit()

        cur.execute("SELECT nome FROM produto WHERE id = %s", (produto_id,))
        row = cur.fetchone()
        return jsonify({
            'ok': True,
            'regra_gravada': regra_gravada,
            'produto_id': produto_id,
            'produto_nome': row['nome'] if row else None,
            'tambem': tambem,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@vendas_bp.route('/regras/editar', methods=['POST'])
@login_required
def editar_regra():
    """Edita o produto de UMA regra do de-para. Alcance:
       'proximos' -> muda so a regra (vale p/ capturas futuras).
       'tudo'     -> muda a regra E reclassifica os itens desse cnpj+cprod.
    cnpj_emitente/cprod vem SEMPRE da regra (server-side)."""
    dados = request.get_json(silent=True) or {}
    try:
        regra_id = int(dados.get('regra_id') or 0)
    except (TypeError, ValueError):
        regra_id = 0
    alcance = (dados.get('alcance') or '').strip()

    if not regra_id:
        return jsonify({'ok': False, 'erro': 'regra_id ausente'}), 400
    if alcance not in ('proximos', 'tudo'):
        return jsonify({'ok': False, 'erro': 'alcance inválido'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        produto_id = _produto_valido(cur, dados.get('produto_id'))
        if not produto_id:
            return jsonify({'ok': False, 'erro': 'escolha um produto válido'}), 400

        cur.execute(
            "SELECT cnpj_emitente, cprod FROM vendas_xml_depara_produto WHERE id = %s",
            (regra_id,),
        )
        regra = cur.fetchone()
        if not regra:
            return jsonify({'ok': False, 'erro': 'regra não encontrada'}), 404

        cur.execute(
            "UPDATE vendas_xml_depara_produto SET produto_id = %s WHERE id = %s",
            (produto_id, regra_id),
        )

        tambem = 0
        if alcance == 'tudo':
            cur.execute(
                """
                UPDATE vendas_xml_itens i
                JOIN vendas_xml v ON v.id = i.venda_id
                   SET i.produto_id = %s
                 WHERE v.cnpj_emitente = %s AND i.cprod = %s
                   AND NOT (i.produto_id <=> %s)
                """,
                (produto_id, regra['cnpj_emitente'], regra['cprod'], produto_id),
            )
            tambem = cur.rowcount or 0
        conn.commit()

        cur.execute("SELECT nome FROM produto WHERE id = %s", (produto_id,))
        row = cur.fetchone()
        return jsonify({
            'ok': True, 'regra_id': regra_id, 'alcance': alcance,
            'produto_id': produto_id, 'produto_nome': row['nome'] if row else None,
            'tambem': tambem,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@vendas_bp.route('/regras/apagar', methods=['POST'])
@login_required
def apagar_regra():
    """Apaga UMA regra do de-para. NAO desfaz o produto_id ja gravado nos itens
    (igual ao comportamento da compra)."""
    dados = request.get_json(silent=True) or {}
    try:
        regra_id = int(dados.get('regra_id') or 0)
    except (TypeError, ValueError):
        regra_id = 0
    if not regra_id:
        return jsonify({'ok': False, 'erro': 'regra_id ausente'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("DELETE FROM vendas_xml_depara_produto WHERE id = %s", (regra_id,))
        conn.commit()
        return jsonify({'ok': True, 'apagou': cur.rowcount or 0})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()
