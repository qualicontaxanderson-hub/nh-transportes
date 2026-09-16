# -*- coding: utf-8 -*-
"""Compras e pagamentos de fornecedor a partir das telas NOVAS.

O relatório antigo (/relatorios/conf_fornecedores) tira a dívida do PEDIDO, que
é digitado por gente. Aqui cada número tem uma fonte só, e é a fonte da tela
que o usuário opera:

    compra      dfe_documentos + dfe_itens    a nota que a SEFAZ entregou
    descarga    descarga_nota -> descargas_pendentes
                                              a régua do ELS, no dia em que
                                              desceu, com o vínculo que o
                                              usuário fez em /estoque
    pagamento   dfe_pagamento_nota -> bank_transactions -> bank_accounts
                                              a linha do extrato que o usuário
                                              amarrou àquela nota, e o banco
                                              de onde o dinheiro saiu

As três respondem, por nota, as perguntas do Anderson: quando comprei, quando
desceu, de quem, a quanto o litro, quantos litros, quanto deu, quando paguei e
por qual banco.

DUAS ARMADILHAS, as duas aprendidas em conf_fornecedores_dfe:

  1. Matriz e filial. Casar pelo CNPJ inteiro separa o mesmo fornecedor em
     dois; a comparação é pela RAIZ (8 primeiros dígitos).
  2. Raiz diferente, mesmo grupo. Paga-se a RODOBRAS COMERCIALIZADORA e a nota
     vem da DISTRIBUIDORA RODOBRAS (raízes 57.370.381 e 33.777.842).
     `fornecedor_grupo_raiz` aponta cada raiz do grupo para um fornecedor
     TITULAR, e aqui o grupo inteiro vira um quadro só.

O NOME que aparece na tela é o do CADASTRO (nome_fantasia, senão razão
social): o emitente do XML vem como "TEMAPE TERMINAIS MARITIMOS DE PERNAMBUCO
S/A" e na casa ele é a PETROVIA. Sem cadastro, fica o nome do XML.

O que NÃO entra: CT-e (é frete, tem a sua própria tela), nota cancelada e
resumo sem XML completo. O valor da nota é o TOTAL do documento, com o
ICMS-ST — é o que sai do caixa; a linha do produto vem ao lado, para a
diferença aparecer em vez de se esconder.
"""
from collections import defaultdict
from datetime import date, timedelta

# So digito, dos dois lados, antes de comparar CNPJ.
_LIMPA_CNPJ = ("REPLACE(REPLACE(REPLACE(REPLACE(f.cnpj,'.',''),'/',''),'-',''),' ','')")


def _f(v):
    """Decimal/None do banco vira float — Decimal com float estoura no meio."""
    return float(v) if v is not None else 0.0


def _dia(v):
    """DATE/DATETIME do banco vira date (o driver devolve os dois)."""
    return v.date() if hasattr(v, 'date') else v


def _nomes(cur):
    """Dois mapas do cadastro: raiz -> nome, e raiz -> chave do grupo.

    O nome sai em consulta separada de propósito: um JOIN por CNPJ com
    `fornecedores` duplica a nota quando a mesma empresa está cadastrada duas
    vezes, e uma nota contada em dobro estragaria o total.
    """
    cur.execute(
        "SELECT f.id, LEFT(LPAD(%s,14,'0'),8) AS raiz, f.razao_social, "
        "       f.nome_fantasia "
        "  FROM fornecedores f "
        " WHERE f.cnpj IS NOT NULL AND f.cnpj <> ''" % _LIMPA_CNPJ)
    por_raiz, por_id = {}, {}
    for r in cur.fetchall():
        nome = (r['nome_fantasia'] or '').strip() or (r['razao_social'] or '').strip()
        if not nome:
            continue
        por_id[r['id']] = nome
        # MIN(id) elege um dono da raiz: matriz e filial cadastradas nao podem
        # dar dois nomes para a mesma raiz.
        if r['raiz'] not in por_raiz or r['id'] < por_raiz[r['raiz']][0]:
            por_raiz[r['raiz']] = (r['id'], nome)
    por_raiz = {k: v[1] for k, v in por_raiz.items()}

    # o grupo: cada raiz aponta para o fornecedor titular
    grupo = {}
    try:
        cur.execute("SELECT raiz, titular_id FROM fornecedor_grupo_raiz")
        for r in cur.fetchall():
            grupo[r['raiz']] = r['titular_id']
    except Exception:
        pass  # a tabela nasce em conf_fornecedores_dfe; sem ela, sem grupo
    return por_raiz, por_id, grupo


