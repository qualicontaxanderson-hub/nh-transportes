from flask import Blueprint, render_template, current_app, url_for, jsonify, request, redirect, flash
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.pagamentos import classificar_recebimento
from utils.fuso import hoje_brasilia, janelas_dia_mes

bp = Blueprint('bases', __name__)

# ── Onda 1 do carrossel do dashboard: regra dura de identificação de produto ──
# 4 combustíveis por cod_anp + ARLA por cprod. NUNCA usa eh_combustivel.
_ONDA1_CASE = (
    "CASE "
    "WHEN i.cod_anp='820101012' THEN 'Diesel S-500' "
    "WHEN i.cod_anp='820101034' THEN 'Diesel S-10' "
    "WHEN i.cod_anp='810101001' THEN 'Etanol' "
    "WHEN i.cod_anp='320102001' THEN 'Gasolina C' "
    "WHEN i.cprod='64' THEN 'ARLA' "
    "ELSE 'Outros' END"
)
# Ordem fixa das linhas nos cards (casa com as cores .onda1-dot--0..--4).
_ONDA1_ORDEM = ['Diesel S-500', 'Diesel S-10', 'Etanol', 'Gasolina C', 'ARLA']


def _dados_onda1_dashboard(hoje=None):
    """Onda 1 do carrossel: Vendas do Dia, Vendas do Mês e Ranking do Dia.

    ISOLADO (conexão própria) e SOMENTE LEITURA. Nunca altera nada nem derruba
    o dashboard: qualquer erro -> retorna estrutura vazia segura.

    `hoje` é SEMPRE a data de Brasília (ver utils.fuso): dh_emissao está em
    horário de Brasília, então as janelas do dia e do mês são montadas nesse
    fuso — nunca no fuso do servidor (UTC).

    Reconciliação (confirmada no banco, resíduo 0,00):
        Total da nota = Σ itens + acréscimo − desconto   (troco não entra)
    Por isso cada período expõe `acrescimo` e `desconto`, e o rodapé fecha
    exatamente no `total` (nível nota).
    """
    if hoje is None:
        hoje = hoje_brasilia()

    ini_dia, fim_dia, ini_mes, fim_mes = janelas_dia_mes(hoje)

    def _p_vazio():
        return {'notas': 0, 'total': 0.0, 'ticket': 0.0, 'litros_comb': 0.0, 'linhas': [],
                'sub_comb': 0.0, 'sub_outros': 0.0, 'qt_outros': 0,
                'sub_produtos': 0.0, 'acrescimo': 0.0, 'desconto': 0.0}
    _r_vazio = {'venda': 0.0, 'comigo': 0.0, 'meu': 0.0, 'repasse': 0.0,
                'total': 0.0, 'operadoras': []}
    vazio = {'dia': _p_vazio(), 'mes': _p_vazio(), 'ranking': [],
             'recebimento': [], 'recebimento_total': 0.0,
             'repasse': {'dia': dict(_r_vazio), 'mes': dict(_r_vazio)}}

    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        def _periodo(ini, fim):
            # Cabeçalho + rodapé: nível NOTA (faturamento fiscal, acréscimo, desconto).
            cur.execute(
                "SELECT COUNT(*) AS notas, "
                "COALESCE(SUM(v.valor_total),0) AS total, "
                "COALESCE(SUM(v.vlr_acrescimo),0) AS acrescimo, "
                "COALESCE(SUM(v.vlr_desconto),0) AS desconto "
                "FROM vendas_xml v WHERE v.situacao <> 'cancelada' "
                "AND v.dh_emissao >= %s AND v.dh_emissao < %s", (ini, fim))
            cab = cur.fetchone() or {}
            notas = int(cab.get('notas') or 0)
            total = float(cab.get('total') or 0)
            # Corpo: por categoria (nível ITEM).
            cur.execute(
                "SELECT " + _ONDA1_CASE + " AS cat, COUNT(*) AS itens, "
                "COALESCE(SUM(i.quantidade),0) AS litros, COALESCE(SUM(i.valor_total),0) AS total "
                "FROM vendas_xml_itens i JOIN vendas_xml v ON v.id = i.venda_id "
                "WHERE v.situacao <> 'cancelada' AND v.dh_emissao >= %s AND v.dh_emissao < %s "
                "GROUP BY cat", (ini, fim))
            por = {r['cat']: r for r in cur.fetchall()}
            linhas, sub_comb, litros_comb = [], 0.0, 0.0
            for lbl in _ONDA1_ORDEM:
                r = por.get(lbl)
                tot = float(r['total']) if r else 0.0
                lit = float(r['litros']) if r else 0.0
                sub_comb += tot
                if lbl != 'ARLA':          # ARLA não soma no total de litros do topo
                    litros_comb += lit
                linhas.append({'label': lbl, 'litros': lit, 'total': tot})
            o = por.get('Outros')
            sub_outros = float(o['total']) if o else 0.0
            return {'notas': notas, 'total': total,
                    'ticket': (total / notas) if notas else 0.0,
                    'litros_comb': litros_comb,
                    'linhas': linhas, 'sub_comb': sub_comb, 'sub_outros': sub_outros,
                    'qt_outros': int(o['itens']) if o else 0,
                    'sub_produtos': sub_comb + sub_outros,
                    'acrescimo': float(cab.get('acrescimo') or 0),
                    'desconto': float(cab.get('desconto') or 0)}

        dia, mes = _periodo(ini_dia, fim_dia), _periodo(ini_mes, fim_mes)

        # ── Ranking do dia: top 4 vendedores por R$ nota + litros por combustível ──
        cur.execute(
            "SELECT COALESCE(NULLIF(TRIM(v.vendedor_raw),''),'Não identificado') AS vendedor, "
            "COUNT(*) AS notas, COALESCE(SUM(v.valor_total),0) AS total FROM vendas_xml v "
            "WHERE v.situacao <> 'cancelada' AND v.dh_emissao >= %s AND v.dh_emissao < %s "
            "GROUP BY vendedor ORDER BY total DESC LIMIT 4", (ini_dia, fim_dia))
        top = cur.fetchall()
        ranking = []
        if top:
            max_tot = float(top[0]['total']) or 1.0
            nomes = [t['vendedor'] for t in top]
            fmap = {n: {'Diesel S-500': 0.0, 'Diesel S-10': 0.0,
                        'Etanol': 0.0, 'Gasolina C': 0.0} for n in nomes}
            place = ",".join(["%s"] * len(nomes))
            cur.execute(
                "SELECT COALESCE(NULLIF(TRIM(v.vendedor_raw),''),'Não identificado') AS vendedor, "
                + _ONDA1_CASE + " AS cat, COALESCE(SUM(i.quantidade),0) AS litros "
                "FROM vendas_xml_itens i JOIN vendas_xml v ON v.id = i.venda_id "
                "WHERE v.situacao <> 'cancelada' AND v.dh_emissao >= %s AND v.dh_emissao < %s "
                "AND i.cod_anp IN ('820101012','820101034','810101001','320102001') "
                "AND COALESCE(NULLIF(TRIM(v.vendedor_raw),''),'Não identificado') IN (" + place + ") "
                "GROUP BY vendedor, cat", [ini_dia, fim_dia] + nomes)
            for r in cur.fetchall():
                if r['vendedor'] in fmap and r['cat'] in fmap[r['vendedor']]:
                    fmap[r['vendedor']][r['cat']] = float(r['litros'] or 0)
            for t in top:
                tot = float(t['total'] or 0)
                ranking.append({'vendedor': t['vendedor'], 'total': tot,
                                'notas': int(t['notas'] or 0),
                                'pct': (tot / max_tot * 100) if max_tot else 0,
                                'fuels': fmap.get(t['vendedor'], {})})

        # ── Recebimento do dia: total por CLASSE (nível nota; esconde zeradas) ──
        recebimento = []
        total_receb = 0.0
        try:
            cur.execute(
                "SELECT forma_pagamento, card_bandeira, card_credenciadora, "
                "card_autorizacao, tef_terminal, cliente_doc, COALESCE(valor_total,0) AS vt "
                "FROM vendas_xml WHERE situacao <> 'cancelada' "
                "AND dh_emissao >= %s AND dh_emissao < %s", (ini_dia, fim_dia))
            por_classe = {}
            for r in cur.fetchall():
                cls = classificar_recebimento(
                    r['forma_pagamento'], r['card_bandeira'], r['card_credenciadora'],
                    r['card_autorizacao'], r['tef_terminal'], r['cliente_doc'])
                vt = float(r['vt'] or 0)
                d = por_classe.setdefault(cls, [0, 0.0])
                d[0] += 1
                d[1] += vt
                total_receb += vt
            recebimento = [
                {'classe': k, 'n': v[0], 'valor': v[1],
                 'pct': (v[1] / total_receb * 100) if total_receb else 0}
                for k, v in por_classe.items()          # só classes com movimento aparecem
            ]
            recebimento.sort(key=lambda x: -x['valor'])   # maior valor primeiro
        except Exception:
            recebimento = []

        # ── Minha Venda × Repasse (dia e mês) ──────────────────────────────
        # MINHA VENDA = mercadoria (Σ itens.valor_total = litros × preço à vista;
        #   o degrau está separado em vlr_acrescimo) = sub_produtos do período.
        # REPASSE = Σ vlr_acrescimo das vendas classe 'Operadora' (card_credenciadora
        #   = cliente_doc), detalhado por operadora. FICA COMIGO = acréscimo restante
        #   (prazo + degrau de cartão comum). Identidade: total = venda + comigo + repasse.
        def _repasse(ini, fim, merc):
            comigo, repasse, por_op = 0.0, 0.0, {}
            try:
                cur.execute(
                    "SELECT cliente_doc, card_credenciadora, cliente_nome, "
                    "COALESCE(vlr_acrescimo,0) AS acr FROM vendas_xml "
                    "WHERE situacao <> 'cancelada' AND vlr_acrescimo > 0 "
                    "AND dh_emissao >= %s AND dh_emissao < %s", (ini, fim))
                for r in cur.fetchall():
                    doc = (r['cliente_doc'] or '').strip()
                    cred = (r['card_credenciadora'] or '').strip()
                    acr = float(r['acr'] or 0)
                    if len(doc) == 14 and doc == cred:        # classe Operadora
                        repasse += acr
                        nome = (r['cliente_nome'] or doc)
                        d = por_op.setdefault(nome, 0.0)
                        por_op[nome] = d + acr
                    else:
                        comigo += acr
            except Exception:
                comigo, repasse, por_op = 0.0, 0.0, {}
            operadoras = sorted(({'nome': k, 'valor': v} for k, v in por_op.items()),
                                key=lambda x: -x['valor'])
            return {'venda': merc, 'comigo': comigo, 'meu': merc + comigo,
                    'repasse': repasse, 'total': merc + comigo + repasse,
                    'operadoras': operadoras}

        repasse_card = {'dia': _repasse(ini_dia, fim_dia, dia['sub_produtos']),
                        'mes': _repasse(ini_mes, fim_mes, mes['sub_produtos'])}

        return {'dia': dia, 'mes': mes, 'ranking': ranking,
                'recebimento': recebimento, 'recebimento_total': total_receb,
                'repasse': repasse_card}
    except Exception:
        current_app.logger.exception('[dashboard onda1] falha ao coletar dados')
        return vazio
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _calcular_lucro_fifo_dashboard(conn, ano, mes):
    """
    Calcula lucro FIFO on-the-fly por produto, agregando todos os clientes/postos.
    Usado no dashboard quando o mês ainda não foi fechado (sem fifo_resumo_mensal).
    Retorna (lista_por_produto, total_lucro).
    """
    import calendar as _cal
    from datetime import date as _date
    from collections import defaultdict as _dd

    data_inicio = _date(ano, mes, 1)
    data_fim = _date(ano, mes, _cal.monthrange(ano, mes)[1])
    if mes == 1:
        ano_ant, mes_ant = ano - 1, 12
    else:
        ano_ant, mes_ant = ano, mes - 1
    ano_mes_ant = f'{ano_ant:04d}-{mes_ant:02d}'

    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT DISTINCT cliente_id FROM vendas_posto "
            "WHERE YEAR(data_movimento)=%s AND MONTH(data_movimento)=%s",
            (ano, mes)
        )
        cliente_ids = [r['cliente_id'] for r in cur.fetchall()]
        if not cliente_ids:
            return [], 0.0

        prod_resultado = {}  # nome -> {'valor': float, 'qtde': float}

        for cliente_id in cliente_ids:
            cur.execute("""
                SELECT DISTINCT p.id, p.nome
                FROM produto p
                INNER JOIN cliente_produtos cp ON cp.produto_id = p.id
                WHERE cp.cliente_id = %s AND cp.ativo = 1
                ORDER BY p.nome
            """, (cliente_id,))
            produtos = cur.fetchall()

            for prod in produtos:
                pid = prod['id']
                pnome = prod['nome']

                # Camadas base: snapshot do mês anterior fechado ou fifo_abertura
                cur.execute("""
                    SELECT fc.id, fc.versao_atual
                    FROM fifo_competencia fc
                    WHERE fc.cliente_id = %s AND fc.ano_mes = %s AND fc.status = 'FECHADO'
                    LIMIT 1
                """, (cliente_id, ano_mes_ant))
                comp_ant = cur.fetchone()

                layers = []
                if comp_ant:
                    cur.execute("""
                        SELECT quantidade_restante AS qtde, custo_unitario AS custo
                        FROM fifo_snapshot_lotes
                        WHERE competencia_id = %s AND produto_id = %s AND versao = %s
                          AND substituido = 0 AND quantidade_restante > 0
                        ORDER BY lote_ordem
                    """, (comp_ant['id'], pid, comp_ant['versao_atual']))
                    layers = [
                        {'qtde': float(l['qtde']), 'custo': float(l['custo'])}
                        for l in cur.fetchall()
                    ]

                if not layers:
                    cur.execute("""
                        SELECT quantidade AS qtde, custo_unitario AS custo,
                               data_abertura
                        FROM fifo_abertura WHERE cliente_id = %s AND produto_id = %s
                    """, (cliente_id, pid))
                    ab = cur.fetchone()
                    if ab and float(ab['qtde']) > 0:
                        layers = [{'qtde': float(ab['qtde']), 'custo': float(ab['custo'])}]

                        # Quando o mês anterior não está fechado, é necessário avançar
                        # as camadas de fifo_abertura até o início do mês corrente,
                        # processando todas as transações intermediárias (mirrors
                        # _advance_layers_to_date em relatorios.py).
                        if not comp_ant:
                            ab_date = ab.get('data_abertura')
                            if ab_date:
                                if isinstance(ab_date, str):
                                    from datetime import date as _date2
                                    ab_date = _date2.fromisoformat(ab_date)
                                if ab_date < data_inicio:
                                    cur.execute("""
                                        SELECT f.data_frete AS data,
                                               COALESCE(f.quantidade_manual, q.valor, 0) AS qtde,
                                               COALESCE(f.preco_produto_unitario, 0)     AS custo
                                        FROM fretes f
                                        LEFT JOIN quantidades q ON f.quantidade_id = q.id
                                        WHERE f.clientes_id = %s AND f.produto_id = %s
                                          AND f.data_frete >= %s AND f.data_frete < %s
                                          AND COALESCE(f.quantidade_manual, q.valor, 0) > 0
                                        ORDER BY f.data_frete
                                    """, (cliente_id, pid, ab_date, data_inicio))
                                    _pre_comp_by_date = _dd(list)
                                    for row in cur.fetchall():
                                        _pre_comp_by_date[row['data']].append(
                                            {'qtde': float(row['qtde']), 'custo': float(row['custo'])}
                                        )
                                    cur.execute("""
                                        SELECT data_movimento AS data,
                                               SUM(COALESCE(quantidade_litros, 0)) AS qtde
                                        FROM vendas_posto
                                        WHERE cliente_id = %s AND produto_id = %s
                                          AND data_movimento >= %s AND data_movimento < %s
                                        GROUP BY data_movimento
                                        ORDER BY data_movimento
                                    """, (cliente_id, pid, ab_date, data_inicio))
                                    _pre_vend_by_date = {
                                        row['data']: float(row['qtde'] or 0)
                                        for row in cur.fetchall()
                                    }
                                    _pre_dates = sorted(
                                        set(list(_pre_comp_by_date.keys()) + list(_pre_vend_by_date.keys()))
                                    )
                                    for _d in _pre_dates:
                                        for _c in _pre_comp_by_date.get(_d, []):
                                            if _c['qtde'] > 0 and _c['custo'] > 0:
                                                layers.append({'qtde': _c['qtde'], 'custo': _c['custo']})
                                        _qv = _pre_vend_by_date.get(_d, 0.0)
                                        if _qv > 0:
                                            _restante = _qv
                                            while _restante > 0.001 and layers:
                                                _lay = layers[0]
                                                if _lay['qtde'] <= _restante + 0.001:
                                                    _restante -= _lay['qtde']
                                                    layers.pop(0)
                                                else:
                                                    _lay['qtde'] -= _restante
                                                    _restante = 0.0

                # Compras = fretes entregues neste client para este produto no mês
                cur.execute("""
                    SELECT f.data_frete AS data,
                           COALESCE(f.quantidade_manual, q.valor, 0) AS qtde,
                           COALESCE(f.preco_produto_unitario, 0) AS custo
                    FROM fretes f
                    LEFT JOIN quantidades q ON f.quantidade_id = q.id
                    WHERE f.clientes_id = %s AND f.produto_id = %s
                      AND f.data_frete BETWEEN %s AND %s
                      AND COALESCE(f.quantidade_manual, q.valor, 0) > 0
                    ORDER BY f.data_frete
                """, (cliente_id, pid, data_inicio, data_fim))
                compras = cur.fetchall()

                # Vendas do posto
                cur.execute("""
                    SELECT data_movimento AS data,
                           SUM(COALESCE(quantidade_litros, 0)) AS qtde,
                           SUM(COALESCE(valor_total, 0)) AS valor_total
                    FROM vendas_posto
                    WHERE cliente_id = %s AND produto_id = %s
                      AND data_movimento BETWEEN %s AND %s
                    GROUP BY data_movimento
                    ORDER BY data_movimento
                """, (cliente_id, pid, data_inicio, data_fim))
                vendas = cur.fetchall()

                if not vendas:
                    continue

                # Calcular FIFO
                comp_by_date = _dd(list)
                for c in compras:
                    comp_by_date[c['data']].append(c)
                vend_by_date = _dd(list)
                for v in vendas:
                    vend_by_date[v['data']].append(v)

                all_dates = sorted(set(list(comp_by_date.keys()) + list(vend_by_date.keys())))
                qtde_saida = 0.0
                receita = 0.0
                cogs = 0.0

                for data in all_dates:
                    for comp in comp_by_date.get(data, []):
                        qtde = float(comp['qtde'])
                        custo = float(comp['custo'])
                        if qtde > 0:
                            layers.append({'qtde': qtde, 'custo': custo})

                    for vend in vend_by_date.get(data, []):
                        qtde_vender = float(vend['qtde'])
                        valor = float(vend['valor_total'])
                        if qtde_vender <= 0:
                            continue
                        qtde_saida += qtde_vender
                        receita += valor
                        restante = qtde_vender
                        while restante > 0.001 and layers:
                            layer = layers[0]
                            if layer['qtde'] <= restante + 0.001:
                                cogs += layer['qtde'] * layer['custo']
                                restante -= layer['qtde']
                                layers.pop(0)
                            else:
                                cogs += restante * layer['custo']
                                layer['qtde'] -= restante
                                restante = 0.0

                lucro = receita - cogs
                if pnome not in prod_resultado:
                    prod_resultado[pnome] = {'valor': 0.0, 'qtde': 0.0}
                prod_resultado[pnome]['valor'] += lucro
                prod_resultado[pnome]['qtde'] += qtde_saida

        resultado_list = [
            {'nome': nome, 'valor': v['valor'], 'qtde': v['qtde']}
            for nome, v in prod_resultado.items()
        ]
        resultado_list.sort(key=lambda x: x['valor'], reverse=True)
        total_lucro = sum(r['valor'] for r in resultado_list)
        return resultado_list, total_lucro
    finally:
        cur.close()


