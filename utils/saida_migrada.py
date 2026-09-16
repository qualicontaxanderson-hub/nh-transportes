# -*- coding: utf-8 -*-
"""A VENDA do posto pelo cupom, e não pelo que alguém digitou.

É o espelho de utils/fornecedor_migrado: lá a entrada (a nota da SEFAZ, a
descarga da régua, o pagamento do extrato); aqui a saída, com uma fonte só —
o XML que a captura trouxe:

    vendas_xml         o cupom (modelo 65) e a NF-e (modelo 55): quando,
                       quanto, como foi pago, por quem foi vendido, para quem
    vendas_xml_itens   o item: qual combustível, quantos litros, a que preço,
                       e por qual bico/bomba/tanque ele saiu

O QUE ENTROU NO CAIXA é a linha do item MAIS o acréscimo MENOS o desconto —
a mesma conta de utils/lucro_migrado._vendas, e pela mesma razão: no posto o
preço do cartão e do prazo vem FORA da linha do produto. No cupom 7350 o S-10
sai por 490 L x R$ 6,49 = R$ 3.180,21 e o cliente paga R$ 3.425,22. Somar só a
linha esconde R$ 245 que entraram.

Isso tem data: até 01/09/2026 o diferencial do cartão vinha embutido no preço
unitário; de 02/09 em diante ele mudou de lugar e passou a vir no acréscimo.
Somando os dois, o preço médio desta tela atravessa essa mudança sem degrau —
é o mesmo número antes e depois.

O QUE FICA DE FORA: nota cancelada (elas são contadas e mostradas à parte, não
somadas). Nada mais fica de fora: o item sem produto classificado não some,
ele vira o card **Outros** — assim o relatório fecha com o faturamento
inteiro, e o que não está classificado aparece em vez de se esconder.

LITRO só de quem é vendido em litro (unidade L ou LT). Óleo em lata é UN: soma
em real, não em litro. Somar "1 unidade" com "1 litro" daria um total que não
é de nada.

SOMENTE LEITURA: todas as funções recebem um cursor já aberto e não escrevem.
"""
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

_MES_PT = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
           'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']

# O item que nao tem produto classificado cai aqui. Numero negativo de
# proposito: nunca colide com um produto.id de verdade.
PID_OUTROS = -1

# Unidades que sao litro. O resto (UN) soma em real e nao em litro.
_UNID_LITRO = ('L', 'LT', 'LTS', 'LITRO')


def _f(v):
    """Decimal/None do banco vira float — Decimal com float estoura no meio."""
    return float(v) if v is not None else 0.0


def _dia(v):
    """DATE/DATETIME do banco vira date (o driver devolve os dois)."""
    return v.date() if hasattr(v, 'date') else v


def _sem_acento(txt):
    return ''.join(c for c in unicodedata.normalize('NFD', txt or '')
                   if unicodedata.category(c) != 'Mn')


# Como cada meio de pagamento chega escrito no XML -> como ele se chama aqui.
# O mesmo meio vem em duas grafias ("Cartão Débito" e "Cartao Debito") porque
# o PDV mudou de versao no meio do caminho; sem esta tabela o relatorio
# mostraria a mesma coisa em duas linhas, e nenhuma das duas estaria certa.
_FORMAS = {
    'CARTAO DEBITO': 'Cartão Débito',
    'CARTAO CREDITO': 'Cartão Crédito',
    'DINHEIRO': 'Dinheiro',
    'CHEQUE': 'Cheque',
    'CREDITO LOJA/PRAZO': 'Prazo (crédito loja)',
    'CREDITO LOJA': 'Prazo (crédito loja)',
    'PRAZO': 'Prazo (crédito loja)',
    'TRANSFERENCIA/CARTEIRA': 'Transferência',
    'TRANSF. BANCARIA': 'Transferência',
    'TRANSFERENCIA': 'Transferência',
    'PIX': 'PIX',
}


