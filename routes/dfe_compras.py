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

        # ---------- AREA 3: REGRAS memorizadas (para ver/apagar) ----------
        cur.execute(
            """
            SELECT r.id, r.emit_cnpj, r.cprod_fornecedor,
                   r.categoria, r.produto_id, r.criado_em,
                   p.nome AS produto_nome,
                   (SELECT d.emit_nome FROM dfe_documentos d
                     WHERE d.emit_cnpj = r.emit_cnpj AND d.emit_nome IS NOT NULL
                     ORDER BY d.id DESC LIMIT 1) AS fornecedor_nome
              FROM dfe_classificacao_regra r
              LEFT JOIN produto p ON p.id = r.produto_id
             ORDER BY fornecedor_nome, r.cprod_fornecedor
            """
        )
        regras = cur.fetchall()

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
            regras=regras,
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
# >>> TEMP-DIAGNOSTICO (REMOVER APOS O TESTE) <<<
# Faz UMA requisicao consChNFe (busca por chave) ao NFeDistribuicaoDFe usando
# o certificado do servidor. READ-ONLY: nao grava no banco, nao manifesta.
# Responde as 2 perguntas: (1) volta procNFe COMPLETO com itens? (2) toma 656?
# Uso: abrir /dfe/_teste-conschnfe  (opcional ?chave=44digitos)
# ==========================================================================
@dfe_compras_bp.route('/_teste-conschnfe', methods=['GET'])
@login_required
def _teste_conschnfe():
    import gzip as _gzip, base64 as _b64
    import xml.etree.ElementTree as _ET
    from flask import Response

    chave = (request.args.get('chave')
             or '52260709250921001230550020000138021718955044')  # ON PETRO 13802
    chave = ''.join(ch for ch in chave if ch.isdigit())
    # versoes a testar (?versao=1.01 forca so uma). Default: tenta 1.35 e 1.01.
    if request.args.get('versao'):
        versoes = [request.args.get('versao')]
    else:
        versoes = ['1.35', '1.01']

    out = []
    def p(s=''): out.append(str(s))

    p('=== TESTE consChNFe (READ-ONLY, nao grava, nao manifesta) ===')
    p('chave: %s  (len=%s)' % (chave, len(chave)))
    p('versoes a testar: %s' % versoes)

    def mostra_itens(r_content):
        """Parseia a resposta 138 e lista itens. Retorna (cStat, veio_completo)."""
        env = _ET.fromstring(r_content)
        ret = cs._find(env, 'retDistDFeInt')
        cStat = cs._text(ret, 'cStat'); xMotivo = cs._text(ret, 'xMotivo')
        p('    cStat/xMotivo : %s  %s' % (cStat, xMotivo))
        p('    ultNSU/maxNSU : %s / %s' % (cs._text(ret, 'ultNSU'), cs._text(ret, 'maxNSU')))
        lote = cs._find(ret, 'loteDistDFeInt')
        docs = [e for e in (lote.iter() if lote is not None else [])
                if cs._local(e.tag) == 'docZip']
        veio_completo = False
        for i, d in enumerate(docs, 1):
            schema = d.get('schema') or '(sem)'
            try:
                root = _ET.fromstring(_gzip.decompress(_b64.b64decode(d.text or '')))
                raiz = cs._local(root.tag)
            except Exception as exc:
                p('      [%s] schema=%s (falha unzip: %s)' % (i, schema, exc)); continue
            dets = [e for e in root.iter() if cs._local(e.tag) == 'det']
            p('      [%s] NSU=%s schema=%s raiz=<%s> ITENS=%s'
              % (i, d.get('NSU'), schema, raiz, len(dets)))
            if schema.lower().startswith(('proc', 'nfeproc')) or len(dets) > 0:
                veio_completo = True
            for de in dets:
                def g(node, nome):
                    for e in node.iter():
                        if cs._local(e.tag) == nome and e.text:
                            return e.text.strip()
                    return '?'
                p('        - %-40s qCom=%s un=%s vProd=%s'
                  % (g(de, 'xProd')[:40], g(de, 'qCom'), g(de, 'uCom'), g(de, 'vProd')))
        return cStat, veio_completo

    try:
        import sys, os
        _raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for _p in (_raiz, os.path.join(_raiz, 'scripts')):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        import consulta_sefaz as cs

        cliente_id, cnpj, cert, chave_priv, cadeia = cs.abrir_certificado()
        p('cert OK: cnpj=%s cadeia=%s' % (cnpj, len(cadeia)))
        sess = cs.montar_sessao_mtls(cert, chave_priv, cadeia)
        headers = {
            'Content-Type': ('application/soap+xml; charset=utf-8; '
                             'action="%s/nfeDistDFeInteresse"' % cs.NS_WSDL),
            'User-Agent': 'nh-transportes/teste-conschnfe (read-only)',
        }

        for ver in versoes:
            corpo = (
                '<distDFeInt xmlns="%s" versao="%s">'
                '<tpAmb>%s</tpAmb><cUFAutor>%s</cUFAutor><CNPJ>%s</CNPJ>'
                '<consChNFe><chNFe>%s</chNFe></consChNFe>'
                '</distDFeInt>'
            ) % (cs.NS_NFE, ver, cs.TP_AMB, cs.C_UF_AUTOR, cnpj, chave)
            soap = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
                '<soap12:Body>'
                '<nfeDistDFeInteresse xmlns="%s"><nfeDadosMsg>%s</nfeDadosMsg>'
                '</nfeDistDFeInteresse></soap12:Body></soap12:Envelope>'
            ) % (cs.NS_WSDL, corpo)

            p('')
            p('#' * 70)
            p('### TENTATIVA versao=%s' % ver)
            p('#' * 70)
            p('--- REQUISICAO (corpo distDFeInt) ---')
            p(corpo)
            r = sess.post(cs.ENDPOINT, data=soap.encode('utf-8'), headers=headers,
                          timeout=cs.TIMEOUT)
            p('--- HTTP %s (%s bytes) ---' % (r.status_code, len(r.content)))
            p('--- RESPOSTA CRUA (ate 2500 chars) ---')
            p(r.text[:2500])
            if r.status_code == 200:
                p('--- PARSE ---')
                try:
                    cStat, completo = mostra_itens(r.content)
                    if cStat == '656':
                        p('    >>> 656: mesma cota do polling. Botao INVIAVEL.')
                    elif cStat == '138':
                        p('    >>> 138 PASSOU. XML completo com itens? %s'
                          % ('SIM -> botao VIAVEL' if completo else 'NAO (so resumo)'))
                except Exception as exc:
                    p('    (falha ao parsear: %s)' % exc)
    except Exception as exc:
        import traceback
        p(''); p('ERRO: %s' % exc); p(traceback.format_exc()[:1500])
    return Response('\n'.join(out), mimetype='text/plain')
