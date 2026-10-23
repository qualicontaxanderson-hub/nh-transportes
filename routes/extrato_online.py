"""
Extrato On-Line — consulta o extrato direto na API do banco (Financeiro).

SÓ LEITURA. Busca o período no banco e mostra, lançamento a lançamento, se
ele JÁ ESTÁ no sistema (veio pelo OFX) ou se falta. Não grava nada em
bank_transactions: a gravação pela API espera a comparação provar que dá
para substituir o OFX sem duplicar e sem perder a conciliação automática
(ver integrations/sicoob_extrato.py).

Mesma casca do /relatorios/conf_cartoes: filtro em cartão, régua de
períodos, o período inteiro num painel e um card + um quadro por TIPO de
movimento (PIX recebido, cartões, transferências...). O tipo sai do próprio
texto do banco — ver _categoria().

Um banco novo é uma entrada em BANCOS: rótulo, conta e o módulo que sabe
ler() e comparar().
"""
from collections import OrderedDict
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

bp = Blueprint('extrato_online', __name__, url_prefix='/banco/extrato-online')

MAX_DIAS = 31
MESES_PT = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']


def _sicoob():
    from integrations import sicoob_extrato
    return sicoob_extrato


BANCOS = {
    'sicoob-nh': {'rotulo': 'SICOOB - NH', 'conta': '5024 / 148.186-0', 'modulo': _sicoob},
}

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
    ('outros_out', {'nome': 'Outras saídas',   'icone': 'bi-dash-circle',       'cor': '#64748b'}),
])


def _categoria(tx):
    """Tipo do movimento pelo texto do banco. Medido na 1ª consulta real
    (16-22/10/2026): 'PIX RECEBIDO - OUTRA IF', 'CR COMPRAS VISA ELECTRON',
    'CR ANTECIPAÇÃO MASTERCARD', 'CRED.TRANSF.CONTAS INTERCREDIS',
    'TARIFA RECEBIMENTO PIX'. O que não se reconhece cai em "Outras"."""
    from integrations.sicoob_extrato import _normal
    d = _normal(f"{tx.get('descricao')} {tx.get('memo')}")
    entrada = tx['tipo'] == 'CREDIT'
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
            ctx.update(_consultar(banco['modulo'](), ini, fim, hoje))
    return render_template('extrato_online/index.html', **ctx)


def _consultar(mod, ini, fim, hoje):
    try:
        # Tela só MOSTRA: o dia de hoje pode entrar (ainda mudando no banco).
        api = mod.ler(ini, fim, incluir_hoje=True)
        r = mod.comparar(api, ini, fim)
    except mod.SemCredencial as exc:
        return {'erro': f'Falta configurar o acesso ao banco: {exc}'}
    except mod.SicoobAuthError as exc:
        return {'erro': f'O banco recusou o acesso (credencial ou certificado): {exc}'}
    except (mod.SicoobError, ValueError) as exc:
        return {'erro': f'Não foi possível ler o extrato: {exc}'}

    linhas = [{'tx': a, 'ofx': o, 'no_sistema': True,
               'texto_igual': mod.mesmo_texto_do_ofx(a, o)} for a, o in r['casados']]
    linhas += [{'tx': a, 'ofx': None, 'no_sistema': False, 'texto_igual': None}
               for a in r['so_api']]
    ordem = {id(a): i for i, a in enumerate(api)}       # a ordem do banco
    linhas.sort(key=lambda l: (l['tx']['data_transacao'], ordem.get(id(l['tx']), 0)))
    for l in linhas:
        tx = l['tx']
        partes = mod.partes_complemento(tx['memo'])
        # 'Recebimento Pix · Nome · CPF': o nome é o que se procura; o resto é detalhe.
        l['quem'] = partes[1] if len(partes) > 1 else (partes[0] if partes else '')
        l['doc_pessoa'] = partes[2] if len(partes) > 2 else ''
        l['cat'] = _categoria(tx)
        l['sinal'] = tx['valor'] if tx['tipo'] == 'CREDIT' else -tx['valor']
        doc = tx['numero_documento'] or ''
        l['doc'] = doc if any(c.isdigit() for c in doc) else None   # 'Pix' não diz nada

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
    return {'consultado': True, 'linhas': linhas, 'cards': cards, 'so_ofx': r['so_ofx'],
            'inclui_hoje': fim >= hoje, 'so_hoje': so_hoje, 'por_dia': por_dia,
            'r': {'total': len(linhas), 'no_sistema': len(r['casados']),
                  'faltam': len(r['so_api']), 'so_ofx': len(r['so_ofx']),
                  'texto_igual': sum(1 for l in linhas if l['texto_igual']),
                  'entradas': entradas, 'saidas': saidas,
                  'ofx_total': len(ofx), 'ofx_ent': ofx_ent, 'ofx_sai': ofx_sai,
                  'bateu': bateu}}
