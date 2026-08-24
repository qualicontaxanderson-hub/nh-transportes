"""PED/FRETE - NOVO — Fase 1: SOMENTE LEITURA.

Porta nova pra enxergar a carga do jeito que ela existe na estrada: o caminhao
carregado, os postos dentro dele e quanto cada um deve. Nao grava nada, nao
altera nada — le `fretes`, `pedidos`, `veiculo_compartimentos`,
`conjuntos_veiculos` e `cobrancas` e monta a leitura.

Por que a tela existe
---------------------
Hoje a carga fisica de um caminhao aparece fatiada em varios pedidos, porque
por muito tempo cobrar UM cliente sozinho exigia arranca-lo pra pedido proprio.
Resultado: ninguem consegue olhar e responder "o que esse caminhao esta levando
e ainda cabe alguma coisa?". Esta tela junta de volta pela chave fisica —
data + veiculo + motorista — sem tocar nos dados.

Tres modos, uma tela:
  dia      — todos os caminhoes do dia (a pergunta frequente)
  caminhao — a linha do tempo de um caminhao (a pergunta ocasional)
  cobrar   — por cliente, atravessando cargas (o que nenhum dos dois resolve)

Fase 2 (nao esta aqui) e emitir a cobranca de dentro desta tela. A tabela de
vinculo boleto<->fretes ja existe e ja e usada: `cobrancas_freites`.
"""

import logging
from datetime import date, timedelta

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from utils.db import get_db_connection
from utils.fuso import hoje_brasilia

bp = Blueprint('ped_frete_novo', __name__)

# Cor do produto que ficou de viagem anterior — cinza, fora da paleta dos
# postos, pra nao ser confundido com carga do dia.
_COR_BORDO = '#5a6472'

# Quantos dias pra tras vale perguntar "isso ficou no caminhao?". Alem disso e
# quase certo que a descarga so nao foi registrada.
_DIAS_BORDO = 7

_tabela_pronta = False

# strftime('%A') devolve o dia da semana no idioma do servidor — que roda em
# ingles. Como a tela e pra Monica ler de relance ("sexta"), a lista vem daqui.
_SEMANA = ('segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo')
_SEMANA_CURTA = ('seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom')


def _semana(d, curta=False):
    if not d:
        return ''
    return (_SEMANA_CURTA if curta else _SEMANA)[d.weekday()]

# Cores dos postos dentro da carga. O indice vem da ordem de litros na viagem,
# entao o maior carregamento fica sempre com a mesma cor no topo da legenda.
_CORES = ['#1D63A5', '#7a6bab', '#17963C', '#c98a2b', '#a32d2d', '#0f7d8c',
          '#8a5a00', '#5c6bc0']

# Boletos nesse estado nao contam como cobranca viva.
_COB_MORTA = ('cancelado',)

# Um frete pode estar coberto de dois jeitos: por uma cobranca que aponta
# direto pra ele (`cobrancas.frete_id`) ou por um boleto agrupado, ligado pela
# tabela `cobrancas_freites`. Hoje 121 dos 129 boletos agrupados usam o
# vinculo, e a tela de Fretes ja decide "faturado" exatamente assim — esta
# subquery existe pra as duas telas responderem a mesma coisa.
#
# A flag `fretes.boleto_emitido` NAO serve como verdade: 33 fretes a tem
# ligada com o boleto cancelado, e 10 fretes com boleto vivo estao com ela
# desligada. Ela e sinal secundario, nunca o criterio.
_COBERTURA = """
    LEFT JOIN (
        SELECT x.frete_id,
               COUNT(*)                       AS n,
               MAX(LOWER(x.status) = 'pago')  AS pago
          FROM (
                SELECT cb.frete_id, cb.status
                  FROM cobrancas cb
                 WHERE cb.frete_id IS NOT NULL
                   AND (cb.status IS NULL OR cb.status <> 'cancelado')
                UNION ALL
                SELECT cf.frete_id, cb.status
                  FROM cobrancas_freites cf
                  JOIN cobrancas cb ON cb.id = cf.cobranca_id
                 WHERE (cb.status IS NULL OR cb.status <> 'cancelado')
               ) x
         GROUP BY x.frete_id
    ) cob ON cob.frete_id = f.id
"""


def _f(v):
    """float() que nunca explode — o banco devolve Decimal e None."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _ensure_tabela():
    """Cria as duas tabelas proprias desta tela. Nada mais e escrito.

    `carga_fechada`     — "essa carga esta montada, o caminhao sai com ela".
    `frete_saldo_bordo` — "esta mercadoria de viagem anterior estava a bordo
                           durante esta carga, e por isso ela nao encheu".

    Nenhuma das duas encosta em `fretes`, `pedidos`, `cobrancas` ou estoque.
    Apagar as duas devolve a tela ao estado de so-leitura sem o sistema
    perder absolutamente nada.
    """
    global _tabela_pronta
    if _tabela_pronta:
        return
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS carga_fechada (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                data_frete    DATE NOT NULL,
                veiculo_id    INT NOT NULL,
                motorista_id  INT NOT NULL DEFAULT 0,
                fechada_por   VARCHAR(80) NULL,
                fechada_em    DATETIME NOT NULL,
                UNIQUE KEY uq_carga_fechada (data_frete, veiculo_id, motorista_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS frete_saldo_bordo (
                id                 INT AUTO_INCREMENT PRIMARY KEY,
                frete_id           INT NOT NULL,
                carga_data         DATE NOT NULL,
                carga_veiculo_id   INT NOT NULL,
                carga_motorista_id INT NOT NULL DEFAULT 0,
                litros             DECIMAL(12,3) NOT NULL DEFAULT 0,
                respondido_por     VARCHAR(80) NULL,
                respondido_em      DATETIME NOT NULL,
                UNIQUE KEY uq_bordo (frete_id, carga_data, carga_veiculo_id)
            )
        """)
        # A primeira versao da tabela so tinha (frete_id, a_bordo). Estas
        # colunas trazem a versao antiga pro formato novo sem perder linha.
        for alter in (
            "ALTER TABLE frete_saldo_bordo ADD COLUMN carga_data DATE NOT NULL",
            "ALTER TABLE frete_saldo_bordo ADD COLUMN carga_veiculo_id INT NOT NULL",
            "ALTER TABLE frete_saldo_bordo ADD COLUMN carga_motorista_id INT NOT NULL DEFAULT 0",
            "ALTER TABLE frete_saldo_bordo ADD COLUMN litros DECIMAL(12,3) NOT NULL DEFAULT 0",
            # Liga o item do pedido ao frete que nasceu com ele. Nula e ignorada
            # por todo o resto do sistema; existe pra que mover ou corrigir um
            # frete leve o item junto, em vez de adivinhar por nome/quantidade.
            "ALTER TABLE pedidos_itens ADD COLUMN frete_id INT NULL",
        ):
            try:
                cur.execute(alter)
                conn.commit()
            except Exception:
                conn.rollback()
        conn.commit()
        _tabela_pronta = True
    except Exception:
        logging.getLogger(__name__).exception(
            "[ped_frete_novo] nao deu pra preparar as tabelas da tela")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _chave(v):
    """A carga em tres campos: data + veiculo + motorista."""
    return (v['data'], v['veiculo_id'], v['motorista_id'] or 0)


def _fechadas(cur, dia):
    """{(data, veiculo, motorista): quem/quando} das cargas ja fechadas no dia."""
    cur.execute("""SELECT data_frete, veiculo_id, motorista_id, fechada_por, fechada_em
                     FROM carga_fechada WHERE data_frete = %s""", (dia,))
    return {(r['data_frete'], r['veiculo_id'], r['motorista_id']): r
            for r in cur.fetchall()}


def _bordo_registrado(cur, dia):
    """{(data, veiculo, motorista): [mercadoria...]} ja marcada como a bordo."""
    cur.execute("""
        SELECT sb.frete_id, sb.carga_data, sb.carga_veiculo_id, sb.carga_motorista_id,
               sb.litros, f.data_frete, pr.nome AS produto, cl.razao_social AS cliente
          FROM frete_saldo_bordo sb
          JOIN fretes f          ON f.id = sb.frete_id
          LEFT JOIN produto pr   ON pr.id = f.produto_id
          LEFT JOIN clientes cl  ON cl.id = f.clientes_id
         WHERE sb.carga_data = %s
         ORDER BY f.data_frete, f.id
    """, (dia,))
    fora = {}
    for r in cur.fetchall():
        r['litros'] = _f(r['litros'])
        ch = (r['carga_data'], r['carga_veiculo_id'], r['carga_motorista_id'])
        fora.setdefault(ch, []).append(r)
    return fora


