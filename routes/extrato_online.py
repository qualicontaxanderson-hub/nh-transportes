"""
Extrato On-Line — consulta o extrato direto na API do banco (Financeiro).

SÓ LEITURA. Busca o período no banco e mostra, lançamento a lançamento, se
ele JÁ ESTÁ no sistema (veio pelo OFX) ou se falta. Não grava nada em
bank_transactions: a gravação pela API espera a comparação provar que dá
para substituir o OFX sem duplicar e sem perder a conciliação automática
(ver integrations/sicoob_extrato.py).

Um banco novo é uma entrada em BANCOS: rótulo, conta e o módulo que sabe
ler() e comparar().
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

bp = Blueprint('extrato_online', __name__, url_prefix='/banco/extrato-online')

MAX_DIAS = 31


def _sicoob():
    from integrations import sicoob_extrato
    return sicoob_extrato


BANCOS = {
    'sicoob-nh': {'rotulo': 'SICOOB - NH', 'conta': '5024 / 148.186-0', 'modulo': _sicoob},
}


def _data(txt, padrao):
    try:
        return date.fromisoformat(txt) if txt else padrao
    except ValueError:
        return padrao


@bp.route('/')
@login_required
def index():
    ontem = date.today() - timedelta(days=1)
    chave = request.args.get('banco') or next(iter(BANCOS))
    banco = BANCOS.get(chave) or BANCOS[next(iter(BANCOS))]
    ini = _data(request.args.get('ini'), ontem - timedelta(days=6))
    fim = _data(request.args.get('fim'), ontem)

    ctx = {'bancos': BANCOS, 'chave': chave, 'banco': banco,
           'ini': ini, 'fim': fim, 'ontem': ontem,
           'consultado': False, 'erro': None, 'r': None, 'dias': []}

    if request.args.get('consultar'):
        if fim > ontem:
            ctx['erro'] = ('Só dá para consultar dias fechados — até ontem '
                           f'({ontem:%d/%m}). O dia de hoje ainda está mudando no banco.')
        elif ini > fim:
            ctx['erro'] = 'A data inicial está depois da final.'
        elif (fim - ini).days + 1 > MAX_DIAS:
            ctx['erro'] = f'Período máximo de {MAX_DIAS} dias por consulta.'
        else:
            ctx.update(_consultar(banco['modulo'](), ini, fim))
    return render_template('extrato_online/index.html', **ctx)


def _consultar(mod, ini, fim):
    try:
        api = mod.ler(ini, fim)
        r = mod.comparar(api, ini, fim)
    except mod.SemCredencial as exc:
        return {'erro': f'Falta configurar o acesso ao banco: {exc}'}
    except mod.SicoobAuthError as exc:
        return {'erro': f'O banco recusou o acesso (credencial ou certificado): {exc}'}
    except (mod.SicoobError, ValueError) as exc:
        return {'erro': f'Não foi possível ler o extrato: {exc}'}

    # Uma lista só, por dia, na ordem do banco — cada linha com o seu selo.
    linhas = [{'tx': a, 'ofx': o, 'no_sistema': True} for a, o in r['casados']]
    linhas += [{'tx': a, 'ofx': None, 'no_sistema': False} for a in r['so_api']]
    linhas.sort(key=lambda l: l['tx']['data_transacao'])
    dias, atual = [], None
    for l in linhas:
        d = l['tx']['data_transacao']
        if atual is None or atual['data'] != d:
            atual = {'data': d, 'linhas': [], 'saldo': 0.0}
            dias.append(atual)
        atual['linhas'].append(l)
        v = l['tx']['valor']
        atual['saldo'] += v if l['tx']['tipo'] == 'CREDIT' else -v

    entradas = sum(l['tx']['valor'] for l in linhas if l['tx']['tipo'] == 'CREDIT')
    saidas = sum(l['tx']['valor'] for l in linhas if l['tx']['tipo'] == 'DEBIT')
    return {'consultado': True, 'dias': dias, 'so_ofx': r['so_ofx'],
            'r': {'total': len(linhas), 'no_sistema': len(r['casados']),
                  'faltam': len(r['so_api']), 'so_ofx': len(r['so_ofx']),
                  'entradas': entradas, 'saidas': saidas}}
