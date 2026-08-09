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
from datetime import date, timedelta
from urllib.parse import urlencode

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

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
            d['vinc_fechadas'] = v['fechadas'] if v else 0
            d['vinc_falta'] = round(float(d.get('total_descarga') or 0)
                                    - (v['litros'] if v else 0.0), 3)
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
            filtros=f, n_filtros=n_filtros, empresas=empresas, tab=tab,
            data_ini_default=data_ini_default, data_fim_default=data_fim_default,
            page_l=page_l, tp_l=tp_l, paginas_l=_janela_paginas(page_l, tp_l),
            page_d=page_d, tp_d=tp_d, paginas_d=_janela_paginas(page_d, tp_d),
            qs_filtros=qs_filtros,
        )
    finally:
        cur.close()
        conn.close()


def _acao_html(cur, descarga_id, estado):
    """HTML do .mig-dia__acao desta descarga, ja renderizado.

    O JS troca esse pedaco na linha depois de vincular/desfazer, entao a pagina
    nao recarrega. Renderiza o MESMO parcial que o index usa — sem isso a
    marcacao viveria em dois lugares (Jinja e JS) e divergiria.
    """
    res = vinculos_resumo(cur, [descarga_id]).get(descarga_id)
    d = {
        'id': descarga_id,
        'vinc_n': res['n'] if res else 0,
        'vinc_litros': res['litros'] if res else 0.0,
        'vinc_numero': res['numero'] if res else None,
        'vinc_falta': estado['falta'],
        'vinc_fechadas': res['fechadas'] if res else 0,
    }
    return render_template('estoque/_acao_descarga.html', d=d)


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
        return jsonify({'ok': True, 'estado': estado,
                        'acao_html': _acao_html(cur, descarga_id, estado)})
    except ValueError as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': 'Falha ao vincular: %s' % e}), 500
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
        return jsonify({'ok': True, 'estado': estado,
                        'descarga_id': estado['descarga_id'],
                        'acao_html': _acao_html(cur, estado['descarga_id'], estado)})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': 'Falha ao desfazer: %s' % e}), 500
    finally:
        cur.close()
        conn.close()
