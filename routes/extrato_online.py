"""
Extrato On-Line — consulta o extrato direto na API do banco (Financeiro).

Busca o período no banco e mostra, lançamento a lançamento, se ele JÁ ESTÁ
no sistema ou se falta. Desde 24/10/2026 a conta com 'grava' (Cora NH e
Prest) LANÇA no sistema o que falta — ao consultar e a cada 10 min
(integrations/extrato_scheduler); o OFX continua entrando e reconhece o que
a API já lançou (integrations/extrato_grava). O Sicoob grava também, com o
id montado em sicoob_extrato.id_sintetico.

Mesma casca do /relatorios/conf_cartoes: filtro em cartão, régua de
períodos, o período inteiro num painel e um card + um quadro por TIPO de
movimento (PIX recebido, cartões, transferências...). O tipo sai do próprio
texto do banco — ver _categoria().

Um banco novo é uma entrada em BANCOS: rótulo, conta, cor e o módulo que
sabe ler(), comparar() e mesmo_texto_do_ofx() — o resto (mTLS, token, HTTP,
comparação) é comum, em integrations/banco_api.

SÓ ADMIN (23/10/2026): ninguém mais vê esta tela por enquanto.

Cada lançamento é um card (modelo A da prévia preview-extrato-cards.html):
o PIX recebido traz o cupom do abastecimento (integrations/extrato_cupom);
o que já está no sistema traz PARA QUEM foi conciliado — o texto do banco
não diz ('DÉB.TIT.COMPE EFETIVADO' foi a EQUATORIAL).

CACHE: um clique num card ou filtro não consulta o banco de novo. O
resultado fica guardado alguns minutos por (banco, período); "Consultar no
banco" sempre busca de novo.
"""
import logging
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, json, render_template, request
from flask_login import login_required

from utils.decorators import admin_required

logger = logging.getLogger(__name__)

bp = Blueprint('extrato_online', __name__, url_prefix='/banco/extrato-online')

MAX_DIAS = 31
MESES_PT = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']


def _sicoob():
    from integrations import sicoob_extrato
    return sicoob_extrato


def _cora(conta):
    def carrega():
        from integrations import cora_extrato
        return cora_extrato.CONTAS[conta]
    return carrega


# 'grava': a API lança no sistema ao lado do OFX (integrations/extrato_grava);
# o id estável do lançamento vem do banco (Cora) ou é montado (Sicoob).
# 'cor': o contorno de tudo daquela conta na tela. 'credenciadora': o CNPJ que
# o cupom grava quando o PIX é liquidado por este banco — é o que permite
# dizer "cupom PIX sem PIX no banco".
BANCOS = {
    'sicoob-nh': {'rotulo': 'SICOOB - NH', 'conta': '5024 / 148.186-0', 'modulo': _sicoob,
                  'cor': '#00897B', 'credenciadora': '02038232000164',
                  'fds_no_dia_util': True,      # ver banco_api.proximo_dia_util
                  'grava': True},
    'cora-nh': {'rotulo': 'CORA - NH', 'conta': '0001 / 3456427-0', 'modulo': _cora('posto'),
                'cor': '#E8336D', 'credenciadora': None, 'grava': True},
    'cora-prest': {'rotulo': 'CORA - PREST', 'conta': '0001 / 27677832', 'modulo': _cora('prest'),
                   'cor': '#8E24AA', 'credenciadora': None, 'grava': True},
}

# Resultado guardado por (banco, início, fim): período com hoje vale 1 min
# (o dia ainda muda), período fechado vale 10 min.
_CACHE = {}
_TRAVA = threading.Lock()
VALE_COM_HOJE = 60
VALE_FECHADO = 600
MAX_GUARDADOS = 8