def _forma(txt):
    """'Dinheiro+Cartao Debito' -> 'Cartão Débito + Dinheiro'.

    Uma venda pode ser paga com mais de um meio, e o XML junta com '+'. As
    partes sao ORDENADAS antes de juntar de novo: sem isso, 'A+B' e 'B+A'
    viram duas linhas do mesmo pagamento (e viram mesmo: tem 14 notas de
    'Cartao Credito+Cartao Debito' e 13 de 'Cartao Debito+Cartao Credito').

    A nota com dois meios conta UMA vez, na combinacao. Ratear o valor entre
    os meios seria inventar: o XML nao diz quanto foi em cada um.
    """
    cru = (txt or '').strip()
    if not cru:
        return 'Sem forma no XML'
    partes = []
    for p in cru.replace(' + ', '+').split('+'):
        chave = ' '.join(_sem_acento(p).upper().split())
        partes.append(_FORMAS.get(chave, p.strip().title()))
    return ' + '.join(sorted(set(partes)))


def meses(cur, hoje=None):
    """A régua de meses que TEM venda, do mais antigo ao mais novo.

    Igual à do Fornecedores Migrados, e pela mesma razão: sai do banco, não de
    um range fixo. A captura de vendas começa em 26/05/2026 — inventar janeiro
    daria uma pílula que só sabe dizer "não tem nada". O mês corrente para
    HOJE, para bater com o período que a tela abre sozinha.
    """
    hoje = hoje or date.today()
    cur.execute(
        "SELECT DATE_FORMAT(v.dh_emissao,'%Y-%m') AS mes, COUNT(*) AS notas "
        "  FROM vendas_xml v "
        " WHERE (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA') "
        " GROUP BY mes ORDER BY mes")
    saida = []
    for r in cur.fetchall():
        ano, mes = int(r['mes'][:4]), int(r['mes'][5:7])
        ini = date(ano, mes, 1)
        fim = (date(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1))
        if fim > hoje:
            fim = hoje
        saida.append({'mes': r['mes'], 'ini': ini, 'fim': fim,
                      'rotulo': '%s/%s' % (_MES_PT[mes - 1], r['mes'][2:4]),
                      'notas': int(r['notas'] or 0)})
    return saida


_SELECT_ITENS = """
    SELECT v.id AS nota, DATE(v.dh_emissao) AS dia, HOUR(v.dh_emissao) AS hora,
           v.modelo, v.serie, v.numero,
           v.forma_pagamento, v.card_bandeira, v.vendedor_raw,
           v.cliente_doc, v.cliente_nome,
           i.produto_id AS pid, i.produto_xml, i.unidade,
           i.bomba, i.bico, i.tanque,
           i.quantidade, i.valor_total, i.vlr_acrescimo, i.vlr_desconto
      FROM vendas_xml v
      JOIN vendas_xml_itens i ON i.venda_id = v.id
     WHERE (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA')
       AND DATE(v.dh_emissao) BETWEEN %s AND %s
"""


def _produtos_cadastro(cur):
    cur.execute("SELECT id, nome FROM produto")
    return {r['id']: r['nome'] for r in cur.fetchall()}


