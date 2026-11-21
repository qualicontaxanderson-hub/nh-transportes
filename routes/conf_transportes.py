"""
Conf. Transportes (21/11/2026) — quanto cada caminhão dá.

Os números são EXATAMENTE os do bloco CAMINHÕES da Conferência de Despesas
(mesma conta: _montar_relatorio filtrado no título CAMINHÕES). Aqui só muda a
leitura: receita do frete primeiro, depois os custos do caminhão, depois os
motoristas, e no fim o resultado (lucro ou prejuízo).

Rota:
  GET /relatorios/conf_transportes
"""
from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from routes.conf_despesas import (_ascii_upper, _default_period, _montar_relatorio,
                                  _fetch_veiculos_motoristas, _compile_veiculo_matchers,
                                  _match_veiculo_row)
from utils.db import get_db_connection

bp = Blueprint('conf_transportes', __name__, url_prefix='/relatorios')


def _titulos_caminhoes(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nome FROM titulos_despesas")
    ids = [str(r['id']) for r in cur.fetchall()
           if 'CAMINHAO' in _ascii_upper(r['nome']) or 'CAMINHOES' in _ascii_upper(r['nome'])]
    cur.close()
    return ids


def _placas(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, placa, placa_carreta, modelo FROM veiculos")
    out = {r['id']: r for r in cur.fetchall()}
    cur.close()
    return out


def _z(months):
    return {m['key']: 0.0 for m in months}


def _caminhoes(blocks, months, veiculos, placas):
    """Transforma o bloco CAMINHÕES em: um quadro por caminhão + outros custos."""
    matchers = _compile_veiculo_matchers(veiculos) if veiculos else []
    mot_por_vid = {v['veiculo_id']: v.get('nome') for v in veiculos}
    trucks, outros = [], []
    for block in blocks:
        if not block.get('is_caminhoes'):
            continue
        usados = set()
        for row in block['rows']:
            vdata = _match_veiculo_row(row.get('categoria_nome', ''), matchers, used_vehicle_ids=usados) \
                if matchers else None
            if not vdata:
                outros.append({'nome': row['categoria_nome'], 'by_month': dict(row['by_month']),
                               'total': row['total']})
                continue
            vid = vdata['veiculo_id']
            usados.add(vid)
            receita, litros = _z(months), _z(months)
            mot = None
            custos = []
            soma_custos = _z(months)
            for sc in row['subcats']:
                if sc.get('is_receita'):
                    receita = {k: -v for k, v in sc['by_month'].items()}
                elif sc.get('is_litros'):
                    litros = dict(sc['by_month'])
                elif sc.get('is_group'):
                    mot = sc
                else:
                    custos.append({'nome': sc['subcat_nome'], 'by_month': dict(sc['by_month']),
                                   'total': sc['total']})
                    for k, v in sc['by_month'].items():
                        soma_custos[k] += v
            mot_bym = dict(mot['by_month']) if mot else _z(months)
            # o que foi lançado na categoria sem subcategoria
            resto = {k: row['by_month'].get(k, 0.0) + receita[k] - mot_bym[k] - soma_custos[k]
                     for k in soma_custos}
            if any(abs(v) >= 0.005 for v in resto.values()):
                custos.append({'nome': 'OUTRAS DESPESAS', 'by_month': resto,
                               'total': sum(resto.values())})
                for k, v in resto.items():
                    soma_custos[k] += v
            custos.sort(key=lambda c: -c['total'])
            pessoas = []
            if mot:
                for p in mot.get('children', []):
                    pessoas.append({'nome': p['subcat_nome'], 'by_month': p['by_month'],
                                    'total': p['total'],
                                    'itens': [{'nome': i['subcat_nome'], 'by_month': i['by_month'],
                                               'total': i['total']} for i in p.get('children', [])]})
            lucro = {k: -row['by_month'].get(k, 0.0) for k in soma_custos}
            pv = placas.get(vid, {})
            t = {
                'vid': vid, 'nome': row['categoria_nome'],
                'placa': pv.get('placa'), 'placa_carreta': pv.get('placa_carreta'),
                'motorista': mot_por_vid.get(vid),
                'receita': receita, 'litros': litros,
                'custos': custos, 'custos_bym': soma_custos,
                'mot_bym': mot_bym, 'pessoas': pessoas,
                'lucro': lucro,
            }
            t['tot'] = {
                'receita': sum(receita.values()), 'litros': sum(litros.values()),
                'custos': sum(soma_custos.values()), 'mot': sum(mot_bym.values()),
                'lucro': sum(lucro.values()),
            }
            trucks.append(t)
    trucks.sort(key=lambda t: -t['tot']['receita'])
    return trucks, outros


@bp.route('/conf_transportes', methods=['GET'])
@login_required
@admin_required
def conf_transportes():
    data_inicio = request.args.get('data_inicio', '').strip()
    data_fim = request.args.get('data_fim', '').strip()
    if not data_inicio or not data_fim:
        data_inicio, data_fim = _default_period()

    conn = get_db_connection()
    try:
        titulo_ids = _titulos_caminhoes(conn)
        veiculos, _ = _fetch_veiculos_motoristas(conn)
        placas = _placas(conn)
    finally:
        conn.close()

    ctx = _montar_relatorio(data_inicio, data_fim, [], titulo_ids) if titulo_ids else {'months': [], 'blocks': []}
    months = ctx['months']
    trucks, outros = _caminhoes(ctx['blocks'], months, veiculos, placas)

    # Frota inteira = caminhões + outros custos de transporte (frete de terceiros…)
    frota = {'receita': _z(months), 'custos': _z(months), 'mot': _z(months),
             'lucro': _z(months), 'litros': _z(months)}
    for t in trucks:
        for k in frota['receita']:
            frota['receita'][k] += t['receita'][k]
            frota['custos'][k] += t['custos_bym'][k]
            frota['mot'][k] += t['mot_bym'][k]
            frota['lucro'][k] += t['lucro'][k]
            frota['litros'][k] += t['litros'][k]
    for o in outros:
        for k in frota['custos']:
            frota['custos'][k] += o['by_month'].get(k, 0.0)
            frota['lucro'][k] -= o['by_month'].get(k, 0.0)
    frota_tot = {k: sum(v.values()) for k, v in frota.items()}

    # Só os meses com movimento
    ativos = [m for m in months
              if any(abs(frota[x][m['key']]) >= 0.005 for x in ('receita', 'custos', 'mot'))]

    return render_template(
        'relatorios/conf_transportes.html',
        data_inicio=data_inicio, data_fim=data_fim,
        months=ativos, trucks=trucks, outros=outros,
        frota=frota, frota_tot=frota_tot,
    )