# Ordem dos cards e dos quadros: primeiro o que entra, depois o que sai.
CATEGORIAS = OrderedDict([
    ('pix_in',   {'nome': 'PIX recebido',     'icone': 'bi-qr-code',            'cor': '#17963C'}),
    ('cartao',   {'nome': 'Cartões',          'icone': 'bi-credit-card',        'cor': '#1D63A5'}),
    ('transf_in', {'nome': 'Transf. recebida', 'icone': 'bi-arrow-down-left',   'cor': '#0f766e'}),
    ('outros_in', {'nome': 'Outras entradas',  'icone': 'bi-plus-circle',       'cor': '#475569'}),
    ('pix_out',  {'nome': 'PIX enviado',      'icone': 'bi-send',               'cor': '#c2410c'}),
    ('transf_out', {'nome': 'Transf. enviada', 'icone': 'bi-arrow-up-right',    'cor': '#a16207'}),
    ('pagto',    {'nome': 'Pagamentos',       'icone': 'bi-receipt',            'cor': '#6f42c1'}),
    ('tarifa',   {'nome': 'Tarifas',          'icone': 'bi-percent',            'cor': '#a32d2d'}),
    ('bloqueio', {'nome': 'Bloqueios',        'icone': 'bi-lock',               'cor': '#334155'}),
    ('outros_out', {'nome': 'Outras saídas',   'icone': 'bi-dash-circle',       'cor': '#64748b'}),
])

# Quando o banco diz o tipo (Cora: transaction.type), vale o que ele diz.
# Lista ABERTA na documentação do Cora: tipo novo cai no texto, abaixo.
POR_TIPO_DO_BANCO = {
    'PIX': ('pix_in', 'pix_out'), 'TRANSFER': ('transf_in', 'transf_out'),
    'PAYMENT': ('outros_in', 'pagto'), 'FEE': ('outros_in', 'tarifa'),
    'CARD': ('cartao', 'pagto'), 'BANK_DOMICILE': ('cartao', 'outros_out'),
    'BLOCK': ('bloqueio', 'bloqueio'), 'JUD_BLOCKER': ('bloqueio', 'bloqueio'),
    'LIMIT_RESERVATION': ('bloqueio', 'bloqueio'),
}


def _categoria(tx):
    """Tipo do movimento. Sem o tipo do banco, pelo texto — medido na 1ª
    consulta real do Sicoob (16-22/10/2026): 'PIX RECEBIDO - OUTRA IF',
    'CR COMPRAS VISA ELECTRON', 'CR ANTECIPAÇÃO MASTERCARD',
    'CRED.TRANSF.CONTAS INTERCREDIS', 'TARIFA RECEBIMENTO PIX'. O que não se
    reconhece cai em "Outras"."""
    from integrations.banco_api import normal
    entrada = tx['tipo'] == 'CREDIT'
    par = POR_TIPO_DO_BANCO.get(tx.get('categoria_banco') or '')
    if par:
        return par[0] if entrada else par[1]
    d = normal(f"{tx.get('descricao')} {tx.get('memo')}")
    if 'TARIFA' in d:
        return 'tarifa'
    if 'PIX' in d:
        return 'pix_in' if entrada else 'pix_out'
    if entrada and ('CR COMPRAS' in d or 'ANTECIPA' in d or 'SIPAG' in d):
        return 'cartao'
    if 'TRANSF' in d or 'TED' in d.split() or 'DOC' in d.split():
        return 'transf_in' if entrada else 'transf_out'
    # 'DÉB.TIT.COMPE EFETIVADO' é boleto pago; 'DÉB.CONV.ORGÃOS GOV.' é convênio
    # (imposto, taxa) — os dois são pagamento, não "outras saídas".
    if not entrada and any(p in d for p in ('PAGTO', 'PAGAMENTO', 'BOLETO', 'CONV',
                                            'TIT.COMPE', 'TITULO')):
        return 'pagto'
    return 'outros_in' if entrada else 'outros_out'


def _data(txt, padrao):
    try:
        return date.fromisoformat(txt) if txt else padrao
    except ValueError:
        return padrao


def _atalhos(hoje):
    """A régua: hoje, ontem, 7 dias e os três últimos meses (o Sicoob só
    devolve extrato recente). O mês corrente vai até hoje."""
    ontem = hoje - timedelta(days=1)
    r = [('Hoje', hoje, hoje), ('Ontem', ontem, ontem),
         ('7 dias', hoje - timedelta(days=6), hoje)]
    meses = []
    ano, mes = hoje.year, hoje.month
    for _ in range(3):
        ini = date(ano, mes, 1)
        prox = date(ano + (mes == 12), mes % 12 + 1, 1)
        meses.append((f'{MESES_PT[mes - 1]}/{str(ano)[2:]}', ini, min(prox - timedelta(days=1), hoje)))
        ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    return r + list(reversed(meses))