def _linhas(cur, ini, fim, nomes):
    """O item, um por um, já com o produto resolvido e o real que entrou.

    Uma consulta só: tudo que a tela mostra — os cards, os sete recortes e o
    dia a dia — sai daqui. Somar sete vezes no banco seria sete varreduras da
    mesma tabela para responder a mesma pergunta.
    """
    cur.execute(_SELECT_ITENS, (ini, fim))
    linhas = []
    for r in cur.fetchall():
        pid = r['pid'] or PID_OUTROS
        unid = (r['unidade'] or '').strip().upper()
        litros = _f(r['quantidade']) if unid in _UNID_LITRO else 0.0
        linhas.append({
            'nota': r['nota'], 'dia': _dia(r['dia']), 'hora': int(r['hora'] or 0),
            'modelo': int(r['modelo'] or 0), 'serie': int(r['serie'] or 0),
            'numero': r['numero'],
            'pid': pid,
            'produto': ('Outros' if pid == PID_OUTROS
                        else (nomes.get(pid) or ('Produto %s' % pid))),
            'produto_xml': r['produto_xml'] or '—',
            'litros': litros,
            # o que ENTROU: a linha do item, mais o acrescimo, menos o desconto
            'rs': (_f(r['valor_total']) + _f(r['vlr_acrescimo'])
                   - _f(r['vlr_desconto'])),
            'linha_rs': _f(r['valor_total']),
            'acrescimo': _f(r['vlr_acrescimo']),
            'desconto': _f(r['vlr_desconto']),
            'forma': _forma(r['forma_pagamento']),
            'bandeira': (r['card_bandeira'] or '').strip(),
            'vendedor': (r['vendedor_raw'] or '').strip(),
            'doc': (r['cliente_doc'] or '').strip(),
            'cliente': (r['cliente_nome'] or '').strip(),
            'bomba': r['bomba'], 'bico': r['bico'], 'tanque': r['tanque'],
        })
    return linhas


def _preco(rs, litros):
    return (rs / litros) if litros else 0.0


# ---------------------------------------------------------------- recortes --
# Cada recorte responde "esse faturamento, aberto por quê?". Todos saem das
# MESMAS linhas de item, entao todos fecham com o mesmo total -- e por isso
# que a nota de dois produtos conta uma vez so (COUNT distinto do id da nota)
# mas os litros dela aparecem inteiros.

def _agrupa(linhas, chave, rotulo, sub=None, ordem=None):
    grupos = {}
    for x in linhas:
        k = chave(x)
        if k is None:
            continue
        g = grupos.get(k)
        if g is None:
            g = grupos[k] = {'chave': k, 'rotulo': rotulo(x), 'sub': '',
                             'litros': 0.0, 'rs': 0.0, 'notas': set()}
        g['litros'] += x['litros']
        g['rs'] += x['rs']
        g['notas'].add(x['nota'])
        if sub:
            g['sub'] = sub(x, g)
    total = sum(g['rs'] for g in grupos.values())
    saida = []
    for g in grupos.values():
        g['notas'] = len(g['notas'])
        g['unit'] = _preco(g['rs'], g['litros'])
        g['fatia'] = (g['rs'] / total * 100) if total else 0.0
        saida.append(g)
    saida.sort(key=ordem or (lambda g: -g['rs']))
    return saida


def _doc_fmt(doc):
    """CPF e CNPJ com a pontuação de sempre — 11 e 14 dígitos."""
    d = ''.join(c for c in (doc or '') if c.isdigit())
    if len(d) == 11:
        return '%s.%s.%s-%s' % (d[:3], d[3:6], d[6:9], d[9:])
    if len(d) == 14:
        return '%s.%s.%s/%s-%s' % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])
    return doc or '—'


