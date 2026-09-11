# -*- coding: utf-8 -*-
"""Apuração de lucro dos postos a partir das telas NOVAS.

O relatório antigo (/relatorios/lucro_postos) nasceu quando a descarga era
lançada de outro jeito, e a variação dele saía muito errada. As telas novas
resolveram isso na origem, e cada número aqui tem uma fonte só — e é a fonte
da tela que o usuário opera:

    estoque   leitura_tanque_diaria (ABERTURA)   a medição do tanque, pelo ELS
    vendas    vendas_xml + itens                 o cupom fiscal, litro a litro
    descarga  descargas_pendentes                a régua, em /estoque?tab=descargas
    nota      descarga_nota -> dfe_itens         a nota que o usuário escolheu
                                                 ao lançar aquela descarga

A armadilha que custou uma versão inteira deste relatório: existem DUAS tabelas
de descarga. `descargas` é a do frete — guarda o que o caminhão carregou, na
data do frete. `descargas_pendentes` é a da tela de estoque — guarda o que a
régua mediu descer, no dia em que desceu. Só a segunda serve para estoque; com
a primeira o relatório acusava milhares de litros de sobra que nunca existiram.

E a nota entra pelo dia em que DESCEU, não pelo dia em que foi emitida. O
vínculo mora em `descarga_nota`, e a alocação é a mesma da conciliação de
estoque — **a nota manda**: quando um item desce em parcelas, a última leva
todo o resto, para a nota fechar exatamente na sua quantidade.

Daí as duas bases, que agora respondem a mesma pergunta por dois caminhos:

  base='nota'      a entrada é o que a nota daquela descarga diz. Casa com o
                   fiscal e com o que se paga ao fornecedor.
  base='descarga'  a entrada é o que a régua mediu. Casa com o tanque.

A diferença entre elas é a perda de temperatura: no etanol de 01/09/2026 a nota
trouxe 8.000 L, a régua mediu 7.960 L e o tanque absorveu 7.995 L. É disso que
se trata — dezenas de litros, não milhares.

Cada dia traz ainda `entrou`, que é a única entrada física e não depende de
nenhum lançamento: `medição de amanhã − a de hoje + o que se vendeu`. É contra
ela que a nota e a régua se medem.

O custo segue a média móvel ponderada (o "custo corrido" do relatório antigo):
a cada entrada o saldo em reais e em litros somam, e a venda do dia sai pelo
custo médio daquele momento.
"""

from datetime import date, timedelta

BASES = ('nota', 'descarga')


def _f(v):
    """Decimal/None do banco vira float — Decimal com float estoura no meio."""
    return float(v) if v is not None else 0.0


def _dias(ini, fim):
    d = ini
    while d <= fim:
        yield d
        d += timedelta(days=1)


# ===========================================================================
# As quatro fontes
# ===========================================================================

def _leituras(cur, cliente_id, ini, fim):
    """{(dia, produto_id): litros} — a medição de ABERTURA de cada tanque.

    So ABERTURA: se um dia tiver tambem a leitura de fechamento, somar as duas
    dobraria o estoque. A conciliacao de estoque filtra igual.

    Vai até fim+1: o estoque final de um dia é a abertura do dia seguinte, e é
    com ela que a variação é medida.
    """
    cur.execute("""
        SELECT DATE(data_leitura) AS d, produto_id, SUM(volume_atual) AS litros
          FROM leitura_tanque_diaria
         WHERE cliente_id = %s
           AND UPPER(TRIM(titulo)) = 'ABERTURA'
           AND DATE(data_leitura) BETWEEN %s AND %s
           AND produto_id IS NOT NULL
         GROUP BY d, produto_id
    """, (cliente_id, ini, fim + timedelta(days=1)))
    return {(r['d'], r['produto_id']): _f(r['litros']) for r in cur.fetchall()}