@bp.route('/')
@login_required
@admin_required
def index():
    hoje = date.today()
    ontem = hoje - timedelta(days=1)
    chave = request.args.get('banco') or next(iter(BANCOS))
    if chave not in BANCOS:
        chave = next(iter(BANCOS))
    banco = BANCOS[chave]
    ini = _data(request.args.get('ini'), ontem - timedelta(days=6))
    fim = _data(request.args.get('fim'), ontem)
    cat = request.args.get('cat') or ''
    ver = request.args.get('ver') or ''

    ctx = {'bancos': BANCOS, 'chave': chave, 'banco': banco, 'ini': ini, 'fim': fim,
           'hoje': hoje, 'atalhos': _atalhos(hoje), 'categorias': CATEGORIAS,
           'cat': cat if cat in CATEGORIAS else '', 'ver': ver,
           'consultado': False, 'erro': None}

    if request.args.get('consultar'):
        if fim > hoje:
            ctx['erro'] = f'A data final não pode passar de hoje ({hoje:%d/%m}).'
        elif ini > fim:
            ctx['erro'] = 'A data inicial está depois da final.'
        elif (fim - ini).days + 1 > MAX_DIAS:
            ctx['erro'] = f'Período máximo de {MAX_DIAS} dias por consulta.'
        else:
            ctx.update(_consultar_guardado(chave, ini, fim, hoje,
                                           novo=bool(request.args.get('novo'))))
    return render_template('extrato_online/index.html', **ctx)


@bp.route('/bruto')
@login_required
@admin_required
def bruto():
    """Os lançamentos do período como o banco mandou, ao lado do texto que o
    OFX gravou para o mesmo lançamento — para montar o texto da API igual ao
    do OFX (as regras e memorizações casam pelo texto). Só lê; baixa um JSON."""
    hoje = date.today()
    chave = request.args.get('banco') or ''
    if chave not in BANCOS:
        return Response('banco desconhecido', status=400)
    ini = _data(request.args.get('ini'), hoje)
    fim = min(_data(request.args.get('fim'), hoje), hoje)
    if ini > fim or (fim - ini).days + 1 > MAX_DIAS:
        return Response('período inválido', status=400)
    res = _consultar_guardado(chave, ini, fim, hoje)
    if res.get('erro'):
        return Response(res['erro'], status=502)
    itens = []
    for l in res['linhas']:
        tx, o = l['tx'], l['ofx'] or {}
        itens.append({'data': str(tx['data_transacao']), 'hora': tx.get('hora'),
                      'tipo': tx['tipo'], 'valor': tx['valor'],
                      'texto_api': tx.get('descricao'),
                      'ofx_descricao': o.get('descricao'), 'ofx_memo': o.get('memo'),
                      'ofx_fitid': o.get('fitid'), 'texto_igual': l['texto_igual'],
                      'bruto': tx.get('bruto')})
    corpo = json.dumps({'banco': chave, 'ini': str(ini), 'fim': str(fim), 'lancamentos': itens},
                       ensure_ascii=False, indent=1, default=str)
    nome = f'extrato-{chave}-{ini:%Y%m%d}-{fim:%Y%m%d}.json'
    return Response(corpo, mimetype='application/json',
                    headers={'Content-Disposition': f'attachment; filename={nome}'})


def _consultar_guardado(chave, ini, fim, hoje, novo=False):
    k = (chave, ini, fim)
    agora = time.monotonic()
    with _TRAVA:
        g = _CACHE.get(k)
        if g and not novo and agora < g[0]:
            return dict(g[1], do_cache=True)
    res = _consultar(BANCOS[chave], ini, fim, hoje)
    if not res.get('erro'):
        with _TRAVA:
            _CACHE[k] = (agora + (VALE_COM_HOJE if fim >= hoje else VALE_FECHADO), res)
            while len(_CACHE) > MAX_GUARDADOS:
                _CACHE.pop(min(_CACHE, key=lambda x: _CACHE[x][0]))
    return dict(res, do_cache=False)