_MES_PT = ('JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
           'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ')


def meses(cur, hoje=None):
    """A regua de meses que TEM nota de compra, do mais antigo ao mais novo.

    Serve a fila de pilulas do topo: um clique troca o periodo inteiro. Sai do
    banco, e nao de um range fixo, porque a captura da SEFAZ comeca em
    07/07/2026 -- inventar janeiro daria uma pilula que so sabe dizer "nao tem
    nada". O mes corrente para HOJE, nao no dia 30: o periodo tem que ser o
    mesmo que a tela abre sozinha.
    """
    hoje = hoje or date.today()
    cur.execute(
        "SELECT DATE_FORMAT(d.dh_emissao,'%Y-%m') AS mes, COUNT(*) AS notas "
        "  FROM dfe_documentos d "
        " WHERE d.tipo = 'NFe' AND d.resumo = 0 "
        "   AND (d.situacao IS NULL OR UPPER(d.situacao) = 'AUTORIZADO') "
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


def apurar(cur, ini, fim, chave=None):
    """As compras do período, agrupadas por fornecedor (grupo).

    `chave` filtra um fornecedor só — é a mesma chave que sai em cada grupo.
    Devolve {'total': {...}, 'grupos': [...]}, os grupos do maior para o menor
    em reais de nota. SOMENTE LEITURA (recebe cursor).
    """
    cur.execute(
        """SELECT d.id, d.numero, d.serie, DATE(d.dh_emissao) AS dia,
                  d.emit_nome, d.emit_cnpj, d.valor_total, d.entrada_manual
             FROM dfe_documentos d
            WHERE d.tipo = 'NFe' AND d.resumo = 0
              AND (d.situacao IS NULL OR UPPER(d.situacao) = 'AUTORIZADO')
              AND DATE(d.dh_emissao) BETWEEN %s AND %s
            ORDER BY d.dh_emissao, d.id""", (ini, fim))
    docs = cur.fetchall()

    vazio = {'total': {'notas': 0, 'litros': 0.0, 'nota_rs': 0.0,
                       'itens_rs': 0.0, 'st': 0.0, 'pago': 0.0, 'saldo': 0.0,
                       'desceu': 0.0, 'sem_pagar': 0, 'sem_descer': 0,
                       'fornecedores': 0, 'unit': 0.0},
             'grupos': []}
    if not docs:
        return vazio

    ids = [d['id'] for d in docs]
    ph = ','.join(['%s'] * len(ids))

    cur.execute(
        """SELECT i.documento_id, i.n_item, i.produto_id, i.categoria,
                  i.produto_xml, i.unidade, i.quantidade, i.valor_unitario,
                  i.valor_total, p.nome AS produto_nome
             FROM dfe_itens i
             LEFT JOIN produto p ON p.id = i.produto_id
            WHERE i.documento_id IN (%s)
            ORDER BY i.documento_id, i.n_item""" % ph, ids)
    itens = cur.fetchall()

    cur.execute(
        """SELECT v.documento_id, v.litros, dp.data_descarga, dp.tanque
             FROM descarga_nota v
             JOIN descargas_pendentes dp ON dp.id = v.descarga_id
            WHERE v.documento_id IN (%s)
            ORDER BY dp.data_descarga, v.id""" % ph, ids)
    descargas = cur.fetchall()

    cur.execute(
        """SELECT pn.documento_id, pn.valor, bt.data_transacao, bt.descricao,
                  ba.banco_nome, ba.apelido
             FROM dfe_pagamento_nota pn
             JOIN bank_transactions bt ON bt.id = pn.transacao_id
             LEFT JOIN bank_accounts ba ON ba.id = bt.account_id
            WHERE pn.documento_id IN (%s)
            ORDER BY bt.data_transacao, pn.id""" % ph, ids)
    pagamentos = cur.fetchall()

    nome_raiz, nome_id, grupo_de = _nomes(cur)

    por_doc_item = defaultdict(list)
    for r in itens:
        por_doc_item[r['documento_id']].append(r)
    por_doc_desc = defaultdict(list)
    for r in descargas:
        por_doc_desc[r['documento_id']].append(r)
    por_doc_pag = defaultdict(list)
    for r in pagamentos:
        por_doc_pag[r['documento_id']].append(r)

    grupos = {}
    for d in docs:
        raiz = (d['emit_cnpj'] or '').zfill(14)[:8]
        titular = grupo_de.get(raiz)
        ch = ('f%s' % titular) if titular else ('r%s' % raiz)
        if chave and ch != chave:
            continue

        its = por_doc_item.get(d['id'], [])
        litros = sum(_f(i['quantidade']) for i in its
                     if (i['categoria'] or '') == 'combustivel')
        itens_rs = sum(_f(i['valor_total']) for i in its)
        total_nota = _f(d['valor_total'])
        pags = [{'dia': _dia(p['data_transacao']), 'valor': _f(p['valor']),
                 'banco': (p['apelido'] or p['banco_nome'] or '—'),
                 'descricao': (p['descricao'] or '')[:80]}
                for p in por_doc_pag.get(d['id'], [])]
        descs = [{'dia': _dia(x['data_descarga']), 'litros': _f(x['litros']),
                  'tanque': x['tanque']}
                 for x in por_doc_desc.get(d['id'], [])]
        pago = sum(p['valor'] for p in pags)

        # O produto e a unidade: litro no combustivel, a unidade da nota no
        # resto. "0 L" numa botina e pior do que nao mostrar nada.
        nomes_prod = [(i['produto_nome'] or (i['produto_xml'] or '')[:22])
                      for i in its]
        nota = {
            'id': d['id'], 'numero': d['numero'], 'serie': d['serie'],
            'dia': _dia(d['dia']), 'emit_nome': d['emit_nome'],
            'produto': ' + '.join(dict.fromkeys(nomes_prod)) or '—',
            'pids': [i['produto_id'] for i in its if i['produto_id']],
            'itens': len(its),
            'litros': litros,
            'qtd': litros if litros else sum(_f(i['quantidade']) for i in its),
            'unidade': 'L' if litros else ((its[0]['unidade'] or '').upper()
                                           if its else ''),
            'unit': (itens_rs / litros) if litros else (
                _f(its[0]['valor_unitario']) if its else 0.0),
            'itens_rs': itens_rs, 'total_nota': total_nota,
            'st': total_nota - itens_rs,
            'descargas': descs, 'desceu': sum(x['litros'] for x in descs),
            'pagamentos': pags, 'pago': pago, 'saldo': total_nota - pago,
            'manual': bool(d['entrada_manual']),
        }

        g = grupos.get(ch)
        if g is None:
            g = grupos[ch] = {
                'chave': ch, 'raiz': raiz,
                'nome': (nome_id.get(titular) or nome_raiz.get(raiz)
                         or (d['emit_nome'] or '—')),
                'emit_nome': d['emit_nome'], 'grupo': bool(titular),
                'raizes': set(), 'notas': [], 'litros': 0.0, 'itens_rs': 0.0,
                'nota_rs': 0.0, 'pago': 0.0, 'desceu': 0.0, 'com_desc': 0,
                'bancos': [], 'litros_pid': defaultdict(float),
            }
        g['raizes'].add(raiz)
        g['notas'].append(nota)
        g['litros'] += litros
        g['itens_rs'] += itens_rs
        g['nota_rs'] += total_nota
        g['pago'] += pago
        g['desceu'] += nota['desceu']
        g['com_desc'] += 1 if descs else 0
        for p in pags:
            if p['banco'] not in g['bancos']:
                g['bancos'].append(p['banco'])
        for i in its:
            if i['produto_id']:
                g['litros_pid'][i['produto_id']] += _f(i['quantidade'])

    for g in grupos.values():
        g['saldo'] = g['nota_rs'] - g['pago']
        g['st'] = g['nota_rs'] - g['itens_rs']
        g['unit'] = (g['itens_rs'] / g['litros']) if g['litros'] else 0.0
        g['sem_pagar'] = sum(1 for n in g['notas'] if not n['pagamentos'])
        g['sem_descer'] = sum(1 for n in g['notas'] if not n['descargas'])
        # A cor nunca decora: ela diz qual combustivel MAIS veio deste
        # fornecedor, em litros. Sem produto classificado, nao tem cor.
        lp = g['litros_pid']
        g['pid'] = max(lp, key=lp.get) if lp else None
        g['raizes'] = sorted(g['raizes'])
        del g['litros_pid']

    lista = sorted(grupos.values(), key=lambda g: -g['nota_rs'])

    tot = {
        'notas': sum(len(g['notas']) for g in lista),
        'litros': sum(g['litros'] for g in lista),
        'nota_rs': sum(g['nota_rs'] for g in lista),
        'itens_rs': sum(g['itens_rs'] for g in lista),
        'pago': sum(g['pago'] for g in lista),
        'desceu': sum(g['desceu'] for g in lista),
        'sem_pagar': sum(g['sem_pagar'] for g in lista),
        'sem_descer': sum(g['sem_descer'] for g in lista),
        'fornecedores': len(lista),
    }
    # de quais bancos o dinheiro saiu, na ordem em que apareceram
    tot['bancos'] = []
    for g in lista:
        for b in g['bancos']:
            if b not in tot['bancos']:
                tot['bancos'].append(b)
    tot['saldo'] = tot['nota_rs'] - tot['pago']
    tot['st'] = tot['nota_rs'] - tot['itens_rs']
    tot['unit'] = (tot['itens_rs'] / tot['litros']) if tot['litros'] else 0.0
    return {'total': tot, 'grupos': lista}


# ===========================================================================
# O MESMO período, virado: quanto se comprou de cada COMBUSTÍVEL, a que preço,
# e de quem. É o corte que responde "de quem eu compro o S-10 mais barato".
#
# Aqui entra só o item de nota que JÁ TEM PRODUTO CLASSIFICADO em
# /dfe/compras -> Classificar. Não é limitação da conta: é o que existe. Por
# isso `sem_classificar` volta junto e a tela avisa — um relatório que esconde
# 700 mil litros não classificados mentiria por omissão.
# ===========================================================================

# O item de combustivel que interessa aqui: nota autorizada, nao resumo, nao
# CT-e, e produto ja classificado. As datas ficam de fora do trecho porque uma
# das consultas anda no periodo ANTERIOR.
_SO_COMB = """
      FROM dfe_itens i
      JOIN dfe_documentos d ON d.id = i.documento_id
     WHERE d.tipo = 'NFe' AND d.resumo = 0
       AND (d.situacao IS NULL OR UPPER(d.situacao) = 'AUTORIZADO')
       AND i.categoria = 'combustivel' AND i.produto_id IS NOT NULL
       AND DATE(d.dh_emissao) BETWEEN %s AND %s
"""


def por_produto(cur, ini, fim, chave=None):
    """Compras do período por combustível.

    Devolve {'produtos': [...], 'total': {...}, 'sem_classificar': {...},
    'notas': [...]} -- `notas` e a relacao nota a nota, com a data da
    compra e a(s) data(s) de descarga, da mais nova para a mais velha.
    Cada produto traz os litros, o preço médio, o menor e o maior preço, o
    preço dia a dia (para a linha do tempo), a variação contra o período
    ANTERIOR de mesmo tamanho, e de quais fornecedores ele veio — ordenados do
    mais barato para o mais caro, que é a pergunta que a tela responde.

    `chave` filtra um fornecedor só, a mesma chave que sai de apurar().
    SOMENTE LEITURA (recebe cursor).
    """
    nome_raiz, nome_id, grupo_de = _nomes(cur)

    def _ch(cnpj):
        raiz = (cnpj or '').zfill(14)[:8]
        titular = grupo_de.get(raiz)
        return (('f%s' % titular) if titular else ('r%s' % raiz)), raiz, titular

    # ---- o item, um por um: e daqui que sai todo o resto ----
    cur.execute("""
        SELECT d.id AS doc, DATE(d.dh_emissao) AS dia, d.emit_cnpj, d.emit_nome,
               i.produto_id AS pid, p.nome AS produto,
               i.quantidade, i.valor_unitario, i.valor_total
          FROM dfe_itens i
          JOIN dfe_documentos d ON d.id = i.documento_id
          LEFT JOIN produto p ON p.id = i.produto_id
         WHERE d.tipo = 'NFe' AND d.resumo = 0
           AND (d.situacao IS NULL OR UPPER(d.situacao) = 'AUTORIZADO')
           AND i.categoria = 'combustivel' AND i.produto_id IS NOT NULL
           AND DATE(d.dh_emissao) BETWEEN %s AND %s
         ORDER BY d.dh_emissao, d.id, i.n_item""", (ini, fim))
    linhas = []
    for r in cur.fetchall():
        ch, raiz, titular = _ch(r['emit_cnpj'])
        if chave and ch != chave:
            continue
        linhas.append({
            'doc': r['doc'], 'dia': _dia(r['dia']), 'pid': r['pid'],
            'produto': r['produto'] or ('Produto %s' % r['pid']),
            'chave': ch, 'raiz': raiz,
            'nome': (nome_id.get(titular) or nome_raiz.get(raiz)
                     or (r['emit_nome'] or '—')),
            'litros': _f(r['quantidade']), 'unit': _f(r['valor_unitario']),
            'rs': _f(r['valor_total']),
        })

    # ---- o periodo ANTERIOR, do mesmo tamanho, so para o preco ter com o que
    #      se comparar: um preco medio sozinho nao diz se subiu ----
    dias_periodo = (fim - ini).days + 1
    ini_ant = ini - timedelta(days=dias_periodo)
    fim_ant = ini - timedelta(days=1)
    cur.execute("SELECT i.produto_id AS pid, SUM(i.quantidade) AS litros, "
                "       SUM(i.valor_total) AS rs "
                + _SO_COMB + " GROUP BY i.produto_id", (ini_ant, fim_ant))
    antes, antes_tot = {}, {'litros': 0.0, 'rs': 0.0}
    for r in cur.fetchall():
        litros, rs = _f(r['litros']), _f(r['rs'])
        antes_tot['litros'] += litros
        antes_tot['rs'] += rs
        if litros:
            antes[r['pid']] = rs / litros

    # ---- o que fica de fora: combustivel sem produto classificado ----
    cur.execute("""
        SELECT DATE_FORMAT(d.dh_emissao, '%Y-%m') AS mes, COUNT(*) AS itens,
               SUM(i.quantidade) AS litros
          FROM dfe_itens i
          JOIN dfe_documentos d ON d.id = i.documento_id
         WHERE d.tipo = 'NFe' AND d.resumo = 0
           AND (d.situacao IS NULL OR UPPER(d.situacao) = 'AUTORIZADO')
           AND i.categoria = 'combustivel' AND i.produto_id IS NULL
         GROUP BY mes ORDER BY mes""")
    meses = [{'mes': r['mes'], 'itens': int(r['itens'] or 0),
              'litros': _f(r['litros'])} for r in cur.fetchall()]
    sem = {'meses': meses,
           'itens': sum(m['itens'] for m in meses),
           'litros': sum(m['litros'] for m in meses)}

    # ---- a relacao, nota por nota: quando comprei e quando desceu -------
    # O card responde o total; aqui responde a linha do tempo. A DESCARGA e do
    # documento inteiro (a regua do ELS amarra a nota, nao o item), entao numa
    # nota com dois produtos a mesma data aparece nos dois -- e a verdade do
    # vinculo, nao um rateio inventado.
    docs_ids = sorted(set(x['doc'] for x in linhas))
    numeros, desc_doc = {}, defaultdict(list)
    if docs_ids:
        ph = ','.join(['%s'] * len(docs_ids))
        cur.execute("SELECT id, numero FROM dfe_documentos WHERE id IN (%s)"
                    % ph, docs_ids)
        numeros = {r['id']: r['numero'] for r in cur.fetchall()}
        cur.execute(
            """SELECT v.documento_id, v.litros, dp.data_descarga, dp.tanque
                 FROM descarga_nota v
                 JOIN descargas_pendentes dp ON dp.id = v.descarga_id
                WHERE v.documento_id IN (%s)
                ORDER BY dp.data_descarga, v.id""" % ph, docs_ids)
        for r in cur.fetchall():
            desc_doc[r['documento_id']].append(
                {'dia': _dia(r['data_descarga']), 'litros': _f(r['litros']),
                 'tanque': r['tanque']})

    # uma linha por NOTA e PRODUTO: duas linhas do mesmo S-10 na mesma nota sao
    # a mesma compra, e separadas so fariam a relacao parecer o dobro.
    junta = {}
    for x in linhas:
        k = (x['doc'], x['pid'])
        n = junta.get(k)
        if n is None:
            n = junta[k] = {
                'doc': x['doc'], 'pid': x['pid'], 'produto': x['produto'],
                'dia': x['dia'], 'numero': numeros.get(x['doc']),
                'chave': x['chave'], 'nome': x['nome'],
                'descargas': desc_doc.get(x['doc'], []),
                'litros': 0.0, 'rs': 0.0,
            }
        n['litros'] += x['litros']
        n['rs'] += x['rs']
    relacao = []
    for n in junta.values():
        n['unit'] = (n['rs'] / n['litros']) if n['litros'] else 0.0
        n['desceu'] = sum(d['litros'] for d in n['descargas'])
        relacao.append(n)
    # a mais nova em cima: o preco que interessa primeiro e o da ultima compra
    relacao.sort(key=lambda n: (n['dia'], n['doc']), reverse=True)

    # ---- monta por produto ----
    prods = {}
    for x in linhas:
        p = prods.get(x['pid'])
        if p is None:
            p = prods[x['pid']] = {
                'pid': x['pid'], 'nome': x['produto'], 'litros': 0.0,
                'rs': 0.0, 'docs': set(), 'menor': None, 'maior': None,
                'dias': defaultdict(lambda: [0.0, 0.0]),   # dia -> [litros, rs]
                'forn': {},
            }
        p['litros'] += x['litros']
        p['rs'] += x['rs']
        p['docs'].add(x['doc'])
        p['menor'] = x['unit'] if p['menor'] is None else min(p['menor'], x['unit'])
        p['maior'] = x['unit'] if p['maior'] is None else max(p['maior'], x['unit'])
        d = p['dias'][x['dia']]
        d[0] += x['litros']
        d[1] += x['rs']
        f = p['forn'].get(x['chave'])
        if f is None:
            f = p['forn'][x['chave']] = {'chave': x['chave'], 'nome': x['nome'],
                                         'litros': 0.0, 'rs': 0.0, 'docs': set()}
        f['litros'] += x['litros']
        f['rs'] += x['rs']
        f['docs'].add(x['doc'])

    total_rs = sum(p['rs'] for p in prods.values())
    saida = []
    for p in prods.values():
        p['notas'] = len(p['docs'])
        p['unit'] = (p['rs'] / p['litros']) if p['litros'] else 0.0
        p['fatia'] = (p['rs'] / total_rs * 100) if total_rs else 0.0
        p['antes'] = antes.get(p['pid'])
        p['delta'] = (p['unit'] - p['antes']) if p['antes'] else None
        p['dia_a_dia'] = [{'dia': d, 'litros': v[0],
                           'unit': (v[1] / v[0]) if v[0] else 0.0}
                          for d, v in sorted(p['dias'].items())]
        fs = sorted(p['forn'].values(),
                    key=lambda f: (f['rs'] / f['litros']) if f['litros'] else 0.0)
        melhor = (fs[0]['rs'] / fs[0]['litros']) if fs and fs[0]['litros'] else 0.0
        for f in fs:
            f['notas'] = len(f['docs'])
            f['unit'] = (f['rs'] / f['litros']) if f['litros'] else 0.0
            # Quanto custou NAO ter comprado do mais barato, naqueles litros.
            # Nao e acusacao -- frete e prazo nao estao aqui. E uma pergunta.
            f['acima'] = f['unit'] - melhor
            f['acima_rs'] = f['acima'] * f['litros']
            del f['docs']
        p['fornecedores'] = fs
        p['forns'] = len(fs)
        del p['docs'], p['dias'], p['forn']
        saida.append(p)

    saida.sort(key=lambda p: -p['rs'])
    tot = {
        'litros': sum(p['litros'] for p in saida),
        'rs': total_rs,
        'notas': len(set(x['doc'] for x in linhas)),
        'produtos': len(saida),
    }
    tot['unit'] = (tot['rs'] / tot['litros']) if tot['litros'] else 0.0

    # ---- o card que soma tudo -------------------------------------------
    # De proposito NAO tem preco medio: media entre S-10 a R$ 6,11 e etanol a
    # R$ 2,87 nao e preco de nada -- ela sobe quando se compra mais diesel, e
    # nao quando o combustivel encarece. O que soma entre produtos diferentes
    # e litro, real e nota; e e so isso que este card mostra.
    dias_g = defaultdict(lambda: [0.0, 0.0])
    for x in linhas:
        d = dias_g[x['dia']]
        d[0] += x['litros']
        d[1] += x['rs']
    geral = {
        'litros': tot['litros'], 'rs': tot['rs'], 'notas': tot['notas'],
        'produtos': len(saida),
        'fornecedores': len(set(x['chave'] for x in linhas)),
        'dia_a_dia': [{'dia': d, 'litros': v[0], 'rs': v[1]}
                      for d, v in sorted(dias_g.items())],
        'antes_rs': antes_tot['rs'], 'antes_litros': antes_tot['litros'],
        'maior': (saida[0]['nome'] if saida else '-'),
        'maior_fatia': (saida[0]['fatia'] if saida else 0.0),
    }
    # a comparacao aqui e de QUANTO se comprou, nao de preco: o preco de uma
    # cesta que muda de composicao nao diz se subiu.
    geral['delta_rs'] = ((geral['rs'] - geral['antes_rs'])
                         if geral['antes_rs'] else None)

    return {'produtos': saida, 'total': tot, 'sem_classificar': sem,
            'notas': relacao, 'geral': geral,
            'ini_ant': ini_ant, 'fim_ant': fim_ant}
