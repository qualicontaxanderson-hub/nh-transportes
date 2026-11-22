"""
Conf. Transportes (21/11/2026) — quanto cada caminhão dá.

Os números são EXATAMENTE os do bloco CAMINHÕES da Conferência de Despesas
(mesma conta: _montar_relatorio filtrado no título CAMINHÕES). Aqui só muda a
leitura: receita do frete primeiro, depois os custos do caminhão, depois os
motoristas, e no fim o resultado (lucro ou prejuízo).

Rota:
  GET  /relatorios/conf_transportes
  POST /relatorios/conf_transportes/frete_simulado  (R$/L simulado por cliente e mês)
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


def _litros_por_destino(conn, data_inicio, data_fim):
    """Litros de cada caminhão por mês, separados por quem recebeu:
    cada cliente que não paga frete (valor do frete = 0, ex.: NH GTBA) numa
    linha, e todo o resto (frete cobrado) em "Geral". Mesma conta de litros
    da Conf. Despesas (COALESCE(quantidade_manual, q.valor, 0)), então a soma
    das linhas bate com o total.
    Retorna ({vid: {nome: {mk: litros}}}, {nome: cliente_id})."""
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT f.veiculos_id AS vid, DATE_FORMAT(f.data_frete, '%Y%m') AS mk,
               CASE WHEN COALESCE(f.valor_total_frete, 0) = 0
                    THEN COALESCE(NULLIF(c.nome_fantasia, ''), c.razao_social, 'Sem cliente')
                    ELSE NULL END AS destino,
               CASE WHEN COALESCE(f.valor_total_frete, 0) = 0 THEN c.id ELSE NULL END AS cid,
               COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)), 0) AS litros
          FROM fretes f
          LEFT JOIN quantidades q ON q.id = f.quantidade_id
          LEFT JOIN clientes c ON c.id = f.clientes_id
         WHERE f.data_frete BETWEEN %s AND %s AND f.veiculos_id IS NOT NULL
         GROUP BY 1, 2, 3, 4
    """, (data_inicio, data_fim))
    out, ids = {}, {}
    for r in cur.fetchall():
        nome = r['destino'] or 'Geral'
        if r['cid']:
            ids[nome] = r['cid']
        d = out.setdefault(r['vid'], {}).setdefault(nome, {})
        d[r['mk']] = d.get(r['mk'], 0.0) + float(r['litros'])
    cur.close()
    return out, ids


