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
import re
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from utils.fuso import BRASILIA, hoje_brasilia

from integrations.descarga_vinculo import (calcular_estado, listar_vinculos,
                                           registrar_vinculo, remover_vinculo,
                                           sugerir_notas, vinculos_resumo)
from utils.db import get_db_connection

estoque_bp = Blueprint('estoque', __name__)

POR_PAGINA = 100

# Rotulo de dia em PT-BR (strftime %A/%b depende de locale, que nao da p/ confiar).
_DIAS_SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']
_MESES_ABREV = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
                'jul', 'ago', 'set', 'out', 'nov', 'dez']


def _rotulo_dia(d):
    """date -> 'quinta, 7 ago' (com o ano junto quando nao e o ano corrente)."""
    if not d:
        return '—'
    txt = f"{_DIAS_SEMANA[d.weekday()]}, {d.day} {_MESES_ABREV[d.month - 1]}"
    if d.year != date.today().year:
        txt += f" {d.year}"
    return txt


def _slug_produto(nome):
    """Nome do produto do ELS -> slug de cor/icone.

    Os nomes chegam do e-mail como 'GASOLINA COMUM', 'ETANOL COMUM',
    'DIESEL S500 COMUM', 'DIESEL S10 COMUM'. Normaliza (sem acento, sem
    separador) para que 'DIESEL S-500' e 'DIESEL S500' caiam no mesmo lugar.
    Um diesel sem S10/S500 fica em 'diesel' (cinza) em vez de chutar qual e.
    """
    if not nome:
        return 'outro'
    txt = unicodedata.normalize('NFKD', str(nome)).encode('ascii', 'ignore').decode('ascii')
    txt = re.sub(r'[^A-Z0-9]+', '', txt.upper())
    if 'GASOLINA' in txt:
        return 'gas'
    if 'ETANOL' in txt or 'ALCOOL' in txt:
        return 'eta'
    if 'S10' in txt:
        return 's10'
    if 'S500' in txt:
        return 's500'
    if 'DIESEL' in txt:
        return 'diesel'
    return 'outro'


def _dia_de(valor):
    """DATETIME ou DATE -> date. descargas_pendentes.data_descarga e DATE puro,
    enquanto data_inicial/data_final sao DATETIME — o COALESCE devolve os dois."""
    if not valor:
        return None
    return valor.date() if hasattr(valor, 'date') else valor


def _hora_de(valor):
    """DATETIME -> 'HH:MM'. Um DATE puro nao tem hora, entao vira travessao."""
    return valor.strftime('%H:%M') if hasattr(valor, 'hour') else '—'


def _agrupar_por_dia(linhas, campo):
    """Lista ordenada por `campo` DESC -> lista de cards de dia.

    Serve as duas abas: leituras (campo data_leitura) e descargas (campo dt,
    o COALESCE ja resolvido). Depende da ordenacao do SQL — agrupa vizinhos
    iguais, nao reordena.
    """
    grupos = []
    for x in linhas:
        chave = _dia_de(x.get(campo))
        if not grupos or grupos[-1]['chave'] != chave:
            grupos.append({'chave': chave, 'rotulo': _rotulo_dia(chave), 'itens': []})
        grupos[-1]['itens'].append(x)
    return grupos


def _marcar_eventos(grupos):
    """LEITURAS: quando o dia tem UMA unica medicao (mesmo horario + mesmo
    titulo), o cabecalho leva a hora e o titulo. Com mais de uma vira
    'N medicoes' e cada linha mostra a sua hora — nada some."""
    for g in grupos:
        eventos = {(i['hora'], i['titulo_fmt']) for i in g['itens']}
        g['n_eventos'] = len(eventos)
        if g['n_eventos'] == 1:
            g['hora'], g['titulo_fmt'] = next(iter(eventos))
        else:
            g['hora'], g['titulo_fmt'] = None, None
    return grupos


def _totalizar(grupos, campo):
    """DESCARGAS: o cabecalho do dia mostra quantas foram e quantos litros."""
    for g in grupos:
        g['n'] = len(g['itens'])
        g['litros'] = sum(float(i[campo] or 0) for i in g['itens'])
    return grupos


_COLS_MANUAL = None   # cache: descargas_pendentes ja tem as colunas do manual?


