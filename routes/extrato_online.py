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

    hoje = date.today()
    ctx['hoje'] = hoje
    if request.args.get('consultar'):
        if fim > hoje:
            ctx['erro'] = f'A data final não pode passar de hoje ({hoje:%d/%m}).'
        elif ini > fim:
            ctx['erro'] = 'A data inicial está depois da final.'
        elif (fim - ini).days + 1 > MAX_DIAS:
            ctx['erro'] = f'Período máximo de {MAX_DIAS} dias por consulta.'
        else:
            ctx.update(_consultar(banco['modulo'](), ini, fim))
    return render_template('extrato_online/index.html', **ctx)


def _consultar(mod, ini, fim):
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

    # Uma lista só, por dia, na ordem do banco — cada linha com o seu selo.
    linhas = [{'tx': a, 'ofx': o, 'no_sistema': True,
               'texto_igual': mod.mesmo_texto_do_ofx(a, o)} for a, o in r['casados']]
    linhas += [{'tx': a, 'ofx': None, 'no_sistema': False, 'texto_igual': None}
               for a in r['so_api']]
    for l in linhas:
        l['partes'] = mod.partes_complemento(l['tx']['memo'])
        doc = l['tx']['numero_documento'] or ''
        l['doc'] = doc if any(c.isdigit() for c in doc) else None   # 'Pix' não diz nada
    ordem = {id(a): i for i, a in enumerate(api)}       # a ordem do banco
    linhas.sort(key=lambda l: (l['tx']['data_transacao'], ordem.get(id(l['tx']), 0)))
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
    # O lado do sistema somado à parte — a conclusão compara os dois totais,
    # não só a contagem de pares.
    ofx = [o for _a, o in r['casados']] + r['so_ofx']
    ofx_ent = sum(float(o['valor']) for o in ofx if o['tipo'] == 'CREDIT')
    ofx_sai = sum(float(o['valor']) for o in ofx if o['tipo'] == 'DEBIT')
    bateu = (not r['so_api'] and not r['so_ofx']
             and round(entradas, 2) == round(ofx_ent, 2) and round(saidas, 2) == round(ofx_sai, 2))
    return {'consultado': True, 'dias': dias, 'so_ofx': r['so_ofx'],
            'r': {'total': len(linhas), 'no_sistema': len(r['casados']),
                  'faltam': len(r['so_api']), 'so_ofx': len(r['so_ofx']),
                  'texto_igual': sum(1 for l in linhas if l['texto_igual']),
                  'entradas': entradas, 'saidas': saidas,
                  'ofx_total': len(ofx), 'ofx_ent': ofx_ent, 'ofx_sai': ofx_sai,
                  'bateu': bateu}}
