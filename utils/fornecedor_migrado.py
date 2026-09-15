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
