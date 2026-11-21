"""
Conf. Transportes (21/11/2026) — quanto cada caminhão dá.

Os números são EXATAMENTE os do bloco CAMINHÕES da Conferência de Despesas
(mesma conta: _montar_relatorio filtrado no título CAMINHÕES). Aqui só muda a
leitura: receita do frete primeiro, depois os custos do caminhão, depois os
motoristas, e no fim o resultado (lucro ou prejuízo).

Rota:
  GET /relatorios/conf_transportes
"""
from calendar import monthrange
from datetime import date

from flask import Blueprint, jsonify, render_template, request
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


def _drill_mot(subcat_id):
    """'comissao_<vid>_<mid>' / 'rub_<vid>_<mid>_<rid>' -> o que abrir ao clicar."""
    try:
        p = str(subcat_id).split('_')
        if p[0] == 'comissao':
            return {'tipo': 'com', 'vid': int(p[1]), 'mid': int(p[2]), 'rid': ''}
        if p[0] == 'rub':
            return {'tipo': 'rub', 'vid': int(p[1]), 'mid': int(p[2]), 'rid': int(p[3])}
    except (ValueError, IndexError):
        pass
    return None


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
                                   'total': sc['total'],
                                   # clicar no número abre os lançamentos (mesma lista da Conf. Despesas)
                                   'drill': ({'tit': block.get('titulo_id'), 'cat': row.get('categoria_id'),
                                              'sub': sc.get('subcat_id')} if sc.get('drill') else None)})
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
                                               'total': i['total'], 'drill': _drill_mot(i['subcat_id'])}
                                              for i in p.get('children', [])]})
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

def _meses(ini, fim, mes):
    """Lista de (ano, mes) do periodo, ou so o mes pedido (YYYYMM)."""
    if mes:
        return [(int(mes[:4]), int(mes[4:6]))]
    out, a, m = [], ini.year, ini.month
    while (a, m) <= (fim.year, fim.month):
        out.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def _moeda(v):
    return '{:,.2f}'.format(v).replace(',', 'X').replace('.', ',').replace('X', '.')


@bp.route('/conf_transportes/motorista', methods=['GET'])
@login_required
@admin_required
def conf_transportes_motorista():
    """De onde vem um número da linha do motorista (só leitura).

    tipo=rub -> lançamentos da folha daquela rubrica + quanto ficou neste caminhão
                (o mês é dividido entre os caminhões pelo nº de fretes);
    tipo=com -> os fretes do motorista neste caminhão com a comissão de cada um.
    """
    a = request.args
    try:
        ini = date.fromisoformat(a.get('data_inicio', ''))
        fim = date.fromisoformat(a.get('data_fim', ''))
        mid, vid = int(a.get('mid')), int(a.get('vid'))
        tipo = a.get('tipo')
        rid = int(a.get('rid')) if tipo == 'rub' else None
        meses = _meses(ini, fim, a.get('mes', ''))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'erro': 'filtro invalido'}), 400
    if tipo not in ('rub', 'com'):
        return jsonify({'ok': False, 'erro': 'tipo invalido'}), 400

    conn = get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        linhas = []
        if tipo == 'com':
            d1 = max(ini, date(meses[0][0], meses[0][1], 1))
            ul = meses[-1]
            d2 = min(fim, date(ul[0], ul[1], monthrange(ul[0], ul[1])[1]))
            cur.execute("""
                SELECT f.id, f.data_frete, f.comissao_motorista, f.valor_total_frete,
                       c.razao_social AS cliente
                  FROM fretes f LEFT JOIN clientes c ON c.id = f.clientes_id
                 WHERE f.motoristas_id = %s AND f.veiculos_id = %s
                   AND f.data_frete BETWEEN %s AND %s
                 ORDER BY f.data_frete, f.id
            """, (mid, vid, d1, d2))
            for r in cur.fetchall():
                linhas.append({
                    'titulo': 'Frete #%s' % r['id'] + (' · ' + r['cliente'] if r['cliente'] else ''),
                    'valor': float(r['comissao_motorista'] or 0),
                    'meta': '%s · frete R$ %s' % (r['data_frete'].strftime('%d/%m/%Y'),
                                                  _moeda(float(r['valor_total_frete'] or 0))),
                })
        else:
            cur.execute("SELECT veiculo_id FROM motoristas WHERE id = %s", (mid,))
            mr = cur.fetchone() or {}
            for (ano, m) in meses:
                mm = '%02d/%d' % (m, ano)
                cur.execute("""
                    SELECT l.id, l.valor, l.referencia, l.observacao, l.statuslancamento,
                           l.datapagamento, cl.razao_social AS empresa, r.nome AS rubrica
                      FROM lancamentosfuncionarios_v2 l
                      LEFT JOIN clientes cl ON cl.id = l.clienteid
                      LEFT JOIN rubricas r ON r.id = l.rubricaid
                     WHERE l.funcionarioid = %s AND l.tipo_funcionario = 'motorista'
                       AND l.rubricaid = %s AND l.mes = %s
                     ORDER BY l.id
                """, (mid, rid, mm))
                folha = cur.fetchall()
                if not folha:
                    continue
                cur.execute("""
                    SELECT veiculos_id AS vid, COUNT(*) AS n FROM fretes
                     WHERE motoristas_id = %s AND YEAR(data_frete) = %s AND MONTH(data_frete) = %s
                     GROUP BY veiculos_id
                """, (mid, ano, m))
                cont = {r['vid']: int(r['n']) for r in cur.fetchall()}
                tot_n = sum(cont.values())
                if tot_n:
                    n = cont.get(vid, 0)
                    frac = n / tot_n
                    rateio = ('neste caminhão: %d de %d fretes dele no mês (%s%%)'
                              % (n, tot_n, ('%.1f' % (frac * 100)).replace('.', ',')))
                else:
                    frac = 1.0 if mr.get('veiculo_id') == vid else 0.0
                    rateio = 'sem frete no mês: vai inteiro para o caminhão fixo do motorista'
                for r in folha:
                    v = float(r['valor'] or 0)
                    meta = [mm, r['empresa'] or '']
                    if r['statuslancamento']:
                        meta.append(r['statuslancamento'].title())
                    if r['datapagamento']:
                        meta.append('pago ' + r['datapagamento'].strftime('%d/%m/%Y'))
                    linhas.append({
                        'titulo': 'Folha #%s · %s' % (r['id'], r['rubrica'] or ''),
                        'obs': ' · '.join(x for x in (r['referencia'], r['observacao']) if x),
                        'meta': ' · '.join(x for x in meta if x),
                        'lancado': v,
                        'valor': round(v * frac, 2),
                        'rateio': rateio if frac < 0.9999 else '',
                    })
        cur.close()
    finally:
        conn.close()
    return jsonify({'ok': True, 'lancamentos': linhas,
                    'total': round(sum(l['valor'] for l in linhas), 2)})