def _candidatos_bordo(cur, dia, veiculo_ids):
    """{veiculo_id: [frete...]} — a mercadoria da carga ANTERIOR do caminhao.

    Quando a carga do dia nao encheu a carreta, e daqui que sai a resposta pra
    "o que ficou a bordo": os fretes da ultima viagem daquele mesmo caminhao.
    Qualquer cliente entra — nao so o Posto. A viagem tambem pode ter saido
    com boca vazia mesmo, e nesse caso a resposta e "nada ficou".
    """
    if not veiculo_ids:
        return {}
    marc = ','.join(['%s'] * len(veiculo_ids))
    cur.execute("""
        SELECT f.id, f.veiculos_id, f.data_frete,
               COALESCE(f.quantidade_manual, q.valor) AS litros,
               pr.nome AS produto, cl.razao_social AS cliente,
               m.nome AS motorista
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN produto pr    ON pr.id = f.produto_id
          LEFT JOIN clientes cl   ON cl.id = f.clientes_id
          LEFT JOIN motoristas m  ON m.id = f.motoristas_id
         WHERE f.veiculos_id IN (%s)
           AND f.data_frete < %%s
           AND f.data_frete >= %%s
         ORDER BY f.veiculos_id, f.data_frete DESC, f.id
    """ % marc, list(veiculo_ids) + [dia, dia - timedelta(days=_DIAS_BORDO)])

    por_veic = {}
    ultima = {}
    for r in cur.fetchall():
        vid = r['veiculos_id']
        # So a viagem mais recente antes do dia — o que ficou a bordo veio
        # dela, nao de uma carga de tres dias atras que ja rodou de novo.
        if vid not in ultima:
            ultima[vid] = r['data_frete']
        if r['data_frete'] != ultima[vid]:
            continue
        r['litros'] = _f(r['litros'])
        por_veic.setdefault(vid, []).append(r)
    return por_veic


def _capacidades(cur):
    """({veiculo_id: {'bocas': [...], 'total': L, 'carreta': placa}}, carreta_ids).

    As bocas estao cadastradas na CARRETA (parte='carreta'), e o pedido/frete
    aponta pro CAVALO. Quem liga os dois e `conjuntos_veiculos` — a coluna
    `veiculos.placa_carreta` esta vazia em todos os registros e nao serve.

    O segundo retorno sao os ids das carretas. Elas estao em `veiculos` e tem
    placa, mas nunca recebem frete (quem puxa e o cavalo), entao nao podem
    aparecer na lista de caminhoes nem virar o padrao do modo "por caminhao".
    """
    cur.execute("SELECT id, placa, caminhao FROM veiculos")
    veic = {r['id']: r for r in cur.fetchall()}

    cur.execute("SELECT veiculo_id, capacidade_l FROM veiculo_compartimentos "
                "ORDER BY veiculo_id, numero_ordem")
    por_veic = {}
    for r in cur.fetchall():
        por_veic.setdefault(r['veiculo_id'], []).append(_f(r['capacidade_l']))

    cur.execute("SELECT cavalo_id, carreta_id FROM conjuntos_veiculos WHERE ativo = 1")
    conj = {r['cavalo_id']: r['carreta_id'] for r in cur.fetchall()}
    carretas = set(conj.values())

    cap = {}
    for vid in veic:
        bocas = list(por_veic.get(vid) or [])
        carreta = None
        cid = conj.get(vid)
        if cid and por_veic.get(cid):
            bocas = list(por_veic[cid])
            carreta = (veic.get(cid) or {}).get('placa')
        cap[vid] = {'bocas': bocas, 'total': sum(bocas), 'carreta': carreta}
    return cap, carretas


def _combina_exato(disponiveis, alvo, menos_bocas=True):
    """Subconjunto das bocas livres que soma EXATAMENTE `alvo` litros.

    `disponiveis` e [(indice, capacidade_em_litros_inteiros)]. Devolve a lista
    de indices, ou None se nao houver combinacao exata.

    Existe porque o guloso erra num caso comum: 6.000 L numa carreta com bocas
    de 5 e 3 vira 5+3, desperdicando 2.000 L de uma boca que outro produto ia
    querer — quando 3+3 fecha certinho. Com no maximo ~10 bocas por carreta o
    numero de somas alcancaveis e pequeno, entao da pra procurar a exata.

    `menos_bocas` decide o desempate, e os dois lados sao necessarios:
      - menos: 10.000 L em 5/5/3/2/5/5/5 vira 5+5, e nao 5+3+2 (que queima
        tres bocas e deixa o proximo produto de 3.000 sem lugar);
      - mais:  15.000 L em 5/5/3/3/3/5/3/3/5 vira 3+3+3+3+3, guardando os
        quatro 5 inteiros pros dois produtos de 10.000 que vem atras.
    Nenhum dos dois ganha sempre — por isso `_encaixar` roda os dois.
    """
    melhor = {0: ()}
    for i, cap in disponiveis:
        if cap <= 0:
            continue
        # Dicionario separado: escrever direto em `melhor` durante a varredura
        # deixaria o mesmo compartimento ser usado duas vezes no mesmo caminho.
        novos = {}
        for s, caminho in melhor.items():
            ns = s + cap
            if ns > alvo:
                continue
            novo = caminho + (i,)
            atual = melhor.get(ns)
            if atual is not None and _ganha(len(atual), len(novo), menos_bocas):
                continue
            se_ja = novos.get(ns)
            if se_ja is None or not _ganha(len(se_ja), len(novo), menos_bocas):
                novos[ns] = novo
        melhor.update(novos)
    caminho = melhor.get(alvo)
    return list(caminho) if caminho else None


def _ganha(atual, novo, menos_bocas):
    """O caminho `atual` continua melhor que `novo`?"""
    return atual <= novo if menos_bocas else atual >= novo


def _tentativa(itens, bocas, maior_primeiro=True, menos_bocas=True, exato=True):
    """Uma distribuicao dos itens nas bocas, com uma estrategia fixa.

    Regra da estrada: uma boca nao mistura produto. Entao cada frete ocupa
    bocas inteiras enquanto der, e a sobra entra numa boca parcial.

    Para cada item tenta primeiro o encaixe EXATO — o conjunto de bocas livres
    que soma a quantidade certa. So quando nao existe combinacao exata cai no
    guloso: maior boca que ainda cabe, e o resto numa boca parcial.
    """
    livres = [{'cap': b, 'usado': 0.0, 'cor': None, 'cliente': None,
               'parcial': False} for b in bocas]
    sobrou = 0.0

    def _ocupa(b, it, usa):
        b['usado'] = usa
        b['cor'] = it['cor']
        b['cliente'] = it['cliente']
        b['parcial'] = usa < b['cap'] - 0.01

    ordenados = sorted(itens, key=lambda x: x['litros'], reverse=maior_primeiro)
    for it in ordenados:
        if exato:
            disp = [(i, int(round(b['cap']))) for i, b in enumerate(livres)
                    if b['cor'] is None]
            escolha = _combina_exato(disp, int(round(it['litros'])), menos_bocas)
            if escolha:
                for i in escolha:
                    _ocupa(livres[i], it, livres[i]['cap'])
                continue

        resta = it['litros']
        while resta > 0.01:
            # Maior boca livre que cabe inteira; se nenhuma cabe, a menor livre.
            cabe = [b for b in livres if b['cor'] is None and b['cap'] <= resta + 0.01]
            if cabe:
                alvo = max(cabe, key=lambda b: b['cap'])
            else:
                vazias = [b for b in livres if b['cor'] is None]
                if not vazias:
                    sobrou += resta
                    break
                alvo = min(vazias, key=lambda b: b['cap'])
            usa = min(alvo['cap'], resta)
            _ocupa(alvo, it, usa)
            resta -= usa
    return livres, sobrou


# (maior_primeiro, menos_bocas, tenta_exato) — a ordem importa: em empate fica
# a primeira, que e a que desenha o compartimento de forma mais natural.
_ESTRATEGIAS = (
    (True, True, True),
    (True, False, True),
    (False, True, True),
    (False, False, True),
    (True, True, False),
)


def _encaixar(itens, bocas):
    """Melhor distribuicao dos itens nas bocas entre algumas estrategias.

    Distribuir produtos em compartimentos e um problema de empacotamento:
    nenhuma regra simples acerta sempre. Duas falham de jeitos opostos —
    preferir menos bocas resolve a carreta 5/5/3/2/5/5/5 e quebra a
    5/5/3/3/3/5/3/3/5; preferir mais faz o contrario. Como sao poucas bocas e
    poucos itens, sai mais barato rodar as duas (e as variantes de ordem) e
    ficar com a que deixa menos produto sem lugar.

    Isso importa pra confianca na tela: dizer "1.000 L nao acharam boca" numa
    carga que cabe inteira e alarme falso, e alarme falso ensina a ignorar o
    aviso de verdade.

    Devolve (desenho, sobrou) onde desenho e uma lista por boca:
        {'cap': L, 'usado': L, 'cor': '#...', 'cliente': str, 'parcial': bool}
    e `sobrou` e o total em litros que nao coube em boca nenhuma.
    """
    melhor = None
    for maior, menos, exato in _ESTRATEGIAS:
        desenho, sobrou = _tentativa(itens, bocas, maior, menos, exato)
        parciais = sum(1 for b in desenho if b['parcial'])
        nota = (sobrou, parciais)
        if melhor is None or nota < melhor[0]:
            melhor = (nota, desenho, sobrou)
        if sobrou <= 0.01 and parciais == 0:
            break  # fechou redondo, nao ha o que melhorar
    return melhor[1], melhor[2]