def _recortes(linhas):
    """Os sete cortes do mesmo faturamento."""
    # CLIENTE: 27 mil das 32 mil notas sao cupom de pista, sem ninguem
    # identificado. Elas nao podem sumir -- viram uma linha so, que e a
    # maior de todas, e a tela diz o que ela e.
    def _cli_chave(x):
        return x['doc'] or '__pista__'

    def _cli_rotulo(x):
        if not x['doc']:
            return 'Consumidor não identificado'
        return x['cliente'] or _doc_fmt(x['doc'])

    def _cli_sub(x, g):
        return '' if not x['doc'] else _doc_fmt(x['doc'])

    # BICO: cada (bomba, bico) serve um tanque e um produto so -- conferido no
    # banco, os 12 bicos sao estaveis. E o unico recorte que liga a venda ao
    # tanque, o mesmo tanque da descarga do outro lado do relatorio.
    #
    # Nem todo item passou por bico: o ARLA e granel, o oleo e lata, e ha
    # venda faturada de combustivel que sai sem a bomba no XML. Esses nao
    # podem ser descartados -- virariam um recorte que nao fecha com o total.
    # Viram UMA linha, no fim da fila, dizendo o que sao.
    _SEM_BICO = (9999, 9999)

    def _bico_chave(x):
        return (x['bomba'], x['bico']) if x['bico'] is not None else _SEM_BICO

    def _bico_rotulo(x):
        if x['bico'] is None:
            return 'Sem bico no XML'
        return 'Bomba %s · Bico %s' % (x['bomba'], x['bico'])

    def _bico_sub(x, g):
        if x['bico'] is None:
            return 'ARLA, óleo e venda faturada'
        tq = ('TQ %s' % x['tanque']) if x['tanque'] is not None else 'TQ —'
        return '%s · %s' % (tq, x['produto'])

    # CAIXA: a serie e o PDV. Modelo 65 e cupom de pista; 55 e NF-e, a venda
    # faturada -- por isso a serie sozinha nao basta como rotulo.
    def _caixa_rotulo(x):
        return ('NF-e série %s' if x['modelo'] == 55 else 'Caixa %s (NFC-e)') % x['serie']

    # BANDEIRA: o XML do PDV manda 'Outros' para quase tudo e vem vazio no
    # dinheiro. Dizer "Outros" e mentir por omissao; a tela diz o que e.
    def _band_rotulo(x):
        b = x['bandeira']
        if not b:
            return 'Sem cartão (ou o XML não informou)'
        if b.strip().lower() == 'outros':
            return 'Cartão sem bandeira no XML'
        return b

    return {
        'forma': _agrupa(linhas, lambda x: x['forma'], lambda x: x['forma']),
        'cliente': _agrupa(linhas, _cli_chave, _cli_rotulo, _cli_sub),
        'vendedor': _agrupa(linhas,
                            lambda x: x['vendedor'] or '__sem__',
                            lambda x: x['vendedor'] or 'Sem vendedor no XML'),
        'bico': _agrupa(linhas, _bico_chave, _bico_rotulo, _bico_sub,
                        ordem=lambda g: (g['chave'][0] or 0, g['chave'][1] or 0)),
        'bandeira': _agrupa(linhas,
                            lambda x: (x['bandeira'].lower() or '__sem__'),
                            _band_rotulo),
        'caixa': _agrupa(linhas, lambda x: (x['modelo'], x['serie']),
                         _caixa_rotulo, ordem=lambda g: -g['rs']),
        'hora': _agrupa(linhas, lambda x: x['hora'],
                        lambda x: '%02dh' % x['hora'],
                        ordem=lambda g: g['chave']),
    }


# Os sete recortes, na ordem em que a tela os oferece. O rotulo e o que a
# pilula mostra; a pergunta e o que a tela explica embaixo dela.
RECORTES = [
    ('forma',    'Forma de recebimento', 'bi-credit-card',
     'como o dinheiro entrou'),
    ('cliente',  'Cliente',              'bi-person-badge',
     'para quem foi — só a nota que identifica o comprador'),
    ('vendedor', 'Vendedor',             'bi-person-workspace',
     'quem estava na bomba'),
    ('bico',     'Bico / bomba',         'bi-fuel-pump',
     'de qual tanque saiu'),
    ('bandeira', 'Bandeira do cartão',   'bi-credit-card-2-front',
     'o que o XML do PDV informou'),
    ('caixa',    'Caixa / PDV',          'bi-pc-display',
     'em qual série a nota foi emitida'),
    ('hora',     'Hora do dia',          'bi-clock-history',
     'quando o movimento acontece'),
]