def _vendas(cur, cliente_id, ini, fim):
    """{(dia, produto_id): (litros, reais)} do cupom fiscal.

    O cupom nao carrega cliente_id: quem diz de que posto ele e o CNPJ do
    emitente. Sem esse laco, um segundo posto misturaria as vendas no mesmo
    relatorio.
    """
    cur.execute("""
        SELECT DATE(v.dh_emissao) AS d, i.produto_id,
               SUM(i.quantidade)  AS litros,
               SUM(i.valor_total) AS reais
          FROM vendas_xml v
          JOIN vendas_xml_itens i ON i.venda_id = v.id
          LEFT JOIN clientes c ON REPLACE(REPLACE(REPLACE(c.cnpj,'.',''),'/',''),'-','')
                                = REPLACE(REPLACE(REPLACE(v.cnpj_emitente,'.',''),'/',''),'-','')
         WHERE DATE(v.dh_emissao) BETWEEN %s AND %s
           AND i.produto_id IS NOT NULL
           AND (c.id = %s OR c.id IS NULL)
           AND (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA')
         GROUP BY d, i.produto_id
    """, (ini, fim, cliente_id))
    return {(r['d'], r['produto_id']): (_f(r['litros']), _f(r['reais']))
            for r in cur.fetchall()}


def _descargas(cur, cliente_id, ini, fim):
    """{(dia, produto_id): litros} — o que a REGUA mediu descer.

    Vem de `descargas_pendentes`, a tabela da tela /estoque?tab=descargas, onde
    o usuario mede a descarga e escolhe a nota dela. Nao e a tabela `descargas`
    do frete: aquela guarda o volume que o caminhao carregou, e e por isso que o
    relatorio saia com milhares de litros de sobra.
    """
    cur.execute("""
        SELECT DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial)) AS d,
               d.produto_id AS pid, SUM(d.total_descarga) AS litros
          FROM descargas_pendentes d
         WHERE d.cliente_id = %s
           AND d.produto_id IS NOT NULL
           AND DATE(COALESCE(d.data_descarga, d.data_final, d.data_inicial))
               BETWEEN %s AND %s
         GROUP BY d, pid
    """, (cliente_id, ini, fim))
    return {(r['d'], r['pid']): _f(r['litros']) for r in cur.fetchall()}