def _fretes_do_periodo(cur, ini, fim, veiculo_id=None):
    """Fretes crus do periodo, ja com posto, produto, veiculo e cobranca.

    Sem GROUP BY de proposito: o banco roda com only_full_group_by e o
    agrupamento por viagem e feito em Python, onde a regra fica legivel.
    """
    sql = """
        SELECT f.id, f.data_frete, f.valor_total_frete, f.boleto_emitido,
               f.veiculos_id, f.motoristas_id, f.clientes_id,
               COALESCE(f.quantidade_manual, q.valor) AS litros,
               cl.razao_social AS cliente,
               pr.nome AS produto,
               v.placa, v.caminhao,
               m.nome AS motorista,
               p.numero AS pedido,
               fo.razao_social AS fornecedor,
               cl.cnpj AS cnpj, o.nome AS origem, ba.nome AS base,
               f.preco_produto_unitario AS preco_unit, f.total_nf_compra AS total_nf,
               f.fornecedores_id, f.produto_id, f.quantidade_id, f.origem_id,
               f.preco_por_litro, f.valor_cte, pi.base_id, pi.id AS item_id,
               COALESCE(cob.n, 0) AS cob_n, COALESCE(cob.pago, 0) AS cob_pago
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN clientes cl   ON cl.id = f.clientes_id
          LEFT JOIN produto pr    ON pr.id = f.produto_id
          LEFT JOIN veiculos v    ON v.id  = f.veiculos_id
          LEFT JOIN motoristas m  ON m.id  = f.motoristas_id
          LEFT JOIN pedidos p     ON p.id  = f.pedido_id
          LEFT JOIN fornecedores fo ON fo.id = f.fornecedores_id
          LEFT JOIN origens o     ON o.id  = f.origem_id
          LEFT JOIN pedidos_itens pi ON pi.frete_id = f.id
          LEFT JOIN bases ba      ON ba.id = pi.base_id
          """ + _COBERTURA + """
         WHERE f.data_frete >= %s AND f.data_frete <= %s
    """
    params = [ini, fim]
    if veiculo_id:
        sql += " AND f.veiculos_id = %s"
        params.append(veiculo_id)
    sql += " ORDER BY f.data_frete, f.veiculos_id, f.id"
    cur.execute(sql, params)
    return cur.fetchall()


def _estado_cobranca(fr):
    """zero | pago | emitido | falta — o que a etiqueta do posto vai dizer.

    `zero` e o Posto Novo Horizonte: viaja em quase toda carga com frete
    R$ 0,00 porque e da casa. Nao pode aparecer como "falta cobrar" nunca.

    O criterio e a cobertura (`_COBERTURA`), nunca `boleto_emitido` — ver a
    explicacao la em cima. Se dependesse da flag, um frete coberto por boleto
    agrupado apareceria como "falta cobrar" e daria pra emitir em duplicidade.
    """
    if _f(fr['valor_total_frete']) <= 0:
        return 'zero'
    if int(fr.get('cob_n') or 0) > 0:
        return 'pago' if int(fr.get('cob_pago') or 0) else 'emitido'
    return 'falta'


def _montar_viagens(fretes, cap):
    """Agrupa os fretes na chave fisica da carga: data + veiculo + motorista.

    Motorista entra na chave porque e o que separa duas viagens do mesmo
    caminhao no mesmo dia — foi o caso de 21/08, quando o RDT saiu com o
    Marcos e depois com o Wellington. Quando o mesmo motorista estoura a
    carreta, a tela avisa em vez de inventar uma segunda viagem.
    """
    viagens = {}
    for fr in fretes:
        ch = (fr['data_frete'], fr['veiculos_id'], fr['motoristas_id'])
        v = viagens.get(ch)
        if v is None:
            c = cap.get(fr['veiculos_id']) or {'bocas': [], 'total': 0.0, 'carreta': None}
            v = viagens[ch] = {
                'data': fr['data_frete'], 'veiculo_id': fr['veiculos_id'],
                'placa': fr['placa'] or '—', 'caminhao': fr['caminhao'] or '',
                'motorista_id': fr['motoristas_id'] or 0,
                'motorista': fr['motorista'] or '—',
                'bocas': c['bocas'], 'capacidade': c['total'], 'carreta': c['carreta'],
                'fretes': [], 'pedidos': [], 'postos': {},
                'litros': 0.0, 'a_cobrar': 0.0, 'emitido': 0.0,
            }
        fr['estado'] = _estado_cobranca(fr)
        fr['litros'] = _f(fr['litros'])
        fr['valor'] = _f(fr['valor_total_frete'])
        # Tudo que a tela usa em conta vira float AQUI. O banco devolve
        # Decimal, e Decimal/float levanta TypeError no meio do template —
        # que roda fora do try e derruba a pagina inteira em 500.
        fr['preco_unit'] = _f(fr.get('preco_unit'))
        fr['preco_por_litro'] = _f(fr.get('preco_por_litro'))
        fr['valor_cte'] = _f(fr.get('valor_cte'))
        fr['preco_cte_litro'] = (fr['valor_cte'] / fr['litros']) if fr['litros'] else 0.0
        v['fretes'].append(fr)
        v['litros'] += fr['litros']
        if fr['estado'] == 'falta':
            v['a_cobrar'] += fr['valor']
        elif fr['estado'] in ('emitido', 'pago'):
            v['emitido'] += fr['valor']
        if fr['pedido'] and fr['pedido'] not in v['pedidos']:
            v['pedidos'].append(fr['pedido'])

        nome = fr['cliente'] or '—'
        p = v['postos'].get(nome)
        if p is None:
            p = v['postos'][nome] = {'nome': nome, 'litros': 0.0, 'valor': 0.0,
                                     'fretes': [], 'estados': set()}
        p['litros'] += fr['litros']
        p['valor'] += fr['valor']
        p['fretes'].append(fr)
        p['estados'].add(fr['estado'])

    saida = []
    for v in viagens.values():
        postos = sorted(v['postos'].values(), key=lambda p: -p['litros'])
        for i, p in enumerate(postos):
            p['cor'] = _CORES[i % len(_CORES)]
            p['pct'] = round(100.0 * p['litros'] / v['litros'], 1) if v['litros'] else 0.0
            # A etiqueta do posto resume os fretes dele: se falta um, falta.
            e = p['estados']
            p['estado'] = ('falta' if 'falta' in e else
                           'zero' if e == {'zero'} else
                           'pago' if e <= {'pago', 'zero'} else 'emitido')
            for fr in p['fretes']:
                fr['cor'] = p['cor']
        v['postos'] = postos

        itens = [{'litros': fr['litros'], 'cor': fr['cor'],
                  'cliente': fr['cliente'] or '—'}
                 for fr in v['fretes'] if fr['litros'] > 0]
        v['desenho'], v['sem_boca'] = _encaixar(itens, v['bocas'])
        v['livre'] = max(0.0, v['capacidade'] - v['litros'])
        v['pct'] = round(100.0 * v['litros'] / v['capacidade'], 1) if v['capacidade'] else 0.0
        v['estoura'] = bool(v['capacidade']) and v['litros'] > v['capacidade'] + 0.01
        v['sem_cadastro'] = not v['capacidade']
        # Preenchidos de verdade por _aplicar_estado.
        v['bordo'] = []
        v['bordo_litros'] = 0.0
        v['ocupado'] = v['litros']
        v['fechada'] = False
        v['tem_espaco'] = bool(v['capacidade'] and v['livre'] > 0.01)
        v['candidatos'] = []
        v['semana'] = _semana(v['data'])
        v['json'] = {'pedido': '—', 'data': '', 'motorista': '', 'placa': '',
                     'itens': []}
        saida.append(v)

    saida.sort(key=lambda v: (v['data'], -v['litros'], v['placa']))
    return saida