# Frete de terceiro SIMULADO (pedido do Anderson, 22/11/2026): para cada
# cliente que não paga frete, quanto custaria pagar um terceiro (R$ por litro,
# um valor por mês, digitado na tela) e quanto a frota economizou com isso.
_DDL_SIM = """
CREATE TABLE IF NOT EXISTS conf_transp_frete_sim (
    cliente_id     INT          NOT NULL,
    mes            CHAR(6)      NOT NULL COMMENT 'YYYYMM',
    valor_litro    DECIMAL(10,4) NOT NULL,
    atualizado_por VARCHAR(80)  NULL,
    atualizado_em  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (cliente_id, mes)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def _frete_sim(conn):
    """{(cliente_id, 'YYYYMM'): R$/L}. CREATE TABLE faz commit: fora de transação."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(_DDL_SIM)
        cur.execute("SELECT cliente_id, mes, valor_litro FROM conf_transp_frete_sim")
        return {(r['cliente_id'], r['mes']): float(r['valor_litro']) for r in cur.fetchall()}
    finally:
        cur.close()


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
                               'total': sum(resto.values()),
                               'drill': ({'tit': block.get('titulo_id'), 'cat': row.get('categoria_id'),
                                          'sub': 'nenhuma'} if row.get('drill') else None)})
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
        litros_dest, cli_ids = _litros_por_destino(conn, data_inicio, data_fim)
        tarifas = _frete_sim(conn)
    finally:
        conn.close()

    ctx = _montar_relatorio(data_inicio, data_fim, [], titulo_ids) if titulo_ids else {'months': [], 'blocks': []}
    months = ctx['months']
    trucks, outros = _caminhoes(ctx['blocks'], months, veiculos, placas)
    # Litros transportados abertos por destino (sem frete primeiro, Geral por último)
    for t in trucks:
        det = []
        for nome, bym in litros_dest.get(t['vid'], {}).items():
            b = {m['key']: bym.get(m['key'], 0.0) for m in months}
            tot = sum(b.values())
            if abs(tot) >= 0.5:
                det.append({'nome': nome, 'by_month': b, 'total': tot})
        det.sort(key=lambda d: (d['nome'] == 'Geral', -d['total']))
        t['litros_det'] = det if len(det) > 1 or (det and det[0]['nome'] != 'Geral') else []

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

    # Custo dos transportes sem cobrança (conta do Anderson, 21/11/2026):
    # o RESULTADO do caminhão no mês é o que custou levar os litros sem
    # cobrança. Prejuízo 7.588,26 ÷ 279.000 L do NH = R$ 0,0272/L. Mês com
    # lucro dá custo negativo (= o frete cobrado pagou tudo e ainda sobrou).
    # Com mais de um cliente sem cobrança no caminhão, divide pelos litros.
    # Na frota: resultado de todos ÷ litros sem cobrança de todos; o que não
    # cabe num caminhão (caminhão sem litro sem cobrança no mês, frete de
    # terceiros) entra numa linha de ajuste, para o total fechar.
    sem_cob = {}
    livre_f = _z(months)                       # litros sem cobrança da frota
    alocado = _z(months)                       # custo já posto nos caminhões
    for t in trucks:
        nome = t['nome'] or ''
        t['curto'] = nome.split('MODELO', 1)[1].strip() if 'MODELO' in nome.upper() else nome
        livres = [d for d in t['litros_det'] if d['nome'] != 'Geral']
        livre = {m['key']: sum(d['by_month'][m['key']] for d in livres) for m in months}
        cpl, c_tot, l_tot = {}, 0.0, 0.0
        for m in months:
            k = m['key']
            if livre[k] >= 0.5:
                cpl[k] = -t['lucro'][k] / livre[k]
                c_tot += -t['lucro'][k]
                l_tot += livre[k]
                alocado[k] += -t['lucro'][k]
                livre_f[k] += livre[k]
            else:
                cpl[k] = None
        t['cpl'] = cpl
        t['cpl_tot'] = (c_tot / l_tot) if l_tot >= 0.5 else None
        for d in t['litros_det']:
            if d['nome'] == 'Geral':
                d['custo'], d['custo_tot'] = _z(months), 0.0
                continue
            d['custo'] = {m['key']: d['by_month'][m['key']] * (cpl[m['key']] or 0.0) for m in months}
            d['custo_tot'] = sum(d['custo'].values())
            sc = sem_cob.setdefault(d['nome'], {'nome': d['nome'], 'linhas': [],
                                                'litros': _z(months), 'custo': _z(months),
                                                'ajuste': _z(months)})
            sc['linhas'].append({'caminhao': t['curto'], 'placa': t['placa'],
                                 'litros': d['by_month'], 'custo': d['custo'],
                                 'litros_tot': d['total'], 'custo_tot': d['custo_tot']})
            for m in months:
                sc['litros'][m['key']] += d['by_month'][m['key']]
                sc['custo'][m['key']] += d['custo'][m['key']]
    # ajuste: resultado da frota que não ficou em nenhum caminhão, dividido
    # entre os clientes sem cobrança pelos litros do mês
    for m in months:
        k = m['key']
        resto = -frota['lucro'][k] - alocado[k]
        if livre_f[k] < 0.5 or abs(resto) < 0.005:
            continue
        for sc in sem_cob.values():
            v = resto * sc['litros'][k] / livre_f[k]
            sc['ajuste'][k] += v
            sc['custo'][k] += v
    sem_cobranca = sorted(sem_cob.values(), key=lambda x: -sum(x['litros'].values()))
    for sc in sem_cobranca:
        sc['litros_tot'] = sum(sc['litros'].values())
        sc['custo_tot'] = sum(sc['custo'].values())
        sc['ajuste_tot'] = sum(sc['ajuste'].values())
        sc['tem_ajuste'] = any(abs(v) >= 0.005 for v in sc['ajuste'].values())
        # frete de terceiro simulado: litros × R$/L do mês; economia = esse frete − nosso custo
        sc['cid'] = cli_ids.get(sc['nome'])
        sc['tarifa'], sc['frete_sim'], sc['economia'] = {}, {}, {}
        f_tot = e_tot = l_tar = 0.0
        for m in months:
            k = m['key']
            t_ = tarifas.get((sc['cid'], k))
            sc['tarifa'][k] = t_
            if t_ is None:
                sc['frete_sim'][k] = sc['economia'][k] = None
                continue
            fs = sc['litros'][k] * t_
            sc['frete_sim'][k] = fs
            sc['economia'][k] = fs - sc['custo'][k]
            f_tot += fs
            e_tot += fs - sc['custo'][k]
            l_tar += sc['litros'][k]
        sc['tem_sim'] = any(v is not None for v in sc['tarifa'].values())
        sc['frete_sim_tot'] = f_tot
        sc['economia_tot'] = e_tot
        sc['tarifa_media'] = (f_tot / l_tar) if l_tar >= 0.5 else None
    frota_cpl = {m['key']: (-frota['lucro'][m['key']] / livre_f[m['key']])
                 if livre_f[m['key']] >= 0.5 else None for m in months}
    _c = sum(-frota['lucro'][m['key']] for m in months if livre_f[m['key']] >= 0.5)
    _l = sum(livre_f.values())
    frota_cpl_tot = (_c / _l) if _l >= 0.5 else None

    # Só os meses com movimento
    ativos = [m for m in months
              if any(abs(frota[x][m['key']]) >= 0.005 for x in ('receita', 'custos', 'mot'))]

    return render_template(
        'relatorios/conf_transportes.html',
        data_inicio=data_inicio, data_fim=data_fim,
        months=ativos, trucks=trucks, outros=outros,
        frota=frota, frota_tot=frota_tot,
        frota_cpl=frota_cpl, frota_cpl_tot=frota_cpl_tot,
        sem_cobranca=sem_cobranca,
    )

