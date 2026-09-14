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

# Quantos dias a conta corre ANTES do periodo pedido, so para chegar no
# primeiro dia com o custo medio ja formado. Sem isso o mesmo 12/09 mostra um
# custo quando se filtra o mes e outro quando se filtra o dia — e um relatorio
# que muda de resposta conforme quem pergunta nao serve para decidir nada.
# Sessenta dias cobrem varias trocas de tanque em qualquer combustivel.
AQUECIMENTO = 60


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
    """{(dia, produto_id): (litros, reais, produto, acrescimo, desconto)}.

    O cupom nao carrega cliente_id: quem diz de que posto ele e o CNPJ do
    emitente. Sem esse laco, um segundo posto misturaria as vendas no mesmo
    relatorio.

    `reais` e o que ENTROU: a linha do produto mais o acrescimo, menos o
    desconto. O acrescimo nao e detalhe -- e o preco do cartao e do prazo,
    que no posto vem fora da linha do produto. No cupom 7350 o S-10 sai por
    490 L x R$ 6,49 = R$ 3.180,21 e o cliente paga R$ 3.425,22, porque foi a
    prazo. Somar so a linha esconde R$ 245 que entraram no caixa -- em
    setembro inteiro, R$ 7.650 de lucro que o relatorio nao via.
    """
    cur.execute("""
        SELECT DATE(v.dh_emissao) AS d, i.produto_id,
               SUM(i.quantidade)  AS litros,
               SUM(i.valor_total) AS reais,
               SUM(COALESCE(i.vlr_acrescimo, 0)) AS acrescimo,
               SUM(COALESCE(i.vlr_desconto, 0))  AS desconto
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
    return {(r['d'], r['produto_id']):
            (_f(r['litros']),
             _f(r['reais']) + _f(r['acrescimo']) - _f(r['desconto']),
             _f(r['reais']), _f(r['acrescimo']), _f(r['desconto']))
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


def _notas(cur, cliente_id, produto_ids, ini, fim, pend_ini=None):
    """A nota pelo dia em que ela DESCEU, e o que dela ainda nao desceu.

    Devolve (descidas, pendente, produto):

        descidas   {(dia, produto_id): (litros, reais)} — o litro da nota
                   alocado ao dia da descarga que a consumiu, ao custo CHEIO
                   da nota (com o ICMS-ST)
        pendente   {(dia, produto_id): litros} — saldo no fim daquele dia do
                   que ja foi faturado e ainda nao desceu
        produto    {(dia, produto_id): reais} — so a linha do produto, sem o
                   que a nota cobra por cima; serve para a tela mostrar a
                   diferenca em vez de esconde-la

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
               i.quantidade AS litros, i.valor_total AS reais,
               doc.valor_total AS nota_total,
               (SELECT SUM(x.valor_total) FROM dfe_itens x
                 WHERE x.documento_id = doc.id) AS itens_total
          FROM dfe_itens i
          JOIN dfe_documentos doc ON doc.id = i.documento_id
         WHERE doc.cliente_id = %s
           AND DATE(doc.dh_emissao) BETWEEN %s AND %s
           AND i.classificado_produto_id IN (""" + marcas + """)
           AND (doc.situacao IS NULL OR UPPER(doc.situacao) NOT LIKE '%%CANCEL%%')
    """, [cliente_id, ini - timedelta(days=90), fim] + list(produto_ids))
    itens = {}
    for r in cur.fetchall():
        itens[r['id']] = {
            'emissao': r['emissao'], 'pid': r['pid'],
            'litros': _f(r['litros']),
            'reais': _custo_do_item(_f(r['reais']), _f(r['nota_total']),
                                    _f(r['itens_total'])),
            'produto_rs': _f(r['reais']),
        }

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

    descidas, baixa, produto = {}, {}, {}   # baixa: por item, (dia, produto)
    for item_id, vs in por_item.items():
        it = itens.get(item_id)
        if not it or not it['litros']:
            continue
        unit = it['reais'] / it['litros']
        unit_prod = it['produto_rs'] / it['litros']
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
                produto[ky] = produto.get(ky, 0.0) + usar * unit_prod

    # O saldo do que falta descer. So contam as notas emitidas ate 30 dias
    # antes do periodo: antes da tela de descargas existir (28/07/2026) nao ha
    # vinculo nenhum, e essas notas ficariam pendentes para sempre.
    # o saldo a descer e do periodo que o usuario pediu, nao do aquecimento
    pend_ini = pend_ini or ini
    corte = pend_ini - timedelta(days=30)
    saldo, emitidas_dia, baixa_dia = {}, {}, {}
    for item_id, it in itens.items():
        # So os itens da janela: antes da tela de descargas existir nao ha
        # vinculo nenhum, e aquelas notas ficariam pendentes para sempre. E a
        # baixa so conta para o item que entrou na conta — subtrair a baixa de
        # um item que nunca foi somado derruba o saldo para milhares negativos.
        if not (corte <= it['emissao'] <= fim):
            continue
        if it['emissao'] < pend_ini:
            saldo[it['pid']] = saldo.get(it['pid'], 0.0) + it['litros']
        else:
            ky = (it['emissao'], it['pid'])
            emitidas_dia[ky] = emitidas_dia.get(ky, 0.0) + it['litros']
        for (d, pid), l in baixa.get(item_id, {}).items():
            if d < pend_ini:
                saldo[pid] = saldo.get(pid, 0.0) - l
            elif d <= fim:
                baixa_dia[(d, pid)] = baixa_dia.get((d, pid), 0.0) + l

    pendente = {}
    for pid in produto_ids:
        acu = saldo.get(pid, 0.0)
        for d in _dias(pend_ini, fim):
            acu += emitidas_dia.get((d, pid), 0.0) - baixa_dia.get((d, pid), 0.0)
            pendente[(d, pid)] = acu
    return descidas, pendente, produto


def _custo_do_item(produto_rs, nota_total, itens_total):
    """O que aquele item custa de verdade: a NOTA, nao a linha do produto.

    O valor da linha e quantidade x preco do produto. O que se paga e o total
    da nota — e nela entra o ICMS-ST, que no combustivel e dinheiro de
    verdade e sai do caixa junto. Na nota 1684 da Tabocao, 8.000 L de etanol
    somam R$ 22.235,54 na linha e R$ 23.600,00 no total: R$ 1.364,46 a mais,
    R$ 0,17 por litro. Ignorar isso barateia a compra e infla o lucro.

    Nem todo fornecedor faz assim — nove dos dezoito fecham a linha igual ao
    total da nota, e ai a conta nao muda nada. Por isso a regra e sempre a
    mesma e nao depende de adivinhar quem cobra ST: vale o total da nota.

    Quando a nota tem mais de um item, cada um leva a sua parte da diferenca
    na proporcao do que representa. E quando o total da nota falta, ou vem
    MENOR que a soma dos itens (nota de devolucao, desconto, resumo sem
    valor), nao ha o que ratear: vale a linha do produto, que e o certo que
    se tem.
    """
    if not produto_rs or not itens_total or itens_total <= 0:
        return produto_rs
    if not nota_total or nota_total <= itens_total:
        return produto_rs
    return produto_rs + (nota_total - itens_total) * (produto_rs / itens_total)


def _preco_medio(cur, cliente_id, produto_ids, ini, fim):
    """Dois precos medios por produto: (do periodo, da abertura).

    Sao dois porque respondem coisas diferentes, e confundi-los estraga o
    custo de quem filtra poucos dias:

      do periodo   as compras de dentro do periodo. Precifica descarga que
                   nao tem nota vinculada.
      da abertura  as compras dos 60 dias ANTERIORES ao periodo. E com ela
                   que se valoriza o combustivel que ja estava no tanque
                   quando o periodo comecou — porque ele foi comprado antes.

    Usar o preco do periodo na abertura faz o custo de um dia unico colar no
    preco da compra daquele dia: o tanque cheio de ontem passa a valer o que
    se pagou hoje. Num mes isso se dilui; num dia, mente.

    Cada um cai no outro quando a sua janela nao tem compra nenhuma.
    """
    if not produto_ids:
        return {}, {}
    marcas = ','.join(['%s'] * len(produto_ids))
    janelas = {}
    for janela_ini, janela_fim in ((ini, fim),
                                   (ini - timedelta(days=60), ini - timedelta(days=1))):
        # pelo mesmo criterio do custo: o que a nota cobra, com o ST dentro
        cur.execute("""
            SELECT i.classificado_produto_id AS pid, i.quantidade AS litros,
                   i.valor_total AS reais, doc.valor_total AS nota_total,
                   (SELECT SUM(x.valor_total) FROM dfe_itens x
                     WHERE x.documento_id = doc.id) AS itens_total
              FROM dfe_itens i
              JOIN dfe_documentos doc ON doc.id = i.documento_id
             WHERE doc.cliente_id = %s
               AND DATE(doc.dh_emissao) BETWEEN %s AND %s
               AND i.classificado_produto_id IN (""" + marcas + """)
               AND (doc.situacao IS NULL
                    OR UPPER(doc.situacao) NOT LIKE '%%CANCEL%%')
        """, [cliente_id, janela_ini, janela_fim] + list(produto_ids))
        soma = {}
        for r in cur.fetchall():
            l, rs = soma.get(r['pid'], (0.0, 0.0))
            soma[r['pid']] = (l + _f(r['litros']),
                              rs + _custo_do_item(_f(r['reais']),
                                                  _f(r['nota_total']),
                                                  _f(r['itens_total'])))
        janelas[(janela_ini, janela_fim)] = {
            pid: (reais / litros) for pid, (litros, reais) in soma.items()
            if litros}

    do_periodo = janelas[(ini, fim)]
    da_abertura = janelas[(ini - timedelta(days=60), ini - timedelta(days=1))]
    # cada um cobre a falta do outro
    periodo = dict(da_abertura); periodo.update(do_periodo)
    abertura = dict(do_periodo); abertura.update(da_abertura)
    return periodo, abertura


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

    # A conta corre desde antes do periodo para o custo medio chegar formado
    # ao primeiro dia da tela; so o que e do periodo aparece.
    aquece = ini - timedelta(days=AQUECIMENTO)
    leitura = _leituras(cur, cliente_id, aquece, fim)
    venda = _vendas(cur, cliente_id, aquece, fim)
    preco, preco_abertura = _preco_medio(cur, cliente_id, produto_ids,
                                         aquece, fim)
    nota, pendente, nota_produto = _notas(cur, cliente_id, produto_ids,
                                          aquece, fim, pend_ini=ini)
    medido_l = _descargas(cur, cliente_id, aquece, fim)
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
        saldo_l = leitura.get((aquece, pid))
        if saldo_l is None:
            saldo_l = 0.0
        saldo_rs = saldo_l * preco_abertura.get(pid, 0.0)
        encadeado = leitura.get((ini, pid)) is None

        dias, tot = [], {'entrada_l': 0.0, 'entrada_rs': 0.0, 'venda_l': 0.0,
                         'venda_rs': 0.0, 'custo_rs': 0.0, 'lucro_rs': 0.0,
                         'variacao_l': 0.0, 'nota_l': 0.0, 'nota_rs': 0.0,
                         'desc_l': 0.0, 'entrou_l': 0.0, 'dias_entrou': 0,
                         'nota_produto_rs': 0.0, 'venda_produto_rs': 0.0,
                         'venda_acr_rs': 0.0, 'venda_desc_rs': 0.0}
        falta_acum = 0.0
        var_acum = 0.0
        lucro_acum = 0.0
        ei_rs = 0.0
        ultimo_custo = preco_abertura.get(pid, 0.0)
        for d in _dias(aquece, fim):
            medido = leitura.get((d, pid))
            # A medicao do dia manda no estoque inicial: ela e a realidade.
            # Quando falta (o e-mail do ELS nao chegou), o dia encadeia com o
            # final calculado do dia anterior, e a tela marca isso.
            if medido is not None and d != aquece:
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
            # O estoque de abertura EM REAIS, capturado no primeiro dia da
            # tela: e o saldo carregado do aquecimento, antes de a compra do
            # dia entrar. Depois disso o saldo ja e outro.
            if d == ini:
                ei_rs = saldo_rs

            ent_l, ent_rs = entrada.get((d, pid), (0.0, 0.0))
            nota_l, nota_rs = nota.get((d, pid), (0.0, 0.0))
            nota_prod_rs = nota_produto.get((d, pid), 0.0)
            desc_l = medido_l.get((d, pid), 0.0)
            ven_l, ven_rs, ven_prod, ven_acr, ven_desc = venda.get(
                (d, pid), (0.0, 0.0, 0.0, 0.0, 0.0))

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
            # O aquecimento serve ao CUSTO, e so a ele. Os acumulados sao do
            # periodo que o usuario pediu: somar os 60 dias de antes faria a
            # tela abrir o dia 1 com um lucro acumulado que ninguem pediu.
            if d < ini:
                continue

            falta_acum = pendente.get((d, pid), 0.0)
            if variacao is not None:
                var_acum += variacao
            lucro_acum += ven_rs - custo_rs
            ultimo_custo = custo_unit

            dias.append({
                'data': d, 'ei': ei, 'ei_medido': ei_medido,
                'entrada_l': ent_l, 'entrada_rs': ent_rs,
                'entrada_unit': (ent_rs / ent_l) if ent_l else 0.0,
                'nota_l': nota_l, 'nota_rs': nota_rs, 'desc_l': desc_l,
                'nota_produto_rs': nota_prod_rs,
                'nota_st_rs': nota_rs - nota_prod_rs,
                'entrou': entrou, 'falta_dia': nota_l - desc_l,
                'medido_l': desc_l,
                'falta_acum': falta_acum, 'var_acum': var_acum,
                'venda_l': ven_l, 'venda_rs': ven_rs,
                'venda_produto_rs': ven_prod, 'venda_acr_rs': ven_acr,
                'venda_desc_rs': ven_desc,
                'venda_unit': (ven_rs / ven_l) if ven_l else 0.0,
                'venda_bomba_unit': (ven_prod / ven_l) if ven_l else 0.0,
                'custo_unit': custo_unit, 'custo_rs': custo_rs,
                'lucro_rs': ven_rs - custo_rs, 'lucro_acum': lucro_acum,
                # A margem e a da BOMBA: o preco do painel menos o custo
                # corrido. O acrescimo do cartao e do prazo fica de fora
                # porque ele existe para cobrir a taxa da operadora -- entra
                # no lucro e no faturamento, nao na conta de pista.
                'margem_l': ((ven_prod - custo_rs) / ven_l) if ven_l else 0.0,
                'ef_calc': ef_calc, 'ef_real': ef_real, 'variacao': variacao,
            })
            tot['entrada_l'] += ent_l
            tot['entrada_rs'] += ent_rs
            tot['nota_l'] += nota_l
            tot['nota_rs'] += nota_rs
            tot['nota_produto_rs'] += nota_prod_rs
            tot['desc_l'] += desc_l
            tot['venda_l'] += ven_l
            tot['venda_rs'] += ven_rs
            tot['venda_produto_rs'] += ven_prod
            tot['venda_acr_rs'] += ven_acr
            tot['venda_desc_rs'] += ven_desc
            tot['custo_rs'] += custo_rs
            tot['lucro_rs'] += ven_rs - custo_rs
            if variacao is not None:
                tot['variacao_l'] += variacao
            if entrou is not None:
                tot['entrou_l'] += entrou
                tot['dias_entrou'] += 1

        tot['ei'] = dias[0]['ei'] if dias else 0.0
        tot['ei_medido'] = dias[0]['ei_medido'] if dias else False
        tot['ei_rs'] = ei_rs if dias else 0.0
        tot['encadeado'] = encadeado
        # o final do periodo e a ULTIMA medicao que existe — nao o calculado
        tot['ef_real'] = next((x['ef_real'] for x in reversed(dias)
                               if x['ef_real'] is not None), None)
        tot['ef_calc'] = dias[-1]['ef_calc'] if dias else 0.0
        tot['falta_l'] = falta_acum
        # O estoque final em reais sai dos MESMOS litros que a tela mostra,
        # ao custo corrido do ultimo dia -- e o que aquele combustivel custou,
        # nao o que ele vale vendido.
        _ef = tot['ef_real'] if tot['ef_real'] is not None else tot['ef_calc']
        tot['ef_rs'] = _ef * ultimo_custo
        tot['ef_unit'] = ultimo_custo
        # o que a nota cobrou alem do produto — ICMS-ST, quase sempre
        tot['nota_st_rs'] = tot['nota_rs'] - tot['nota_produto_rs']
        tot['nota_produto_unit'] = ((tot['nota_produto_rs'] / tot['nota_l'])
                                    if tot['nota_l'] else 0.0)
        tot['nota_unit'] = ((tot['nota_rs'] / tot['nota_l'])
                            if tot['nota_l'] else 0.0)
        tot['margem_l'] = (((tot['venda_produto_rs'] - tot['custo_rs'])
                            / tot['venda_l']) if tot['venda_l'] else 0.0)
        tot['custo_unit'] = (tot['custo_rs'] / tot['venda_l']) if tot['venda_l'] else 0.0
        tot['entrada_unit'] = ((tot['entrada_rs'] / tot['entrada_l'])
                               if tot['entrada_l'] else 0.0)
        tot['venda_unit'] = ((tot['venda_rs'] / tot['venda_l'])
                             if tot['venda_l'] else 0.0)
        tot['venda_bomba_unit'] = ((tot['venda_produto_rs'] / tot['venda_l'])
                                   if tot['venda_l'] else 0.0)
        tot['dias_medidos'] = sum(1 for x in dias if x['ei_medido'])
        tot['dias'] = len(dias)
        fora[pid] = {'dias': dias, 'total': tot}
    return fora


def comparar(cur, cliente_id, produto_ids, ini, fim):
    """As tres entradas lado a lado, SOBRE OS MESMOS DIAS.

    O "mesmos dias" nao e detalhe: e a conta inteira. `entrou` so existe onde
    ha as duas medicoes de tanque — a de hoje e a de amanha —, e o ultimo dia
    do periodo nunca tem a de amanha ainda. Somar a nota do mes inteiro contra
    um `entrou` que para um dia antes acusa uma diferenca que nao existe: no
    etanol de 12/09/2026 desceram 10.000 L de nota que o tanque ainda nao
    tinha como confirmar, e a tela dizia "a nota erra 9.831 L".

    Entao a comparacao anda so pelos dias medidos, e devolve o que ficou de
    fora para a tela poder dizer isso em portugues.

    A diferenca que sobra e real: a regua mede com perda de temperatura, e a
    nota nao. O tanque e o juiz dos dois.
    """
    nota = apurar(cur, cliente_id, produto_ids, ini, fim, 'nota')
    fora = {}
    for pid in nota:
        tn = nota[pid]['total']
        medidos = [d for d in nota[pid]['dias'] if d['entrou'] is not None]
        nota_l = sum(d['nota_l'] for d in medidos)
        desc_l = sum(d['desc_l'] for d in medidos)
        entrou_l = sum(d['entrou'] for d in medidos)
        # o que entrou mas o tanque ainda nao confirmou
        espera_n = tn['nota_l'] - nota_l
        espera_d = tn['desc_l'] - desc_l
        fora[pid] = {
            'nota_l': nota_l, 'descarga_l': desc_l, 'entrou_l': entrou_l,
            'diferenca_l': nota_l - desc_l,
            'nota_variacao': entrou_l - nota_l,
            'descarga_variacao': entrou_l - desc_l,
            'espera_nota_l': espera_n, 'espera_desc_l': espera_d,
            'espera': espera_n > 1 or espera_d > 1,
            'dia_espera': next((d['data'] for d in reversed(nota[pid]['dias'])
                                if d['entrou'] is None
                                and (d['nota_l'] or d['desc_l'])), None),
            'dias_entrou': len(medidos), 'dias': tn['dias'],
            # os totais do periodo inteiro continuam a mao, para quem quiser
            'nota_periodo_l': tn['nota_l'], 'descarga_periodo_l': tn['desc_l'],
        }
    return fora