def _aplicar_estado(viagens, fechadas, bordo, candidatos):
    """Aplica na viagem o que a tela sabe: fechada ou nao, e o que ficou a bordo.

    O ciclo que o usuario descreveu:
      - carga aberta   -> ela ainda esta montando. "Sobram 25.000 L" e convite,
                          nao afirmacao, entao a tela nao pergunta nada.
      - clicou fechar  -> se encheu a carreta, fecha direto e acabou.
                          Se sobrou espaco, ai sim pergunta o que ficou a bordo,
                          escolhendo entre as mercadorias da viagem anterior
                          daquele caminhao (qualquer cliente) — ou respondendo
                          que nada ficou, que ela saiu com boca vazia mesmo.
      - fechada        -> o numero vira afirmacao: "saiu com 25.000 L de espaco".
    """
    for v in viagens:
        ch = _chave(v)
        f = fechadas.get(ch)
        v['fechada'] = bool(f)
        v['fechada_por'] = (f or {}).get('fechada_por')
        v['fechada_em'] = (f or {}).get('fechada_em')

        itens_bordo = list(bordo.get(ch) or [])
        v['bordo'] = itens_bordo
        v['bordo_litros'] = sum(b['litros'] for b in itens_bordo)

        if itens_bordo:
            itens = [{'litros': fr['litros'], 'cor': fr['cor'],
                      'cliente': fr['cliente'] or '—'}
                     for fr in v['fretes'] if fr['litros'] > 0]
            itens += [{'litros': b['litros'], 'cor': _COR_BORDO,
                       'cliente': '%s · ficou de %s' % (b['produto'] or '?',
                                                        b['data_frete'].strftime('%d/%m'))}
                      for b in itens_bordo]
            v['desenho'], v['sem_boca'] = _encaixar(itens, v['bocas'])

        ocupado = v['litros'] + v['bordo_litros']
        v['ocupado'] = ocupado
        v['livre'] = max(0.0, v['capacidade'] - ocupado)
        v['pct'] = round(100.0 * ocupado / v['capacidade'], 1) if v['capacidade'] else 0.0
        v['estoura'] = bool(v['capacidade']) and ocupado > v['capacidade'] + 0.01

        # A carreta ainda tem espaco? E o que decide se FECHAR precisa perguntar
        # alguma coisa. Carreta cheia fecha direto, sem pergunta nenhuma.
        v['tem_espaco'] = bool(v['capacidade'] and v['livre'] > 0.01)
        # Os candidatos ficam disponiveis o tempo todo na carga aberta, mas o
        # painel so aparece quando ela PEDE: ou clicando "carga a bordo" no
        # comeco do carregamento, ou ao fechar uma carga que nao encheu.
        # Mostrar sozinho, enquanto ela ainda esta montando, so atrapalhava.
        v['candidatos'] = list(candidatos.get(v['veiculo_id']) or []) \
            if not v['fechada'] else []
        v['semana'] = _semana(v['data'])
        # O que o texto do WhatsApp precisa. Mesmo conteudo que a tela antiga
        # de Pedidos manda hoje — agrupado por distribuidora, com CNPJ, origem,
        # base, quantidade, preco e total.
        v['json'] = {
            'pedido': ', '.join(v['pedidos']) or '—',
            'data': v['data'].strftime('%d/%m/%Y'),
            'motorista': v['motorista'],
            'placa': v['placa'],
            'itens': [{
                'cliente': fr['cliente'] or '—',
                'cnpj': fr.get('cnpj') or '',
                'fornecedor': fr.get('fornecedor') or '—',
                'produto': fr['produto'] or '—',
                'origem': fr.get('origem') or '',
                'base': fr.get('base') or '',
                'qtd': fr['litros'],
                'preco': _f(fr.get('preco_unit')),
                'total': _f(fr.get('total_nf')),
            } for fr in v['fretes']],
        }


def _marcar_viagens_do_dia(viagens):
    """Quando a mesma placa aparece 2x no dia, numera 1a/2a viagem.

    E o unico ponto em que o modo "dia" perdia pro modo "caminhao": dois
    cartoes com a mesma placa confundem. A etiqueta resolve.
    """
    cont = {}
    for v in viagens:
        cont[(v['data'], v['placa'])] = cont.get((v['data'], v['placa']), 0) + 1
    vez = {}
    for v in viagens:
        ch = (v['data'], v['placa'])
        if cont[ch] > 1:
            vez[ch] = vez.get(ch, 0) + 1
            v['viagem_n'] = vez[ch]
            v['viagem_de'] = cont[ch]
        else:
            v['viagem_n'] = 0
            v['viagem_de'] = 1


def _dias_com_carga(cur, ate, quantos=14, veiculo_id=None):
    """Ultimos dias que tiveram frete — a regua de datas do topo."""
    sql = ("SELECT f.data_frete AS d, COUNT(*) AS n, "
           "COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor)),0) AS litros "
           "FROM fretes f LEFT JOIN quantidades q ON q.id = f.quantidade_id "
           "WHERE f.data_frete <= %s")
    params = [ate]
    if veiculo_id:
        sql += " AND f.veiculos_id = %s"
        params.append(veiculo_id)
    sql += " GROUP BY f.data_frete ORDER BY f.data_frete DESC LIMIT %s"
    params.append(quantos)
    cur.execute(sql, params)
    dias = cur.fetchall()
    for d in dias:
        d['litros'] = _f(d['litros'])
        d['semana'] = _semana(d['d'], curta=True)
    dias.reverse()
    return dias


def _a_cobrar(cur, desde):
    """Fretes entregues, com valor, e sem boleto vivo — agrupados por cliente.

    E a aba que nem o modo dia nem o modo caminhao resolvem: os fretes do FJM
    estao espalhados em varios dias e mais de um caminhao, e so fazem sentido
    juntos. Aqui ela e SO LEITURA — o botao de emitir e da Fase 2.
    """
    cur.execute("""
        SELECT f.id, f.data_frete, f.valor_total_frete,
               COALESCE(f.quantidade_manual, q.valor) AS litros,
               cl.id AS cid, cl.razao_social AS cliente,
               pr.nome AS produto, v.placa
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN clientes cl   ON cl.id = f.clientes_id
          LEFT JOIN produto pr    ON pr.id = f.produto_id
          LEFT JOIN veiculos v    ON v.id  = f.veiculos_id
          """ + _COBERTURA + """
         WHERE f.data_frete >= %s
           AND f.valor_total_frete > 0
           AND cob.frete_id IS NULL
         ORDER BY cl.razao_social, f.data_frete, f.id
    """, (desde,))
    por_cli = {}
    for fr in cur.fetchall():
        nome = fr['cliente'] or '—'
        c = por_cli.get(nome)
        if c is None:
            c = por_cli[nome] = {'cliente': nome, 'cid': fr['cid'], 'fretes': [],
                                 'litros': 0.0, 'valor': 0.0,
                                 'de': fr['data_frete'], 'ate': fr['data_frete'],
                                 'placas': []}
        fr['litros'] = _f(fr['litros'])
        fr['valor'] = _f(fr['valor_total_frete'])
        fr['semana'] = _semana(fr['data_frete'], curta=True)
        c['fretes'].append(fr)
        c['litros'] += fr['litros']
        c['valor'] += fr['valor']
        if fr['data_frete'] < c['de']:
            c['de'] = fr['data_frete']
        if fr['data_frete'] > c['ate']:
            c['ate'] = fr['data_frete']
        if fr['placa'] and fr['placa'] not in c['placas']:
            c['placas'].append(fr['placa'])
    lista = sorted(por_cli.values(), key=lambda c: -c['valor'])
    for c in lista:
        c['dias'] = len({fr['data_frete'] for fr in c['fretes']})
    return lista


def _abertos_por_cliente(cur, cliente_ids, desde):
    """{cliente_id: [frete...]} — tudo que o cliente deve e ainda nao tem boleto.

    A escolha do que entra no boleto atravessa carga e dia: o Terra Branca
    costuma juntar dois fretes do mesmo dia em caminhoes diferentes com um do
    dia seguinte, e sai um boleto so pros tres. Por isso o seletor que abre
    dentro da carga mostra a lista INTEIRA do cliente, nao so o que esta ali —
    os desta carga so vem pre-marcados.
    """
    if not cliente_ids:
        return {}
    marc = ','.join(['%s'] * len(cliente_ids))
    cur.execute("""
        SELECT f.id, f.clientes_id, f.data_frete, f.valor_total_frete AS valor,
               COALESCE(f.quantidade_manual, q.valor) AS litros,
               pr.nome AS produto, v.placa
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN produto pr    ON pr.id = f.produto_id
          LEFT JOIN veiculos v    ON v.id  = f.veiculos_id
          """ + _COBERTURA + """
         WHERE f.clientes_id IN (%s)
           AND f.data_frete >= %%s
           AND f.valor_total_frete > 0
           AND cob.frete_id IS NULL
         ORDER BY f.data_frete, f.id
    """ % marc, list(cliente_ids) + [desde])
    fora = {}
    for r in cur.fetchall():
        r['litros'] = _f(r['litros'])
        r['valor'] = _f(r['valor'])
        r['semana'] = _semana(r['data_frete'], curta=True)
        fora.setdefault(r['clientes_id'], []).append(r)
    return fora