def safe_url(endpoint, **values):
    """
    Retorna url_for(endpoint, **values) se o endpoint existir no app,
    caso contrário retorna '#'. Evita BuildError no template.
    """
    try:
        if endpoint in current_app.view_functions:
            return url_for(endpoint, **values)
    except Exception:
        pass
    return '#'


@bp.route('/', methods=['GET'])
@login_required
def index():
    # Redirecionar usuários PISTA e SUPERVISOR para suas páginas específicas
    # SUPERVISOR não deve acessar a página inicial, vai direto para lançamentos_caixa
    if current_user.is_authenticated:
        nivel = getattr(current_user, 'nivel', '').strip().upper()
        if nivel == 'PISTA':
            return redirect(url_for('troco_pix.pista'))
        if nivel == 'SUPERVISOR':
            return redirect(url_for('lancamentos_caixa.lista'))
    
    import calendar
    from datetime import datetime, date

    # coletar métricas simples do banco (fallback para 0 em caso de erro)
    totals = {
        'total_clientes': 0,
        'total_fornecedores': 0,
        'total_motoristas': 0,
        'total_fretes': 0,
        'total_pedidos': 0,
        'fretes_mes': 0,
        'pedidos_mes': 0,
        'volume_transportado_mes': 0.0,
        'volume_vendido_mes': 0.0,
        'receita_mes': 0.0,
        'lucro_fretes_mes': 0.0,
    }
    volume_transportado_por_produto = []
    volume_vendido_por_produto = []
    fretes_por_empresa = []
    fretes_por_empresa_total_qtd = 0.0
    fretes_por_empresa_total_valor = 0.0
    lucro_por_produto = []
    lucro_postos_mes = 0.0
    lucro_postos_disponivel = False
    lucro_postos_fechado = False

    # Dados para gráficos (últimos 6 meses)
    hoje = date.today()
    meses_labels = []
    fretes_por_mes = []
    pedidos_por_mes = []
    volume_por_mes = []
    for i in range(5, -1, -1):
        # calcular mês/ano
        mes_offset = hoje.month - i
        ano_offset = hoje.year
        while mes_offset <= 0:
            mes_offset += 12
            ano_offset -= 1
        meses_labels.append(f"{mes_offset:02d}/{ano_offset}")
        fretes_por_mes.append(0)
        pedidos_por_mes.append(0)
        volume_por_mes.append(0)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(1) FROM clientes")
            totals['total_clientes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_clientes'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM fornecedores")
            totals['total_fornecedores'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_fornecedores'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM motoristas")
            totals['total_motoristas'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_motoristas'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM fretes")
            totals['total_fretes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_fretes'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM pedidos")
            totals['total_pedidos'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_pedidos'] = 0

        # Fretes do mês atual
        try:
            cursor.execute(
                "SELECT COUNT(1) FROM fretes WHERE YEAR(data_frete)=%s AND MONTH(data_frete)=%s",
                (hoje.year, hoje.month)
            )
            totals['fretes_mes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['fretes_mes'] = 0

        # Pedidos do mês atual
        try:
            cursor.execute(
                "SELECT COUNT(1) FROM pedidos WHERE YEAR(data_pedido)=%s AND MONTH(data_pedido)=%s",
                (hoje.year, hoje.month)
            )
            totals['pedidos_mes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['pedidos_mes'] = 0

        # Fretes por mês (últimos 6 meses)
        try:
            cursor.execute(
                """SELECT MONTH(data_frete) AS mes, YEAR(data_frete) AS ano, COUNT(1) AS total
                   FROM fretes
                   WHERE data_frete >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
                   GROUP BY ano, mes
                   ORDER BY ano, mes"""
            )
            rows = cursor.fetchall()
            for row in rows:
                mes_ano = f"{int(row[0]):02d}/{int(row[1])}"
                if mes_ano in meses_labels:
                    idx = meses_labels.index(mes_ano)
                    fretes_por_mes[idx] = int(row[2])
        except Exception:
            pass

        # Pedidos por mês (últimos 6 meses)
        try:
            cursor.execute(
                """SELECT MONTH(data_pedido) AS mes, YEAR(data_pedido) AS ano, COUNT(1) AS total
                   FROM pedidos
                   WHERE data_pedido >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
                   GROUP BY ano, mes
                   ORDER BY ano, mes"""
            )
            rows = cursor.fetchall()
            for row in rows:
                mes_ano = f"{int(row[0]):02d}/{int(row[1])}"
                if mes_ano in meses_labels:
                    idx = meses_labels.index(mes_ano)
                    pedidos_por_mes[idx] = int(row[2])
        except Exception:
            pass

        # Volume transportado do mês atual (soma quantidade fretes)
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor)), 0)
                   FROM fretes f
                   LEFT JOIN quantidades q ON f.quantidade_id = q.id
                   WHERE YEAR(f.data_frete)=%s AND MONTH(f.data_frete)=%s""",
                (hoje.year, hoje.month)
            )
            totals['volume_transportado_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['volume_transportado_mes'] = 0.0

        # Volume vendido do mês atual (vendas_posto – litros vendidos nos postos)
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(vp.quantidade_litros), 0)
                   FROM vendas_posto vp
                   WHERE YEAR(vp.data_movimento)=%s AND MONTH(vp.data_movimento)=%s""",
                (hoje.year, hoje.month)
            )
            totals['volume_vendido_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['volume_vendido_mes'] = 0.0

        # Receita do mês atual (valor_total_frete)
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(valor_total_frete), 0) FROM fretes
                   WHERE YEAR(data_frete)=%s AND MONTH(data_frete)=%s""",
                (hoje.year, hoje.month)
            )
            totals['receita_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['receita_mes'] = 0.0

        # Lucro fretes do mês atual
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(lucro), 0) FROM fretes
                   WHERE YEAR(data_frete)=%s AND MONTH(data_frete)=%s""",
                (hoje.year, hoje.month)
            )
            totals['lucro_fretes_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['lucro_fretes_mes'] = 0.0

        # Volume transportado por mês (últimos 6 meses)
        try:
            cursor.execute(
                """SELECT MONTH(f.data_frete) AS mes, YEAR(f.data_frete) AS ano,
                          COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor)), 0) AS total
                   FROM fretes f
                   LEFT JOIN quantidades q ON f.quantidade_id = q.id
                   WHERE f.data_frete >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
                   GROUP BY ano, mes
                   ORDER BY ano, mes"""
            )
            rows = cursor.fetchall()
            for row in rows:
                mes_ano = f"{int(row[0]):02d}/{int(row[1])}"
                if mes_ano in meses_labels:
                    idx = meses_labels.index(mes_ano)
                    volume_por_mes[idx] = float(row[2])
        except Exception:
            pass

        # Volume transportado por produto do mês atual
        volume_transportado_por_produto = []
        try:
            cursor.execute(
                """SELECT COALESCE(pr.nome, 'Não especificado'),
                          COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor)), 0) AS vol
                   FROM fretes f
                   LEFT JOIN quantidades q ON f.quantidade_id = q.id
                   LEFT JOIN produto pr ON f.produto_id = pr.id
                   WHERE YEAR(f.data_frete)=%s AND MONTH(f.data_frete)=%s
                   GROUP BY pr.id, pr.nome
                   ORDER BY vol DESC""",
                (hoje.year, hoje.month)
            )
            volume_transportado_por_produto = [
                {'nome': row[0], 'valor': float(row[1] or 0)}
                for row in cursor.fetchall()
            ]
        except Exception:
            pass

        # Volume vendido por produto do mês atual (vendas_posto)
        volume_vendido_por_produto = []
        try:
            cursor.execute(
                """SELECT COALESCE(pr.nome, 'Não especificado'),
                          COALESCE(SUM(vp.quantidade_litros), 0) AS vol
                   FROM vendas_posto vp
                   LEFT JOIN produto pr ON vp.produto_id = pr.id
                   WHERE YEAR(vp.data_movimento)=%s AND MONTH(vp.data_movimento)=%s
                   GROUP BY vp.produto_id, pr.nome
                   ORDER BY vol DESC""",
                (hoje.year, hoje.month)
            )
            volume_vendido_por_produto = [
                {'nome': row[0], 'valor': float(row[1] or 0)}
                for row in cursor.fetchall()
            ]
        except Exception:
            pass

        # Fretes por empresa do mês atual (top 5 + DEMAIS EMPRESAS)
        fretes_por_empresa = []
        fretes_por_empresa_total_qtd = 0.0
        fretes_por_empresa_total_valor = 0.0
        try:
            cursor.execute(
                """SELECT COALESCE(cl.razao_social, 'Não especificado') AS empresa,
                          COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)), 0) AS qtd_frete,
                          COALESCE(SUM(f.valor_total_frete), 0) AS valor_frete
                   FROM fretes f
                   LEFT JOIN quantidades q ON f.quantidade_id = q.id
                   LEFT JOIN clientes cl ON f.clientes_id = cl.id
                   WHERE YEAR(f.data_frete)=%s AND MONTH(f.data_frete)=%s
                   GROUP BY f.clientes_id, cl.razao_social
                   ORDER BY qtd_frete DESC""",
                (hoje.year, hoje.month)
            )
            all_emp = [
                {'empresa': row[0], 'qtd_frete': float(row[1] or 0), 'valor_frete': float(row[2] or 0)}
                for row in cursor.fetchall()
            ]
            top5 = all_emp[:5]
            demais = all_emp[5:]
            if demais:
                top5.append({
                    'empresa': 'DEMAIS EMPRESAS',
                    'qtd_frete': sum(e['qtd_frete'] for e in demais),
                    'valor_frete': sum(e['valor_frete'] for e in demais),
                })
            fretes_por_empresa = top5
            fretes_por_empresa_total_qtd = sum(e['qtd_frete'] for e in all_emp)
            fretes_por_empresa_total_valor = sum(e['valor_frete'] for e in all_emp)
        except Exception:
            pass

        # Lucro por produto do mês atual (fifo_resumo_mensal – postos FIFO)
        lucro_por_produto = []
        lucro_postos_mes = 0.0
        lucro_postos_disponivel = False
        lucro_postos_fechado = False
        try:
            ano_mes = hoje.strftime('%Y-%m')
            cursor.execute(
                """SELECT COALESCE(pr.nome, 'Não especificado'),
                          COALESCE(SUM(rm.lucro_bruto), 0) AS lucro,
                          COALESCE(SUM(rm.qtde_saida), 0) AS qtde
                   FROM fifo_resumo_mensal rm
                   JOIN fifo_competencia fc ON rm.competencia_id = fc.id
                   LEFT JOIN produto pr ON rm.produto_id = pr.id
                   WHERE fc.ano_mes = %s
                     AND rm.substituido = 0
                   GROUP BY rm.produto_id, pr.nome
                   ORDER BY lucro DESC""",
                (ano_mes,)
            )
            rows = cursor.fetchall()
            if rows:
                lucro_postos_disponivel = True
                lucro_postos_fechado = True
                lucro_por_produto = [
                    {'nome': row[0], 'valor': float(row[1] or 0), 'qtde': float(row[2] or 0)}
                    for row in rows
                ]
                lucro_postos_mes = sum(p['valor'] for p in lucro_por_produto)
            else:
                # Mês não fechado – calcular on-the-fly via FIFO
                try:
                    lucro_por_produto, lucro_postos_mes = _calcular_lucro_fifo_dashboard(
                        conn, hoje.year, hoje.month
                    )
                    if lucro_por_produto:
                        lucro_postos_disponivel = True
                except Exception:
                    pass
        except Exception:
            pass

    except Exception:
        # se não conseguiu conectar, deixamos os totais em zero
        pass
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    # Onda 1 do carrossel (isolado; conexão própria; nunca derruba o dashboard).
    # Usa a data de BRASÍLIA, não `hoje` (= date.today() = data UTC no servidor):
    # senão, depois das 21h BRT os cards do dia zeram. Cards antigos intocados.
    onda1 = _dados_onda1_dashboard(hoje_brasilia())

    # Construir URLs do relatório de lucro para o mês atual
    primeiro_dia = date(hoje.year, hoje.month, 1)
    ultimo_dia = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
    lucro_mes_url = (
        f"https://app.postonovohorizonte.com.br/relatorios/lucro_postos"
        f"?data_inicio={primeiro_dia.strftime('%Y-%m-%d')}"
        f"&data_fim={ultimo_dia.strftime('%Y-%m-%d')}"
        f"&cliente_ids[]=1&produto_ids[]=1&produto_ids[]=2"
        f"&produto_ids[]=3&produto_ids[]=5&produto_ids[]=4"
    )
    importar_pedido_url = "https://app.postonovohorizonte.com.br/pedidos/importar"

    grafico = {
        'labels': meses_labels,
        'fretes': fretes_por_mes,
        'pedidos': pedidos_por_mes,
        'volume': volume_por_mes,
    }

    # URLs seguras para o template (se endpoint inexistente, retorna '#')
    links = {
        'fretes_novo_url': safe_url('fretes.novo'),
        'pedidos_novo_url': safe_url('pedidos.novo'),
        'clientes_novo_url': safe_url('clientes.novo'),
        'fornecedores_novo_url': safe_url('fornecedores.novo'),
        'clientes_lista_url': safe_url('clientes.lista'),
        'fornecedores_lista_url': safe_url('fornecedores.lista'),
        'motoristas_lista_url': safe_url('motoristas.lista'),
        'fretes_lista_url': safe_url('fretes.lista'),
        'pedidos_index_url': safe_url('pedidos.index') or safe_url('pedidos.lista') or '#',
        'alterar_senha_url': safe_url('auth.alterar_senha'),
        'logout_url': safe_url('auth.logout'),
        'listar_usuarios_url': safe_url('auth.listar_usuarios'),
        'cadastro_url': safe_url('auth.criar_usuario'),
        'relatorios_index_url': safe_url('relatorios.index'),
        'perfil_url': safe_url('auth.perfil'),
        'importar_pedido_url': importar_pedido_url,
        'lucro_mes_url': lucro_mes_url,
    }

    context = {}
    context.update(totals)
    context.update(links)
    context['grafico'] = grafico
    context['volume_transportado_por_produto'] = volume_transportado_por_produto
    context['volume_vendido_por_produto'] = volume_vendido_por_produto
    context['fretes_por_empresa'] = fretes_por_empresa
    context['fretes_por_empresa_total_qtd'] = fretes_por_empresa_total_qtd
    context['fretes_por_empresa_total_valor'] = fretes_por_empresa_total_valor
    context['lucro_por_produto'] = lucro_por_produto
    context['lucro_postos_mes'] = lucro_postos_mes
    context['lucro_postos_disponivel'] = lucro_postos_disponivel
    context['lucro_postos_fechado'] = lucro_postos_fechado
    _meses_pt = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                 'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    context['mes_atual'] = f"{_meses_pt[hoje.month - 1]}/{hoje.year}"
    context['onda1'] = onda1

    return render_template('dashboard.html', **context)


@bp.route('/bases/', methods=['GET'])
@login_required
def lista():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nome, cidade, observacao, ativo FROM bases ORDER BY nome")
        bases = cursor.fetchall()
    except Exception:
        bases = []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return render_template('bases/index.html', bases=bases)


@bp.route('/bases/nova', methods=['GET', 'POST'])
@login_required
def nova():
    """
    Rota mínima para criação de Base (endpoint 'bases.nova').
    - GET: renderiza o formulário/templates/bases/nova.html
    - POST: comportamento mínimo: redireciona para a lista (implemente o salvamento se desejar)
    """
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        cidade = request.form.get('cidade', '').strip() or None
        observacao = request.form.get('observacao', '').strip() or None
        ativo = 1 if request.form.get('ativo') else 0
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO bases (nome, cidade, observacao, ativo) VALUES (%s, %s, %s, %s)",
                (nome, cidade, observacao, ativo)
            )
            conn.commit()
            flash('Base cadastrada com sucesso!', 'success')
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            flash(f'Erro ao cadastrar base: {str(e)}', 'danger')
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        return redirect(url_for('bases.lista'))
    return render_template('bases/nova.html')


@bp.route('/bases/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            nome = request.form.get('nome', '').strip()
            cidade = request.form.get('cidade', '').strip() or None
            observacao = request.form.get('observacao', '').strip() or None
            ativo = 1 if request.form.get('ativo') else 0
            cursor.execute(
                "UPDATE bases SET nome=%s, cidade=%s, observacao=%s, ativo=%s WHERE id=%s",
                (nome, cidade, observacao, ativo, id)
            )
            conn.commit()
            flash('Base atualizada com sucesso!', 'success')
            return redirect(url_for('bases.lista'))
        cursor.execute("SELECT id, nome, cidade, observacao, ativo FROM bases WHERE id=%s", (id,))
        base = cursor.fetchone()
        if not base:
            flash('Base não encontrada.', 'danger')
            return redirect(url_for('bases.lista'))
        return render_template('bases/editar.html', base=base)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        flash(f'Erro ao editar base: {str(e)}', 'danger')
        return redirect(url_for('bases.lista'))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@bp.route('/bases/excluir/<int:id>', methods=['GET', 'POST'])
@login_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bases WHERE id=%s", (id,))
        conn.commit()
        flash('Base excluída com sucesso!', 'success')
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        flash(f'Erro ao excluir base: {str(e)}', 'danger')
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return redirect(url_for('bases.lista'))


@bp.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')