@bp.route('/conf_transportes/frete_simulado', methods=['POST'])
@login_required
@admin_required
def conf_transportes_frete_simulado():
    """Grava (ou apaga, com valor vazio) o R$/L simulado de um cliente sem
    cobrança para um ou mais meses. JSON: {cliente_id, meses: ['YYYYMM'], valor}."""
    from flask_login import current_user
    d = request.get_json(silent=True) or {}
    try:
        cid = int(d.get('cliente_id'))
        meses = [str(m) for m in (d.get('meses') or [])]
        assert meses and all(len(m) == 6 and m.isdigit() and 1 <= int(m[4:]) <= 12 for m in meses)
        txt = str(d.get('valor') or '').strip().replace('R$', '').replace(' ', '')
        if ',' in txt:
            txt = txt.replace('.', '').replace(',', '.')
        valor = float(txt) if txt else None
        assert valor is None or 0 <= valor < 100
    except (TypeError, ValueError, AssertionError):
        return jsonify({'ok': False, 'erro': 'valor inválido (ex.: 0,13)'}), 400
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(_DDL_SIM)
        for m in meses:
            if valor is None:
                cur.execute("DELETE FROM conf_transp_frete_sim WHERE cliente_id=%s AND mes=%s", (cid, m))
            else:
                cur.execute("""INSERT INTO conf_transp_frete_sim (cliente_id, mes, valor_litro, atualizado_por)
                               VALUES (%s, %s, %s, %s)
                               ON DUPLICATE KEY UPDATE valor_litro=VALUES(valor_litro),
                                                       atualizado_por=VALUES(atualizado_por)""",
                            (cid, m, round(valor, 4), getattr(current_user, 'username', None)))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify({'ok': True})


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
                if frac == 0:
                    continue   # nada deste mes ficou neste caminhao
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