def _anexar_abertos(viagens, abertos):
    """Poe a lista de fretes em aberto do cliente dentro do bloco dele na carga.

    `desta_carga` marca quais ja vem selecionados: os que estao justamente na
    carga que a Monica esta olhando. O resto ela marca se quiser juntar.
    """
    for v in viagens:
        for p in v['postos']:
            if p['estado'] != 'falta':
                p['abertos'] = []
                continue
            cid = next((fr['clientes_id'] for fr in p['fretes'] if fr.get('clientes_id')), None)
            daqui = {fr['id'] for fr in p['fretes']}
            lista = []
            for a in (abertos.get(cid) or []):
                a = dict(a)
                a['desta_carga'] = a['id'] in daqui
                lista.append(a)
            p['abertos'] = lista
            p['cliente_id'] = cid


def _divergencias(cur, desde):
    """Pedido e frete apontando pra veiculos diferentes.

    Editar o veiculo do pedido nao propaga pros fretes dele, e e o FRETE que
    manda em comissao, CT-e e relatorio. Sao pouquissimos casos, mas quando
    acontece a carga aparece no caminhao errado — entao a tela mostra.
    """
    cur.execute("""
        SELECT p.numero, p.data_pedido, vp.placa AS placa_pedido,
               vf.placa AS placa_frete, COUNT(*) AS n
          FROM fretes f
          JOIN pedidos p     ON p.id = f.pedido_id
          LEFT JOIN veiculos vp ON vp.id = p.veiculo_id
          LEFT JOIN veiculos vf ON vf.id = f.veiculos_id
         WHERE f.veiculos_id <> p.veiculo_id
           AND p.data_pedido >= %s
         GROUP BY p.numero, p.data_pedido, vp.placa, vf.placa
         ORDER BY p.data_pedido DESC
    """, (desde,))
    return cur.fetchall()


# Regras que os 406 fretes desde 01/06 seguem, conferidas no banco. Elas fazem
# a ARITMETICA do lancamento — nunca a decisao. O preco do frete por litro fica
# de fora de proposito: o RLM ja foi cobrado a 0,100, 0,125 e 0,130, sendo os
# dois ultimos na MESMA rota. Preco e negociacao, entao e sempre digitado.
_COMISSAO_POR_LITRO = 0.01     # 406 de 406 fretes
_COMISSAO_CTE_PCT = 0.08       # 402 de 406


def _calcular_frete(litros, preco_litro, preco_mercadoria, paga_comissao=True,
                    preco_cte=None):
    """Deriva os valores do frete a partir do que a Monica digitou.

    Ela digita quantidade e preco do frete por litro; o resto e conta.

    O CT-e tem preco PROPRIO, que na maioria das vezes e o mesmo do frete (347
    de 406) mas nem sempre — e o Posto Novo Horizonte e o caso extremo: sao 240
    fretes com valor R$ 0,00 (posto da casa, nao se cobra) e CT-e a R$ 0,130/L
    assim mesmo, porque o documento fiscal existe de qualquer jeito. Por isso
    `preco_cte` e separado; quando nao vem, espelha o do frete.

    Frete zerado zera junto a comissao do motorista e o lucro — nos 240 casos
    do banco os dois estao em 0,00. Sem isso o posto da casa apareceria dando
    prejuizo em todo relatorio.
    """
    litros = _f(litros)
    preco_litro = _f(preco_litro)
    p_cte = preco_litro if preco_cte in (None, '') else _f(preco_cte)

    valor_frete = round(litros * preco_litro, 2)
    tem_frete = valor_frete > 0
    comissao = round(litros * _COMISSAO_POR_LITRO, 2) if (paga_comissao and tem_frete) else 0.0
    valor_cte = round(litros * p_cte, 2)
    comissao_cte = round(valor_cte * _COMISSAO_CTE_PCT, 2)
    return {
        'total_nf': round(litros * _f(preco_mercadoria), 2),
        'valor_total_frete': valor_frete,
        'comissao_motorista': comissao,
        'valor_cte': valor_cte,
        'comissao_cte': comissao_cte,
        'lucro': round(valor_frete - comissao - comissao_cte, 2) if tem_frete else 0.0,
    }


def _opcoes(cur):
    """Listas dos campos do lancamento, ja com o que a tela precisa mostrar."""
    cur.execute("""SELECT c.id, c.razao_social, c.destino_id, d.nome AS destino
                     FROM clientes c LEFT JOIN destinos d ON d.id = c.destino_id
                    ORDER BY c.razao_social""")
    clientes = cur.fetchall()
    cur.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    fornecedores = cur.fetchall()
    cur.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cur.fetchall()
    cur.execute("SELECT id, nome FROM origens ORDER BY nome")
    origens = cur.fetchall()
    cur.execute("SELECT id, nome FROM bases WHERE ativo = 1 ORDER BY nome")
    bases = cur.fetchall()
    cur.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
    quantidades = cur.fetchall()
    for q in quantidades:
        q['valor'] = _f(q['valor'])

    # Historico de preco por cliente: consulta, nunca sugestao preenchida.
    cur.execute("""
        SELECT f.clientes_id AS cid, o.nome AS origem,
               f.preco_por_litro AS preco, COUNT(*) AS n
          FROM fretes f
          LEFT JOIN origens o ON o.id = f.origem_id
         WHERE f.data_frete >= DATE_SUB(CURDATE(), INTERVAL 120 DAY)
           AND f.preco_por_litro > 0
         GROUP BY f.clientes_id, o.nome, f.preco_por_litro
         ORDER BY n DESC
    """)
    hist = {}
    for r in cur.fetchall():
        linhas = hist.setdefault(r['cid'], [])
        if len(linhas) < 4:
            linhas.append({'preco': _f(r['preco']), 'origem': r['origem'] or '—',
                           'n': int(r['n'])})
    # Vai pra tela como JSON unico, nao como <option> repetido em cada cartao
    # de carga: no celular a lista de postos sozinha ja e enorme, e repetida
    # por caminhao ela dobrava o tamanho da pagina.
    js = {
        'clientes': [{'id': c['id'], 'nome': c['razao_social'],
                      'destino': c['destino'] or '',
                      'hist': hist.get(c['id']) or []} for c in clientes],
        'fornecedores': [{'id': f['id'], 'nome': f['razao_social']} for f in fornecedores],
        'produtos': [{'id': p['id'], 'nome': p['nome']} for p in produtos],
        'origens': [{'id': o['id'], 'nome': o['nome']} for o in origens],
        'bases': [{'id': b['id'], 'nome': b['nome']} for b in bases],
        'quantidades': [{'id': q['id'], 'litros': q['valor'],
                         'nome': '{:,.0f}'.format(q['valor']).replace(',', '.') + ' litros'}
                        for q in quantidades],
    }
    return {'clientes': clientes, 'fornecedores': fornecedores,
            'produtos': produtos, 'origens': origens, 'bases': bases,
            'quantidades': quantidades, 'historico': hist, 'json': js}


