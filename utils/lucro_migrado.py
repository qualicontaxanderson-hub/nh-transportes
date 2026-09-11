# -*- coding: utf-8 -*-
"""Apuração de lucro dos postos a partir das telas NOVAS.

O relatório antigo (/relatorios/lucro_postos) nasceu quando a descarga era
lançada de outro jeito, e a variação dele saía muito errada. As telas novas
resolveram isso na origem, e cada número agora tem uma fonte só:

    estoque   leitura_tanque_diaria   (a medição do tanque, pelo ELS)
    vendas    vendas_xml + itens      (o cupom fiscal, litro a litro)
    compras   dfe_itens               (a NOTA de compra, pelo DFe)
    descarga  descargas + fretes      (o que DESCEU no tanque)

Compra e descarga são coisas diferentes, e é por isso que existem duas bases:

  base='nota'      a entrada é o que a nota diz. É a visão fiscal: casa com o
                   livro e com o que se paga ao fornecedor.
  base='descarga'  a entrada é o que desceu no tanque. É a visão física: casa
                   com a régua.

No S-500 de 09/09/2026, por exemplo, a nota trouxe 12.000 L e a descarga do dia
foram 5.000 L — o resto desceu depois. Nenhuma das duas está errada; elas
respondem perguntas diferentes, e misturá-las é o que fazia a variação mentir.

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

    Vai até fim+1: o estoque final de um dia é a abertura do dia seguinte, e é
    com ela que a variação é medida.
    """
    cur.execute("""
        SELECT DATE(data_leitura) AS d, produto_id, SUM(volume_atual) AS litros
          FROM leitura_tanque_diaria
         WHERE cliente_id = %s
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


def _compras_nota(cur, cliente_id, ini, fim):
    """{(dia, produto_id): (litros, reais)} pela NOTA de compra (DFe)."""
    cur.execute("""
        SELECT DATE(doc.dh_emissao) AS d, i.classificado_produto_id AS pid,
               SUM(i.quantidade)  AS litros,
               SUM(i.valor_total) AS reais
          FROM dfe_itens i
          JOIN dfe_documentos doc ON doc.id = i.documento_id
         WHERE doc.cliente_id = %s
           AND DATE(doc.dh_emissao) BETWEEN %s AND %s
           AND i.classificado_produto_id IS NOT NULL
           AND (doc.situacao IS NULL OR UPPER(doc.situacao) NOT LIKE '%%CANCEL%%')
         GROUP BY d, i.classificado_produto_id
    """, (cliente_id, ini, fim))
    return {(r['d'], r['pid']): (_f(r['litros']), _f(r['reais']))
            for r in cur.fetchall()}


def _compras_descarga(cur, cliente_id, ini, fim, preco):
    """{(dia, produto_id): (litros, reais)} pelo que DESCEU no tanque.

    O litro vem da descarga; o preco vem da nota daquele produto — a descarga
    mede volume, nao dinheiro. Quando ha nota vinculada (descarga_nota), vale o
    preco dela; senao, o preco medio de compra do produto no periodo, que e a
    melhor aproximacao disponivel e fica dita na tela.
    """
    cur.execute("""
        SELECT d.data_descarga AS d, f.produto_id AS pid,
               SUM(COALESCE(NULLIF(d.volume_descarregado, 0),
                            d.volume_descarga)) AS litros,
               SUM(COALESCE(dn.litros, 0))      AS litros_com_nota,
               SUM(COALESCE(di.valor_unitario, 0) * COALESCE(dn.litros, 0)) AS reais_nota
          FROM descargas d
          JOIN fretes f ON f.id = d.frete_id
          LEFT JOIN descarga_nota dn ON dn.descarga_id = d.id
          LEFT JOIN dfe_itens di ON di.id = dn.item_id
         WHERE f.clientes_id = %s
           AND d.data_descarga BETWEEN %s AND %s
           AND f.produto_id IS NOT NULL
         GROUP BY d.data_descarga, f.produto_id
    """, (cliente_id, ini, fim))
    fora = {}
    for r in cur.fetchall():
        litros = _f(r['litros'])
        com_nota = _f(r['litros_com_nota'])
        reais = _f(r['reais_nota'])
        # o que desceu sem nota vinculada entra pelo preco medio do periodo
        sobra = max(0.0, litros - com_nota)
        reais += sobra * preco.get(r['pid'], 0.0)
        fora[(r['d'], r['pid'])] = (litros, reais)
    return fora


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

    Devolve {produto_id: {'dias': [...], 'total': {...}}}. Cada dia traz o que
    a tela mostra: estoque inicial, entrada, venda, custo corrido, estoque
    final calculado, estoque final medido e a variação entre os dois.
    """
    if base not in BASES:
        raise ValueError('base deve ser %r' % (BASES,))
    produto_ids = [int(p) for p in (produto_ids or [])]
    if not produto_ids:
        return {}

    leitura = _leituras(cur, cliente_id, ini, fim)
    venda = _vendas(cur, cliente_id, ini, fim)
    preco = _preco_medio(cur, cliente_id, produto_ids, ini, fim)
    entrada = (_compras_nota(cur, cliente_id, ini, fim) if base == 'nota'
               else _compras_descarga(cur, cliente_id, ini, fim, preco))

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
                         'variacao_l': 0.0}
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

            dias.append({
                'data': d, 'ei': ei, 'ei_medido': ei_medido,
                'entrada_l': ent_l, 'entrada_rs': ent_rs,
                'entrada_unit': (ent_rs / ent_l) if ent_l else 0.0,
                'venda_l': ven_l, 'venda_rs': ven_rs,
                'venda_unit': (ven_rs / ven_l) if ven_l else 0.0,
                'custo_unit': custo_unit, 'custo_rs': custo_rs,
                'lucro_rs': ven_rs - custo_rs,
                'margem_l': ((ven_rs - custo_rs) / ven_l) if ven_l else 0.0,
                'ef_calc': ef_calc, 'ef_real': ef_real, 'variacao': variacao,
            })
            tot['entrada_l'] += ent_l
            tot['entrada_rs'] += ent_rs
            tot['venda_l'] += ven_l
            tot['venda_rs'] += ven_rs
            tot['custo_rs'] += custo_rs
            tot['lucro_rs'] += ven_rs - custo_rs
            if variacao is not None:
                tot['variacao_l'] += variacao

        tot['ei'] = dias[0]['ei'] if dias else 0.0
        tot['ei_medido'] = dias[0]['ei_medido'] if dias else False
        tot['encadeado'] = encadeado
        # o final do periodo e a ULTIMA medicao que existe — nao o calculado
        tot['ef_real'] = next((x['ef_real'] for x in reversed(dias)
                               if x['ef_real'] is not None), None)
        tot['ef_calc'] = dias[-1]['ef_calc'] if dias else 0.0
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
    """As duas bases lado a lado, para ver onde nota e descarga discordam.

    A diferenca entre elas nao e erro: e produto que a nota ja registrou e que
    ainda nao desceu (ou o contrario). Ver as duas juntas e o que responde
    "cade o que falta".
    """
    nota = apurar(cur, cliente_id, produto_ids, ini, fim, 'nota')
    desc = apurar(cur, cliente_id, produto_ids, ini, fim, 'descarga')
    fora = {}
    for pid in nota:
        tn = nota[pid]['total']
        td = desc.get(pid, {}).get('total', {})
        fora[pid] = {
            'nota_l': tn['entrada_l'], 'descarga_l': td.get('entrada_l', 0.0),
            'diferenca_l': tn['entrada_l'] - td.get('entrada_l', 0.0),
            'nota_variacao': tn['variacao_l'],
            'descarga_variacao': td.get('variacao_l', 0.0),
        }
    return fora