def _gravar(banco, mod, api):
    """Conta que grava: o que a API trouxe e o sistema não tem entra agora
    (integrations/extrato_grava). Falha aqui não impede a consulta."""
    if not banco.get('grava'):
        return None
    from integrations.extrato_grava import sincronizar
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        return sincronizar(mod, api, cur, conn)
    except Exception:
        conn.rollback()
        logger.exception('[extrato-online] gravar pela API falhou (%s)', banco['rotulo'])
        return {'erro': True}
    finally:
        cur.close()
        conn.close()


def _dia_pelos_vizinhos(api):
    """O lançamento do fim de semana que o cupom não datou (PIX enviado,
    tarifa, PIX sem cupom): o banco devolve na ordem em que entrou, então
    entre dois vizinhos do MESMO dia ele é desse dia. Na ponta (antes do
    primeiro datado ou depois do último) só quando o vizinho já é o primeiro
    ou o último dia possível. A direção da lista sai dos próprios vizinhos
    datados; ordem confusa -> não chuta."""
    grupos = OrderedDict()
    for tx in api:
        if len(tx.get('dias') or []) > 1:
            grupos.setdefault(tx['data_banco'], []).append(tx)
    for txs in grupos.values():
        datados = [tx['data_transacao'] for tx in txs if tx.get('dia_pelo_cupom')]
        if not datados:
            continue
        com_direcao = len(set(datados)) > 1
        if com_direcao:
            if datados == sorted(datados, reverse=True):
                txs = txs[::-1]                 # do mais antigo para o mais novo
            elif datados != sorted(datados):
                continue
        dia = [tx['data_transacao'] if tx.get('dia_pelo_cupom') else None for tx in txs]
        for i, tx in enumerate(txs):
            if dia[i] is not None:
                continue
            antes = next((d for d in reversed(dia[:i]) if d), None)
            depois = next((d for d in dia[i + 1:] if d), None)
            if antes and depois:
                if antes != depois:
                    continue
            elif not com_direcao:
                continue                        # sem direção, a ponta é chute
            elif depois and depois != tx['dias'][0]:
                continue
            elif antes and antes != tx['dias'][-1]:
                continue
            tx['data_transacao'] = antes or depois
            tx['dia_pelo_cupom'] = 'ordem do banco'


def _so_do_periodo(linhas, r, ini, fim):
    """Deixa só o que entrou em [ini, fim]. O lançamento sem dia certo
    ('entrou entre 24/10 e 25/10') fica se um dos dias possíveis cai no
    período. O que só o sistema tem fica pela data do OFX. O quadro banco ×
    sistema é refeito sobre o que ficou."""
    def no_periodo(tx):
        if len(tx.get('dias') or []) > 1 and not tx.get('dia_pelo_cupom'):
            return any(ini <= d <= fim for d in tx['dias'])
        return ini <= tx['data_transacao'] <= fim
    linhas = [l for l in linhas if no_periodo(l['tx'])]
    ficou = {id(l['tx']) for l in linhas}
    r = dict(r, casados=[(a, o) for a, o in r['casados'] if id(a) in ficou],
             so_api=[a for a in r['so_api'] if id(a) in ficou],
             so_ofx=[o for o in r['so_ofx'] if ini <= o['data_transacao'] <= fim])
    return linhas, r