def _notas(cur, cliente_id, produto_ids, ini, fim):
    """A nota pelo dia em que ela DESCEU, e o que dela ainda nao desceu.

    Devolve (descidas, pendente):

        descidas   {(dia, produto_id): (litros, reais)} — o litro da nota
                   alocado ao dia da descarga que a consumiu
        pendente   {(dia, produto_id): litros} — saldo no fim daquele dia do
                   que ja foi faturado e ainda nao desceu

    O vinculo mora em `descarga_nota` (item da nota <-> descarga medida), e a
    alocacao e a mesma da conciliacao de estoque: **a nota manda**. Quando um
    item desce em parcelas, cada parcela leva o litro que registrou e a ULTIMA
    leva todo o resto, para a nota fechar exatamente na sua quantidade — a
    regua mede com perda de temperatura, e essa perda nao pode virar estoque.

    Repare no que isto muda: a nota de 9.000 L emitida em 05/09 nao entra em
    05/09. Ela entra no dia em que o caminhao desceu. E e por isso que os dois
    lados passam a fechar.
    """
    marcas = ','.join(['%s'] * len(produto_ids))

    # Os itens de nota que interessam: os que desceram no periodo (o vinculo
    # diz quais) e os emitidos perto dele (para o saldo pendente).
    cur.execute("""
        SELECT i.id, DATE(doc.dh_emissao) AS emissao,
               i.classificado_produto_id AS pid,
               i.quantidade AS litros, i.valor_total AS reais
          FROM dfe_itens i
          JOIN dfe_documentos doc ON doc.id = i.documento_id
         WHERE doc.cliente_id = %s
           AND DATE(doc.dh_emissao) BETWEEN %s AND %s
           AND i.classificado_produto_id IN (""" + marcas + """)
           AND (doc.situacao IS NULL OR UPPER(doc.situacao) NOT LIKE '%%CANCEL%%')
    """, [cliente_id, ini - timedelta(days=90), fim] + list(produto_ids))
    itens = {r['id']: {'emissao': r['emissao'], 'pid': r['pid'],
                       'litros': _f(r['litros']), 'reais': _f(r['reais'])}
             for r in cur.fetchall()}

    # Os vinculos INTEIROS de cada item — inclusive os de fora do periodo, sem
    # os quais a ultima parcela nao fecharia certo.
    cur.execute("""
        SELECT dn.item_id, dn.litros AS vinc_l,
               DATE(COALESCE(dp.data_descarga, dp.data_final,
                             dp.data_inicial)) AS d,
               dp.produto_id AS pid
          FROM descarga_nota dn
          JOIN descargas_pendentes dp ON dp.id = dn.descarga_id
         WHERE dp.cliente_id = %s
           AND dp.produto_id IN (""" + marcas + """)
         ORDER BY dn.item_id, d, dn.id
    """, [cliente_id] + list(produto_ids))
    por_item = {}
    for r in cur.fetchall():
        por_item.setdefault(r['item_id'], []).append(r)

    descidas, baixa = {}, {}   # baixa: por item, depois por (dia, produto)
    for item_id, vs in por_item.items():
        it = itens.get(item_id)
        if not it or not it['litros']:
            continue
        unit = it['reais'] / it['litros']
        resto = it['litros']
        for k, r in enumerate(vs):
            if len(vs) == 1:
                usar = it['litros']
            elif k < len(vs) - 1:
                usar = min(_f(r['vinc_l']), max(resto, 0.0))
            else:
                usar = resto                      # a ultima fecha a nota
            resto -= usar
            ky = (r['d'], r['pid'])
            baixa.setdefault(item_id, {})
            baixa[item_id][ky] = baixa[item_id].get(ky, 0.0) + usar
            if ini <= r['d'] <= fim:
                l, rs = descidas.get(ky, (0.0, 0.0))
                descidas[ky] = (l + usar, rs + usar * unit)

    # O saldo do que falta descer. So contam as notas emitidas ate 30 dias
    # antes do periodo: antes da tela de descargas existir (28/07/2026) nao ha
    # vinculo nenhum, e essas notas ficariam pendentes para sempre.
    corte = ini - timedelta(days=30)
    saldo, emitidas_dia, baixa_dia = {}, {}, {}
    for item_id, it in itens.items():
        # So os itens da janela: antes da tela de descargas existir nao ha
        # vinculo nenhum, e aquelas notas ficariam pendentes para sempre. E a
        # baixa so conta para o item que entrou na conta — subtrair a baixa de
        # um item que nunca foi somado derruba o saldo para milhares negativos.
        if not (corte <= it['emissao'] <= fim):
            continue
        if it['emissao'] < ini:
            saldo[it['pid']] = saldo.get(it['pid'], 0.0) + it['litros']
        else:
            ky = (it['emissao'], it['pid'])
            emitidas_dia[ky] = emitidas_dia.get(ky, 0.0) + it['litros']
        for (d, pid), l in baixa.get(item_id, {}).items():
            if d < ini:
                saldo[pid] = saldo.get(pid, 0.0) - l
            elif d <= fim:
                baixa_dia[(d, pid)] = baixa_dia.get((d, pid), 0.0) + l

    pendente = {}
    for pid in produto_ids:
        acu = saldo.get(pid, 0.0)
        for d in _dias(ini, fim):
            acu += emitidas_dia.get((d, pid), 0.0) - baixa_dia.get((d, pid), 0.0)
            pendente[(d, pid)] = acu
    return descidas, pendente


def _preco_medio(cur, cliente_id, produto_ids, ini, fim):
    """{produto_id: R$/L} das compras do período — e, na falta, dos 60 dias antes.

    Serve para dois lugares: precificar descarga sem nota e dar um custo ao
    estoque que ja estava no tanque quando o periodo comecou.
    """
    if not produto_ids:
        return {}
    marcas = ','.join(['%s'] * len(produto_ids))
    preco = {}
    for janela_ini, janela_fim in ((ini, fim),
                                   (ini - timedelta(days=60), ini - timedelta(days=1))):
        cur.execute("""
            SELECT i.classificado_produto_id AS pid,
                   SUM(i.valor_total) AS reais, SUM(i.quantidade) AS litros
              FROM dfe_itens i
              JOIN dfe_documentos doc ON doc.id = i.documento_id
             WHERE doc.cliente_id = %s
               AND DATE(doc.dh_emissao) BETWEEN %s AND %s
               AND i.classificado_produto_id IN (""" + marcas + """)
             GROUP BY i.classificado_produto_id
        """, [cliente_id, janela_ini, janela_fim] + list(produto_ids))
        for r in cur.fetchall():
            litros = _f(r['litros'])
            if litros and r['pid'] not in preco:
                preco[r['pid']] = _f(r['reais']) / litros
    return preco


# ===========================================================================
# A apuração
# ===========================================================================