def _tem_colunas_manual(cur):
    """descargas_pendentes ja tem origem/descricao/criado_por?

    O Railway sobe o codigo assim que a branch e pushada, mas a migration roda
    a mao depois. Sem esta checagem o SELECT com `origem` derrubaria a tela
    inteira nessa janela. Consulta uma vez por processo.
    """
    global _COLS_MANUAL
    if _COLS_MANUAL is None:
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'descargas_pendentes' "
            "AND column_name IN ('origem','descricao','criado_por')")
        _COLS_MANUAL = ((cur.fetchone() or {}).get('n') or 0) >= 3
    return _COLS_MANUAL


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
        'produto':  (request.args.get('produto') or '').strip(),
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
        # Produto filtra SO as leituras (a aba Descargas segue como estava).
        if f['produto']:
            w_l.append("l.produto_nome = %s"); p_l.append(f['produto'])
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

        # -------- Leituras: enfeites p/ os cards (cor/icone, hora, titulo) --------
        for l in leituras:
            l['slug'] = _slug_produto(l.get('produto_nome'))
            l['hora'] = _hora_de(l.get('data_leitura'))
            l['titulo_fmt'] = (l.get('titulo') or '').strip().lower()

        # Sem filtro de produto -> cards por dia. Com filtro -> lista corrida.
        if f['produto']:
            dias = []
            serie = {
                'nome':    f['produto'],
                'slug':    _slug_produto(f['produto']),
                'tanques': sorted({l['tanque'] for l in leituras if l.get('tanque') is not None}),
                'n':       total_leituras,
            }
        else:
            dias = _marcar_eventos(_agrupar_por_dia(leituras, 'data_leitura'))
            serie = None

        # -------- Descargas (paginada) --------
        tp_d = max(1, math.ceil(totais['descargas'] / POR_PAGINA))
        page_d = min(page_d, tp_d)
        # Antes da migration as colunas nao existem: finge 'els_email' em vez
        # de derrubar a tela.
        sel_manual = ("d.origem, d.descricao," if _tem_colunas_manual(cur)
                      else "'els_email' AS origem, NULL AS descricao,")
        cur.execute(
            f"""
            SELECT d.id, d.data_final, d.data_inicial, d.data_descarga, d.tanque,
                   d.produto_nome, d.total_descarga, d.total_descarga_20c,
                   d.status, d.frete_id, {sel_manual}
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

        # -------- Descargas: mesmos cards por dia da aba Leituras --------
        # Resumo dos vinculos das descargas da pagina, numa consulta so.
        resumos_v = vinculos_resumo(cur, [d['id'] for d in descargas])
        for d in descargas:
            d['slug'] = _slug_produto(d.get('produto_nome'))
            d['dt'] = d.get('data_final') or d.get('data_inicial') or d.get('data_descarga')
            d['hora'] = _hora_de(d['dt'])
            v = resumos_v.get(d['id'])
            d['vinc_n'] = v['n'] if v else 0
            d['vinc_litros'] = v['litros'] if v else 0.0
            d['vinc_numero'] = v['numero'] if v else None
            d['vinc_falta'] = round(float(d.get('total_descarga') or 0)
                                    - (v['litros'] if v else 0.0), 3)
            # A perda/sobra pertence a descarga que FECHOU a nota (o lancamento
            # integral) — nao a toda descarga da nota. Com a nota baixada em
            # duas viagens, mostrar nas duas duplicaria o numero: as duas
            # exibiriam -232 e a auditoria somaria -464.
            # `dif` ja vem preenchido SO na descarga que exibe o numero do
            # conjunto (a do ultimo vinculo integral); nas outras vem None.
            d['vinc_integral'] = bool(v and v['fechadas'])
            d['vinc_dif'] = v['dif'] if v else None
        dias_d = _totalizar(_agrupar_por_dia(descargas, 'dt'), 'total_descarga')

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

        # -------- Produtos p/ dropdown (so os que aparecem nas leituras) --------
        cur.execute(
            """
            SELECT DISTINCT produto_nome
            FROM leitura_tanque_diaria
            WHERE produto_nome IS NOT NULL AND produto_nome <> ''
            ORDER BY produto_nome
            """
        )
        produtos = [r['produto_nome'] for r in cur.fetchall()]

        # Cadastro de produtos para o dropdown do lancamento manual. O filtro
        # acima usa o produto_nome que vem do ELS; aqui precisamos do id real.
        cur.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos_cad = cur.fetchall()

        # Com o card de filtros recolhido por padrao, um filtro ativo ficaria
        # invisivel — o selo no titulo mostra quantos estao valendo.
        n_filtros = sum(1 for v in f.values() if v)

        hoje = date.today()
        data_ini_default = f['data_ini'] or (hoje - timedelta(days=90)).strftime('%Y-%m-%d')
        data_fim_default = f['data_fim'] or hoje.strftime('%Y-%m-%d')
        qs_filtros = urlencode({k: v for k, v in f.items() if v})

        return render_template(
            'estoque/index.html',
            leituras=leituras, descargas=descargas, totais=totais,
            dias=dias, dias_d=dias_d, serie=serie, produtos=produtos,
            produtos_cad=produtos_cad, hoje_iso=hoje.strftime('%Y-%m-%d'),
            filtros=f, n_filtros=n_filtros, empresas=empresas, tab=tab,
            data_ini_default=data_ini_default, data_fim_default=data_fim_default,
            page_l=page_l, tp_l=tp_l, paginas_l=_janela_paginas(page_l, tp_l),
            page_d=page_d, tp_d=tp_d, paginas_d=_janela_paginas(page_d, tp_d),
            qs_filtros=qs_filtros,
        )
    finally:
        cur.close()
        conn.close()


def _rotulo_status(status, vinc_n, integral):
    """Rotulo e cor do status NA TELA.

    O status no banco fica 'vinculada' assim que as notas da descarga fecham,
    mesmo para a descarga que so trouxe um pedaco. Na tela isso confunde: a
    descarga que nao fechou nota nenhuma e 'parcial' (roxo), e so quem fechou
    aparece como 'vinculada'.
    """
    if status == 'ignorada':
        return 'ignorada', 'ign'
    if integral:
        return 'vinculada', 'ok'
    if vinc_n:
        return 'parcial', 'parcial'
    return 'pendente', 'pend'


def _linha_descarga(cur, descarga_id, estado):
    """O que o JS precisa para atualizar a linha sem recarregar: o HTML da acao
    e o rotulo/cor do status.

    O HTML sai do MESMO parcial que o index usa — sem isso a marcacao viveria
    em dois lugares (Jinja e JS) e divergiria.
    """
    res = vinculos_resumo(cur, [descarga_id]).get(descarga_id)
    integral = bool(res and res['fechadas'])
    # origem: necessaria p/ o botao "Excluir" (so descarga manual) reaparecer
    # logo apos desfazer o vinculo, sem F5. So_desta_vez: 1 SELECT barato.
    cur.execute("SELECT origem, total_descarga FROM descargas_pendentes WHERE id = %s",
                (descarga_id,))
    _dp = cur.fetchone() or {}
    d = {
        'id': descarga_id,
        'origem': _dp.get('origem'),
        'total_descarga': _dp.get('total_descarga'),
        'vinc_n': res['n'] if res else 0,
        'vinc_litros': res['litros'] if res else 0.0,
        'vinc_numero': res['numero'] if res else None,
        'vinc_falta': estado['falta'],
        'vinc_integral': integral,
        'vinc_dif': res['dif'] if res else None,
    }
    rotulo, classe = _rotulo_status(estado.get('status'), d['vinc_n'], integral)
    return {'acao_html': render_template('estoque/_acao_descarga.html', d=d),
            'rotulo': rotulo, 'classe': classe}


# ==========================================================================
# CAMADA 2 — vinculo descarga <-> NF-e de compra.
# Tres rotas JSON consumidas pelo modal da aba Descargas. O base.html ja
# injeta o X-CSRFToken no fetch, entao os POST chegam com CSRF valido.
# ==========================================================================

@estoque_bp.route('/estoque/descarga/<int:descarga_id>/vinculo', methods=['GET'])
@login_required
def vinculo_modal(descarga_id):
    """Tudo que o modal precisa: descarga, estado, vinculos e candidatas."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # atualizar_status=False: um GET nao pode ter efeito colateral.
        estado = calcular_estado(cur, descarga_id, atualizar_status=False)
        if not estado:
            return jsonify({'ok': False, 'erro': 'Descarga não encontrada.'}), 404
        sug = sugerir_notas(cur, descarga_id) or {}
        return jsonify({
            'ok': True,
            'descarga': sug.get('descarga'),
            'estado': estado,
            'vinculos': listar_vinculos(cur, descarga_id),
            'candidatas': sug.get('candidatas', []),
            'motivo_vazio': sug.get('motivo_vazio'),
        })
    finally:
        cur.close()
        conn.close()


@estoque_bp.route('/estoque/descarga/<int:descarga_id>/vincular', methods=['POST'])
@login_required
def vincular(descarga_id):
    """Grava o vinculo e recalcula o estado — tudo no MESMO commit."""
    dados = request.get_json(silent=True) or {}
    try:
        item_id = int(dados.get('item_id') or 0)
    except (TypeError, ValueError):
        item_id = 0
    if not item_id:
        return jsonify({'ok': False, 'erro': 'Escolha a nota.'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        estado = registrar_vinculo(
            cur, descarga_id, item_id, dados.get('litros'),
            usuario_id=getattr(current_user, 'id', None),   # nunca do formulario
            observacao=dados.get('observacao'),
            modo=(dados.get('modo') or 'parcial'),
        )
        conn.commit()
        linha = _linha_descarga(cur, descarga_id, estado)
        return jsonify(dict({'ok': True, 'estado': estado}, **linha))
    except ValueError as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': 'Falha ao vincular: %s' % e}), 500
    finally:
        cur.close()
        conn.close()


@estoque_bp.route('/estoque/descarga/manual', methods=['POST'])
@login_required
def descarga_manual():
    """Lanca a mao uma descarga que o e-mail do ELS nao capturou.

    Entra igual as do ELS (status 'pendente', pronta para vincular), mas com
    origem='manual' e o motivo gravado — sem o motivo, daqui a seis meses
    ninguem sabe por que aquela descarga existe.

    volume_inicial/final e total_descarga_20c ficam NULL de proposito: num
    lancamento manual esses numeros nao sao conhecidos, e inventa-los seria
    pior do que assumir a ausencia.
    """
    dados = request.get_json(silent=True) or {}

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    cliente_id = _int(dados.get('cliente_id'))
    produto_id = _int(dados.get('produto_id'))
    tanque = _int(dados.get('tanque'))
    motivo = (dados.get('descricao') or '').strip()
    try:
        litros = float(str(dados.get('litros') or '').replace(',', '.'))
    except (TypeError, ValueError):
        litros = 0.0

    if not cliente_id:
        return jsonify({'ok': False, 'erro': 'Escolha a empresa.'}), 400
    if not produto_id:
        return jsonify({'ok': False, 'erro': 'Escolha o produto.'}), 400
    if tanque <= 0:
        return jsonify({'ok': False, 'erro': 'Informe o tanque.'}), 400
    if litros <= 0:
        return jsonify({'ok': False, 'erro': 'Os litros precisam ser maiores que zero.'}), 400
    if not motivo:
        return jsonify({'ok': False,
                        'erro': 'Escreva o motivo do lançamento manual.'}), 400

    # datetime-local: 'AAAA-MM-DDTHH:MM'
    bruto = (dados.get('data') or '').strip().replace('T', ' ')
    try:
        quando = datetime.strptime(bruto[:16], '%Y-%m-%d %H:%M')
    except ValueError:
        return jsonify({'ok': False, 'erro': 'Data e hora inválidas.'}), 400
    if quando > datetime.now():
        return jsonify({'ok': False,
                        'erro': 'A data não pode ser no futuro — descarga é fato passado.'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        if not _tem_colunas_manual(cur):
            return jsonify({'ok': False, 'erro': 'O banco ainda não tem as colunas do '
                                                 'lançamento manual. Rode a migration '
                                                 'alter_descargas_pendentes_manual.py.'}), 400

        cur.execute("SELECT id FROM clientes WHERE id = %s", (cliente_id,))
        if not cur.fetchone():
            return jsonify({'ok': False, 'erro': 'Empresa não encontrada.'}), 400
        cur.execute("SELECT id, nome FROM produto WHERE id = %s", (produto_id,))
        prod = cur.fetchone()
        if not prod:
            return jsonify({'ok': False, 'erro': 'Produto não encontrado.'}), 400

        # A chave e UNIQUE: montada com tanque+minuto+litros, um duplo clique
        # bate na constraint em vez de criar duas descargas iguais.
        chave = 'MAN-%d-%s-%.3f' % (tanque, quando.strftime('%Y%m%d%H%M'), litros)
        cur.execute("SELECT id FROM descargas_pendentes WHERE chave = %s", (chave,))
        if cur.fetchone():
            return jsonify({'ok': False,
                            'erro': 'Essa descarga já foi lançada (mesmo tanque, '
                                    'minuto e litros).'}), 409

        cur.execute(
            """
            INSERT INTO descargas_pendentes
              (cliente_id, tanque, produto_nome, produto_id, data_descarga,
               data_inicial, data_final, volume_inicial, volume_final,
               total_descarga, total_descarga_20c, status, chave,
               origem, descricao, criado_por)
            VALUES (%s,%s,%s,%s,%s, NULL,%s, NULL, NULL, %s, NULL,
                    'pendente', %s, 'manual', %s, %s)
            """,
            (cliente_id, tanque, prod['nome'], produto_id,
             quando.strftime('%Y-%m-%d'), quando.strftime('%Y-%m-%d %H:%M:%S'),
             litros, chave, motivo[:255], getattr(current_user, 'id', None)),
        )
        conn.commit()
        return jsonify({'ok': True, 'id': cur.lastrowid,
                        'mensagem': 'Descarga manual de %s L lançada.' % litros})
    except Exception as e:
        conn.rollback()
        if 'Duplicate' in str(e) or '1062' in str(e):
            return jsonify({'ok': False,
                            'erro': 'Essa descarga já foi lançada.'}), 409
        return jsonify({'ok': False, 'erro': 'Falha ao lançar: %s' % e}), 500
    finally:
        cur.close()
        conn.close()


@estoque_bp.route('/estoque/descarga/<int:descarga_id>/volumes', methods=['POST'])
@login_required
def corrigir_volumes(descarga_id):
    """Corrige os volumes de uma descarga medida errada pelo ELS.

    O caso real que motivou isto: descarga #88 de 11/08, em que o sensor
    marcou volume inicial 449 L com o tanque em ~3.400 — o proprio e-mail do
    ELS avisou "Volume inicial suspeito". A correcao NAO e automatica: quem
    decide e o usuario, por este botao.

    Recebe volume_inicial e volume_final; o total e SEMPRE final - inicial
    (nao se digita total na mao). O 20°C e reescalado na mesma proporcao do
    que havia. O valor antigo fica registrado na descricao, com autor e data
    — corrigir nao pode apagar a historia.
    """
    vi = (request.form.get('volume_inicial') or '').replace(',', '.').strip()
    vf = (request.form.get('volume_final') or '').replace(',', '.').strip()
    try:
        vi, vf = float(vi), float(vf)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'erro': 'Volumes inválidos.'}), 400
    if vi < 0 or vf <= vi:
        return jsonify({'ok': False,
                        'erro': 'O volume final tem de ser maior que o inicial.'}), 400

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            'SELECT volume_inicial, volume_final, total_descarga,'
            '       total_descarga_20c, descricao'
            ' FROM descargas_pendentes WHERE id = %s', (descarga_id,))
        d = cur.fetchone()
        if not d:
            return jsonify({'ok': False, 'erro': 'Descarga não encontrada.'}), 404

        total = round(vf - vi, 3)
        # 20°C reescalado na proporcao antiga; sem base, fica igual ao total.
        t_old = float(d['total_descarga'] or 0)
        c_old = float(d['total_descarga_20c'] or 0)
        t20 = round(total * (c_old / t_old), 3) if (t_old and c_old) else total

        usuario = getattr(current_user, 'username', '') or 'sistema'
        carimbo = ('[volumes corrigidos por %s em %s: era %s→%s L (total %s)]'
                   % (usuario, date.today().strftime('%d/%m/%Y'),
                      d['volume_inicial'], d['volume_final'],
                      d['total_descarga']))
        descricao = ((d['descricao'] or '') + ' ' + carimbo).strip()[:1000]

        cur.execute(
            'UPDATE descargas_pendentes'
            ' SET volume_inicial=%s, volume_final=%s, total_descarga=%s,'
            '     total_descarga_20c=%s, descricao=%s'
            ' WHERE id=%s',
            (vi, vf, total, t20, descricao, descarga_id))
        conn.commit()
        return jsonify({'ok': True, 'total': total})
    except Exception as e:
        conn.rollback()
        current_app.logger.exception('[corrigir_volumes] falhou')
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@estoque_bp.route('/estoque/descarga/<int:descarga_id>/excluir', methods=['POST'])
@login_required
def excluir_descarga(descarga_id):
    """Exclui uma descarga lancada MANUALMENTE (produto ficou no caminhao, nao
    desceu). So manual e so sem vinculo -- duas travas no servidor, nao confia
    no front. Como nao ha vinculo em descarga_nota, o DELETE nao deixa orfao.
    """
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, origem, total_descarga "
                    "FROM descargas_pendentes WHERE id = %s", (descarga_id,))
        d = cur.fetchone()
        if not d:
            return jsonify({'ok': False, 'erro': 'Descarga não encontrada.'}), 404

        # TRAVA 1: so descargas manuais podem ser excluidas (as do ELS sao reais).
        if d.get('origem') != 'manual':
            return jsonify({'ok': False,
                            'erro': 'Só descargas manuais podem ser excluídas.'}), 403

        # TRAVA 2: nao pode ter vinculo com nota (desfaca o vinculo antes).
        cur.execute("SELECT 1 FROM descarga_nota WHERE descarga_id = %s LIMIT 1",
                    (descarga_id,))
        if cur.fetchone():
            return jsonify({'ok': False,
                            'erro': 'Desfaça o vínculo com a(s) nota(s) antes de excluir.'}), 409

        # DELETE com AND origem='manual' (belt-and-suspenders contra corrida).
        cur.execute("DELETE FROM descargas_pendentes WHERE id = %s AND origem = 'manual'",
                    (descarga_id,))
        conn.commit()
        current_app.logger.info('[estoque] descarga manual %s (%s L) excluida por user %s',
                                 descarga_id, d.get('total_descarga'),
                                 getattr(current_user, 'id', None))
        return jsonify({'ok': True, 'id': descarga_id, 'apagou': cur.rowcount or 0})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': 'Falha ao excluir: %s' % e}), 500
    finally:
        cur.close()
        conn.close()


@estoque_bp.route('/estoque/vinculo/<int:vinculo_id>/desfazer', methods=['POST'])
@login_required
def desfazer_vinculo(vinculo_id):
    """Apaga o vinculo e recalcula — o status volta sozinho para 'pendente'."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        estado = remover_vinculo(cur, vinculo_id)
        if estado is None:
            return jsonify({'ok': False, 'erro': 'Vínculo não encontrado.'}), 404
        conn.commit()
        linha = _linha_descarga(cur, estado['descarga_id'], estado)
        return jsonify(dict({'ok': True, 'estado': estado,
                             'descarga_id': estado['descarga_id']}, **linha))
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': 'Falha ao desfazer: %s' % e}), 500
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# CONCILIACAO de estoque (por dia + produto + empresa, em LITROS).
#   Inicial + Recebido - Vendas = Esperado ; Perda/Sobra = Final - Esperado
#   Final de hoje = Inicial (leitura ABERTURA) de amanha, mesmo cliente/produto.
# Duas visoes: Recebido = NOTA (dfe) ou DESCARGA (descargas_pendentes). As duas
# dividem Inicial, Vendas e Final; a diferenca no Recebido = perda/sobra do
# recebimento (a nota diz X, desceu Y).
# Produto SEMPRE por produto_id (nunca cod_anp). So os 4 combustiveis.
# ==========================================================================
# produto_id -> (nome curto, cor, tom de fundo do icone, ordem de exibicao)
CONC_PRODUTOS = {
    2: {'nome': 'Gasolina', 'cor': '#BA7517', 'cbg': '#f7eede', 'ordem': 0},
    1: {'nome': 'Etanol',   'cor': '#639922', 'cbg': '#eaf3dd', 'ordem': 1},
    4: {'nome': 'S-500',    'cor': '#185FA5', 'cbg': '#e2edf7', 'ordem': 2},
    5: {'nome': 'S-10',     'cor': '#534AB7', 'cbg': '#e9e7f6', 'ordem': 3},
}
CONC_IDS = (1, 2, 4, 5)
_EPS_L = 0.5  # tolerancia p/ considerar recebido nota == descarga

# Corte de data da tela "Pendente pra descer": so lista notas emitidas nesta
# data em diante (as de julho/anteriores somem). Vale SO no pendente-descer
# (o selo na Compras nao usa isto). Ajuste aqui se precisar mudar o corte.
DATA_CORTE_PENDENTE = '2026-08-01'


# ==========================================================================
# AUDITORIA DE ESTOQUE — uma tabela por produto, com as DUAS contas por dia:
# N (nota fiscal) e D (descarga medida). Inicial, Vendas e Final sao iguais
# nas duas; o que muda e a compra — por isso viram sublinhas, nao telas.
#
# Regras aprovadas na prova:
#   Escritural = Inicial + Compras − Vendas
#   Perda/Sobra = Final − Escritural  (Final = ABERTURA do dia seguinte)
#   A NOTA MANDA: na linha N entra a quantidade da nota, lancada no dia em
#   que DESCEU (pelo vinculo). Integral = a nota inteira; fracionada = as
#   parcelas do vinculo, com a ULTIMA fechando a conta para somar a nota.
#   Cada parcela sabe de qual nota veio (F "de 13.000") — e nota emitida que
#   ainda nao desceu nao conta.
# ==========================================================================

def _aud_num(v):
    """9573.0 -> '9.573'; None -> em-dash."""
    if v is None:
        return '—'
    s = format(int(round(abs(v))), ',').replace(',', '.')
    return ('-' if v < 0 else '') + s


def _aud_saldo(v):
    """Perda com sinal e vermelha; sobra sem sinal e verde; zero neutro."""
    if v is None:
        return {'t': '—', 'c': 'neutro'}
    n = int(round(v))
    if n == 0:
        return {'t': '0', 'c': 'neutro'}
    s = format(abs(n), ',').replace(',', '.')
    if n < 0:
        return {'t': '−' + s, 'c': 'neg'}
    return {'t': s, 'c': 'pos'}


_AUD_DIAS_SEM = ('seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom')


def _auditoria_dados(cur, cliente_id, d_ini, d_fim):
    """Monta a auditoria: por produto, os dias com as duas contas.

    Pura de Flask de proposito: recebe cursor e datas, devolve estruturas ja
    formatadas pro template — e o teste roda isto direto contra o banco.
    """
    ids_in = ",".join(str(i) for i in CONC_IDS)
    d_fim_leitura = d_fim + timedelta(days=1)

    # -- leituras ABERTURA (inicial do dia; a do dia+1 e o final) ---------
    cur.execute(f"""
        SELECT DATE(l.data_leitura) AS dia, l.produto_id AS pid,
               SUM(l.volume_atual) AS litros
        FROM leitura_tanque_diaria l
        WHERE UPPER(TRIM(l.titulo)) = 'ABERTURA'
          AND l.cliente_id = %s AND l.produto_id IN ({ids_in})
          AND DATE(l.data_leitura) BETWEEN %s AND %s
        GROUP BY dia, pid""", (cliente_id, d_ini, d_fim_leitura))
    leit = {(r['dia'], r['pid']): float(r['litros'] or 0) for r in cur.fetchall()}

    # -- vendas (mesma ponte por CNPJ da conciliacao) ---------------------
    cur.execute(f"""
        SELECT DATE(v.dh_emissao) AS dia, i.produto_id AS pid,
               SUM(i.quantidade) AS litros
        FROM vendas_xml_itens i
        JOIN vendas_xml v ON v.id = i.venda_id
        JOIN clientes cl
          ON REPLACE(REPLACE(REPLACE(REPLACE(cl.cnpj, '.', ''), '/', ''), '-', ''), ' ', '')
             = v.cnpj_emitente
        WHERE cl.id = %s AND i.produto_id IN ({ids_in})
          AND i.unidade = 'L' AND v.situacao <> 'cancelada'
          AND DATE(v.dh_emissao) BETWEEN %s AND %s
        GROUP BY dia, pid""", (cliente_id, d_ini, d_fim))
    ven = {(r['dia'], r['pid']): float(r['litros'] or 0) for r in cur.fetchall()}

    # -- linha N: vinculos, com a alocacao "a nota manda" -----------------
    # Historia completa por item (um item pode ter parcela fora do periodo;
    # a alocacao precisa dela para a ultima parcela fechar certo).
    cur.execute(f"""
        SELECT dn.item_id, i.quantidade AS nota_l, dn.litros AS vinc_l,
               DATE(COALESCE(dp.data_descarga, dp.data_final, dp.data_inicial)) AS dia,
               dp.produto_id AS pid
        FROM descarga_nota dn
        JOIN dfe_itens i ON i.id = dn.item_id
        JOIN descargas_pendentes dp ON dp.id = dn.descarga_id
        WHERE dp.cliente_id = %s AND dp.produto_id IN ({ids_in})
        ORDER BY dn.item_id, dia, dn.id""", (cliente_id,))
    por_item = {}
    for r in cur.fetchall():
        por_item.setdefault(r['item_id'], []).append(r)

    nota, parcelas = {}, {}
    for _item, vs in por_item.items():
        nota_total = float(vs[0]['nota_l'] or 0)
        frac = len(vs) > 1
        resto = nota_total
        for k, r in enumerate(vs):
            if not frac:
                usar = nota_total
            elif k < len(vs) - 1:
                usar = min(float(r['vinc_l'] or 0), max(resto, 0.0))
            else:
                usar = resto
            resto -= usar
            if not (d_ini <= r['dia'] <= d_fim):
                continue
            ky = (r['dia'], r['pid'])
            nota[ky] = nota.get(ky, 0.0) + usar
            parcelas.setdefault(ky, []).append(
                {'l': _aud_num(usar), 'frac': frac, 'de': _aud_num(nota_total)})

    # -- linha D: a descarga medida ---------------------------------------
    cur.execute(f"""
        SELECT DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial)) AS dia,
               d.produto_id AS pid, SUM(d.total_descarga) AS litros
        FROM descargas_pendentes d
        WHERE d.cliente_id = %s AND d.produto_id IN ({ids_in})
          AND DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial))
              BETWEEN %s AND %s
        GROUP BY dia, pid""", (cliente_id, d_ini, d_fim))
    desc = {(r['dia'], r['pid']): float(r['litros'] or 0) for r in cur.fetchall()}

    # -- montagem ---------------------------------------------------------
    produtos, resumo = [], []
    tot_res_n = tot_res_d = 0.0
    for pid, info in sorted(CONC_PRODUTOS.items(), key=lambda kv: kv[1]['ordem']):
        linhas = []
        acu_n = acu_d = 0.0
        tot_cn = tot_cd = tot_v = 0.0
        perdas_n = sobras_n = perdas_d = sobras_d = 0.0
        dias_medidos = 0
        fim_n = fim_d = None
        d = d_ini
        while d <= d_fim:
            i2 = leit.get((d, pid))
            f2 = leit.get((d + timedelta(days=1), pid))
            v = ven.get((d, pid), 0.0)
            cn_ = nota.get((d, pid), 0.0)
            cd = desc.get((d, pid), 0.0)
            esc_n = (i2 + cn_ - v) if i2 is not None else None
            esc_d = (i2 + cd - v) if i2 is not None else None
            per_n = (f2 - esc_n) if (esc_n is not None and f2 is not None) else None
            per_d = (f2 - esc_d) if (esc_d is not None and f2 is not None) else None
            if per_n is not None:
                acu_n += per_n
                fim_n = acu_n
                dias_medidos += 1
                if per_n < 0:
                    perdas_n += per_n
                else:
                    sobras_n += per_n
            if per_d is not None:
                acu_d += per_d
                fim_d = acu_d
                if per_d < 0:
                    perdas_d += per_d
                else:
                    sobras_d += per_d
            tot_cn += cn_
            tot_cd += cd
            tot_v += v

            piores = [x for x in (per_n, per_d) if x is not None]
            destaque = ''
            if piores and min(piores) < -300:
                destaque = 'ruim'
            elif piores and max(piores) > 300 and min(piores) > -300:
                destaque = 'sobra'

            linhas.append({
                'data': d.strftime('%d/%m'), 'dsem': _AUD_DIAS_SEM[d.weekday()],
                'destaque': destaque,
                'ini': _aud_num(i2), 'ven': _aud_num(v), 'fin': _aud_num(f2),
                'cn': _aud_num(cn_), 'cd': _aud_num(cd),
                'esc_n': _aud_num(esc_n), 'esc_d': _aud_num(esc_d),
                'per_n': _aud_saldo(per_n), 'per_d': _aud_saldo(per_d),
                'acu_n': _aud_saldo(acu_n if per_n is not None else None),
                'acu_d': _aud_saldo(acu_d if per_d is not None else None),
                'parcelas': parcelas.get((d, pid), []),
            })
            d += timedelta(days=1)

        produtos.append({
            'pid': pid, 'nome': info['nome'], 'cor': info['cor'],
            'cbg': info['cbg'], 'linhas': linhas,
            'tot_cn': _aud_num(tot_cn), 'tot_cd': _aud_num(tot_cd),
            'tot_v': _aud_num(tot_v),
            'fim_n': _aud_saldo(fim_n), 'fim_d': _aud_saldo(fim_d),
        })
        resumo.append({
            'nome': info['nome'], 'cor': info['cor'], 'dias': dias_medidos,
            'per_n': _aud_saldo(perdas_n if perdas_n else 0),
            'per_d': _aud_saldo(perdas_d if perdas_d else 0),
            'sob_n': _aud_saldo(sobras_n if sobras_n else 0),
            'sob_d': _aud_saldo(sobras_d if sobras_d else 0),
            'sal_n': _aud_saldo(fim_n if fim_n is not None else 0),
            'sal_d': _aud_saldo(fim_d if fim_d is not None else 0),
        })
        tot_res_n += (fim_n or 0)
        tot_res_d += (fim_d or 0)

    return produtos, resumo, {'n': _aud_saldo(tot_res_n), 'd': _aud_saldo(tot_res_d)}


@estoque_bp.route('/estoque/auditoria', methods=['GET'])
@login_required
def auditoria():
    hoje = date.today()
    f_empresa = (request.args.get('empresa') or '').strip()
    f_ini = (request.args.get('data_ini') or '').strip()
    f_fim = (request.args.get('data_fim') or '').strip()
    # Sem filtro, vem o MES CORRENTE: do dia 1 ate hoje. E o recorte que o
    # posto fecha — "quanto perdemos em agosto" — nao uma janela movel.
    try:
        d_ini = (datetime.strptime(f_ini, '%Y-%m-%d').date()
                 if f_ini else hoje.replace(day=1))
        d_fim = datetime.strptime(f_fim, '%Y-%m-%d').date() if f_fim else hoje
    except ValueError:
        d_ini, d_fim = hoje.replace(day=1), hoje
    if d_fim < d_ini:
        d_ini, d_fim = d_fim, d_ini
    # Teto de 92 dias: cada dia sao 4 produtos x varias consultas em memoria;
    # um range de anos por engano nao pode derrubar a tela.
    if (d_fim - d_ini).days > 92:
        d_ini = d_fim - timedelta(days=92)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # empresas auditaveis: as que tem leitura de tanque
        cur.execute(
            """
            SELECT DISTINCT c.id, COALESCE(NULLIF(c.nome_fantasia, ''),
                                           c.razao_social) AS nome
            FROM clientes c
            WHERE c.id IN (SELECT cliente_id FROM leitura_tanque_diaria
                           WHERE cliente_id IS NOT NULL)
            ORDER BY nome
            """
        )
        empresas = cur.fetchall()
        cliente_id = None
        if f_empresa.isdigit() and any(e['id'] == int(f_empresa) for e in empresas):
            cliente_id = int(f_empresa)
        elif empresas:
            cliente_id = empresas[0]['id']

        produtos, resumo, totais = ([], [], {'n': _aud_saldo(None), 'd': _aud_saldo(None)})
        if cliente_id:
            produtos, resumo, totais = _auditoria_dados(cur, cliente_id, d_ini, d_fim)

        return render_template(
            'estoque/auditoria.html',
            empresas=empresas, cliente_id=cliente_id,
            produtos=produtos, resumo=resumo, totais=totais,
            data_ini=d_ini.strftime('%Y-%m-%d'), data_fim=d_fim.strftime('%Y-%m-%d'),
            n_filtros=(1 if f_empresa else 0) + (1 if f_ini or f_fim else 0),
        )
    finally:
        cur.close()
        conn.close()


@estoque_bp.route('/estoque/conciliacao', methods=['GET'])
@login_required
def conciliacao():
    f = {
        'empresa':  (request.args.get('empresa') or '').strip(),
        'produto':  (request.args.get('produto') or '').strip(),
        'data_ini': (request.args.get('data_ini') or '').strip(),
        'data_fim': (request.args.get('data_fim') or '').strip(),
    }
    hoje = date.today()
    data_ini = f['data_ini'] or (hoje - timedelta(days=14)).strftime('%Y-%m-%d')
    data_fim = f['data_fim'] or hoje.strftime('%Y-%m-%d')
    # Final do ultimo dia = ABERTURA do dia seguinte -> leituras vao ate +1 dia.
    data_fim_leitura = (datetime.strptime(data_fim, '%Y-%m-%d').date()
                        + timedelta(days=1)).strftime('%Y-%m-%d')

    # produto_id do filtro (se informado e valido).
    pid_filtro = None
    if f['produto']:
        try:
            pf = int(f['produto'])
            if pf in CONC_PRODUTOS:
                pid_filtro = pf
        except (TypeError, ValueError):
            pid_filtro = None

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Empresas p/ dropdown: as que tem leitura de tanque (as conciliaveis).
        cur.execute(
            """
            SELECT DISTINCT c.id, COALESCE(c.nome_fantasia, c.razao_social) AS nome
            FROM clientes c
            WHERE c.id IN (SELECT cliente_id FROM leitura_tanque_diaria
                           WHERE cliente_id IS NOT NULL)
            ORDER BY nome
            """
        )
        empresas = cur.fetchall()

        ids_in = ",".join(str(i) for i in CONC_IDS)

        # ---- 1) INICIAL/FINAL: leitura ABERTURA (volume_atual) ----
        # Uma so consulta cobre inicial (dia) e final (dia+1). Range ate +1 dia.
        sql_ini = f"""
            SELECT l.cliente_id, DATE(l.data_leitura) AS dia, l.produto_id AS pid,
                   SUM(l.volume_atual) AS litros,
                   GROUP_CONCAT(DISTINCT l.tanque ORDER BY l.tanque) AS tanques
            FROM leitura_tanque_diaria l
            WHERE UPPER(TRIM(l.titulo)) = 'ABERTURA'
              AND l.produto_id IN ({ids_in})
              AND DATE(l.data_leitura) BETWEEN %s AND %s
        """
        p_ini = [data_ini, data_fim_leitura]
        if f['empresa']:
            sql_ini += " AND l.cliente_id = %s"; p_ini.append(f['empresa'])
        if pid_filtro:
            sql_ini += " AND l.produto_id = %s"; p_ini.append(pid_filtro)
        sql_ini += " GROUP BY l.cliente_id, dia, pid"
        cur.execute(sql_ini, p_ini)
        leitura_map = {}   # (cid, dia, pid) -> {'litros', 'tanques'}
        for r in cur.fetchall():
            leitura_map[(r['cliente_id'], r['dia'], r['pid'])] = {
                'litros': float(r['litros'] or 0), 'tanques': r['tanques']}

        # ---- 2) VENDAS: por empresa (ponte cnpj), produto ja resolvido ----
        sql_ven = f"""
            SELECT cl.id AS cliente_id, DATE(v.dh_emissao) AS dia,
                   i.produto_id AS pid, SUM(i.quantidade) AS litros
            FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            JOIN clientes cl
              ON REPLACE(REPLACE(REPLACE(REPLACE(cl.cnpj, '.', ''), '/', ''), '-', ''), ' ', '')
                 = v.cnpj_emitente
            WHERE i.produto_id IN ({ids_in})
              AND i.unidade = 'L'
              AND v.situacao <> 'cancelada'
              AND DATE(v.dh_emissao) BETWEEN %s AND %s
        """
        p_ven = [data_ini, data_fim]
        if f['empresa']:
            sql_ven += " AND cl.id = %s"; p_ven.append(f['empresa'])
        if pid_filtro:
            sql_ven += " AND i.produto_id = %s"; p_ven.append(pid_filtro)
        sql_ven += " GROUP BY cl.id, dia, pid"
        cur.execute(sql_ven, p_ven)
        vendas_map = {(r['cliente_id'], r['dia'], r['pid']): float(r['litros'] or 0)
                      for r in cur.fetchall()}

        # ---- 3) RECEBIDO-NOTA: dfe_itens (COALESCE classificado, produto_id) ----
        sql_rn = f"""
            SELECT d.cliente_id, DATE(d.dh_emissao) AS dia,
                   COALESCE(i.classificado_produto_id, i.produto_id) AS pid,
                   SUM(i.quantidade) AS litros
            FROM dfe_itens i
            JOIN dfe_documentos d ON d.id = i.documento_id
            WHERE d.tipo = 'NFe' AND d.situacao = 'autorizado'
              AND (i.categoria IS NULL OR i.categoria <> 'ignorar')
              AND COALESCE(i.classificado_produto_id, i.produto_id) IN ({ids_in})
              AND DATE(d.dh_emissao) BETWEEN %s AND %s
        """
        p_rn = [data_ini, data_fim]
        if f['empresa']:
            sql_rn += " AND d.cliente_id = %s"; p_rn.append(f['empresa'])
        if pid_filtro:
            sql_rn += " AND COALESCE(i.classificado_produto_id, i.produto_id) = %s"
            p_rn.append(pid_filtro)
        sql_rn += " GROUP BY d.cliente_id, dia, pid"
        cur.execute(sql_rn, p_rn)
        recnota_map = {(r['cliente_id'], r['dia'], r['pid']): float(r['litros'] or 0)
                       for r in cur.fetchall()}

        # ---- 4) RECEBIDO-DESCARGA: descargas_pendentes ----
        sql_rd = f"""
            SELECT d.cliente_id,
                   DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial)) AS dia,
                   d.produto_id AS pid, SUM(d.total_descarga) AS litros
            FROM descargas_pendentes d
            WHERE d.produto_id IN ({ids_in})
              AND DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial))
                  BETWEEN %s AND %s
        """
        p_rd = [data_ini, data_fim]
        if f['empresa']:
            sql_rd += " AND d.cliente_id = %s"; p_rd.append(f['empresa'])
        if pid_filtro:
            sql_rd += " AND d.produto_id = %s"; p_rd.append(pid_filtro)
        sql_rd += " GROUP BY d.cliente_id, dia, pid"
        cur.execute(sql_rd, p_rd)
        recdesc_map = {(r['cliente_id'], r['dia'], r['pid']): float(r['litros'] or 0)
                       for r in cur.fetchall()}

        # Nome das empresas (p/ card quando nao ha filtro de empresa).
        nome_emp = {e['id']: e['nome'] for e in empresas}

        # ---- MONTAGEM: chaves = tudo que tem leitura (no range pedido) OU
        #      movimento (venda/nota/descarga). Final vem da leitura de dia+1. ----
        d_ini = datetime.strptime(data_ini, '%Y-%m-%d').date()
        d_fim = datetime.strptime(data_fim, '%Y-%m-%d').date()

        chaves = set()
        for (cid, dia, pid), _v in leitura_map.items():
            if d_ini <= dia <= d_fim:            # leitura de dia+1 nao vira card sozinha
                chaves.add((cid, dia, pid))
        for m in (vendas_map, recnota_map, recdesc_map):
            for (cid, dia, pid) in m:
                if d_ini <= dia <= d_fim:
                    chaves.add((cid, dia, pid))

        dias_map = {}   # dia -> lista de cards
        for (cid, dia, pid) in chaves:
            info = CONC_PRODUTOS.get(pid)
            if not info:
                continue
            li = leitura_map.get((cid, dia, pid))
            lf = leitura_map.get((cid, dia + timedelta(days=1), pid))
            ini = li['litros'] if li else None
            fin = lf['litros'] if lf else None
            ven = vendas_map.get((cid, dia, pid), 0.0)
            rec_nota = recnota_map.get((cid, dia, pid), 0.0)
            rec_desc = recdesc_map.get((cid, dia, pid), 0.0)

            def _conta(rec):
                if ini is None:
                    return None, None
                esp = ini + rec - ven
                perda = (fin - esp) if fin is not None else None
                return esp, perda

            esp_n, perda_n = _conta(rec_nota)
            esp_d, perda_d = _conta(rec_desc)

            card = {
                'cliente_id': cid,
                'empresa_nome': nome_emp.get(cid, '—'),
                'pid': pid, 'nome': info['nome'], 'cor': info['cor'],
                'ordem': info['ordem'],
                'tanques': (li or lf or {}).get('tanques'),
                'ini': ini, 'fin': fin, 'ven': ven,
                'rec_nota': rec_nota, 'rec_desc': rec_desc,
                'esp_nota': esp_n, 'perda_nota': perda_n,
                'esp_desc': esp_d, 'perda_desc': perda_d,
                'delta_rec': (rec_nota - rec_desc)
                             if abs(rec_nota - rec_desc) > _EPS_L else None,
            }
            dias_map.setdefault(dia, []).append(card)

        # Ordena cards no dia (produto, depois empresa) e calcula saldo do dia.
        dias = []
        for dia in sorted(dias_map.keys(), reverse=True):
            cards = sorted(dias_map[dia], key=lambda c: (c['ordem'], c['empresa_nome']))
            perdas_n = [c['perda_nota'] for c in cards if c['perda_nota'] is not None]
            perdas_d = [c['perda_desc'] for c in cards if c['perda_desc'] is not None]
            dias.append({
                'data': dia,
                'rotulo': _rotulo_dia(dia),
                'saldo_nota': (sum(perdas_n) if perdas_n else None),
                'saldo_desc': (sum(perdas_d) if perdas_d else None),
                'cards': cards,
            })

        n_filtros = sum(1 for k in ('empresa', 'produto', 'data_ini', 'data_fim') if f[k])

        return render_template(
            'estoque/conciliacao.html',
            dias=dias, empresas=empresas, filtros=f,
            data_ini_default=data_ini, data_fim_default=data_fim,
            produtos_opts=sorted(CONC_PRODUTOS.items(), key=lambda kv: kv[1]['ordem']),
            n_filtros=n_filtros, um_empresa=bool(f['empresa']),
        )
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# RELER E-MAILS de descarga (botao na aba Descargas). Rele LIDOS + nao-lidos
# dos ultimos dias e captura os que faltam, SEM marcar como lido. Idempotente
# (chave UNIQUE + gravar_descarga pula duplicadas). Usa o MESMO GET_LOCK do
# scheduler p/ nao rodar concorrente com um tick da importacao.
# ==========================================================================
_RELER_DIAS = 3
_ELS_LOCK = "els_email_import"


@estoque_bp.route('/estoque/descargas/reler', methods=['POST'])
@login_required
def descargas_reler():
    conn = get_db_connection()
    cur = conn.cursor()
    got = 0
    try:
        # Espera ate 5s pelo lock; se o scheduler estiver importando, avisa.
        cur.execute("SELECT GET_LOCK(%s, 5)", (_ELS_LOCK,))
        row = cur.fetchone()
        got = row[0] if row else 0
        if got != 1:
            return jsonify({'ok': False,
                            'erro': 'Importação em andamento; tente em instantes.'}), 409

        from integrations.els_email import reprocessar
        saida = reprocessar(dias=_RELER_DIAS)
        if isinstance(saida, dict) and saida.get('erro'):
            return jsonify({'ok': False, 'erro': saida['erro']}), 500

        novas = int(saida.get('novas', 0))
        if novas == 1:
            msg = '1 nova descarga capturada'
        elif novas > 1:
            msg = '%d novas descargas capturadas' % novas
        else:
            msg = 'Nenhuma descarga nova'
        return jsonify({'ok': True, 'novas': novas, 'msg': msg, 'detalhe': saida})
    except Exception as e:
        current_app.logger.exception('[estoque/reler] falha ao reler e-mails')
        return jsonify({'ok': False, 'erro': 'Falha ao reler e-mails: %s' % e}), 500
    finally:
        try:
            if got == 1:
                cur.execute("SELECT RELEASE_LOCK(%s)", (_ELS_LOCK,))
                cur.fetchall()
        except Exception:
            pass
        cur.close()
        conn.close()


# ==========================================================================
# HELPERS reutilizaveis (usados pela tela /estoque/tempo-real E pela home).
#   Saldo agora = Abertura de hoje + Recebido hoje (descarga) - Vendas hoje,
#   de UMA empresa, "hoje" = America/Sao_Paulo. SOMENTE LEITURA (recebe cursor).
# ==========================================================================
def dados_tempo_real(cur, cliente_id=1):
    """Saldo agora (aproximado) dos 4 combustiveis de UMA empresa, hoje.
    Retorna lista ORDENADA (Gasolina, Etanol, S-500, S-10) com nome/cor/abriu/
    rec/ven/saldo. saldo=None quando nao ha leitura de ABERTURA hoje."""
    hoje_s = hoje_brasilia().strftime('%Y-%m-%d')
    ids_in = ",".join(str(i) for i in CONC_IDS)

    cur.execute(
        f"""SELECT produto_id AS pid, SUM(volume_atual) AS litros
            FROM leitura_tanque_diaria
            WHERE UPPER(TRIM(titulo)) = 'ABERTURA' AND produto_id IN ({ids_in})
              AND DATE(data_leitura) = %s AND cliente_id = %s
            GROUP BY produto_id""",
        (hoje_s, cliente_id),
    )
    abertura = {r['pid']: float(r['litros'] or 0) for r in cur.fetchall()}

    cur.execute(
        f"""SELECT produto_id AS pid, SUM(total_descarga) AS litros
            FROM descargas_pendentes
            WHERE produto_id IN ({ids_in})
              AND DATE(COALESCE(data_descarga, data_final, data_inicial)) = %s
              AND cliente_id = %s
            GROUP BY produto_id""",
        (hoje_s, cliente_id),
    )
    recebido = {r['pid']: float(r['litros'] or 0) for r in cur.fetchall()}

    cur.execute(
        f"""SELECT i.produto_id AS pid, SUM(i.quantidade) AS litros
            FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            JOIN clientes cl
              ON REPLACE(REPLACE(REPLACE(REPLACE(cl.cnpj, '.', ''), '/', ''), '-', ''), ' ', '')
                 = v.cnpj_emitente
            WHERE i.produto_id IN ({ids_in}) AND i.unidade = 'L'
              AND v.situacao <> 'cancelada'
              AND DATE(v.dh_emissao) = %s AND cl.id = %s
            GROUP BY i.produto_id""",
        (hoje_s, cliente_id),
    )
    vendas = {r['pid']: float(r['litros'] or 0) for r in cur.fetchall()}

    out = []
    for pid, info in sorted(CONC_PRODUTOS.items(), key=lambda kv: kv[1]['ordem']):
        tem_ab = pid in abertura
        ab = abertura.get(pid)
        rec = recebido.get(pid, 0.0)
        ven = vendas.get(pid, 0.0)
        out.append({
            'pid': pid, 'nome': info['nome'], 'cor': info['cor'],
            'abriu': ab, 'rec': rec, 'ven': ven,
            'saldo': (ab + rec - ven) if tem_ab else None,
        })
    return out


# ==========================================================================
# ESTOQUE EM TEMPO REAL (saldo APROXIMADO de HOJE, por produto/empresa).
#   Saldo agora = Abertura de hoje + Recebido hoje (descarga/e-mail) - Vendas hoje
# O "Recebido" vem da DESCARGA (descargas_pendentes, e-mail/ELS), imediata; a
# nota fiscal e vinculada depois -> saldo aproximado, nao contabil.
# "Hoje" = America/Sao_Paulo (mesmo criterio da Conciliacao).
# ==========================================================================
@estoque_bp.route('/estoque/tempo-real', methods=['GET'])
@login_required
def tempo_real():
    empresa = (request.args.get('empresa') or '').strip()
    hoje = hoje_brasilia()
    hoje_s = hoje.strftime('%Y-%m-%d')
    agora_hm = datetime.now(BRASILIA).strftime('%H:%M')

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Empresas p/ dropdown: as que tem leitura de tanque (as conciliaveis).
        cur.execute(
            """
            SELECT DISTINCT c.id, COALESCE(c.nome_fantasia, c.razao_social) AS nome
            FROM clientes c
            WHERE c.id IN (SELECT cliente_id FROM leitura_tanque_diaria
                           WHERE cliente_id IS NOT NULL)
            ORDER BY nome
            """
        )
        empresas = cur.fetchall()
        nome_emp = {e['id']: e['nome'] for e in empresas}

        ids_in = ",".join(str(i) for i in CONC_IDS)

        # ---- 1) ABERTURA de hoje ----
        sql_ab = f"""
            SELECT l.cliente_id, l.produto_id AS pid, SUM(l.volume_atual) AS litros,
                   GROUP_CONCAT(DISTINCT l.tanque ORDER BY l.tanque) AS tanques
            FROM leitura_tanque_diaria l
            WHERE UPPER(TRIM(l.titulo)) = 'ABERTURA'
              AND l.produto_id IN ({ids_in})
              AND DATE(l.data_leitura) = %s
        """
        p_ab = [hoje_s]
        if empresa:
            sql_ab += " AND l.cliente_id = %s"; p_ab.append(empresa)
        sql_ab += " GROUP BY l.cliente_id, pid"
        cur.execute(sql_ab, p_ab)
        abertura = {(r['cliente_id'], r['pid']): {'litros': float(r['litros'] or 0),
                                                  'tanques': r['tanques']}
                    for r in cur.fetchall()}

        # ---- 2) RECEBIDO hoje (descarga do e-mail) ----
        sql_rec = f"""
            SELECT d.cliente_id, d.produto_id AS pid, SUM(d.total_descarga) AS litros
            FROM descargas_pendentes d
            WHERE d.produto_id IN ({ids_in})
              AND DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial)) = %s
        """
        p_rec = [hoje_s]
        if empresa:
            sql_rec += " AND d.cliente_id = %s"; p_rec.append(empresa)
        sql_rec += " GROUP BY d.cliente_id, pid"
        cur.execute(sql_rec, p_rec)
        recebido = {(r['cliente_id'], r['pid']): float(r['litros'] or 0)
                    for r in cur.fetchall()}

        # ---- 3) VENDAS hoje (produto ja resolvido; ponte cnpj -> cliente_id) ----
        sql_ven = f"""
            SELECT cl.id AS cliente_id, i.produto_id AS pid, SUM(i.quantidade) AS litros
            FROM vendas_xml_itens i
            JOIN vendas_xml v ON v.id = i.venda_id
            JOIN clientes cl
              ON REPLACE(REPLACE(REPLACE(REPLACE(cl.cnpj, '.', ''), '/', ''), '-', ''), ' ', '')
                 = v.cnpj_emitente
            WHERE i.produto_id IN ({ids_in})
              AND i.unidade = 'L'
              AND v.situacao <> 'cancelada'
              AND DATE(v.dh_emissao) = %s
        """
        p_ven = [hoje_s]
        if empresa:
            sql_ven += " AND cl.id = %s"; p_ven.append(empresa)
        sql_ven += " GROUP BY cl.id, pid"
        cur.execute(sql_ven, p_ven)
        vendas = {(r['cliente_id'], r['pid']): float(r['litros'] or 0)
                  for r in cur.fetchall()}

        # ---- MONTAGEM: um card por (empresa, produto) com qualquer sinal hoje ----
        chaves = set(abertura) | set(recebido) | set(vendas)
        cards = []
        for (cid, pid) in chaves:
            info = CONC_PRODUTOS.get(pid)
            if not info:
                continue
            ab = abertura.get((cid, pid))
            rec = recebido.get((cid, pid), 0.0)
            ven = vendas.get((cid, pid), 0.0)
            tem_ab = ab is not None
            saldo = (ab['litros'] + rec - ven) if tem_ab else None
            cards.append({
                'cliente_id': cid,
                'empresa_nome': nome_emp.get(cid, '—'),
                'pid': pid, 'nome': info['nome'], 'cor': info['cor'],
                'cbg': info['cbg'], 'ordem': info['ordem'],
                'tanques': ab['tanques'] if tem_ab else None,
                'abriu': ab['litros'] if tem_ab else None,
                'rec': rec, 'ven': ven, 'saldo': saldo,
            })
        cards.sort(key=lambda c: (c['empresa_nome'], c['ordem']))

        return render_template(
            'estoque/tempo_real.html',
            cards=cards, empresas=empresas, empresa=empresa,
            um_empresa=bool(empresa),
            empresa_nome=(nome_emp.get(int(empresa)) if empresa.isdigit() else None),
            agora_hm=agora_hm,
        )
    finally:
        cur.close()
        conn.close()


# ==========================================================================
# PENDENTE PRA DESCER: notas que compraram combustivel mas nao desceram tudo.
#   saldo = dfe_itens.quantidade - SUM(descarga_nota.litros do item)
#   descarta itens FECHADOS (existe descarga_nota.modo='integral') e
#   categoria='ignorar'. Produto = COALESCE(classificado_produto_id, produto_id),
#   so combustivel {1,2,4,5}, so NFe autorizado. Lista os com saldo > 0.
# Motorista/placa vem do CT-e vinculado (dfe_cte_nfe -> dfe_cte); 1 nota pode
# ter N CT-e -> mostra o principal + "+N".
# ==========================================================================
@estoque_bp.route('/estoque/pendente-descer', methods=['GET'])
@login_required
def pendente_descer():
    empresa = (request.args.get('empresa') or '').strip()
    produto = (request.args.get('produto') or '').strip()
    pid_filtro = int(produto) if (produto.isdigit() and int(produto) in CONC_PRODUTOS) else None

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Empresas p/ dropdown: as que tem NF-e capturada.
        cur.execute(
            """
            SELECT DISTINCT c.id, COALESCE(c.nome_fantasia, c.razao_social) AS nome
            FROM clientes c
            WHERE c.id IN (SELECT cliente_id FROM dfe_documentos
                           WHERE tipo = 'NFe' AND cliente_id IS NOT NULL)
            ORDER BY nome
            """
        )
        empresas = cur.fetchall()
        nome_emp = {e['id']: e['nome'] for e in empresas}

        ids_in = ",".join(str(i) for i in CONC_IDS)

        # ---- Itens de NF-e combustivel com SALDO > 0 (formula da Camada 2) ----
        sql = f"""
            SELECT doc.id AS documento_id, doc.chave, doc.numero, doc.serie,
                   doc.dh_emissao, doc.cliente_id, doc.emit_nome,
                   COALESCE(i.classificado_produto_id, i.produto_id) AS pid,
                   i.quantidade AS nota_litros,
                   COALESCE(v.litros, 0) AS ja_desceu,
                   (i.quantidade - COALESCE(v.litros, 0)) AS saldo
            FROM dfe_itens i
            JOIN dfe_documentos doc ON doc.id = i.documento_id
            LEFT JOIN (SELECT item_id, SUM(litros) AS litros
                         FROM descarga_nota GROUP BY item_id) v
                   ON v.item_id = i.id
            WHERE doc.tipo = 'NFe' AND doc.situacao = 'autorizado'
              AND DATE(doc.dh_emissao) >= %s
              AND COALESCE(i.classificado_produto_id, i.produto_id) IN ({ids_in})
              AND (i.categoria IS NULL OR i.categoria <> 'ignorar')
              AND NOT EXISTS (SELECT 1 FROM descarga_nota f
                              WHERE f.item_id = i.id AND f.modo = 'integral')
              AND (i.quantidade - COALESCE(v.litros, 0)) > 0.001
        """
        p = [DATA_CORTE_PENDENTE]
        if empresa:
            sql += " AND doc.cliente_id = %s"; p.append(empresa)
        if pid_filtro:
            sql += " AND COALESCE(i.classificado_produto_id, i.produto_id) = %s"
            p.append(pid_filtro)
        sql += " ORDER BY doc.dh_emissao DESC, doc.id DESC"
        cur.execute(sql, p)
        rows = cur.fetchall()

        # ---- CT-e (motorista/placa) por chave da NF-e ----
        ctes = {}
        chaves = list({r['chave'] for r in rows if r['chave']})
        if chaves:
            marc = ",".join(["%s"] * len(chaves))
            cur.execute(
                f"""
                SELECT n.chave_nfe, ct.motorista_nome, ct.placa
                FROM dfe_cte_nfe n
                JOIN dfe_documentos c ON c.id = n.documento_id AND c.tipo = 'CTe'
                LEFT JOIN dfe_cte ct ON ct.documento_id = c.id
                WHERE n.chave_nfe IN ({marc})
                ORDER BY c.dh_emissao
                """,
                chaves,
            )
            for r in cur.fetchall():
                ctes.setdefault(r['chave_nfe'], []).append(r)

        cards = []
        total_litros = 0.0
        notas = set()
        for r in rows:
            info = CONC_PRODUTOS.get(r['pid'])
            if not info:
                continue
            saldo = float(r['saldo'] or 0)
            total_litros += saldo
            notas.add(r['documento_id'])

            # Motorista principal + "+N" (deduplica por nome).
            mot_nome = placa = None
            mais = 0
            vistos = []
            for x in ctes.get(r['chave'], []):
                mn = (x.get('motorista_nome') or '').strip()
                if mn and mn not in [s[0] for s in vistos]:
                    vistos.append((mn, x.get('placa')))
            if vistos:
                mot_nome, placa = vistos[0]
                mais = len(vistos) - 1

            cards.append({
                'empresa_nome': nome_emp.get(r['cliente_id'], '—'),
                'pid': r['pid'], 'nome': info['nome'], 'cor': info['cor'],
                'numero': r['numero'], 'serie': r['serie'],
                'data': r['dh_emissao'], 'fornecedor': r['emit_nome'],
                'mot_nome': mot_nome, 'placa': placa, 'mais': mais,
                'nota_litros': float(r['nota_litros'] or 0),
                'ja_desceu': float(r['ja_desceu'] or 0),
                'saldo': saldo,
            })

        totais = {'notas': len(notas), 'litros': total_litros}
        n_filtros = sum(1 for x in (empresa, produto) if x)

        return render_template(
            'estoque/pendente_descer.html',
            cards=cards, totais=totais, empresas=empresas,
            empresa=empresa, produto=produto, um_empresa=bool(empresa),
            produtos_opts=sorted(CONC_PRODUTOS.items(), key=lambda kv: kv[1]['ordem']),
            n_filtros=n_filtros,
        )
    finally:
        cur.close()
        conn.close()