def _consultar(banco, ini, fim, hoje):
    from integrations.banco_api import (BancoAuthError, BancoError, SemCredencial,
                                        dias_possiveis, proximo_dia_util)
    from integrations.extrato_cupom import casar as casar_cupons
    mod = banco['modulo']()
    t0 = time.monotonic()
    try:
        # Tela só MOSTRA: o dia de hoje pode entrar (ainda mudando no banco).
        # No fim de semana/feriado o Sicoob lança o que entra com a data do
        # próximo dia útil: pedido só até o fim, o sábado (datado segunda) não
        # vinha. Pede até o próximo dia útil e depois separa pelo dia real.
        fim_banco = fim
        if banco.get('fds_no_dia_util'):
            fim_banco = proximo_dia_util(fim)
        api = mod.ler(ini, fim_banco, incluir_hoje=True)
        t1 = time.monotonic()
        gravou = _gravar(banco, mod, api)
        r = mod.comparar(api, ini, fim_banco)   # banco × OFX: pela data do banco
        if banco.get('fds_no_dia_util'):
            # Para a tela, o dia em que ENTROU. Um dia só possível (sábado
            # consultado no sábado) -> é ele; vários (domingo, segunda) -> o
            # cupom decide em extrato_cupom.casar.
            for tx in api:
                dias = dias_possiveis(tx['data_transacao'], hoje)
                if dias != [tx['data_transacao']]:
                    tx['data_banco'] = tx['data_transacao']
                    tx['dias'] = dias
                    tx['data_transacao'] = dias[0] if len(dias) == 1 else tx['data_banco']
    except SemCredencial as exc:
        return {'erro': f'Falta configurar o acesso ao banco: {exc}'}
    except BancoAuthError as exc:
        return {'erro': f'O banco recusou o acesso (credencial ou certificado): {exc}'}
    except (BancoError, ValueError) as exc:
        return {'erro': f'Não foi possível ler o extrato: {exc}'}
    t2 = time.monotonic()

    linhas = [{'tx': a, 'ofx': o, 'no_sistema': True,
               'texto_igual': mod.mesmo_texto_do_ofx(a, o)} for a, o in r['casados']]
    linhas += [{'tx': a, 'ofx': None, 'no_sistema': False, 'texto_igual': None}
               for a in r['so_api']]
    ordem = {id(a): i for i, a in enumerate(api)}       # a ordem do banco
    linhas.sort(key=lambda l: (l['tx']['data_transacao'], l['tx'].get('hora') or '',
                               ordem.get(id(l['tx']), 0)))
    for l in linhas:
        tx = l['tx']
        # Quem pagou / recebeu: cada adapter já entrega separado do texto.
        l['quem'] = tx.get('quem') or ''
        l['doc_pessoa'] = tx.get('doc_pessoa') or ''
        l['cat'] = _categoria(tx)
        l['sinal'] = tx['valor'] if tx['tipo'] == 'CREDIT' else -tx['valor']
        doc = tx['numero_documento'] or ''
        l['doc'] = doc if any(c.isdigit() for c in doc) else None   # 'Pix' não diz nada
        # Para quem foi, segundo a conciliação do sistema (ver banco_api.conciliacao_de).
        l['conc'] = (l['ofx'] or {}).get('conciliacao')
        l['cupom'] = None

    # Sem nome, só documento (PIX enviado do Sicoob): o nome vem do sistema.
    try:
        from integrations.banco_api import nomes_por_documento
        sem_nome = [l for l in linhas if not l['quem'] and l['doc_pessoa'] and '*' not in l['doc_pessoa']]
        achados = nomes_por_documento([l['doc_pessoa'] for l in sem_nome])
        for l in sem_nome:
            n = achados.get(''.join(ch for ch in l['doc_pessoa'] if ch.isdigit()))
            if n:
                l['quem'], l['quem_fonte'] = n
    except Exception:
        logger.exception('[extrato-online] busca de nome por CNPJ falhou')
    for l in linhas:
        l['mensagem'] = l['tx'].get('mensagem') or ''

    # PIX recebido ⇄ cupom do abastecimento (Vendas Migradas).
    pix_in = [l for l in linhas if l['cat'] == 'pix_in']
    sem_pix = []
    if pix_in:
        try:
            # Cupons de todos os dias em que esses PIX podem ter entrado: o
            # domingo consultado como "Ontem" (sábado) ainda tem de achar o
            # cupom de domingo, senão casa com um de sábado de mesmo valor.
            fim_cupom = max([fim] + [d for l in pix_in for d in (l['tx'].get('dias') or [])])
            casa, sem_pix = casar_cupons([l['tx'] for l in pix_in], ini, fim_cupom,
                                         banco.get('credenciadora'))
            for l in pix_in:
                l['cupom'] = casa.get(id(l['tx']))
            sem_pix = [c for c in sem_pix if ini <= c['dh_emissao'].date() <= fim]
        except Exception:
            # O cupom é complemento: se a consulta das vendas falhar, o extrato
            # continua valendo e a tela mostra sem ele.
            logger.exception('[extrato-online] casamento PIX x cupom falhou')
    if banco.get('fds_no_dia_util'):
        # Sábado e domingo vêm juntos (datados segunda): cada lançamento fica
        # no dia em que entrou — o cupom diz, ou a ordem do banco entre os
        # vizinhos —, e o período mostra só os seus dias.
        _dia_pelos_vizinhos(api)
        linhas, r = _so_do_periodo(linhas, r, ini, fim)
        pix_in = [l for l in pix_in if any(l is m for m in linhas)]
        linhas.sort(key=lambda l: (l['tx']['data_transacao'], l['tx'].get('hora') or '',
                                   ordem.get(id(l['tx']), 0)))
    t3 = time.monotonic()
    logger.info('[extrato-online] %s %s..%s: banco %.1fs, sistema %.1fs, cupons %.1fs, %d lançamentos',
                banco['rotulo'], ini, fim, t1 - t0, t2 - t1, t3 - t2, len(linhas))

    # Um card por tipo de movimento, com a soma, a conferência e o dia a dia.
    cards = OrderedDict()
    for k, meta in CATEGORIAS.items():
        ls = [l for l in linhas if l['cat'] == k]
        if not ls:
            continue
        por_dia = OrderedDict()
        for l in ls:
            d = l['tx']['data_transacao']
            por_dia[d] = por_dia.get(d, 0.0) + abs(l['sinal'])
        cards[k] = dict(meta, chave=k, linhas=ls, n=len(ls),
                        total=sum(abs(l['sinal']) for l in ls),
                        entrada=ls[0]['tx']['tipo'] == 'CREDIT',
                        n_sistema=sum(1 for l in ls if l['no_sistema']),
                        n_falta=sum(1 for l in ls if not l['no_sistema']),
                        por_dia=por_dia, ultimo=ls[-1]['tx']['data_transacao'])

    entradas = sum(l['tx']['valor'] for l in linhas if l['tx']['tipo'] == 'CREDIT')
    saidas = sum(l['tx']['valor'] for l in linhas if l['tx']['tipo'] == 'DEBIT')
    # O lado do sistema somado à parte — a conclusão compara os dois totais,
    # não só a contagem de pares.
    ofx = [o for _a, o in r['casados']] + r['so_ofx']
    ofx_ent = sum(float(o['valor']) for o in ofx if o['tipo'] == 'CREDIT')
    ofx_sai = sum(float(o['valor']) for o in ofx if o['tipo'] == 'DEBIT')
    so_hoje = ini == fim == hoje
    bateu = (not r['so_api'] and not r['so_ofx']
             and round(entradas, 2) == round(ofx_ent, 2) and round(saidas, 2) == round(ofx_sai, 2))
    por_dia = OrderedDict()
    for l in linhas:
        d = l['tx']['data_transacao']
        por_dia[d] = por_dia.get(d, 0.0) + l['sinal']
    cup = [l['cupom'] or {} for l in pix_in]
    return {'consultado': True, 'linhas': linhas, 'cards': cards, 'so_ofx': r['so_ofx'],
            'gravou': gravou,
            # o saldo que o banco informou na mesma resposta (banco_api.Extrato)
            'saldo_banco': {'valor': getattr(api, 'saldo', None),
                            'quando': getattr(api, 'saldo_quando', ''),
                            'obs': getattr(api, 'saldo_obs', '')},
            'inclui_hoje': fim >= hoje, 'so_hoje': so_hoje, 'por_dia': por_dia,
            'consultado_em': datetime.now().strftime('%H:%M'),
            'tempos': {'banco': t1 - t0, 'sistema': t2 - t1, 'cupons': t3 - t2},
            'pix': {'n': len(pix_in), 'total': sum(l['tx']['valor'] for l in pix_in),
                    'casou': sum(1 for c in cup if c.get('status') == 'casou'),
                    'provavel': sum(1 for c in cup if c.get('status') == 'provavel'),
                    'possiveis': sum(1 for c in cup if c.get('status') == 'possiveis'),
                    'sem': sum(1 for c in cup if c.get('status') == 'sem'),
                    'cupons_sem_pix': sem_pix},
            'r': {'total': len(linhas), 'no_sistema': len(r['casados']),
                  'faltam': len(r['so_api']), 'so_ofx': len(r['so_ofx']),
                  'texto_igual': sum(1 for l in linhas if l['texto_igual']),
                  'entradas': entradas, 'saidas': saidas,
                  'ofx_total': len(ofx), 'ofx_ent': ofx_ent, 'ofx_sai': ofx_sai,
                  'bateu': bateu}}