def _carga_do_dia(cursor, dia, vid, mid, criar=True):
    """Acha o pedido daquela carga (data + veiculo + motorista), ou cria um.

    Nao fatia: se o caminhao ja tem carga naquela data, o item entra nela. O
    pedido continua sendo a carga fisica.
    """
    cursor.execute("""SELECT id, numero FROM pedidos
                       WHERE data_pedido=%s AND veiculo_id=%s
                         AND COALESCE(motorista_id,0)=%s LIMIT 1""",
                   (dia, vid, mid))
    ped = cursor.fetchone()
    if ped:
        return ped['id'], ped['numero'], False
    if not criar:
        return None, None, False
    cursor.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(numero, 5) AS UNSIGNED)), 0) "
                   "AS m FROM pedidos")
    numero = 'PED-%05d' % (int((cursor.fetchone() or {}).get('m') or 0) + 1)
    cursor.execute("""INSERT INTO pedidos (numero, data_pedido, status,
                             observacoes, motorista_id, veiculo_id)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                   (numero, dia, 'Faturado', '', mid or None, vid))
    return cursor.lastrowid, numero, True


def _tem_boleto(cursor, frete_id):
    """Existe cobranca viva cobrindo esse frete? (direta ou agrupada)"""
    cursor.execute("""
        SELECT COUNT(*) AS n FROM (
            SELECT cb.id FROM cobrancas cb
             WHERE cb.frete_id = %s AND (cb.status IS NULL OR cb.status <> 'cancelado')
            UNION ALL
            SELECT cb.id FROM cobrancas_freites cf
              JOIN cobrancas cb ON cb.id = cf.cobranca_id
             WHERE cf.frete_id = %s AND (cb.status IS NULL OR cb.status <> 'cancelado')
        ) x
    """, (frete_id, frete_id))
    return int((cursor.fetchone() or {}).get('n') or 0) > 0


@bp.route('/ped-frete-novo/editar', methods=['POST'])
@login_required
def editar():
    """Corrige um frete da carga — e o item do pedido junto.

    Sem isso a Fase 3 ficava pela metade: dava pra adicionar mas o primeiro
    erro de digitacao mandava a Monica de volta pra tela de Fretes, onde o
    pedido e o frete voltam a divergir.

    Quantidade e precos so mudam enquanto NAO existe boleto vivo: mexer neles
    depois de emitido faria o boleto cobrar um valor que o frete nao diz mais.
    Fornecedor, produto e base nao tocam em dinheiro e mudam sempre.
    """
    dados = request.get_json(silent=True) or {}
    try:
        frete_id = int(dados.get('frete_id') or 0)
    except (TypeError, ValueError):
        frete_id = 0
    if not frete_id:
        return jsonify({'ok': False, 'erro': 'frete não informado'}), 400

    _ensure_tabela()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT f.*, COALESCE(f.quantidade_manual, q.valor) AS litros
                            FROM fretes f
                            LEFT JOIN quantidades q ON q.id = f.quantidade_id
                           WHERE f.id = %s""", (frete_id,))
        fr = cursor.fetchone()
        if not fr:
            return jsonify({'ok': False, 'erro': 'frete não encontrado'}), 404

        cursor.execute("""SELECT id FROM carga_fechada
                           WHERE data_frete=%s AND veiculo_id=%s AND motorista_id=%s""",
                       (fr['data_frete'], fr['veiculos_id'], fr['motoristas_id'] or 0))
        if cursor.fetchone():
            return jsonify({'ok': False,
                            'erro': 'a carga está fechada — reabra antes de editar'}), 409

        def _num(chave, atual):
            v = dados.get(chave)
            return atual if v in (None, '') else _f(v)

        def _id(chave, atual):
            v = dados.get(chave)
            if v in (None, ''):
                return atual
            try:
                return int(v) or None
            except (TypeError, ValueError):
                return atual

        litros = _num('litros', _f(fr['litros']))
        preco_litro = _num('preco_litro', _f(fr['preco_por_litro']))
        preco_merc = _num('preco_mercadoria', _f(fr['preco_produto_unitario']))
        cte_atual = (_f(fr['valor_cte']) / _f(fr['litros'])) if _f(fr['litros']) else 0.0
        preco_cte = _num('preco_cte', cte_atual)

        mexeu_dinheiro = (abs(litros - _f(fr['litros'])) > 0.001
                          or abs(preco_litro - _f(fr['preco_por_litro'])) > 0.0001
                          or abs(preco_cte - cte_atual) > 0.0001)
        if mexeu_dinheiro and _tem_boleto(cursor, frete_id):
            return jsonify({'ok': False,
                            'erro': 'esse frete já tem boleto. Cancele o boleto '
                                    'antes de mudar quantidade ou preço.'}), 409

        cursor.execute("SELECT paga_comissao FROM motoristas WHERE id = %s",
                       (fr['motoristas_id'],))
        paga = bool((cursor.fetchone() or {}).get('paga_comissao', 1))
        val = _calcular_frete(litros, preco_litro, preco_merc, paga, preco_cte)

        forn = _id('fornecedor_id', fr['fornecedores_id'])
        prod = _id('produto_id', fr['produto_id'])
        qid = _id('quantidade_id', fr['quantidade_id'])
        base = dados.get('base_id')
        base = (None if base in (None, '', 0, '0')
                else (int(base) if str(base).isdigit() else None))

        cursor.execute("""
            UPDATE fretes SET fornecedores_id=%s, produto_id=%s, quantidade_id=%s,
                   quantidade_manual=%s, preco_produto_unitario=%s, preco_por_litro=%s,
                   total_nf_compra=%s, valor_total_frete=%s, comissao_motorista=%s,
                   valor_cte=%s, comissao_cte=%s, lucro=%s, updated_at=NOW()
             WHERE id=%s
        """, (forn, prod, qid, litros, preco_merc, preco_litro, val['total_nf'],
              val['valor_total_frete'], val['comissao_motorista'], val['valor_cte'],
              val['comissao_cte'], val['lucro'], frete_id))

        cursor.execute("""
            UPDATE pedidos_itens SET produto_id=%s, fornecedor_id=%s, base_id=%s,
                   quantidade=%s, quantidade_id=%s, preco_unitario=%s, total_nf=%s
             WHERE frete_id=%s
        """, (prod, forn, base, litros, qid, preco_merc, val['total_nf'], frete_id))
        itens = cursor.rowcount
        conn.commit()
        return jsonify({'ok': True, 'itens': itens, 'valores': val})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.getLogger(__name__).exception("[ped_frete_novo] editar")
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


@bp.route('/ped-frete-novo/excluir', methods=['POST'])
@login_required
def excluir():
    """Tira um frete da carga — com o item do pedido.

    Frete com boleto vivo NUNCA some: apagar deixaria cobranca sem origem. E a
    regra que voce definiu, e aqui ela vale tanto pro emitido quanto pro pago.
    """
    dados = request.get_json(silent=True) or {}
    try:
        frete_id = int(dados.get('frete_id') or 0)
    except (TypeError, ValueError):
        frete_id = 0
    if not frete_id:
        return jsonify({'ok': False, 'erro': 'frete não informado'}), 400

    _ensure_tabela()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT data_frete, veiculos_id, motoristas_id, pedido_id
                            FROM fretes WHERE id = %s""", (frete_id,))
        fr = cursor.fetchone()
        if not fr:
            return jsonify({'ok': False, 'erro': 'frete não encontrado'}), 404

        cursor.execute("""SELECT id FROM carga_fechada
                           WHERE data_frete=%s AND veiculo_id=%s AND motorista_id=%s""",
                       (fr['data_frete'], fr['veiculos_id'], fr['motoristas_id'] or 0))
        if cursor.fetchone():
            return jsonify({'ok': False,
                            'erro': 'a carga está fechada — reabra antes de excluir'}), 409

        if _tem_boleto(cursor, frete_id):
            return jsonify({'ok': False,
                            'erro': 'esse frete tem boleto. Cancele o boleto antes '
                                    'de excluir.'}), 409

        cursor.execute("DELETE FROM pedidos_itens WHERE frete_id=%s", (frete_id,))
        itens = cursor.rowcount
        cursor.execute("DELETE FROM frete_saldo_bordo WHERE frete_id=%s", (frete_id,))
        cursor.execute("DELETE FROM fretes WHERE id=%s", (frete_id,))
        # Pedido que ficou sem nenhum frete nao serve pra nada.
        vazio = False
        if fr['pedido_id']:
            cursor.execute("SELECT COUNT(*) AS n FROM fretes WHERE pedido_id=%s",
                           (fr['pedido_id'],))
            if int((cursor.fetchone() or {}).get('n') or 0) == 0:
                cursor.execute("DELETE FROM pedidos_itens WHERE pedido_id=%s",
                               (fr['pedido_id'],))
                cursor.execute("DELETE FROM pedidos WHERE id=%s", (fr['pedido_id'],))
                vazio = True
        conn.commit()
        return jsonify({'ok': True, 'itens': itens, 'pedido_vazio': vazio})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.getLogger(__name__).exception("[ped_frete_novo] excluir")
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


@bp.route('/ped-frete-novo/mover', methods=['POST'])
@login_required
def mover():
    """Passa um frete para outro caminhao da mesma data.

    Na correria a Monica lanca tudo num caminhao so e divide depois. Aqui a
    troca leva junto o item do pedido e o vinculo com a carga de destino — que
    e o que a tela de Pedidos nunca fez, e a origem das divergencias que a
    gente consertou na mao duas vezes.
    """
    dados = request.get_json(silent=True) or {}
    try:
        frete_id = int(dados.get('frete_id') or 0)
        vid = int(dados.get('veiculo_id') or 0)
        mid = int(dados.get('motorista_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'erro': 'dados inválidos'}), 400
    if not frete_id or not vid:
        return jsonify({'ok': False, 'erro': 'informe o frete e o caminhão'}), 400

    _ensure_tabela()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""SELECT f.id, f.data_frete, f.pedido_id, f.veiculos_id,
                                 f.motoristas_id
                            FROM fretes f WHERE f.id = %s""", (frete_id,))
        fr = cursor.fetchone()
        if not fr:
            return jsonify({'ok': False, 'erro': 'frete não encontrado'}), 404
        dia = fr['data_frete']

        # Carga fechada, dos dois lados, nao aceita movimento sem reabrir.
        for v_, m_, onde in ((fr['veiculos_id'], fr['motoristas_id'] or 0, 'de origem'),
                             (vid, mid, 'de destino')):
            cursor.execute("""SELECT id FROM carga_fechada
                               WHERE data_frete=%s AND veiculo_id=%s AND motorista_id=%s""",
                           (dia, v_, m_))
            if cursor.fetchone():
                return jsonify({'ok': False,
                                'erro': 'a carga %s está fechada — reabra antes '
                                        'de mover' % onde}), 409

        pedido_id, numero, criou = _carga_do_dia(cursor, dia, vid, mid)
        cursor.execute("""UPDATE fretes SET veiculos_id=%s, motoristas_id=%s,
                                 pedido_id=%s, updated_at=NOW()
                           WHERE id=%s""",
                       (vid, mid or None, pedido_id, frete_id))
        # O item do pedido vai junto — e o que mantem os dois lados de acordo.
        cursor.execute("UPDATE pedidos_itens SET pedido_id=%s WHERE frete_id=%s",
                       (pedido_id, frete_id))
        itens = cursor.rowcount
        conn.commit()
        return jsonify({'ok': True, 'pedido': numero, 'pedido_novo': criou,
                        'itens_movidos': itens})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.getLogger(__name__).exception("[ped_frete_novo] mover")
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


