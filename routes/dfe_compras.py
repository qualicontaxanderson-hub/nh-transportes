"""
Tela de CLASSIFICACAO DE COMPRAS do servico DFe.  ISOLADA, aditiva.

Rota: /dfe/compras  (acesso por URL; ainda sem item de menu)

Duas areas na mesma pagina:
  AREA 1 "Classificar" -> itens pendentes (dfe_itens.categoria IS NULL), agrupados
                          por nota (mais recente em cima). Por item o usuario escolhe
                          categoria (e produto, se combustivel) e:
                            - "Memorizar"    -> grava regra + classifica (modo memorizado)
                            - "So desta vez" -> classifica so o item (modo so_desta_vez)
  AREA 2 "Consultar"  -> mega-filtros sobre os itens ja gravados, com totais (R$ e litros).

Padroes do app: blueprint *_bp (auto-registro), @login_required, CSRF normal
(o base.html injeta o token em forms/fetch), get_db_connection() + cursor(dictionary=True),
SQL 100% parametrizado (%s). NAO altera nada existente.
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from utils.db import get_db_connection

dfe_compras_bp = Blueprint('dfe_compras', __name__, url_prefix='/dfe')

# Categorias possiveis: (valor gravado, rotulo exibido).
CATEGORIAS = [
    ('combustivel', 'Combustível'),
    ('despesa',     'Despesa'),
    ('ativo',       'Ativo Imobilizado'),
    ('produto',     'Produto/Lubrificante'),
]
_CATEGORIAS_VALIDAS = {c[0] for c in CATEGORIAS}


def _produtos(cur):
    """Lista de produtos para o dropdown de combustivel."""
    cur.execute("SELECT id, nome FROM produto ORDER BY nome")
    return cur.fetchall()


# ==========================================================================
# PAGINA PRINCIPAL: Classificar (pendentes) + Consultar (filtros).
# ==========================================================================
@dfe_compras_bp.route('/compras', methods=['GET'])
@login_required
def compras():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        produtos = _produtos(cur)

        # ---------- AREA 1: PENDENTES (categoria IS NULL), por nota ----------
        cur.execute(
            """
            SELECT d.id            AS doc_id,
                   d.chave, d.numero, d.serie, d.dh_emissao,
                   d.emit_nome, d.emit_cnpj, d.dest_cnpj,
                   d.valor_total   AS nota_valor,
                   d.situacao,
                   i.id            AS item_id,
                   i.n_item, i.produto_xml, i.cprod_fornecedor, i.cean,
                   i.ncm, i.cod_anp, i.unidade, i.quantidade,
                   i.valor_total   AS item_valor
            FROM dfe_documentos d
            JOIN dfe_itens i ON i.documento_id = d.id
            WHERE d.tipo = 'NFe' AND i.categoria IS NULL
            ORDER BY d.dh_emissao DESC, d.id DESC, i.n_item ASC
            """
        )
        linhas = cur.fetchall()

        # Agrupa itens por nota preservando a ordem (mais recente em cima).
        notas = []
        idx = {}
        for r in linhas:
            doc_id = r['doc_id']
            if doc_id not in idx:
                idx[doc_id] = len(notas)
                notas.append({
                    'doc_id': doc_id,
                    'chave': r['chave'],
                    'numero': r['numero'],
                    'serie': r['serie'],
                    'dh_emissao': r['dh_emissao'],
                    'emit_nome': r['emit_nome'],
                    'emit_cnpj': r['emit_cnpj'],
                    'nota_valor': r['nota_valor'],
                    'situacao': r['situacao'],
                    'itens': [],
                })
            notas[idx[doc_id]]['itens'].append({
                'item_id': r['item_id'],
                'n_item': r['n_item'],
                'produto_xml': r['produto_xml'],
                'cprod_fornecedor': r['cprod_fornecedor'],
                'cean': r['cean'],
                'ncm': r['ncm'],
                'cod_anp': r['cod_anp'],
                'unidade': r['unidade'],
                'quantidade': r['quantidade'],
                'item_valor': r['item_valor'],
            })

        # ---------- AREA 2: CONSULTAR (mega-filtros) ----------
        f = {
            'fornecedor':   (request.args.get('fornecedor') or '').strip(),
            'categoria':    (request.args.get('categoria') or '').strip(),
            'produto_id':   (request.args.get('produto_id') or '').strip(),
            'data_ini':     (request.args.get('data_ini') or '').strip(),
            'data_fim':     (request.args.get('data_fim') or '').strip(),
            'valor_min':    (request.args.get('valor_min') or '').strip(),
            'valor_max':    (request.args.get('valor_max') or '').strip(),
            'situacao':     (request.args.get('situacao') or '').strip(),
            'classificado': (request.args.get('classificado') or '').strip(),  # ''|sim|nao
            'ncm':          (request.args.get('ncm') or '').strip(),
        }
        filtrou = request.args.get('filtrar') == '1'

        resultados = []
        totais = {'valor': 0, 'litros': 0, 'itens': 0}
        LIMITE = 1000
        truncado = False

        if filtrou:
            where = ["d.tipo = 'NFe'"]
            params = []
            if f['fornecedor']:
                where.append("(d.emit_nome LIKE %s OR d.emit_cnpj LIKE %s)")
                termo = f"%{f['fornecedor']}%"
                params += [termo, termo]
            if f['categoria'] in _CATEGORIAS_VALIDAS:
                where.append("i.categoria = %s")
                params.append(f['categoria'])
            if f['produto_id']:
                where.append("i.classificado_produto_id = %s")
                params.append(f['produto_id'])
            if f['data_ini']:
                where.append("d.dh_emissao >= %s")
                params.append(f['data_ini'] + " 00:00:00")
            if f['data_fim']:
                where.append("d.dh_emissao <= %s")
                params.append(f['data_fim'] + " 23:59:59")
            if f['valor_min']:
                where.append("i.valor_total >= %s")
                params.append(f['valor_min'].replace(',', '.'))
            if f['valor_max']:
                where.append("i.valor_total <= %s")
                params.append(f['valor_max'].replace(',', '.'))
            if f['situacao']:
                where.append("d.situacao = %s")
                params.append(f['situacao'])
            if f['classificado'] == 'sim':
                where.append("i.categoria IS NOT NULL")
            elif f['classificado'] == 'nao':
                where.append("i.categoria IS NULL")
            if f['ncm']:
                where.append("i.ncm LIKE %s")
                params.append(f"%{f['ncm']}%")

            where_sql = " AND ".join(where)

            # Totais (independentes do LIMITE, sobre TODO o filtro).
            cur.execute(
                f"""
                SELECT COALESCE(SUM(i.valor_total), 0) AS total_valor,
                       COALESCE(SUM(CASE WHEN i.categoria = 'combustivel'
                                         THEN i.quantidade ELSE 0 END), 0) AS total_litros,
                       COUNT(*) AS total_itens
                FROM dfe_documentos d
                JOIN dfe_itens i ON i.documento_id = d.id
                WHERE {where_sql}
                """,
                params,
            )
            agg = cur.fetchone() or {}
            totais = {
                'valor': agg.get('total_valor') or 0,
                'litros': agg.get('total_litros') or 0,
                'itens': agg.get('total_itens') or 0,
            }

            # Linhas (limitadas para nao estourar a tela).
            cur.execute(
                f"""
                SELECT d.chave, d.numero, d.serie, d.dh_emissao,
                       d.emit_nome, d.emit_cnpj, d.situacao,
                       i.id AS item_id, i.produto_xml, i.cprod_fornecedor,
                       i.ncm, i.cod_anp, i.unidade, i.quantidade,
                       i.valor_total AS item_valor, i.categoria,
                       i.classificado_produto_id, i.classificado_modo,
                       p.nome AS produto_nome
                FROM dfe_documentos d
                JOIN dfe_itens i ON i.documento_id = d.id
                LEFT JOIN produto p ON p.id = i.classificado_produto_id
                WHERE {where_sql}
                ORDER BY d.dh_emissao DESC, i.n_item ASC
                LIMIT %s
                """,
                params + [LIMITE],
            )
            resultados = cur.fetchall()
            truncado = len(resultados) >= LIMITE and (totais['itens'] or 0) > LIMITE

        # Rotulos de categoria para exibicao.
        rot_categoria = dict(CATEGORIAS)

        # Padroes uteis para o form (periodo dos ultimos 90 dias, sem forcar).
        hoje = date.today()
        data_ini_default = f['data_ini'] or (hoje - timedelta(days=90)).strftime('%Y-%m-%d')
        data_fim_default = f['data_fim'] or hoje.strftime('%Y-%m-%d')

        aba = request.args.get('aba') or ('consultar' if filtrou else 'classificar')

        return render_template(
            'dfe_compras/index.html',
            notas=notas,
            total_pendentes_itens=len(linhas),
            total_pendentes_notas=len(notas),
            produtos=produtos,
            categorias=CATEGORIAS,
            rot_categoria=rot_categoria,
            filtros=f,
            filtrou=filtrou,
            resultados=resultados,
            totais=totais,
            truncado=truncado,
            limite=LIMITE,
            data_ini_default=data_ini_default,
            data_fim_default=data_fim_default,
            aba=aba,
        )
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# ACAO: classificar UM item (AJAX/JSON). Memorizar regra ou so desta vez.
# ==========================================================================
@dfe_compras_bp.route('/compras/classificar', methods=['POST'])
@login_required
def classificar():
    dados = request.get_json(silent=True) or {}
    try:
        item_id = int(dados.get('item_id') or 0)
    except (TypeError, ValueError):
        item_id = 0
    categoria = (dados.get('categoria') or '').strip()
    modo = (dados.get('modo') or '').strip()  # 'memorizar' | 'so_desta_vez'
    produto_id_raw = dados.get('produto_id')

    if not item_id:
        return jsonify({'ok': False, 'erro': 'item_id ausente'}), 400
    if categoria not in _CATEGORIAS_VALIDAS:
        return jsonify({'ok': False, 'erro': 'categoria inválida'}), 400
    if modo not in ('memorizar', 'so_desta_vez'):
        return jsonify({'ok': False, 'erro': 'modo inválido'}), 400

    # produto_id so vale para combustivel.
    produto_id = None
    if categoria == 'combustivel':
        try:
            produto_id = int(produto_id_raw) if produto_id_raw not in (None, '', '0') else None
        except (TypeError, ValueError):
            produto_id = None
        if not produto_id:
            return jsonify({'ok': False, 'erro': 'combustível exige selecionar o produto'}), 400

    modo_grava = 'memorizado' if modo == 'memorizar' else 'so_desta_vez'

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Busca fornecedor (emit_cnpj) + cProd do item (necessarios p/ regra).
        cur.execute(
            """
            SELECT i.id, i.cprod_fornecedor, d.emit_cnpj
            FROM dfe_itens i
            JOIN dfe_documentos d ON d.id = i.documento_id
            WHERE i.id = %s
            """,
            (item_id,),
        )
        item = cur.fetchone()
        if not item:
            return jsonify({'ok': False, 'erro': 'item não encontrado'}), 404

        # 1) Classifica o item.
        cur.execute(
            """
            UPDATE dfe_itens
               SET categoria = %s,
                   classificado_produto_id = %s,
                   classificado_em = NOW(),
                   classificado_modo = %s
             WHERE id = %s
            """,
            (categoria, produto_id, modo_grava, item_id),
        )

        # 2) Memoriza a regra (se pedido e se houver cProd para chavear) e a
        #    aplica RETROATIVAMENTE aos demais itens pendentes do mesmo
        #    emit_cnpj + cprod_fornecedor (classificar um resolve todos os iguais).
        regra_gravada = False
        tambem = 0
        aviso = None
        if modo == 'memorizar':
            emit_cnpj = item.get('emit_cnpj')
            cprod = item.get('cprod_fornecedor')
            if emit_cnpj and cprod:
                cur.execute(
                    """
                    INSERT INTO dfe_classificacao_regra
                        (emit_cnpj, cprod_fornecedor, categoria, produto_id)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        categoria = VALUES(categoria),
                        produto_id = VALUES(produto_id)
                    """,
                    (emit_cnpj, cprod, categoria, produto_id),
                )
                regra_gravada = True

                # Retroativo: classifica os pendentes iguais (o item clicado ja
                # nao esta NULL, entao nao entra na contagem).
                cur.execute(
                    """
                    UPDATE dfe_itens i
                    JOIN dfe_documentos d ON d.id = i.documento_id
                       SET i.categoria = %s,
                           i.classificado_produto_id = %s,
                           i.classificado_em = NOW(),
                           i.classificado_modo = 'memorizado'
                     WHERE i.categoria IS NULL
                       AND d.emit_cnpj = %s
                       AND i.cprod_fornecedor = %s
                    """,
                    (categoria, produto_id, emit_cnpj, cprod),
                )
                tambem = cur.rowcount or 0
            else:
                aviso = ('Item classificado, mas SEM regra memorizada: '
                         'falta CNPJ do emitente e/ou cProd do fornecedor.')

        conn.commit()
        return jsonify({
            'ok': True,
            'item_id': item_id,
            'categoria': categoria,
            'modo': modo_grava,
            'regra_gravada': regra_gravada,
            'tambem': tambem,
            'aviso': aviso,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()
