"""
Tela de CLASSIFICACAO DE COMPRAS do servico DFe.  ISOLADA, aditiva.

Rota: /dfe/compras  (acesso por URL; ainda sem item de menu)

Duas areas na mesma pagina:
  AREA 1 "Classificar" -> itens pendentes (dfe_itens.categoria IS NULL), agrupados
                          por nota (mais recente em cima). Por item o usuario escolhe
                          categoria (e produto, se combustivel) e:
                            - "Memorizar"    -> grava regra + classifica (modo memorizado)
                            - "So desta vez" -> classifica so o item (modo so_desta_vez)
  AREA 2 "Compras"    -> listagem POR NOTA (agrupada), pre-filtrada (30 dias), com
                          totalizador (litros + R$) e, ao expandir, os produtos da
                          nota + o CT-e vinculado (motorista/placa/transportadora/frete).

Padroes do app: blueprint *_bp (auto-registro), @login_required, CSRF normal
(o base.html injeta o token em forms/fetch), get_db_connection() + cursor(dictionary=True),
SQL 100% parametrizado (%s). NAO altera nada existente.
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request, jsonify, current_app
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

        # ---------- AREA 2: COMPRAS (listagem POR NOTA) ----------
        # Substitui a antiga "Consultar" (por item). Agora agrupa por NOTA, ja
        # vem pre-filtrada (ultimos 30 dias), traz o totalizador (litros + R$) e,
        # ao expandir, os produtos da nota + o CT-e vinculado (dfe_cte_nfe).
        hoje = date.today()
        f = {
            'empresa':    (request.args.get('empresa') or '').strip(),
            'fornecedor': (request.args.get('fornecedor') or '').strip(),
            'categoria':  (request.args.get('categoria') or '').strip(),
            'situacao':   (request.args.get('situacao') or '').strip(),
            'data_ini':   (request.args.get('data_ini') or '').strip(),
            'data_fim':   (request.args.get('data_fim') or '').strip(),
        }
        # Pre-filtrado: ultimos 30 dias por padrao (o usuario pode trocar).
        c_data_ini = f['data_ini'] or (hoje - timedelta(days=30)).strftime('%Y-%m-%d')
        c_data_fim = f['data_fim'] or hoje.strftime('%Y-%m-%d')
        # Selo "N ativos": conta filtros ALEM do periodo default.
        filtros_ativos = sum(1 for k in ('empresa', 'fornecedor', 'categoria', 'situacao') if f[k]) \
            + (1 if f['data_ini'] else 0) + (1 if f['data_fim'] else 0)

        where = ["d.tipo = 'NFe'"]
        params = []
        where.append("d.dh_emissao >= %s"); params.append(c_data_ini + " 00:00:00")
        where.append("d.dh_emissao <= %s"); params.append(c_data_fim + " 23:59:59")
        if f['empresa']:
            where.append("d.cliente_id = %s"); params.append(f['empresa'])
        if f['fornecedor']:
            where.append("(d.emit_nome LIKE %s OR d.emit_cnpj LIKE %s)")
            termo = f"%{f['fornecedor']}%"; params += [termo, termo]
        if f['situacao']:
            where.append("d.situacao = %s"); params.append(f['situacao'])
        if f['categoria'] in _CATEGORIAS_VALIDAS:
            # Nota que TENHA ao menos um item da categoria escolhida.
            where.append("EXISTS (SELECT 1 FROM dfe_itens ix "
                         "WHERE ix.documento_id = d.id AND ix.categoria = %s)")
            params.append(f['categoria'])
        where_sql = " AND ".join(where)

        LIMITE = 500

        # 1) TOTALIZADOR (todo o periodo, sem LIMITE): litros de combustivel + R$
        #    (inclui despesas no R$) + nº de notas.
        cur.execute(
            f"""
            SELECT COALESCE(SUM(sub.litros), 0)     AS litros,
                   COALESCE(SUM(sub.nota_valor), 0) AS valor,
                   COUNT(*)                         AS notas
            FROM (
                SELECT d.id, d.valor_total AS nota_valor,
                       SUM(CASE WHEN i.categoria = 'combustivel'
                                THEN i.quantidade ELSE 0 END) AS litros
                FROM dfe_documentos d
                JOIN dfe_itens i ON i.documento_id = d.id
                WHERE {where_sql}
                GROUP BY d.id, d.valor_total
            ) sub
            """,
            params,
        )
        agg = cur.fetchone() or {}
        compras_totais = {
            'litros': agg.get('litros') or 0,
            'valor':  agg.get('valor') or 0,
            'notas':  agg.get('notas') or 0,
        }

        # 2) LISTA por nota (limitada). Agrupa por documento (PK) -> os demais
        #    campos de d/emp sao funcionalmente dependentes.
        cur.execute(
            f"""
            SELECT d.id AS doc_id, d.chave, d.numero, d.serie, d.dh_emissao,
                   d.situacao, d.emit_nome, d.emit_cnpj,
                   d.valor_total AS nota_valor,
                   COALESCE(emp.nome_fantasia, emp.razao_social) AS empresa_nome,
                   SUM(CASE WHEN i.categoria = 'combustivel'
                            THEN i.quantidade ELSE 0 END) AS litros,
                   SUM(CASE WHEN i.categoria = 'combustivel'
                            THEN i.valor_total ELSE 0 END) AS valor_comb
            FROM dfe_documentos d
            JOIN dfe_itens i ON i.documento_id = d.id
            LEFT JOIN clientes emp ON emp.id = d.cliente_id
            WHERE {where_sql}
            GROUP BY d.id
            ORDER BY d.dh_emissao DESC, d.id DESC
            LIMIT %s
            """,
            params + [LIMITE],
        )
        compras = cur.fetchall()
        truncado = len(compras) >= LIMITE

        # 3) Itens das notas da pagina (para o expandir + resumo "N produtos").
        # 4) CT-e vinculado por chave da NF-e (reusa o vinculo dfe_cte_nfe).
        itens_por_doc = {}
        ctes_por_chave = {}
        if compras:
            ids = [c['doc_id'] for c in compras]
            marc = ",".join(["%s"] * len(ids))
            cur.execute(
                f"""
                SELECT i.documento_id, i.n_item, i.produto_xml, i.cprod_fornecedor,
                       i.categoria, i.quantidade, i.unidade,
                       i.valor_total AS item_valor, p.nome AS produto_nome
                FROM dfe_itens i
                LEFT JOIN produto p ON p.id = i.classificado_produto_id
                WHERE i.documento_id IN ({marc})
                ORDER BY i.documento_id, i.n_item
                """,
                ids,
            )
            for it in cur.fetchall():
                itens_por_doc.setdefault(it['documento_id'], []).append(it)

            chaves = [c['chave'] for c in compras if c['chave']]
            if chaves:
                marc2 = ",".join(["%s"] * len(chaves))
                cur.execute(
                    f"""
                    SELECT n.chave_nfe, c.numero AS cte_numero,
                           c.emit_nome AS transportadora, c.emit_cnpj AS transp_cnpj,
                           ct.vprest AS frete, ct.placa,
                           ct.motorista_nome, ct.motorista_cpf,
                           ct.mun_ini, ct.uf_ini, ct.mun_fim, ct.uf_fim
                    FROM dfe_cte_nfe n
                    JOIN dfe_documentos c ON c.id = n.documento_id AND c.tipo = 'CTe'
                    LEFT JOIN dfe_cte ct ON ct.documento_id = c.id
                    WHERE n.chave_nfe IN ({marc2})
                    ORDER BY c.dh_emissao
                    """,
                    chaves,
                )
                for r in cur.fetchall():
                    ctes_por_chave.setdefault(r['chave_nfe'], []).append(r)

        # Monta cada nota: itens, CT-e, rotulo "nosso produto" e V.unit.
        _rot = dict(CATEGORIAS)
        for c in compras:
            itens = itens_por_doc.get(c['doc_id'], [])
            c['itens'] = itens
            c['ctes'] = ctes_por_chave.get(c['chave'], [])
            c['situacao_ok'] = (c['situacao'] == 'autorizado')

            # Token por item: combustivel -> nosso produto; senao -> categoria.
            def _tok(it):
                if it['categoria'] == 'combustivel':
                    return it['produto_nome'] or 'Combustível'
                if it['categoria']:
                    return _rot.get(it['categoria'], it['categoria'])
                return 'pendente'
            tokens = list(dict.fromkeys(_tok(it) for it in itens))
            c['n_produtos'] = len(tokens)
            c['produto_label'] = tokens[0] if len(tokens) == 1 else ('%d produtos' % len(tokens))

            # V.unit (R$/litro) so p/ combustivel com UM unico produto.
            litros = float(c['litros'] or 0)
            so_comb = bool(itens) and all(it['categoria'] == 'combustivel' for it in itens)
            c['v_unit'] = (float(c['valor_comb'] or 0) / litros) if (len(tokens) == 1 and so_comb and litros) else None

        # ---------- AREA 3: REGRAS memorizadas (para ver/apagar) ----------
        cur.execute(
            """
            SELECT r.id, r.emit_cnpj, r.cprod_fornecedor,
                   r.categoria, r.produto_id, r.criado_em,
                   p.nome AS produto_nome,
                   (SELECT d.emit_nome FROM dfe_documentos d
                     WHERE d.emit_cnpj = r.emit_cnpj AND d.emit_nome IS NOT NULL
                     ORDER BY d.id DESC LIMIT 1) AS fornecedor_nome,
                   -- Como o FORNECEDOR chama o produto (xProd = dfe_itens.produto_xml),
                   -- pego da nota mais recente daquele emit_cnpj + cProd.
                   (SELECT i.produto_xml FROM dfe_itens i
                     JOIN dfe_documentos d2 ON d2.id = i.documento_id
                     WHERE d2.emit_cnpj = r.emit_cnpj
                       AND i.cprod_fornecedor = r.cprod_fornecedor
                       AND i.produto_xml IS NOT NULL
                     ORDER BY d2.id DESC LIMIT 1) AS xprod_fornecedor
              FROM dfe_classificacao_regra r
              LEFT JOIN produto p ON p.id = r.produto_id
             ORDER BY fornecedor_nome, r.cprod_fornecedor
            """
        )
        regras = cur.fetchall()

        # Agrupa as regras por fornecedor (emit_cnpj) preservando a ordem
        # (mesma tecnica usada para 'notas' acima). Cada grupo leva nome +
        # a lista de regras; o template renderiza um accordion por fornecedor.
        fornecedores_regras = []
        _idxf = {}
        for r in regras:
            ck = r['emit_cnpj'] or ''
            if ck not in _idxf:
                _idxf[ck] = len(fornecedores_regras)
                fornecedores_regras.append({
                    'emit_cnpj': r['emit_cnpj'],
                    'nome': r['fornecedor_nome'],
                    'regras': [],
                })
            fornecedores_regras[_idxf[ck]]['regras'].append(r)

        # ---------- AREA 4: AGUARDANDO XML (resumos, resumo=1, sem itens) ----------
        # Notas que entraram so como resumo (resNFe): existem no banco mas ainda
        # SEM o XML completo (logo, sem itens para classificar). Aparecem aqui so
        # para VISIBILIDADE/conferencia. Quando o XML completo chega numa proxima
        # captura, resumo vira 0, os itens sao inseridos e a nota migra sozinha
        # para a aba Classificar. O app NAO manifesta (isso e papel do SGA).
        cur.execute(
            """
            SELECT d.id, d.chave, d.numero, d.serie, d.dh_emissao,
                   d.emit_nome, d.emit_cnpj, d.valor_total, d.situacao
            FROM dfe_documentos d
            WHERE d.tipo = 'NFe' AND d.resumo = 1
            ORDER BY d.dh_emissao DESC, d.id DESC
            """
        )
        resumos = cur.fetchall()

        # Empresas que TEM NF-e (para o dropdown de filtro por empresa).
        cur.execute(
            """SELECT DISTINCT d.cliente_id AS id,
                      COALESCE(emp.nome_fantasia, emp.razao_social) AS nome
                 FROM dfe_documentos d
                 JOIN clientes emp ON emp.id = d.cliente_id
                WHERE d.tipo = 'NFe'
                ORDER BY nome"""
        )
        empresas = cur.fetchall()

        # Rotulos de categoria para exibicao.
        rot_categoria = dict(CATEGORIAS)

        # Datas para preencher o form (o periodo default de 30 dias ja calculado).
        data_ini_default = c_data_ini
        data_fim_default = c_data_fim

        aba = request.args.get('aba') or ('consultar' if filtros_ativos else 'classificar')

        return render_template(
            'dfe_compras/index.html',
            notas=notas,
            total_pendentes_itens=len(linhas),
            total_pendentes_notas=len(notas),
            produtos=produtos,
            categorias=CATEGORIAS,
            rot_categoria=rot_categoria,
            filtros=f,
            empresas=empresas,
            compras=compras,
            compras_totais=compras_totais,
            filtros_ativos=filtros_ativos,
            truncado=truncado,
            limite=LIMITE,
            data_ini_default=data_ini_default,
            data_fim_default=data_fim_default,
            regras=regras,
            fornecedores_regras=fornecedores_regras,
            resumos=resumos,
            aba=aba,
        )
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# ACAO: apagar UMA regra memorizada (AJAX/JSON). So remove a regra; os itens
# ja classificados por ela permanecem como estao.
# ==========================================================================
@dfe_compras_bp.route('/compras/regras/apagar', methods=['POST'])
@login_required
def apagar_regra():
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
        cur.execute("DELETE FROM dfe_classificacao_regra WHERE id = %s", (regra_id,))
        conn.commit()
        return jsonify({'ok': True, 'apagou': cur.rowcount or 0})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# ACAO: listar as notas (itens) de UMA regra -> fornecedor(emit_cnpj)+cProd.
# Usada pelo modal de edicao na opcao "b) alterar somente uma nota": o usuario
# escolhe qual item corrigir. O emit_cnpj/cprod vem SEMPRE da regra (server-side,
# lido por regra_id) -- o cliente so manda o regra_id.
# ==========================================================================
@dfe_compras_bp.route('/compras/regras/notas', methods=['POST'])
@login_required
def listar_notas_regra():
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
        cur.execute(
            "SELECT emit_cnpj, cprod_fornecedor FROM dfe_classificacao_regra WHERE id = %s",
            (regra_id,),
        )
        regra = cur.fetchone()
        if not regra:
            return jsonify({'ok': False, 'erro': 'regra não encontrada'}), 404

        cur.execute(
            """
            SELECT i.id AS item_id, d.numero, d.serie, d.dh_emissao,
                   i.categoria, i.classificado_modo, p.nome AS produto_nome
              FROM dfe_itens i
              JOIN dfe_documentos d ON d.id = i.documento_id
              LEFT JOIN produto p ON p.id = i.classificado_produto_id
             WHERE d.emit_cnpj = %s AND i.cprod_fornecedor = %s
             ORDER BY d.dh_emissao DESC, d.id DESC
            """,
            (regra['emit_cnpj'], regra['cprod_fornecedor']),
        )
        itens = cur.fetchall()
        notas = [{
            'item_id': it['item_id'],
            'numero': it['numero'],
            'serie': it['serie'],
            'data': it['dh_emissao'].strftime('%d/%m/%Y') if it['dh_emissao'] else '—',
            'categoria': it['categoria'],
            'modo': it['classificado_modo'],
            'produto_nome': it['produto_nome'],
        } for it in itens]
        return jsonify({'ok': True, 'notas': notas})
    except Exception as e:
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# ACAO: editar UMA regra memorizada (AJAX/JSON). O usuario escolhe o ALCANCE:
#   'proximos' -> muda SO a regra (vale para capturas futuras).
#   'tudo'     -> muda a regra E reclassifica os itens que ela criou
#                 (classificado_modo='memorizado'); preserva 'so_desta_vez'.
#   'uma'      -> NAO muda a regra; reclassifica SO o item escolhido (item_id),
#                 marcando-o 'so_desta_vez' (protege da opcao 'tudo' futura).
# emit_cnpj/cprod vem SEMPRE da regra (server-side) -> nao reclassifica alheio.
# ==========================================================================
@dfe_compras_bp.route('/compras/regras/editar', methods=['POST'])
@login_required
def editar_regra():
    dados = request.get_json(silent=True) or {}
    try:
        regra_id = int(dados.get('regra_id') or 0)
    except (TypeError, ValueError):
        regra_id = 0
    categoria = (dados.get('categoria') or '').strip()
    alcance = (dados.get('alcance') or '').strip()  # 'tudo'|'uma'|'proximos'
    produto_id_raw = dados.get('produto_id')

    if not regra_id:
        return jsonify({'ok': False, 'erro': 'regra_id ausente'}), 400
    if categoria not in _CATEGORIAS_VALIDAS:
        return jsonify({'ok': False, 'erro': 'categoria inválida'}), 400
    if alcance not in ('tudo', 'uma', 'proximos'):
        return jsonify({'ok': False, 'erro': 'alcance inválido'}), 400

    # produto_id so vale (e e obrigatorio) para combustivel.
    produto_id = None
    if categoria == 'combustivel':
        try:
            produto_id = int(produto_id_raw) if produto_id_raw not in (None, '', '0') else None
        except (TypeError, ValueError):
            produto_id = None
        if not produto_id:
            return jsonify({'ok': False, 'erro': 'combustível exige selecionar o produto'}), 400

    # 'uma' exige o item escolhido.
    item_id = None
    if alcance == 'uma':
        try:
            item_id = int(dados.get('item_id') or 0)
        except (TypeError, ValueError):
            item_id = 0
        if not item_id:
            return jsonify({'ok': False, 'erro': 'escolha a nota a corrigir'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Trava: rele a regra pelo id -> usa emit_cnpj/cprod DO BANCO.
        cur.execute(
            "SELECT id, emit_cnpj, cprod_fornecedor FROM dfe_classificacao_regra WHERE id = %s",
            (regra_id,),
        )
        regra = cur.fetchone()
        if not regra:
            return jsonify({'ok': False, 'erro': 'regra não encontrada'}), 404
        emit_cnpj = regra['emit_cnpj']
        cprod = regra['cprod_fornecedor']

        tambem = 0
        regra_alterada = False

        if alcance in ('proximos', 'tudo'):
            # (c) e parte de (a): atualiza a REGRA.
            cur.execute(
                "UPDATE dfe_classificacao_regra SET categoria = %s, produto_id = %s WHERE id = %s",
                (categoria, produto_id, regra_id),
            )
            regra_alterada = True

        if alcance == 'tudo':
            # (a) reclassifica os itens que ESTA regra criou; preserva 'so_desta_vez'.
            cur.execute(
                """
                UPDATE dfe_itens i
                  JOIN dfe_documentos d ON d.id = i.documento_id
                   SET i.categoria = %s,
                       i.classificado_produto_id = %s,
                       i.classificado_em = NOW(),
                       i.classificado_modo = 'memorizado'
                 WHERE d.emit_cnpj = %s
                   AND i.cprod_fornecedor = %s
                   AND i.classificado_modo = 'memorizado'
                """,
                (categoria, produto_id, emit_cnpj, cprod),
            )
            tambem = cur.rowcount or 0

        elif alcance == 'uma':
            # (b) regra INTACTA; reclassifica SO o item escolhido, marcando
            # 'so_desta_vez'. O AND emit_cnpj/cprod confere que o item e deste
            # fornecedor+cProd (impede reclassificar item alheio).
            cur.execute(
                """
                UPDATE dfe_itens i
                  JOIN dfe_documentos d ON d.id = i.documento_id
                   SET i.categoria = %s,
                       i.classificado_produto_id = %s,
                       i.classificado_em = NOW(),
                       i.classificado_modo = 'so_desta_vez'
                 WHERE i.id = %s
                   AND d.emit_cnpj = %s
                   AND i.cprod_fornecedor = %s
                """,
                (categoria, produto_id, item_id, emit_cnpj, cprod),
            )
            tambem = cur.rowcount or 0
            if not tambem:
                conn.rollback()
                return jsonify({'ok': False,
                                'erro': 'nota não encontrada para este fornecedor/cProd'}), 404

        conn.commit()

        # Rotulo do produto para o JS atualizar a linha.
        produto_nome = None
        if produto_id:
            cur.execute("SELECT nome FROM produto WHERE id = %s", (produto_id,))
            row = cur.fetchone()
            produto_nome = row['nome'] if row else None

        return jsonify({
            'ok': True,
            'regra_id': regra_id,
            'alcance': alcance,
            'categoria': categoria,
            'produto_id': produto_id,
            'produto_nome': produto_nome,
            'regra_alterada': regra_alterada,
            'tambem': tambem,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


# ==========================================================================
# ACAO: disparar UMA captura de DFe AGORA (botao "Capturar agora"). Roda em
# background (thread), retorna na hora. Respeita a cota: o proprio job usa
# GET_LOCK global (nao roda 2x) e pre-checa proximo_permitido (nao consulta a
# SEFAZ se a cota ainda esta fechada por 656). Reaproveita disparar_captura_async
# do agendador -> nenhuma logica de captura nova.
# ==========================================================================
@dfe_compras_bp.route('/capturar-agora', methods=['POST'])
@login_required
def capturar_agora():
    # 1) Le o estado atual da cota (best-effort) so para dar feedback na tela.
    estado = {}
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT ult_consulta, proximo_permitido, ult_status, "
            "(proximo_permitido IS NOT NULL AND proximo_permitido > NOW()) AS bloqueado "
            "FROM dfe_nsu LIMIT 1"
        )
        estado = cur.fetchone() or {}
    except Exception:
        pass
    finally:
        cur.close()
        conn.close()

    # 2) Dispara em background. O job se autoprotege (lock + proximo_permitido),
    #    entao disparar mesmo "bloqueado" e inofensivo (ele so pula).
    try:
        from integrations.dfe_scheduler import disparar_captura_async
        disparar_captura_async(current_app._get_current_object())
    except Exception as e:
        current_app.logger.exception("[dfe] falha ao disparar captura manual")
        return jsonify({'ok': False, 'erro': 'não foi possível iniciar a captura: %s' % e}), 500

    bloqueado = bool(estado.get('bloqueado'))
    if bloqueado:
        mensagem = ('A SEFAZ pediu para aguardar até %s (cota/656). A captura não vai '
                    'consultar agora; o agendador tenta de novo automaticamente.'
                    % estado.get('proximo_permitido'))
    else:
        mensagem = ('Captura iniciada em segundo plano. Aguarde ~1–2 min — a página '
                    'recarrega sozinha para mostrar as notas novas.')

    return jsonify({
        'ok': True,
        'bloqueado': bloqueado,
        'mensagem': mensagem,
        'proximo_permitido': str(estado.get('proximo_permitido') or ''),
        'ult_status': estado.get('ult_status'),
        'ult_consulta': str(estado.get('ult_consulta') or ''),
    })


# ==========================================================================
# ACAO: buscar o XML COMPLETO de UMA nota (resumo) pela chave, via consChNFe.
# Usa distDFeInt versao "1.01" (consulta por chave) -- comprovado que traz o
# procNFe completo com itens e NAO cai na cota/656 do polling (a versao 1.35,
# usada no polling distNSU, retorna 215 no consChNFe). Reusa processar_um_doc
# (upsert nota resumo->0 + itens + Dropbox, com commit interno) e aplica as
# regras memorizadas. NAO manifesta (isso e papel do SGA).
# ==========================================================================
@dfe_compras_bp.route('/compras/buscar-xml', methods=['POST'])
@login_required
def buscar_xml():
    import xml.etree.ElementTree as _ET
    from datetime import datetime as _dt, timedelta as _td
    import sys as _sys, os as _os

    dados = request.get_json(silent=True) or {}

    # Aceita OU doc_id (botao da linha "Aguardando XML") OU chave avulsa
    # (campo novo: cola a chave de 44 digitos pega no SGA). A chave digitada
    # tem prioridade e permite buscar QUALQUER nota, mesmo que nunca tenha
    # passado pelo polling (nao existe no banco).
    try:
        doc_id = int(dados.get('doc_id') or 0)
    except (TypeError, ValueError):
        doc_id = 0
    # Filtra so digitos: descarta pontos/espacos que possam vir colados do SGA.
    chave_in = ''.join(ch for ch in str(dados.get('chave') or '') if ch.isdigit())

    if not chave_in and not doc_id:
        return jsonify({'ok': False, 'erro': 'informe a chave ou o doc_id'}), 400
    if chave_in and len(chave_in) != 44:
        return jsonify({'ok': False,
                        'erro': 'a chave deve ter 44 digitos (recebi %d)' % len(chave_in)}), 400

    # scripts/ no sys.path p/ importar consulta_sefaz e processa_dfe.
    _raiz = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for _p in (_raiz, _os.path.join(_raiz, 'scripts')):
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    import consulta_sefaz as cs
    import processa_dfe as pd
    from integrations.dfe_classificacao import aplicar_regras
    import pymysql

    # 1) Chave da nota. Se veio digitada (chave avulsa), usa direto -- nao
    #    precisa existir no banco. Senao, resolve pelo doc_id (server-side).
    cli_id = None   # empresa do documento -> usa o cert certo (multi-empresa)
    if chave_in:
        chave = chave_in
    else:
        conn = pymysql.connect(**cs.CONN)
        try:
            with conn.cursor() as cur0:
                cur0.execute("SELECT chave, numero, resumo, cliente_id FROM dfe_documentos WHERE id=%s",
                             (doc_id,))
                doc = cur0.fetchone()
        finally:
            conn.close()
        if not doc:
            return jsonify({'ok': False, 'erro': 'documento nao encontrado'}), 404
        cli_id = doc.get('cliente_id')
        chave = ''.join(ch for ch in str(doc['chave']) if ch.isdigit())
        if len(chave) != 44:
            return jsonify({'ok': False, 'erro': 'chave invalida'}), 400

    # 2) Certificado + consulta consChNFe (versao 1.01).
    try:
        cliente_id, cnpj_cert, cert, chave_priv, cadeia = cs.abrir_certificado(cliente_id=cli_id)
        corpo = (
            '<distDFeInt xmlns="%s" versao="1.01">'
            '<tpAmb>%s</tpAmb><cUFAutor>%s</cUFAutor>%s'
            '<consChNFe><chNFe>%s</chNFe></consChNFe>'
            '</distDFeInt>'
        ) % (cs.NS_NFE, cs.TP_AMB, cs.C_UF_AUTOR, cs.tag_interessado(cnpj_cert), chave)
        soap = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
            '<soap12:Body><nfeDistDFeInteresse xmlns="%s"><nfeDadosMsg>%s'
            '</nfeDadosMsg></nfeDistDFeInteresse></soap12:Body></soap12:Envelope>'
        ) % (cs.NS_WSDL, corpo)
        sess = cs.montar_sessao_mtls(cert, chave_priv, cadeia)
        headers = {
            'Content-Type': ('application/soap+xml; charset=utf-8; '
                             'action="%s/nfeDistDFeInteresse"' % cs.NS_WSDL),
            'User-Agent': 'nh-transportes/buscar-xml-conschnfe',
        }
        r = sess.post(cs.ENDPOINT, data=soap.encode('utf-8'),
                      headers=headers, timeout=cs.TIMEOUT)
        if r.status_code != 200:
            return jsonify({'ok': False, 'erro': 'SEFAZ HTTP %s' % r.status_code}), 502
        env = _ET.fromstring(r.content)
        ret = cs._find(env, 'retDistDFeInt')
        cStat = cs._text(ret, 'cStat'); xMotivo = cs._text(ret, 'xMotivo')
    except Exception as e:
        current_app.logger.exception('[dfe] buscar-xml: falha na consulta SEFAZ')
        return jsonify({'ok': False, 'erro': 'falha ao consultar a SEFAZ: %s' % e}), 500

    if cStat != '138':
        return jsonify({'ok': False, 'cStat': cStat,
                        'erro': 'SEFAZ nao retornou o documento (cStat %s: %s)'
                                % (cStat, xMotivo)}), 200

    # 3) Processa os docZip (reusa processar_um_doc: grava nota completa + itens,
    #    eventos etc.; gravar_nota faz commit interno e sobe o XML no Dropbox).
    lote = cs._find(ret, 'loteDistDFeInt')
    docs = [e for e in (lote.iter() if lote is not None else [])
            if cs._local(e.tag) == 'docZip']
    if not docs:
        return jsonify({'ok': False, 'erro': 'SEFAZ 138 mas lote vazio'}), 200

    agora = _dt.now()
    expira = (agora + _td(days=pd.DIAS_RETENCAO)).date()
    n_nota = n_itens = n_evento = n_resumo = 0
    conn = pymysql.connect(**cs.CONN)
    try:
        cur = conn.cursor()
        for d in docs:
            try:
                kind, ni, _c = pd.processar_um_doc(
                    conn, cur, cliente_id, cnpj_cert, d, agora, expira)
            except Exception as e:
                conn.rollback()
                current_app.logger.warning('[dfe] buscar-xml: doc falhou: %s', e)
                continue
            if kind == 'nota':
                n_nota += 1; n_itens += ni
            elif kind == 'evento':
                n_evento += 1
            elif kind == 'resumo':
                n_resumo += 1
        # auto-classificacao (best-effort, isolada -- a nota ja esta salva).
        n_cls = 0
        try:
            n_cls = aplicar_regras(cur)
            if n_cls:
                conn.commit()
        except Exception:
            conn.rollback(); n_cls = 0
        cur.close()
    finally:
        conn.close()

    if n_nota == 0:
        return jsonify({'ok': False, 'cStat': cStat, 'so_resumo': n_resumo > 0,
                        'erro': 'A SEFAZ ainda nao liberou o XML completo desta nota '
                                '(veio so o resumo). Tente novamente mais tarde.'}), 200

    return jsonify({'ok': True, 'itens': n_itens, 'eventos': n_evento,
                    'auto_classificados': n_cls,
                    'mensagem': 'Nota completa capturada (%s item(ns)).' % n_itens})