def apurar(cur, ini, fim, pid=None):
    """Tudo o que a tela mostra, de uma consulta só.

    Devolve {'produtos', 'geral', 'total', 'recortes', 'dias', ...}.

    `pid` escolhe UM produto: os cards continuam todos na tela (eles são o
    seletor), mas os sete recortes e o dia a dia passam a falar só dele. É o
    mesmo comportamento do card do Fornecedores Migrados, de propósito.
    """
    nomes = _produtos_cadastro(cur)
    linhas = _linhas(cur, ini, fim, nomes)

    # ---- as canceladas: contadas, nunca somadas ----
    cur.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(valor_total),0) AS rs "
        "  FROM vendas_xml "
        " WHERE UPPER(situacao) = 'CANCELADA' "
        "   AND DATE(dh_emissao) BETWEEN %s AND %s", (ini, fim))
    c = cur.fetchone() or {}
    canceladas = {'notas': int(c.get('n') or 0), 'rs': _f(c.get('rs'))}

    # ---- o periodo ANTERIOR, do mesmo tamanho: um preco sozinho nao diz se
    #      subiu, e um faturamento sozinho nao diz se cresceu ----
    dias_periodo = (fim - ini).days + 1
    ini_ant = ini - timedelta(days=dias_periodo)
    fim_ant = ini - timedelta(days=1)
    cur.execute(
        "SELECT i.produto_id AS pid, i.unidade, "
        "       SUM(i.quantidade) AS litros, "
        "       SUM(i.valor_total + COALESCE(i.vlr_acrescimo,0) "
        "           - COALESCE(i.vlr_desconto,0)) AS rs "
        "  FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id "
        " WHERE (v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA') "
        "   AND DATE(v.dh_emissao) BETWEEN %s AND %s "
        " GROUP BY i.produto_id, i.unidade", (ini_ant, fim_ant))
    ant_l, ant_rs = defaultdict(float), defaultdict(float)
    antes_tot = {'litros': 0.0, 'rs': 0.0}
    for r in cur.fetchall():
        p = r['pid'] or PID_OUTROS
        eh_litro = (r['unidade'] or '').strip().upper() in _UNID_LITRO
        litros = _f(r['litros']) if eh_litro else 0.0
        ant_l[p] += litros
        ant_rs[p] += _f(r['rs'])
        antes_tot['litros'] += litros
        antes_tot['rs'] += _f(r['rs'])
    antes = {p: (ant_rs[p] / ant_l[p]) for p in ant_l if ant_l[p]}

    # ---- por produto ----
    prods = {}
    for x in linhas:
        p = prods.get(x['pid'])
        if p is None:
            p = prods[x['pid']] = {
                'pid': x['pid'], 'nome': x['produto'], 'litros': 0.0,
                'rs': 0.0, 'acrescimo': 0.0, 'notas': set(), 'itens': 0,
                'menor': None, 'maior': None,
                'dias': defaultdict(lambda: [0.0, 0.0]),
                'variantes': defaultdict(lambda: [0.0, 0.0]),
            }
        p['litros'] += x['litros']
        p['rs'] += x['rs']
        p['acrescimo'] += x['acrescimo']
        p['notas'].add(x['nota'])
        p['itens'] += 1
        if x['litros']:
            u = _preco(x['rs'], x['litros'])
            p['menor'] = u if p['menor'] is None else min(p['menor'], u)
            p['maior'] = u if p['maior'] is None else max(p['maior'], u)
        d = p['dias'][x['dia']]
        d[0] += x['litros']
        d[1] += x['rs']
        # O card Outros junta ARLA, oleo e acessorio: sem a lista do que ele
        # junta, ele seria uma caixa preta com R$ 60 mil dentro.
        v = p['variantes'][x['produto_xml']]
        v[0] += x['litros']
        v[1] += x['rs']

    total_rs = sum(p['rs'] for p in prods.values())
    saida = []
    for p in prods.values():
        p['notas'] = len(p['notas'])
        p['unit'] = _preco(p['rs'], p['litros'])
        p['fatia'] = (p['rs'] / total_rs * 100) if total_rs else 0.0
        p['antes'] = antes.get(p['pid'])
        p['delta'] = (p['unit'] - p['antes']) if p['antes'] else None
        p['antes_rs'] = ant_rs.get(p['pid'], 0.0)
        p['delta_rs'] = ((p['rs'] - p['antes_rs']) if p['antes_rs'] else None)
        p['eh_outros'] = (p['pid'] == PID_OUTROS)
        if p['eh_outros']:
            # Outros junta ARLA (granel, em litro) com lata de oleo (em
            # unidade). Um "preco medio" ai seria media de coisas diferentes,
            # como no card TODOS -- some real e litro, nao preco.
            p['unit'] = p['menor'] = p['maior'] = None
            p['antes'] = p['delta'] = None
        p['dia_a_dia'] = [{'dia': d, 'litros': v[0], 'rs': v[1],
                           'unit': _preco(v[1], v[0])}
                          for d, v in sorted(p['dias'].items())]
        p['lista'] = sorted(
            ({'nome': k, 'litros': v[0], 'rs': v[1]}
             for k, v in p['variantes'].items()), key=lambda v: -v['rs'])
        del p['dias'], p['variantes']
        saida.append(p)
    # O Outros vai para o fim da fila mesmo quando fatura mais que a gasolina:
    # ele nao e um combustivel, e a fila e dos combustiveis.
    saida.sort(key=lambda p: (p['eh_outros'], -p['rs']))

    tot = {
        'litros': sum(p['litros'] for p in saida),
        'rs': total_rs,
        'notas': len(set(x['nota'] for x in linhas)),
        'itens': len(linhas),
        'produtos': len([p for p in saida if not p['eh_outros']]),
        'acrescimo': sum(p['acrescimo'] for p in saida),
    }
    tot['unit'] = _preco(tot['rs'], tot['litros'])

    # ---- o card que soma tudo ----
    # Sem preco medio, de proposito: media entre S-10 a R$ 6,37 e etanol a
    # R$ 3,37 nao e preco de nada -- ela sobe quando se vende mais diesel, e
    # nao quando o combustivel encarece. Entre produtos diferentes so somam
    # litro, real e nota.
    dias_g = defaultdict(lambda: [0.0, 0.0])
    for x in linhas:
        d = dias_g[x['dia']]
        d[0] += x['litros']
        d[1] += x['rs']
    combust = [p for p in saida if not p['eh_outros']]
    geral = {
        'litros': tot['litros'], 'rs': tot['rs'], 'notas': tot['notas'],
        'produtos': len(combust),
        'clientes': len(set(x['doc'] for x in linhas if x['doc'])),
        'vendedores': len(set(x['vendedor'] for x in linhas if x['vendedor'])),
        'dia_a_dia': [{'dia': d, 'litros': v[0], 'rs': v[1]}
                      for d, v in sorted(dias_g.items())],
        'antes_rs': antes_tot['rs'], 'antes_litros': antes_tot['litros'],
        'maior': (combust[0]['nome'] if combust else '—'),
        'maior_fatia': (combust[0]['fatia'] if combust else 0.0),
        'canceladas': canceladas,
        'acrescimo': tot['acrescimo'],
    }
    geral['delta_rs'] = ((geral['rs'] - geral['antes_rs'])
                         if geral['antes_rs'] else None)

    # ---- daqui para baixo, o produto escolhido manda ----
    foco = [x for x in linhas if x['pid'] == pid] if pid else linhas

    dias_f = defaultdict(lambda: [0.0, 0.0, set()])
    for x in foco:
        d = dias_f[x['dia']]
        d[0] += x['litros']
        d[1] += x['rs']
        d[2].add(x['nota'])
    dias = [{'dia': d, 'litros': v[0], 'rs': v[1], 'notas': len(v[2]),
             'unit': _preco(v[1], v[0])}
            for d, v in sorted(dias_f.items(), reverse=True)]

    return {
        'produtos': saida, 'total': tot, 'geral': geral,
        'recortes': _recortes(foco), 'dias': dias,
        'ini_ant': ini_ant, 'fim_ant': fim_ant,
    }
