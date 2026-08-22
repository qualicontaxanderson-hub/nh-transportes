"""PED/FRETE - NOVO — Fase 1: SOMENTE LEITURA.

Porta nova pra enxergar a carga do jeito que ela existe na estrada: o caminhao
carregado, os postos dentro dele e quanto cada um deve. Nao grava nada, nao
altera nada — le `fretes`, `pedidos`, `veiculo_compartimentos`,
`conjuntos_veiculos` e `cobrancas` e monta a leitura.

Por que a tela existe
---------------------
Hoje a carga fisica de um caminhao aparece fatiada em varios pedidos, porque
pra cobrar UM cliente sozinho foi preciso arranca-lo pra pedido proprio (o
boleto e de um frete so). Resultado: ninguem consegue olhar e responder "o que
esse caminhao esta levando e ainda cabe alguma coisa?". Esta tela junta de
volta pela chave fisica — data + veiculo + motorista — sem tocar nos dados.

Tres modos, uma tela:
  dia      — todos os caminhoes do dia (a pergunta frequente)
  caminhao — a linha do tempo de um caminhao (a pergunta ocasional)
  cobrar   — por cliente, atravessando cargas (o que nenhum dos dois resolve)

Fase 2 (nao esta aqui) liga a cobranca agrupada, que precisa de tabela nova.
"""

from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from utils.db import get_db_connection
from utils.fuso import hoje_brasilia

bp = Blueprint('ped_frete_novo', __name__)

# Cores dos postos dentro da carga. O indice vem da ordem de litros na viagem,
# entao o maior carregamento fica sempre com a mesma cor no topo da legenda.
_CORES = ['#1D63A5', '#7a6bab', '#17963C', '#c98a2b', '#a32d2d', '#0f7d8c',
          '#8a5a00', '#5c6bc0']

# Boletos nesse estado nao contam como cobranca viva.
_COB_MORTA = ('cancelado',)


def _f(v):
    """float() que nunca explode — o banco devolve Decimal e None."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


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
               co.status AS cob_status, co.data_vencimento AS cob_venc
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN clientes cl   ON cl.id = f.clientes_id
          LEFT JOIN produto pr    ON pr.id = f.produto_id
          LEFT JOIN veiculos v    ON v.id  = f.veiculos_id
          LEFT JOIN motoristas m  ON m.id  = f.motoristas_id
          LEFT JOIN pedidos p     ON p.id  = f.pedido_id
          LEFT JOIN fornecedores fo ON fo.id = f.fornecedores_id
          LEFT JOIN cobrancas co   ON co.frete_id = f.id AND co.status NOT IN ('cancelado')
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
    """
    if _f(fr['valor_total_frete']) <= 0:
        return 'zero'
    st = (fr.get('cob_status') or '').lower()
    if st == 'pago':
        return 'pago'
    if st:
        return 'emitido'
    return 'emitido' if fr.get('boleto_emitido') else 'falta'


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
                'motorista': fr['motorista'] or '—',
                'bocas': c['bocas'], 'capacidade': c['total'], 'carreta': c['carreta'],
                'fretes': [], 'pedidos': [], 'postos': {},
                'litros': 0.0, 'a_cobrar': 0.0, 'emitido': 0.0,
            }
        fr['estado'] = _estado_cobranca(fr)
        fr['litros'] = _f(fr['litros'])
        fr['valor'] = _f(fr['valor_total_frete'])
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
        saida.append(v)

    saida.sort(key=lambda v: (v['data'], -v['litros'], v['placa']))
    return saida


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
               pr.nome AS produto, v.placa,
               co.status AS cob_status
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN clientes cl   ON cl.id = f.clientes_id
          LEFT JOIN produto pr    ON pr.id = f.produto_id
          LEFT JOIN veiculos v    ON v.id  = f.veiculos_id
          LEFT JOIN cobrancas co   ON co.frete_id = f.id AND co.status NOT IN ('cancelado')
         WHERE f.data_frete >= %s
           AND f.valor_total_frete > 0
           AND co.id IS NULL
           AND (f.boleto_emitido = 0 OR f.boleto_emitido IS NULL)
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


@bp.route('/ped-frete-novo/', methods=['GET'])
@login_required
def index():
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
           'viagens': [], 'ociosos': [], 'dias': [], 'veiculos': [],
           'cobrar': [], 'divergencias': [], 'erro': None,
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
            ctx['viagens'] = viagens

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