def apurar(cur, cliente_id, produto_ids, ini, fim, base='nota'):
    """Dia a dia por produto, na base escolhida.

    Devolve {produto_id: {'dias': [...], 'total': {...}}}. Cada dia traz as
    TRES entradas ao mesmo tempo, porque so as tres juntas explicam o dia:

        nota_l    o que o fornecedor faturou naquele dia
        desc_l    o que a descarga registra ter descido
        entrou    o que o TANQUE absorveu de verdade:
                  medicao de amanha - medicao de hoje + o que se vendeu

    A ultima e a unica fisica, e so existe quando as duas medicoes existem.
    A variacao do dia e sempre `entrou - entrada da base` — por isso ela
    dispara quando a nota vem num dia e o caminhao no outro, e por isso o
    numero que vale e o ACUMULADO, que fecha o descompasso.
    """
    if base not in BASES:
        raise ValueError('base deve ser %r' % (BASES,))
    produto_ids = [int(p) for p in (produto_ids or [])]
    if not produto_ids:
        return {}

    leitura = _leituras(cur, cliente_id, ini, fim)
    venda = _vendas(cur, cliente_id, ini, fim)
    preco = _preco_medio(cur, cliente_id, produto_ids, ini, fim)
    nota, pendente = _notas(cur, cliente_id, produto_ids, ini, fim)
    medido_l = _descargas(cur, cliente_id, ini, fim)
    # A descarga mede volume, nao dinheiro: o preco do litro que desceu e o da
    # nota que desceu com ele. Sem vinculo, o preco medio de compra do periodo.
    desc = {}
    for ky, litros in medido_l.items():
        nl, nrs = nota.get(ky, (0.0, 0.0))
        unit = (nrs / nl) if nl else preco.get(ky[1], 0.0)
        desc[ky] = (litros, litros * unit)
    entrada = nota if base == 'nota' else desc

    fora = {}
    for pid in produto_ids:
        # O estoque que ja estava no tanque: litros medidos, ao preco medio de
        # compra. E uma estimativa, e a tela diz isso — o tanque nao guarda
        # nota fiscal.
        saldo_l = leitura.get((ini, pid))
        encadeado = saldo_l is None
        if saldo_l is None:
            saldo_l = 0.0
        saldo_rs = saldo_l * preco.get(pid, 0.0)

        dias, tot = [], {'entrada_l': 0.0, 'entrada_rs': 0.0, 'venda_l': 0.0,
                         'venda_rs': 0.0, 'custo_rs': 0.0, 'lucro_rs': 0.0,
                         'variacao_l': 0.0, 'nota_l': 0.0, 'nota_rs': 0.0,
                         'desc_l': 0.0, 'entrou_l': 0.0, 'dias_entrou': 0}
        falta_acum = 0.0
        var_acum = 0.0
        lucro_acum = 0.0
        for d in _dias(ini, fim):
            medido = leitura.get((d, pid))
            # A medicao do dia manda no estoque inicial: ela e a realidade.
            # Quando falta (o e-mail do ELS nao chegou), o dia encadeia com o
            # final calculado do dia anterior, e a tela marca isso.
            if medido is not None and d != ini:
                # a diferenca entre o calculado de ontem e a medicao de hoje ja
                # foi contada como variacao de ontem; aqui o saldo se corrige
                if saldo_l:
                    custo_unit = saldo_rs / saldo_l
                else:
                    custo_unit = preco.get(pid, 0.0)
                saldo_l = medido
                saldo_rs = medido * custo_unit
            ei = saldo_l
            ei_medido = medido is not None

            ent_l, ent_rs = entrada.get((d, pid), (0.0, 0.0))
            nota_l, nota_rs = nota.get((d, pid), (0.0, 0.0))
            desc_l = medido_l.get((d, pid), 0.0)
            ven_l, ven_rs = venda.get((d, pid), (0.0, 0.0))

            saldo_l += ent_l
            saldo_rs += ent_rs
            custo_unit = (saldo_rs / saldo_l) if saldo_l else preco.get(pid, 0.0)
            custo_rs = ven_l * custo_unit
            saldo_l -= ven_l
            saldo_rs -= custo_rs

            ef_calc = ei + ent_l - ven_l
            ef_real = leitura.get((d + timedelta(days=1), pid))
            variacao = (ef_real - ef_calc) if ef_real is not None else None

            # O que o tanque absorveu de verdade. So faz sentido com as duas
            # medicoes na mao — sem elas, a conta voltaria encadeada e diria
            # exatamente o que ja se supos, ou seja, nada.
            entrou = (ef_real - ei + ven_l) if (ef_real is not None
                                                and ei_medido) else None

            # O que ja foi faturado e ainda nao desceu, no fim daquele dia.
            # Nao e acumulado de coluna: vem do saldo real de cada item de
            # nota, que so baixa quando a descarga o consome.
            falta_acum = pendente.get((d, pid), 0.0)
            if variacao is not None:
                var_acum += variacao
            lucro_acum += ven_rs - custo_rs

            dias.append({
                'data': d, 'ei': ei, 'ei_medido': ei_medido,
                'entrada_l': ent_l, 'entrada_rs': ent_rs,
                'entrada_unit': (ent_rs / ent_l) if ent_l else 0.0,
                'nota_l': nota_l, 'nota_rs': nota_rs, 'desc_l': desc_l,
                'entrou': entrou, 'falta_dia': nota_l - desc_l,
                'medido_l': desc_l,
                'falta_acum': falta_acum, 'var_acum': var_acum,
                'venda_l': ven_l, 'venda_rs': ven_rs,
                'venda_unit': (ven_rs / ven_l) if ven_l else 0.0,
                'custo_unit': custo_unit, 'custo_rs': custo_rs,
                'lucro_rs': ven_rs - custo_rs, 'lucro_acum': lucro_acum,
                'margem_l': ((ven_rs - custo_rs) / ven_l) if ven_l else 0.0,
                'ef_calc': ef_calc, 'ef_real': ef_real, 'variacao': variacao,
            })
            tot['entrada_l'] += ent_l
            tot['entrada_rs'] += ent_rs
            tot['nota_l'] += nota_l
            tot['nota_rs'] += nota_rs
            tot['desc_l'] += desc_l
            tot['venda_l'] += ven_l
            tot['venda_rs'] += ven_rs
            tot['custo_rs'] += custo_rs
            tot['lucro_rs'] += ven_rs - custo_rs
            if variacao is not None:
                tot['variacao_l'] += variacao
            if entrou is not None:
                tot['entrou_l'] += entrou
                tot['dias_entrou'] += 1

        tot['ei'] = dias[0]['ei'] if dias else 0.0
        tot['ei_medido'] = dias[0]['ei_medido'] if dias else False
        tot['encadeado'] = encadeado
        # o final do periodo e a ULTIMA medicao que existe — nao o calculado
        tot['ef_real'] = next((x['ef_real'] for x in reversed(dias)
                               if x['ef_real'] is not None), None)
        tot['ef_calc'] = dias[-1]['ef_calc'] if dias else 0.0
        tot['falta_l'] = falta_acum
        tot['margem_l'] = (tot['lucro_rs'] / tot['venda_l']) if tot['venda_l'] else 0.0
        tot['custo_unit'] = (tot['custo_rs'] / tot['venda_l']) if tot['venda_l'] else 0.0
        tot['entrada_unit'] = ((tot['entrada_rs'] / tot['entrada_l'])
                               if tot['entrada_l'] else 0.0)
        tot['venda_unit'] = ((tot['venda_rs'] / tot['venda_l'])
                             if tot['venda_l'] else 0.0)
        tot['dias_medidos'] = sum(1 for x in dias if x['ei_medido'])
        tot['dias'] = len(dias)
        fora[pid] = {'dias': dias, 'total': tot}
    return fora


def comparar(cur, cliente_id, produto_ids, ini, fim):
    """As tres entradas lado a lado, para ver onde elas discordam.

    A diferenca entre nota e descarga nao e erro: e produto que a nota ja
    registrou e que ainda nao desceu (ou o contrario). E o tanque e o juiz —
    `entrou_l` e o que ele absorveu, e e contra ele que as outras duas se
    medem. As tres saem de uma apuracao so, porque nota, descarga e tanque
    convivem no mesmo dia.
    """
    nota = apurar(cur, cliente_id, produto_ids, ini, fim, 'nota')
    fora = {}
    for pid in nota:
        tn = nota[pid]['total']
        fora[pid] = {
            'nota_l': tn['nota_l'], 'descarga_l': tn['desc_l'],
            'entrou_l': tn['entrou_l'],
            'diferenca_l': tn['nota_l'] - tn['desc_l'],
            'nota_variacao': tn['entrou_l'] - tn['nota_l'],
            'descarga_variacao': tn['entrou_l'] - tn['desc_l'],
            'dias_entrou': tn['dias_entrou'], 'dias': tn['dias'],
        }
    return fora