@bp.route('/ped-frete-novo/lancar', methods=['POST'])
@login_required
def lancar():
    """Poe um posto na carga: grava pedido + item + frete de uma vez so.

    O defeito antigo era esse: o pedido nascia numa tela e o frete em outra, e
    depois seguiam vidas separadas — trocar o caminhao no pedido nao trocava
    nos fretes, reduzir a quantidade nao reduzia. Nascendo no mesmo INSERT, os
    dois sempre concordam.

    O pedido NAO e fatiado: se ja existe carga daquele caminhao naquela data,
    o item entra nela. O pedido continua sendo a carga fisica.
    """
    dados = request.get_json(silent=True) or {}
    carga = _carga_do_pedido(dados)
    if not carga:
        return jsonify({'ok': False, 'erro': 'carga não informada'}), 400
    dia, vid, mid = carga

    def _int(fonte, chave):
        try:
            return int((fonte or {}).get(chave) or 0)
        except (TypeError, ValueError):
            return 0

    cliente_id = _int(dados, 'cliente_id')
    origem_id = _int(dados, 'origem_id')
    if not cliente_id:
        return jsonify({'ok': False, 'erro': 'falta o posto'}), 400
    if not origem_id:
        return jsonify({'ok': False, 'erro': 'falta a origem'}), 400

    # Um posto, varios produtos: e como a carga acontece de verdade. Fazer um
    # lancamento por produto obrigava a reescolher posto e origem toda vez.
    itens = dados.get('itens')
    if not isinstance(itens, list) or not itens:
        return jsonify({'ok': False, 'erro': 'nenhum produto informado'}), 400

    linhas = []
    for n, it in enumerate(itens, 1):
        fornecedor_id = _int(it, 'fornecedor_id')
        produto_id = _int(it, 'produto_id')
        litros = _f((it or {}).get('litros'))
        falta = [r for r, v in (('fornecedor', fornecedor_id),
                                ('produto', produto_id)) if not v]
        if falta:
            return jsonify({'ok': False,
                            'erro': 'produto %d: falta %s' % (n, ', '.join(falta))}), 400
        if litros <= 0:
            return jsonify({'ok': False,
                            'erro': 'produto %d: informe a quantidade' % n}), 400
        # 0 e resposta valida: o Posto Novo Horizonte viaja com frete R$ 0,00.
        # Por isso a checagem e "veio o campo?", nao "e maior que zero?".
        if (it or {}).get('preco_litro') in (None, ''):
            return jsonify({'ok': False,
                            'erro': 'produto %d: informe o frete por litro' % n}), 400
        linhas.append({
            'fornecedor_id': fornecedor_id, 'produto_id': produto_id,
            'base_id': _int(it, 'base_id') or None,
            'quantidade_id': _int(it, 'quantidade_id') or None,
            'litros': litros,
            'preco_mercadoria': _f(it.get('preco_mercadoria')),
            'preco_litro': _f(it.get('preco_litro')),
            'preco_cte': it.get('preco_cte'),
        })

    _ensure_tabela()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Carga fechada nao recebe item novo: fechar significa que o caminhao
        # saiu com aquilo. Reabrir e um clique, e deixa o rastro certo.
        cursor.execute("""SELECT id FROM carga_fechada
                           WHERE data_frete=%s AND veiculo_id=%s AND motorista_id=%s""",
                       (dia, vid, mid))
        if cursor.fetchone():
            return jsonify({'ok': False,
                            'erro': 'esta carga está fechada — reabra antes de '
                                    'adicionar um posto'}), 409

        cursor.execute("SELECT destino_id FROM clientes WHERE id = %s", (cliente_id,))
        cli = cursor.fetchone()
        if not cli:
            return jsonify({'ok': False, 'erro': 'posto não encontrado'}), 404
        destino_id = cli['destino_id']

        cursor.execute("SELECT paga_comissao FROM motoristas WHERE id = %s", (mid,))
        mot = cursor.fetchone()
        paga = bool((mot or {}).get('paga_comissao', 1))

        pedido_id, numero, criou_pedido = _carga_do_dia(cursor, dia, vid, mid)

        criados = []
        for ln in linhas:
            valores = _calcular_frete(ln['litros'], ln['preco_litro'],
                                      ln['preco_mercadoria'], paga, ln['preco_cte'])

            # o transporte — mesmo caminhao, motorista e quantidade do item
            cursor.execute("""
                INSERT INTO fretes
                       (data_frete, status, observacoes, clientes_id, fornecedores_id,
                        produto_id, origem_id, destino_id, motoristas_id, veiculos_id,
                        quantidade_id, quantidade_manual, preco_produto_unitario,
                        preco_por_litro, total_nf_compra, valor_total_frete,
                        comissao_motorista, valor_cte, comissao_cte, lucro,
                        pedido_id, boleto_emitido)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
            """, (dia, 'Pendente', dados.get('observacoes') or '', cliente_id,
                  ln['fornecedor_id'], ln['produto_id'], origem_id, destino_id,
                  mid or None, vid, ln['quantidade_id'], ln['litros'],
                  ln['preco_mercadoria'], ln['preco_litro'], valores['total_nf'],
                  valores['valor_total_frete'], valores['comissao_motorista'],
                  valores['valor_cte'], valores['comissao_cte'], valores['lucro'],
                  pedido_id))
            frete_id = cursor.lastrowid

            # a mercadoria — ja apontando pro frete que nasceu com ela, pra que
            # mover ou corrigir depois leve os dois juntos
            cursor.execute("""
                INSERT INTO pedidos_itens
                       (pedido_id, cliente_id, produto_id, fornecedor_id, origem_id,
                        base_id, quantidade, quantidade_id, tipo_quantidade,
                        preco_unitario, total_nf, frete_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pedido_id, cliente_id, ln['produto_id'], ln['fornecedor_id'],
                  origem_id, ln['base_id'], ln['litros'], ln['quantidade_id'],
                  'lista' if ln['quantidade_id'] else 'manual',
                  ln['preco_mercadoria'], valores['total_nf'], frete_id))
            criados.append({'frete_id': frete_id, 'item_id': cursor.lastrowid,
                            'litros': ln['litros'], 'valores': valores})

        conn.commit()
        return jsonify({'ok': True, 'pedido': numero, 'pedido_novo': criou_pedido,
                        'criados': criados, 'quantos': len(criados)})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.getLogger(__name__).exception("[ped_frete_novo] lancar")
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


def _quem():
    return (getattr(current_user, 'username', None)
            or getattr(current_user, 'nome_completo', None) or '')[:80]


def _carga_do_pedido(dados):
    """Le data + veiculo + motorista do corpo da requisicao."""
    try:
        d = date.fromisoformat(dados.get('data') or '')
    except (TypeError, ValueError):
        return None
    try:
        vid = int(dados.get('veiculo_id') or 0)
        mid = int(dados.get('motorista_id') or 0)
    except (TypeError, ValueError):
        return None
    if not vid:
        return None
    return d, vid, mid


@bp.route('/ped-frete-novo/fechar', methods=['POST'])
@login_required
def fechar():
    """Fecha a carga e, se ela nao encheu, registra o que ficou a bordo.

    A partir daqui "sobram 5.000 L" deixa de ser "faltam lancar" e passa a ser
    "saiu com 5.000 L de espaco". As duas coisas vao juntas de proposito: e no
    momento de fechar que a Monica sabe o que ficou no caminhao.

    Escreve so em `carga_fechada` e `frete_saldo_bordo`.
    """
    dados = request.get_json(silent=True) or {}
    carga = _carga_do_pedido(dados)
    if not carga:
        return jsonify({'ok': False, 'erro': 'carga não informada'}), 400
    dia, vid, mid = carga

    itens = dados.get('bordo') or []
    if not isinstance(itens, list):
        itens = []
    # A Monica tambem marca o que ficou a bordo NO COMECO do carregamento, pra
    # o painel de bocas ja contar certo enquanto ela enche o caminhao. Nesse
    # caso grava o saldo e nao fecha nada.
    so_bordo = bool(dados.get('apenas_bordo'))

    _ensure_tabela()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        gravados = 0
        for it in itens:
            try:
                fid = int((it or {}).get('frete_id') or 0)
                litros = _f((it or {}).get('litros'))
            except (TypeError, ValueError, AttributeError):
                continue
            if not fid or litros <= 0:
                continue
            cursor.execute("SELECT id FROM fretes WHERE id = %s", (fid,))
            if not cursor.fetchone():
                continue
            cursor.execute("""
                INSERT INTO frete_saldo_bordo
                       (frete_id, carga_data, carga_veiculo_id, carga_motorista_id,
                        litros, respondido_por, respondido_em)
                     VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE litros = VALUES(litros),
                                        carga_motorista_id = VALUES(carga_motorista_id),
                                        respondido_por = VALUES(respondido_por),
                                        respondido_em = NOW()
            """, (fid, dia, vid, mid, litros, _quem()))
            gravados += 1

        if not so_bordo:
            cursor.execute("""
                INSERT INTO carga_fechada (data_frete, veiculo_id, motorista_id,
                                           fechada_por, fechada_em)
                     VALUES (%s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE fechada_por = VALUES(fechada_por),
                                        fechada_em = NOW()
            """, (dia, vid, mid, _quem()))
        conn.commit()
        return jsonify({'ok': True, 'bordo': gravados, 'fechou': not so_bordo})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.getLogger(__name__).exception("[ped_frete_novo] fechar")
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


@bp.route('/ped-frete-novo/reabrir', methods=['POST'])
@login_required
def reabrir():
    """Desfaz o fechamento e apaga o que tinha sido marcado como a bordo.

    Existe porque errar o clique tem que sair barato: a tela volta exatamente
    ao que era, sem deixar rastro que atrapalhe a leitura do dia seguinte.
    """
    dados = request.get_json(silent=True) or {}
    carga = _carga_do_pedido(dados)
    if not carga:
        return jsonify({'ok': False, 'erro': 'carga não informada'}), 400
    dia, vid, mid = carga

    _ensure_tabela()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""DELETE FROM carga_fechada
                           WHERE data_frete=%s AND veiculo_id=%s AND motorista_id=%s""",
                       (dia, vid, mid))
        cursor.execute("""DELETE FROM frete_saldo_bordo
                           WHERE carga_data=%s AND carga_veiculo_id=%s""",
                       (dia, vid))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logging.getLogger(__name__).exception("[ped_frete_novo] reabrir")
        return jsonify({'ok': False, 'erro': str(e)}), 500
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


@bp.route('/ped-frete-novo/', methods=['GET'])
@login_required
def index():
    _ensure_tabela()
    hoje = hoje_brasilia()
    modo = (request.args.get('modo') or 'dia').lower()
    if modo not in ('dia', 'caminhao', 'cobrar'):
        modo = 'dia'

    try:
        dia = date.fromisoformat(request.args.get('data') or '')
    except ValueError:
        dia = hoje

    try:
        veiculo_id = int(request.args.get('veiculo') or 0) or None
    except ValueError:
        veiculo_id = None

    ctx = {'modo': modo, 'dia': dia, 'hoje': hoje, 'veiculo_id': veiculo_id,
           'semana': _semana(dia), 'semana_ontem': _semana(dia - timedelta(days=1), True),
           'semana_amanha': _semana(dia + timedelta(days=1), True),
           # +3 dias e o prazo da casa: 151 dos 188 boletos desde junho, e
           # todo cliente fica entre +2,7 e +3,0. Vem preenchido, da pra mudar.
           'vencimento_padrao': (hoje + timedelta(days=3)).isoformat(),
           'viagens': [], 'ociosos': [], 'dias': [], 'veiculos': [],
           'cobrar': [], 'divergencias': [], 'erro': None, 'destinos': [],
           'op': {'clientes': [], 'fornecedores': [], 'produtos': [],
                  'origens': [], 'bases': [], 'quantidades': [], 'historico': {},
                  'json': {}},
           'ontem': dia - timedelta(days=1), 'amanha': dia + timedelta(days=1),
           'totais': {'litros': 0.0, 'a_cobrar': 0.0, 'emitido': 0.0,
                      'viagens': 0, 'postos': 0}}

    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cap, carretas = _capacidades(cursor)

        # A frota da tela e quem PUXA: carreta tem placa e esta em `veiculos`,
        # mas nunca aparece em frete. Deixar ela na lista fazia o modo
        # "por caminhao" abrir num veiculo que nunca teve carga.
        cursor.execute("SELECT id, placa, caminhao, tipo_veiculo FROM veiculos "
                       "WHERE ativo = 1 AND placa <> '' ORDER BY caminhao, placa")
        veiculos = [v for v in cursor.fetchall()
                    if v['id'] not in carretas
                    and (v.get('tipo_veiculo') or '').strip().lower() != 'carreta']
        for v in veiculos:
            c = cap.get(v['id']) or {}
            v['capacidade'] = c.get('total') or 0.0
            v['carreta'] = c.get('carreta')
        ctx['veiculos'] = veiculos

        if modo == 'cobrar':
            ctx['cobrar'] = _a_cobrar(cursor, hoje - timedelta(days=120))
            ctx['totais']['a_cobrar'] = sum(c['valor'] for c in ctx['cobrar'])
            ctx['totais']['postos'] = len(ctx['cobrar'])
        else:
            if modo == 'caminhao' and not veiculo_id and veiculos:
                # Abre no caminhao que rodou por ultimo — abrir num que nunca
                # teve carga daria "nenhuma carga" logo de cara.
                cursor.execute("SELECT veiculos_id, MAX(data_frete) AS ult "
                               "FROM fretes WHERE veiculos_id IS NOT NULL "
                               "GROUP BY veiculos_id ORDER BY ult DESC")
                ult = {r['veiculos_id']: r['ult'] for r in cursor.fetchall()}
                ordenados = sorted(veiculos,
                                   key=lambda v: (ult.get(v['id']) is not None,
                                                  ult.get(v['id']) or date.min),
                                   reverse=True)
                veiculo_id = ctx['veiculo_id'] = ordenados[0]['id']

            alvo = veiculo_id if modo == 'caminhao' else None
            ctx['dias'] = _dias_com_carga(cursor, hoje, 14, alvo)
            fretes = _fretes_do_periodo(cursor, dia, dia, alvo)
            viagens = _montar_viagens(fretes, cap)
            _marcar_viagens_do_dia(viagens)
            vids = {v['veiculo_id'] for v in viagens if v['veiculo_id']}
            _aplicar_estado(viagens,
                            _fechadas(cursor, dia),
                            _bordo_registrado(cursor, dia),
                            _candidatos_bordo(cursor, dia, vids))
            # Para onde da pra mover um frete: as outras cargas do dia (que ja
            # tem motorista definido) e os caminhoes parados, com o motorista
            # do cadastro. Na correria ela lanca tudo num caminhao e divide
            # depois — esse e o momento.
            cursor.execute("""SELECT veiculo_id, id, nome FROM motoristas
                               WHERE ativo = 1 AND veiculo_id IS NOT NULL""")
            padrao = {r['veiculo_id']: r for r in cursor.fetchall()}
            destinos, vistos = [], set()
            for v in viagens:
                ch = (v['veiculo_id'], v['motorista_id'] or 0)
                if ch in vistos:
                    continue
                vistos.add(ch)
                destinos.append({'veiculo_id': v['veiculo_id'],
                                 'motorista_id': v['motorista_id'] or 0,
                                 'label': '%s · %s' % (v['placa'], v['motorista'])})
            for vc in veiculos:
                m = padrao.get(vc['id'])
                ch = (vc['id'], (m or {}).get('id') or 0)
                if ch in vistos:
                    continue
                vistos.add(ch)
                destinos.append({'veiculo_id': vc['id'],
                                 'motorista_id': (m or {}).get('id') or 0,
                                 'label': '%s · %s' % (vc['placa'],
                                                       (m or {}).get('nome') or 'sem motorista')})
            ctx['destinos'] = destinos

            cids = {fr['clientes_id'] for v in viagens for p in v['postos']
                    if p['estado'] == 'falta' for fr in p['fretes']
                    if fr.get('clientes_id')}
            _anexar_abertos(viagens,
                            _abertos_por_cliente(cursor, cids,
                                                 hoje - timedelta(days=120)))
            ctx['viagens'] = viagens
            ctx['op'] = _opcoes(cursor)

            usados = {v['veiculo_id'] for v in viagens}
            ctx['ociosos'] = [v for v in veiculos if v['id'] not in usados
                              and (alvo is None or v['id'] == alvo)]

            ctx['totais'] = {
                'litros': sum(v['litros'] for v in viagens),
                'a_cobrar': sum(v['a_cobrar'] for v in viagens),
                'emitido': sum(v['emitido'] for v in viagens),
                'viagens': len(viagens),
                'postos': len({p['nome'] for v in viagens for p in v['postos']}),
            }

        ctx['divergencias'] = _divergencias(cursor, hoje - timedelta(days=45))
    except Exception as e:  # a tela e de leitura: erro vira aviso, nao stack
        ctx['erro'] = str(e)
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

    return render_template('ped_frete_novo/index.html', **ctx)
