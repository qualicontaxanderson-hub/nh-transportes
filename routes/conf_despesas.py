"""
Relatório de Conferência de Despesas.

Exibe uma matriz pivot: blocos por Título de despesa,
linhas por Categoria, colunas pelos meses do período selecionado
(JAN–DEZ) + coluna ACUM (acumulado do período).

Multi-empresa: filtro empresa_ids[] restringe quais empresas
contribuem com dados; os valores são somados em uma única matriz.

Rota:
  GET /relatorios/conf_despesas
"""
import re
import unicodedata
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('conf_despesas', __name__, url_prefix='/relatorios')

_MES_LABELS = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ascii_upper(s):
    """Converte para maiúsculas e remove acentos para comparação robusta."""
    return (unicodedata.normalize('NFD', (s or '').upper())
            .encode('ascii', 'ignore').decode('ascii'))


def _default_period():
    """Padrão: ano corrente completo (01/01 – 31/12)."""
    hoje = date.today()
    return f'{hoje.year}-01-01', f'{hoje.year}-12-31'


def _months_in_range(data_inicio_str, data_fim_str):
    """
    Retorna lista ordenada de dicts {year, month, label, key}
    para cada mês entre data_inicio e data_fim (inclusive).
    key = 'YYYYMM' string.
    """
    try:
        d_ini = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        d_fim = datetime.strptime(data_fim_str,    '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return []
    months = []
    y, m = d_ini.year, d_ini.month
    while (y, m) <= (d_fim.year, d_fim.month):
        months.append({
            'year':  y,
            'month': m,
            'label': _MES_LABELS[m - 1],
            'key':   f'{y}{m:02d}',
        })
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _empresas_list(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT DISTINCT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome
             FROM clientes c
             INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome"""
    )
    result = cur.fetchall()
    cur.close()
    return result


def _titulos_list(conn):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nome FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome"
    )
    result = cur.fetchall()
    cur.close()
    return result


def _fetch_veiculos_motoristas(conn):
    """
    Retorna uma tupla (veiculos, nome_to_vid):
      veiculos  – [{veiculo_id, nome, aliases}]
      nome_to_vid – {motorista_nome_upper: veiculo_id}  (reservado para uso futuro)

    Usado para anotar as linhas da seção CAMINHÕES no relatório conf_despesas
    com o badge do nome do motorista.
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
               v.id AS veiculo_id,
               v.caminhao,
               v.modelo,
               v.tipo_veiculo,
               v.placa,
               v.placa_carreta,
               GROUP_CONCAT(DISTINCT m.nome ORDER BY m.nome SEPARATOR ' / ') AS motorista_nome
        FROM   veiculos  v
        LEFT   JOIN motoristas m ON m.veiculo_id = v.id
        WHERE  v.caminhao IS NOT NULL
        GROUP BY v.id, v.caminhao, v.modelo, v.tipo_veiculo, v.placa, v.placa_carreta
    """)
    rows = cur.fetchall()
    cur.close()

    veiculos = []
    nome_to_vid = {}
    for r in rows:
        motorista_nome = (r.get('motorista_nome') or '').strip() or None
        veiculos.append({
            'veiculo_id': r['veiculo_id'],
            'nome': motorista_nome,
            'aliases': _build_veiculo_aliases(
                r.get('tipo_veiculo'),
                r.get('caminhao'),
                r.get('modelo'),
                r.get('placa'),
                r.get('placa_carreta'),
            ),
        })
        if motorista_nome:
            nome_to_vid[_ascii_upper(motorista_nome)] = r['veiculo_id']

    return veiculos, nome_to_vid


def _build_veiculo_aliases(tipo_veiculo, caminhao, modelo, placa=None, placa_carreta=None):
    """
    Gera aliases textuais para localizar a linha correta do caminhão no bloco.

    Ex.: caminhao='Scania', modelo='R540' → ['SCANIA R540', 'R540', 'ABC1D23']
    """
    aliases = []

    def _push(*parts):
        text = _ascii_upper(' '.join(str(p).strip() for p in parts if p and str(p).strip()))
        if text and text not in aliases:
            aliases.append(text)

    caminhao_up = _ascii_upper(caminhao)
    modelo_up = _ascii_upper(modelo)
    tipo_up = _ascii_upper(tipo_veiculo)
    placa_up = _ascii_upper(placa)
    placa_carreta_up = _ascii_upper(placa_carreta)

    if caminhao_up and modelo_up:
        _push(caminhao_up, modelo_up)
    if modelo_up:
        _push(modelo_up)
    elif caminhao_up:
        _push(caminhao_up)

    if tipo_up and caminhao_up and modelo_up:
        _push(tipo_up, caminhao_up, modelo_up)
    if tipo_up and modelo_up:
        _push(tipo_up, modelo_up)

    _push(placa_up)
    _push(placa_carreta_up)

    aliases.sort(key=lambda s: (-len(s), s))
    return aliases


def _compile_veiculo_matchers(veiculos):
    """Compila regexes ordenadas do alias mais específico para o menos específico."""
    matchers = []
    for veiculo in veiculos:
        for alias in veiculo.get('aliases', []):
            matchers.append({
                'veiculo': veiculo,
                'alias': alias,
                'pattern': re.compile(r'(?<![A-Z0-9])' + re.escape(alias) + r'(?![A-Z0-9])'),
            })
    matchers.sort(key=lambda item: (-len(item['alias']), item['alias']))
    return matchers


def _match_veiculo_row(categoria_nome, matchers):
    """Retorna o veículo cujo alias melhor casa com a categoria do bloco CAMINHÕES."""
    nome_up = _ascii_upper(categoria_nome or '')
    for matcher in matchers:
        if matcher['pattern'].search(nome_up):
            return matcher['veiculo']
    return None


def _fetch_frete_data_by_vehicle(conn, data_inicio, data_fim):
    """
    Agrega dados de fretes por veículo e mês para injeção no bloco CAMINHÕES.

    Retorna {veiculos_id: {'receita': {mk: float}, 'litros': {mk: float}}}
    onde:
      receita  = SUM(valor_total_frete) — faturamento de frete do veículo
      litros   = SUM(COALESCE(quantidade_manual, q.valor, 0)) — litros transportados
                 (inclui todos os fretes, independente de pagamento)
    mk = 'YYYYMM' string, igual ao padrão do restante do relatório.
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT
            f.veiculos_id,
            DATE_FORMAT(f.data_frete, '%Y%m')                           AS mk,
            COALESCE(SUM(f.valor_total_frete), 0)                       AS receita,
            COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)), 0) AS litros
        FROM fretes f
        LEFT JOIN quantidades q ON q.id = f.quantidade_id
        WHERE f.data_frete BETWEEN %s AND %s
          AND f.veiculos_id IS NOT NULL
        GROUP BY f.veiculos_id, DATE_FORMAT(f.data_frete, '%Y%m')
    """, (data_inicio, data_fim))
    rows = cur.fetchall()
    cur.close()

    result = {}
    for r in rows:
        vid = r['veiculos_id']
        mk  = r['mk']
        if vid not in result:
            result[vid] = {'receita': {}, 'litros': {}}
        result[vid]['receita'][mk] = float(r['receita'])
        result[vid]['litros'][mk]  = float(r['litros'])
    return result


def _fetch_litros_comprados(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna litros comprados (entregues) pelas empresas selecionadas, por mês.

    Filtra a tabela fretes por clientes_id IN (empresa_ids) — os clientes
    dos fretes são os postos/empresas que receberam a carga.
    Retorna {mk: float} onde mk = 'YYYYMM'.
    Retorna {} se empresa_ids for vazio.
    """
    if not empresa_ids:
        return {}
    cur = conn.cursor(dictionary=True)
    ph  = ','.join(['%s'] * len(empresa_ids))
    cur.execute(f"""
        SELECT
            DATE_FORMAT(f.data_frete, '%Y%m')                           AS mk,
            COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor, 0)), 0) AS litros
        FROM fretes f
        LEFT JOIN quantidades q ON q.id = f.quantidade_id
        WHERE f.data_frete BETWEEN %s AND %s
          AND f.clientes_id IN ({ph})
        GROUP BY DATE_FORMAT(f.data_frete, '%Y%m')
    """, [data_inicio, data_fim] + list(empresa_ids))
    rows = cur.fetchall()
    cur.close()
    return {r['mk']: float(r['litros']) for r in rows}


def _build_motorista_salary_rows(func_rows, months):
    """
    Constrói um mapa de linhas de salário por motorista.
    Retorna {motorista_nome_ascii_upper: row_dict} onde cada row_dict tem a
    mesma estrutura das linhas de categoria do relatório (categoria_nome,
    by_month, total, subcats) e pode ser injetado diretamente em block.rows
    logo após a linha do caminhão vinculado.
    """
    month_keys_set = {m['key'] for m in months}

    def _mes_to_mk(mes_str):
        try:
            parts = mes_str.split('/')
            return f"{parts[1]}{parts[0]}"
        except Exception:
            return None

    # nome_upper → rubrica → mk → float
    tree     = {}
    nome_map = {}  # nome_upper → nome para exibição

    for row in func_rows:
        if row['categoria_func'] != 'MOTORISTA':
            continue
        nome   = row['funcionario_nome'] or ''
        nome_up = _ascii_upper(nome)
        rub    = row['rubrica_nome']
        mk     = _mes_to_mk(row['mes'])
        if not mk or mk not in month_keys_set:
            continue
        val = float(row['valor'])
        nome_map[nome_up] = nome
        tree.setdefault(nome_up, {})
        tree[nome_up].setdefault(rub, {})
        tree[nome_up][rub][mk] = tree[nome_up][rub].get(mk, 0.0) + val

    result = {}
    for nome_up, rubs in tree.items():
        cat_by_month = {m['key']: 0.0 for m in months}
        subcats      = []
        for rub in sorted(rubs):
            rub_by_month = {}
            rub_total    = 0.0
            for m in months:
                v = rubs[rub].get(m['key'], 0.0)
                rub_by_month[m['key']] = v
                rub_total             += v
                cat_by_month[m['key']] += v
            subcats.append({
                'subcat_id':   f'mot_{nome_up}_{rub}',
                'subcat_nome': rub,
                'by_month':    rub_by_month,
                'total':       rub_total,
            })
        cat_total = sum(cat_by_month.values())
        result[nome_up] = {
            'categoria_id':   f'mot_{nome_up}',
            'categoria_nome': nome_map[nome_up],
            'by_month':       cat_by_month,
            'total':          cat_total,
            'subcats':        subcats,
        }
    return result


def _fetch_aluguel_from_caixa(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna lançamentos sintéticos de ALUGUEL provenientes de comprovações
    'RETIRADA ALUGUEL' em lancamentos_caixa_comprovacao.

    O formato do retorno é compatível com o de _fetch_lancamentos, para que
    os valores possam ser mesclados antes de _build_category_matrix.
    """
    cur = conn.cursor(dictionary=True)

    # Busca a categoria ALUGUEL e o seu título pai
    cur.execute("""
        SELECT c.id     AS categoria_id,
               c.nome   AS categoria_nome,
               c.ordem  AS categoria_ordem,
               t.id     AS titulo_id,
               t.nome   AS titulo_nome,
               t.ordem  AS titulo_ordem
          FROM categorias_despesas c
          INNER JOIN titulos_despesas t ON t.id = c.titulo_id
         WHERE UPPER(c.nome) = 'ALUGUEL'
           AND c.ativo = 1
         LIMIT 1
    """)
    cat_row = cur.fetchone()
    cur.close()

    if not cat_row:
        return []

    # Filtra comprovações do caixa por tipo e descrição
    where = [
        "lc.data BETWEEN %s AND %s",
        "fp.tipo = 'RETIRADA_PAGAMENTO'",
        "UPPER(TRIM(COALESCE(lcc.descricao, ''))) = 'RETIRADA ALUGUEL'",
    ]
    params = [data_inicio, data_fim]

    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        where.append(f"lc.cliente_id IN ({ph})")
        params.extend(empresa_ids)

    sql = f"""
        SELECT lcc.valor, lc.data
          FROM lancamentos_caixa_comprovacao lcc
          INNER JOIN lancamentos_caixa lc
                  ON lc.id = lcc.lancamento_caixa_id
          INNER JOIN formas_pagamento_caixa fp
                  ON fp.id = lcc.forma_pagamento_id
         WHERE {' AND '.join(where)}
           AND lcc.valor > 0
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()

    # Monta linhas sintéticas no mesmo formato que _fetch_lancamentos retorna
    result = []
    for i, row in enumerate(rows):
        result.append({
            'id':                 f'caixa_aluguel_{i}',
            'data':               row['data'],
            'valor':              float(row['valor']),
            'titulo_id':          cat_row['titulo_id'],
            'titulo_ordem':       cat_row['titulo_ordem'],
            'titulo_nome':        cat_row['titulo_nome'],
            'categoria_id':       cat_row['categoria_id'],
            'categoria_ordem':    cat_row['categoria_ordem'],
            'categoria_nome':     cat_row['categoria_nome'],
            'subcategoria_id':    None,
            'subcategoria_ordem': 9999,
            'subcategoria_nome':  None,
        })
    return result


def _fetch_lancamentos(conn, data_inicio, data_fim, empresa_ids, titulo_ids):
    """Retorna lançamentos de despesas filtrados com metadados de título, categoria e subcategoria."""
    where = ["ld.data BETWEEN %s AND %s"]
    params = [data_inicio, data_fim]

    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        where.append(f"ld.cliente_id IN ({ph})")
        params.extend(empresa_ids)

    if titulo_ids:
        ph = ','.join(['%s'] * len(titulo_ids))
        where.append(f"ld.titulo_id IN ({ph})")
        params.extend(titulo_ids)

    sql = f"""
        SELECT
            ld.id,
            ld.data,
            COALESCE(ld.valor, 0)                               AS valor,
            ld.titulo_id,
            COALESCE(t.ordem,  9999)                            AS titulo_ordem,
            t.nome                                              AS titulo_nome,
            ld.categoria_id,
            COALESCE(c.ordem,  9999)                            AS categoria_ordem,
            c.nome                                              AS categoria_nome,
            ld.subcategoria_id,
            COALESCE(s.ordem,  9999)                            AS subcategoria_ordem,
            s.nome                                              AS subcategoria_nome
        FROM lancamentos_despesas ld
        INNER JOIN titulos_despesas      t ON t.id = ld.titulo_id
        INNER JOIN categorias_despesas   c ON c.id = ld.categoria_id
        LEFT  JOIN subcategorias_despesas s ON s.id = ld.subcategoria_id
        WHERE {' AND '.join(where)}
        ORDER BY titulo_ordem, t.nome, categoria_ordem, c.nome,
                 COALESCE(s.ordem, 9999), COALESCE(s.nome, ''), ld.data
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_category_matrix(lancamentos, months):
    """
    Constrói a matriz pivot:

        bloco    = Título  (grupo de despesa, ex.: FUNCIONÁRIOS, CAMINHÃO)
        linha    = Categoria dentro do título  (totais em negrito)
        sub-linha = Subcategoria dentro da categoria (sem negrito, indentada)
        coluna   = mês  (chave YYYYMM)

    Retorna:
        blocks (list) – cada elemento:
          titulo_id, titulo_nome,
          rows (list):
            categoria_id, categoria_nome,
            by_month {key: float}, total (float),
            subcats (list):  ← [] se a categoria não tem subcategorias nomeadas
              subcat_id, subcat_nome, by_month {key: float}, total (float)
          total_by_month {key: float}, total (float)

        grand_by_month {key: float}
        grand_total    float
    """
    month_keys = {m['key'] for m in months}

    # titulo_id → (nome, ordem)
    titulo_meta = {}
    # cat_id → (nome, titulo_id, ordem)
    cat_meta    = {}
    # sub_key → (ordem, nome)
    subcat_meta = {}
    # titulo_id → cat_id → sub_key → month_key → float
    #   sub_key = subcategoria_id  or  None  (for rows without subcategoria)
    tree = {}

    for row in lancamentos:
        tit_id  = row['titulo_id']
        cat_id  = row['categoria_id']
        sub_id  = row['subcategoria_id']   # may be None
        d       = row['data']
        if isinstance(d, str):
            try:
                d = datetime.strptime(d, '%Y-%m-%d').date()
            except ValueError:
                continue
        mk = f'{d.year}{d.month:02d}'
        if mk not in month_keys:
            continue

        titulo_meta.setdefault(tit_id, (row['titulo_nome'], row['titulo_ordem']))
        cat_meta.setdefault(cat_id,    (row['categoria_nome'], tit_id, row['categoria_ordem']))
        if sub_id is not None:
            subcat_meta.setdefault(sub_id, (row['subcategoria_ordem'], row['subcategoria_nome'] or ''))

        tree.setdefault(tit_id, {})
        tree[tit_id].setdefault(cat_id, {})
        tree[tit_id][cat_id].setdefault(sub_id, {})
        tree[tit_id][cat_id][sub_id][mk] = (
            tree[tit_id][cat_id][sub_id].get(mk, 0.0) + float(row['valor'])
        )

    grand_by_month = {m['key']: 0.0 for m in months}
    grand_total    = 0.0
    blocks         = []

    for tit_id in sorted(tree, key=lambda x: (titulo_meta[x][1], titulo_meta[x][0])):
        block_by_month = {m['key']: 0.0 for m in months}
        rows = []

        for cat_id in sorted(
            tree[tit_id],
            key=lambda x: (cat_meta[x][2], cat_meta[x][0]),
        ):
            cat_by_month = {m['key']: 0.0 for m in months}
            subcats      = []

            # sub_keys: None first (rows without subcategoria), then named subcats sorted by ordem/nome
            sub_keys_sorted = sorted(
                tree[tit_id][cat_id].keys(),
                key=lambda x: subcat_meta.get(x, (9999, '')) if x is not None else (-1, ''),
            )

            for sub_id in sub_keys_sorted:
                sub_by_month = {}
                sub_total    = 0.0
                for m in months:
                    val = tree[tit_id][cat_id][sub_id].get(m['key'], 0.0)
                    sub_by_month[m['key']] = val
                    sub_total             += val
                    cat_by_month[m['key']] += val

                if sub_id is not None:
                    subcats.append({
                        'subcat_id':   sub_id,
                        'subcat_nome': subcat_meta[sub_id][1],
                        'by_month':    sub_by_month,
                        'total':       sub_total,
                    })
                # (if sub_id is None the values are already accumulated into cat_by_month)

            cat_total = sum(cat_by_month.values())
            for m in months:
                block_by_month[m['key']] += cat_by_month[m['key']]

            rows.append({
                'categoria_id':   cat_id,
                'categoria_nome': cat_meta[cat_id][0],
                'by_month':       cat_by_month,
                'total':          cat_total,
                'subcats':        subcats,
            })

        block_total = sum(block_by_month.values())
        for mk, v in block_by_month.items():
            grand_by_month[mk] = grand_by_month.get(mk, 0.0) + v
        grand_total += block_total

        blocks.append({
            'titulo_id':        tit_id,
            'titulo_nome':      titulo_meta[tit_id][0],
            'rows':             rows,
            'total_by_month':   block_by_month,
            'total':            block_total,
        })

    return blocks, grand_by_month, grand_total


def _fetch_func_lancamentos(conn, months, empresa_ids):
    """
    Retorna lançamentos de funcionários (lancamentosfuncionarios_v2) para os
    meses do período, com metadados de funcionário, categoria, veículo e rubrica.

    O campo ``mes`` nessa tabela é 'MM/YYYY'; convertemos para a chave YYYYMM
    antes de retornar.

    IMPORTANTE: lf.funcionarioid pode referenciar funcionarios.id (frentistas/
    outros) OU motoristas.id (motoristas). Ambas as tabelas têm auto-increment
    iniciando em 1, portanto os IDs colidem. A coluna tipo_funcionario
    (adicionada via _ensure_tipo_funcionario) resolve a ambiguidade: 'motorista'
    para motoristas, 'funcionario' para todos os demais.
    """
    if not months:
        return []

    # Garante que a coluna tipo_funcionario existe e está backfilled
    from routes.lancamentos_funcionarios import _ensure_tipo_funcionario
    _ensure_tipo_funcionario(conn)

    # Constrói lista de strings 'MM/YYYY' para o período
    mes_list = [f"{m['month']:02d}/{m['year']}" for m in months]
    ph       = ','.join(['%s'] * len(mes_list))
    params   = list(mes_list)

    where = [f"lf.mes IN ({ph})"]
    if empresa_ids:
        ph2 = ','.join(['%s'] * len(empresa_ids))
        where.append(f"lf.clienteid IN ({ph2})")
        params.extend(empresa_ids)

    sql = f"""
        SELECT
            lf.funcionarioid,
            CASE
                WHEN lf.tipo_funcionario = 'motorista' THEN m.nome
                ELSE f.nome
            END                                                            AS funcionario_nome,
            CASE
                WHEN lf.tipo_funcionario = 'motorista' THEN 'MOTORISTA'
                ELSE UPPER(COALESCE(f.categoria, 'OUTROS'))
            END                                                            AS categoria_func,
            lf.caminhaoid                                                  AS veiculo_id,
            COALESCE(
                CONCAT(v.caminhao,
                       CASE WHEN v.modelo IS NOT NULL AND v.modelo != ''
                            THEN CONCAT(' ', v.modelo) ELSE '' END),
                'SEM CAMINHÃO'
            )                                                              AS veiculo_nome,
            lf.mes,
            COALESCE(r.nome, 'OUTROS')                                    AS rubrica_nome,
            COALESCE(r.tipo, 'PROVENTO')                                  AS rubrica_tipo,
            lf.valor
        FROM lancamentosfuncionarios_v2 lf
        LEFT  JOIN funcionarios f ON f.id = lf.funcionarioid AND lf.tipo_funcionario = 'funcionario'
        LEFT  JOIN motoristas   m ON m.id = lf.funcionarioid AND lf.tipo_funcionario = 'motorista'
        LEFT  JOIN veiculos v     ON v.id = lf.caminhaoid
        LEFT  JOIN rubricas r     ON r.id = lf.rubricaid
        WHERE {' AND '.join(where)}
        ORDER BY categoria_func, funcionario_nome, lf.mes
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _build_func_blocks(func_rows, months):
    """
    Constrói blocos sintéticos de custo de pessoal para o relatório conf_despesas.

    Todas as categorias funcionais (FRENTISTA, MOTORISTA, OUTROS, …) são tratadas
    da mesma forma:
      - Um bloco por categoria funcional (ex.: "FRENTISTAS", "MOTORISTAS")
      - Linhas (categorias) = cada funcionário
      - Sub-linhas = cada rubrica do funcionário

    Retorna (blocks_list, combined_by_month, combined_total).
    Os blocos devem ser ADICIONADOS ao grand_total do relatório.
    """
    month_keys_set = {m['key'] for m in months}

    def _mes_to_mk(mes_str):
        """'MM/YYYY' → 'YYYYMM'"""
        try:
            parts = mes_str.split('/')
            return f"{parts[1]}{parts[0]}"
        except Exception:
            return None

    # ── Agrupa todas as categorias da mesma forma ────────────────────────────
    # cat_func → fid → rubrica_nome → mk → float
    cat_func_tree  = {}
    cat_func_names = {}
    func_names     = {}

    for row in func_rows:
        fid      = row['funcionarioid']
        nome     = row['funcionario_nome']
        cat_func = row['categoria_func']
        rub      = row['rubrica_nome']
        mes      = row['mes']
        mk       = _mes_to_mk(mes)
        if not mk or mk not in month_keys_set:
            continue
        val = float(row['valor'])

        cat_func_names[cat_func] = True
        func_names[(fid, cat_func)] = nome  # keyed by (fid, cat_func) to prevent collision-ID name bleed

        cat_func_tree.setdefault(cat_func, {})
        cat_func_tree[cat_func].setdefault(fid, {})
        cat_func_tree[cat_func][fid].setdefault(rub, {})
        cat_func_tree[cat_func][fid][rub][mk] = (
            cat_func_tree[cat_func][fid][rub].get(mk, 0.0) + val
        )

    combined_by_month = {m['key']: 0.0 for m in months}
    out_blocks        = []

    # Ordena categorias: FRENTISTA antes de MOTORISTA, demais no final
    # MOTORISTA é pulado aqui — o custo de pessoal de motoristas é injetado
    # diretamente no bloco CAMINHÕES, logo após a linha do caminhão vinculado.
    cat_order = {'FRENTISTA': 0, 'MOTORISTA': 1}
    for cat_func in sorted(cat_func_names, key=lambda c: (cat_order.get(c, 99), c)):
        if cat_func == 'MOTORISTA':
            continue  # exibido inline no bloco CAMINHÕES
        block_by_month = {m['key']: 0.0 for m in months}
        rows_out       = []

        for fid in sorted(cat_func_tree[cat_func], key=lambda x: func_names.get((x, cat_func), '')):
            func_nome    = func_names.get((fid, cat_func), str(fid))
            cat_by_month = {m['key']: 0.0 for m in months}
            subcats      = []

            for rub in sorted(cat_func_tree[cat_func][fid]):
                rub_by_month = {}
                rub_total    = 0.0
                for m in months:
                    v = cat_func_tree[cat_func][fid][rub].get(m['key'], 0.0)
                    rub_by_month[m['key']] = v
                    rub_total             += v
                    cat_by_month[m['key']] += v
                subcats.append({
                    'subcat_id':   f'func_{fid}_{rub}',
                    'subcat_nome': rub,
                    'by_month':    rub_by_month,
                    'total':       rub_total,
                })

            cat_total = sum(cat_by_month.values())
            for mk, v in cat_by_month.items():
                block_by_month[mk] = block_by_month.get(mk, 0.0) + v

            rows_out.append({
                'categoria_id':   f'func_{fid}',
                'categoria_nome': func_nome,
                'by_month':       cat_by_month,
                'total':          cat_total,
                'subcats':        subcats,
            })

        block_total = sum(block_by_month.values())
        for mk, v in block_by_month.items():
            combined_by_month[mk] = combined_by_month.get(mk, 0.0) + v

        # Pluraliza o título: FRENTISTA→FRENTISTAS, MOTORISTA→MOTORISTAS, OUTROS→OUTROS
        titulo = cat_func + 'S' if not cat_func.endswith('S') else cat_func

        out_blocks.append({
            'titulo_id':      f'func_{cat_func.lower()}',
            'titulo_nome':    titulo,
            'rows':           rows_out,
            'total_by_month': block_by_month,
            'total':          block_total,
        })

    combined_total = sum(combined_by_month.values())
    return out_blocks, combined_by_month, combined_total


def _add_business_days(d, n):
    """Adiciona n dias úteis à data d, pulando fins de semana. Ignora feriados."""
    count = 0
    while count < n:
        d = d + timedelta(days=1)
        if d.weekday() < 5:   # Segunda = 0, Sexta = 4
            count += 1
    return d


def _last_day_of_next_month(d):
    """Retorna o último dia do mês seguinte ao mês de d."""
    if d.month == 12:
        year, month = d.year + 1, 1
    else:
        year, month = d.year, d.month + 1
    _, last = monthrange(year, month)
    return date(year, month, last)


def _fetch_taxas_cartao(conn, data_inicio, data_fim, empresa_ids, months):
    """
    Calcula as taxas de cartão para injeção no bloco FINANCEIRO do conf_despesas.

    Para cada bandeira ativa:
      taxa[mk] = SUM(vendas cujo recebimento ESPERADO cai no mês mk)
                 − SUM(recebimentos REAIS recebidos no mês mk)

    O recebimento esperado é calculado adicionando prazo_compensacao_dias dias
    úteis à data de venda (mesmo critério do conf_cartoes). Isso alinha os valores
    com a coluna DIF do conf_cartoes para cada mês.

    Inclui lookback de 14 dias para capturar vendas pré-período cujo recebimento
    esperado cai dentro do período consultado (ex.: sextas de dezembro que chegam
    na segunda de janeiro).

    Retorna lista de dicts:
      {'bid': int, 'nome': str, 'tipo': str,
       'fee_by_month': {mk: float}, 'fee_total': float}
    """
    cur = conn.cursor(dictionary=True)

    # Bandeiras ativas com prazo de compensação e saldo anterior
    try:
        cur.execute("""
            SELECT id, nome, tipo,
                   COALESCE(prazo_compensacao_dias, 1)  AS prazo,
                   COALESCE(saldo_anterior, 0)          AS saldo_anterior,
                   saldo_anterior_data
              FROM bandeiras_cartao
             WHERE ativo = 1
             ORDER BY tipo, nome
        """)
    except Exception:
        cur.execute(
            "SELECT id, nome, tipo, 1 AS prazo, 0 AS saldo_anterior, NULL AS saldo_anterior_data "
            "FROM bandeiras_cartao WHERE ativo = 1 ORDER BY tipo, nome"
        )
    bandeiras = {b['id']: b for b in cur.fetchall()}

    # Vínculos bandeira → formas_recebimento
    try:
        cur.execute(
            "SELECT bandeira_cartao_id, forma_recebimento_id FROM conf_cartoes_vinculos"
        )
        vinculos_rows = cur.fetchall()
    except Exception:
        vinculos_rows = []
    vinculos_map = defaultdict(list)
    for v in vinculos_rows:
        vinculos_map[v['bandeira_cartao_id']].append(v['forma_recebimento_id'])

    # Janela de datas
    try:
        d_ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        d_fim = datetime.strptime(data_fim,    '%Y-%m-%d').date()
    except Exception:
        cur.close()
        return []

    # Lookback: captura vendas pré-período cujo recebimento esperado cai no período.
    # 14 dias cobre até prazo=5 dias úteis + fins de semana adjacentes (5 dias úteis
    # = no máximo ~8 dias corridos mais folga). Bandeiras com prazo > 7 dias úteis
    # são raras no mercado brasileiro de cartões de débito/crédito.
    _LOOKBACK = 14
    data_inicio_ext = (d_ini - timedelta(days=_LOOKBACK)).isoformat()

    # Vendas individuais por (bandeira, data_venda)
    where_v = ["lc.data BETWEEN %s AND %s", "lcc.bandeira_cartao_id IS NOT NULL"]
    params_v = [data_inicio_ext, data_fim]
    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        where_v.append(f"lc.cliente_id IN ({ph})")
        params_v.extend(empresa_ids)

    cur.execute(f"""
        SELECT lcc.bandeira_cartao_id          AS bandeira_id,
               lc.data                         AS data_venda,
               COALESCE(SUM(lcc.valor), 0)     AS valor
          FROM lancamentos_caixa_comprovacao lcc
          JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
         WHERE {' AND '.join(where_v)}
         GROUP BY lcc.bandeira_cartao_id, lc.data
    """, params_v)
    sale_rows = cur.fetchall()

    # Recebimentos por (forma_recebimento, mês)
    all_forma_ids = list({fid for fids in vinculos_map.values() for fid in fids})
    receb_idx = {}
    if all_forma_ids:
        ph  = ','.join(['%s'] * len(all_forma_ids))
        where_r = [
            "bt.tipo = 'CREDIT'",
            f"bt.forma_recebimento_id IN ({ph})",
            "bt.data_transacao BETWEEN %s AND %s",
        ]
        params_r = list(all_forma_ids) + [data_inicio, data_fim]
        if empresa_ids:
            ep = ','.join(['%s'] * len(empresa_ids))
            where_r.append(f"ba.cliente_id IN ({ep})")
            params_r.extend(empresa_ids)
        try:
            cur.execute(f"""
                SELECT bt.forma_recebimento_id               AS forma_id,
                       YEAR(bt.data_transacao)               AS yr,
                       MONTH(bt.data_transacao)              AS mo,
                       COALESCE(SUM(bt.valor), 0)            AS total
                  FROM bank_transactions bt
                  JOIN bank_accounts ba ON ba.id = bt.account_id
                 WHERE {' AND '.join(where_r)}
                 GROUP BY bt.forma_recebimento_id,
                          YEAR(bt.data_transacao),
                          MONTH(bt.data_transacao)
            """, params_r)
            for r in cur.fetchall():
                # YEAR/MONTH integers avoid DATE_FORMAT type ambiguity (bytes vs str)
                mk_r = f"{int(r['yr'])}{int(r['mo']):02d}"
                receb_idx[(int(r['forma_id']), mk_r)] = float(r['total'])
        except Exception:
            pass

    cur.close()

    # Atribui cada venda ao mês de recebimento ESPERADO (cycle attribution).
    # Ciclos cujo recebimento esperado ainda não chegou (expected >= hoje) são
    # excluídos: espelha conf_cartoes que atribui cycle_fee=0 quando has_receipt=False.
    # Meses já fechados não são afetados pois todos os expected estão no passado.
    _today = date.today()
    month_keys_set = {m['key'] for m in months}
    vendas_by_band_mk = defaultdict(lambda: defaultdict(float))

    for r in sale_rows:
        bid = int(r['bandeira_id'])
        if bid not in bandeiras:
            continue
        prazo = int(bandeiras[bid].get('prazo', 1))
        dv = r['data_venda']
        if isinstance(dv, str):
            try:
                dv = datetime.strptime(dv, '%Y-%m-%d').date()
            except Exception:
                continue

        # Calcula data de recebimento esperada
        expected = dv if prazo == 0 else _add_business_days(dv, prazo)

        # Só inclui se o recebimento esperado cai dentro do período consultado
        if expected < d_ini or expected > d_fim:
            continue
        mk_exp = f'{expected.year}{expected.month:02d}'
        if mk_exp not in month_keys_set:
            continue

        # Exclui ciclos ainda pendentes: recebimento esperado hoje ou no futuro
        if expected >= _today:
            continue

        vendas_by_band_mk[bid][mk_exp] += float(r['valor'])

    # Calcula taxa por bandeira e mês
    # O primeiro mês do período recebe o saldo_anterior (igual ao conf_cartoes),
    # que representa vendas pré-período cujo recebimento chega no início do período.
    first_mk = months[0]['key'] if months else None
    result = []
    for bid, band in bandeiras.items():
        forma_ids = vinculos_map.get(bid, [])

        # Determina se saldo_anterior é aplicável para este período
        saldo_anterior    = float(band.get('saldo_anterior') or 0)
        sad_raw           = band.get('saldo_anterior_data')
        saldo_aplicavel   = False
        if saldo_anterior != 0.0 and sad_raw and d_ini:
            if isinstance(sad_raw, str):
                try:
                    sad_raw = datetime.strptime(sad_raw, '%Y-%m-%d').date()
                except Exception:
                    sad_raw = None
            if sad_raw:
                ultimo_dia_aplicavel = _last_day_of_next_month(sad_raw)
                saldo_aplicavel = d_ini <= ultimo_dia_aplicavel

        fee_by_month = {}
        fee_total    = 0.0
        has_data     = False

        for m in months:
            mk    = m['key']
            venda = vendas_by_band_mk.get(bid, {}).get(mk, 0.0)
            # Adiciona saldo_anterior ao primeiro mês (mesmo critério que conf_cartoes).
            # saldo_anterior é global (consolidado de todas as empresas) e só deve
            # ser aplicado quando NÃO há filtro de empresa; caso contrário inflaria
            # o primeiro mês de empresas que não possuem maquininha vinculada.
            if saldo_aplicavel and mk == first_mk and not empresa_ids:
                venda += saldo_anterior
            receb = sum(receb_idx.get((fid, mk), 0.0) for fid in forma_ids)
            fee   = venda - receb
            fee_by_month[mk] = fee
            fee_total += fee
            if abs(venda) > 0.005 or abs(receb) > 0.005:
                has_data = True

        if not has_data:
            continue

        result.append({
            'bid':          bid,
            'nome':         band['nome'],
            'tipo':         band['tipo'],
            'fee_by_month': fee_by_month,
            'fee_total':    fee_total,
        })

    return result


# Bandeiras que devem aparecer como linhas STANDALONE (não agrupadas por tipo)
_STANDALONE_CARD_PATTERNS = ('BARATAO', 'X7')


def _is_standalone_bandeira(nome):
    """Retorna True se a bandeira deve ser exibida como linha standalone."""
    norm = _ascii_upper(nome)
    return any(p in norm for p in _STANDALONE_CARD_PATTERNS)


def _build_taxas_cartao_rows(taxas_data, months):
    """
    Constrói linhas de taxa de cartão para o bloco FINANCEIRO:

      - DÉBITO:  linha pai "CARTÃO DE DÉBITO"  + sub-linhas por bandeira
      - CRÉDITO (exceto standalone): linha pai "CARTÃO DE CRÉDITO" + sub-linhas
      - Standalone (BARATÃO, X7 BANK): linha única sem subcats

    Retorna (rows, combined_by_month, combined_total).
    """
    if not taxas_data:
        return [], {m['key']: 0.0 for m in months}, 0.0

    _TIPO_LABEL = {'DEBITO': 'CARTÃO DE DÉBITO', 'CREDITO': 'CARTÃO DE CRÉDITO'}
    _TIPO_ORDER = {'DEBITO': 0, 'CREDITO': 1}

    # Separa standalone das demais
    grouped    = defaultdict(list)   # tipo → [band]
    standalones = []
    for t in taxas_data:
        if _is_standalone_bandeira(t['nome']):
            standalones.append(t)
        else:
            grouped[t['tipo']].append(t)

    rows              = []
    combined_by_month = {m['key']: 0.0 for m in months}
    combined_total    = 0.0

    # Grupos DÉBITO / CRÉDITO com sub-linhas por bandeira
    for tipo in sorted(grouped, key=lambda t: (_TIPO_ORDER.get(t, 99), t)):
        bands = grouped[tipo]
        label = _TIPO_LABEL.get(tipo, f'CARTÃO {tipo}')

        grp_by_month = {m['key']: 0.0 for m in months}
        grp_total    = 0.0
        subcats      = []

        for band in bands:
            for mk, v in band['fee_by_month'].items():
                grp_by_month[mk] = grp_by_month.get(mk, 0.0) + v
            grp_total += band['fee_total']
            subcats.append({
                'subcat_id':   f'taxa_cartao_{band["bid"]}',
                'subcat_nome': band['nome'],
                'by_month':    band['fee_by_month'],
                'total':       band['fee_total'],
            })

        for mk, v in grp_by_month.items():
            combined_by_month[mk] = combined_by_month.get(mk, 0.0) + v
        combined_total += grp_total

        rows.append({
            'categoria_id':   f'taxa_cartao_{tipo.lower()}',
            'categoria_nome': label,
            'by_month':       grp_by_month,
            'total':          grp_total,
            'subcats':        subcats,
        })

    # Standalones (BARATÃO, X7 BANK) – linha única sem subcats
    for band in sorted(standalones, key=lambda b: b['nome']):
        for mk, v in band['fee_by_month'].items():
            combined_by_month[mk] = combined_by_month.get(mk, 0.0) + v
        combined_total += band['fee_total']
        rows.append({
            'categoria_id':   f'taxa_cartao_{band["bid"]}',
            'categoria_nome': band['nome'],
            'by_month':       band['fee_by_month'],
            'total':          band['fee_total'],
            'subcats':        [],
        })

    return rows, combined_by_month, combined_total


# ──────────────────────────────────────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/conf_despesas', methods=['GET'])
@login_required
@admin_required
def conf_despesas():
    args = request.args

    # ── Filters ──────────────────────────────────────────────────────────────
    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()

    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]
    titulo_ids  = [t for t in args.getlist('titulo_ids[]')  if t]

    conn = get_db_connection()
    try:
        empresas = _empresas_list(conn)
        titulos  = _titulos_list(conn)

        months            = []
        blocks            = []
        grand_by_month    = {}
        grand_total       = 0.0
        total_lancamentos = 0

        litros_comprados_by_month = {}
        litros_comprados_total    = 0.0
        custo_por_litro_by_month  = {}
        custo_por_litro_acum      = 0.0

        if data_inicio and data_fim:
            months = _months_in_range(data_inicio, data_fim)
            lancamentos = _fetch_lancamentos(
                conn, data_inicio, data_fim, empresa_ids, titulo_ids,
            )

            # ── Inclui ALUGUEL proveniente de RETIRADA ALUGUEL do caixa ─────
            # Só inclui quando nenhum filtro de título está ativo OU quando o
            # título selecionado corresponde à categoria ALUGUEL
            # (identificado comparando titulo_id dos dados sintéticos).
            aluguel_caixa = _fetch_aluguel_from_caixa(
                conn, data_inicio, data_fim, empresa_ids,
            )
            if aluguel_caixa:
                if not titulo_ids:
                    lancamentos = list(lancamentos) + aluguel_caixa
                else:
                    aluguel_titulo_id = str(aluguel_caixa[0]['titulo_id'])
                    if aluguel_titulo_id in titulo_ids:
                        lancamentos = list(lancamentos) + aluguel_caixa

            total_lancamentos = len(lancamentos)
            blocks, grand_by_month, grand_total = _build_category_matrix(
                lancamentos, months
            )

            # ── Adiciona custo de pessoal (lancamentosfuncionarios_v2) ──────
            func_rows = _fetch_func_lancamentos(conn, months, empresa_ids)
            func_blocks, func_by_month, func_total = _build_func_blocks(
                func_rows, months
            )
            # Só inclui os blocos de pessoal (FRENTISTAS, OUTROS…) quando nenhum
            # filtro de título está ativo OU quando um dos títulos selecionados
            # corresponde a "FUNCIONÁRIOS" (dados de lancamentosfuncionarios_v2).
            _titulo_nome_by_id = {str(t['id']): t['nome'] for t in titulos}
            include_func_blocks = (
                not titulo_ids
                or any(
                    'FUNCIONARI' in _ascii_upper(_titulo_nome_by_id.get(tid, ''))
                    for tid in titulo_ids
                )
            )
            if include_func_blocks:
                blocks.extend(func_blocks)
                for m in months:
                    mk = m['key']
                    grand_by_month[mk] = grand_by_month.get(mk, 0.0) + func_by_month.get(mk, 0.0)
                grand_total    += func_total
            total_lancamentos += len(func_rows)

            # ── Anota linhas de caminhão com motorista (badge), injeta salário, receita e litros ──
            # Restringe a blocos cujo título contenha "CAMINHÃO"/"CAMINHÕES"
            # para não vazar dados em blocos como INVESTIMENTOS.
            # Por veículo:
            #   1. Badge do motorista na linha do caminhão
            #   2. Subcats RECEITA (negativa — deduz receita de frete do custo líquido)
            #      e LITROS (informativa — litragem transportada)
            #   3. Linha de salário do motorista injetada logo após o caminhão
            veiculo_mot, _ = _fetch_veiculos_motoristas(conn)
            mot_salary_rows = _build_motorista_salary_rows(func_rows, months)
            frete_by_vid    = _fetch_frete_data_by_vehicle(conn, data_inicio, data_fim)
            if veiculo_mot:
                veiculo_matchers = _compile_veiculo_matchers(veiculo_mot)
                for block in blocks:
                    titulo_norm = _ascii_upper(block['titulo_nome'])
                    if 'CAMINHAO' not in titulo_norm and 'CAMINHOES' not in titulo_norm:
                        continue
                    block['is_caminhoes'] = True
                    new_rows = []
                    for row in block.get('rows', []):
                        new_rows.append(row)
                        vdata = _match_veiculo_row(row.get('categoria_nome', ''), veiculo_matchers)
                        if not vdata:
                            continue

                        if vdata.get('nome'):
                            row['motorista_nome'] = vdata['nome']
                        vid = vdata['veiculo_id']

                        # ── Injeta RECEITA e LITROS como primeiras subcats ──
                        if vid in frete_by_vid:
                            vfrete = frete_by_vid[vid]
                            receita_by_month = {}
                            litros_by_month  = {}
                            receita_total    = 0.0
                            litros_total     = 0.0
                            for m_ in months:
                                mk_ = m_['key']
                                # receita é negativa: subtrai do custo líquido
                                r_val = -vfrete['receita'].get(mk_, 0.0)
                                l_val =  vfrete['litros'].get(mk_,  0.0)
                                receita_by_month[mk_] = r_val
                                litros_by_month[mk_]  = l_val
                                receita_total += r_val
                                litros_total  += l_val

                            # Primeiro: RECEITA (monetária, subtrai do total)
                            row['subcats'].insert(0, {
                                'subcat_id':   f'receita_{vid}',
                                'subcat_nome': 'RECEITA',
                                'by_month':    receita_by_month,
                                'total':       receita_total,
                                'is_receita':  True,
                            })
                            # Segundo: LITROS (informativa, não afeta totais monetários)
                            row['subcats'].insert(1, {
                                'subcat_id':   f'litros_{vid}',
                                'subcat_nome': 'LITROS TRANSPORTADOS',
                                'by_month':    litros_by_month,
                                'total':       litros_total,
                                'is_litros':   True,
                            })
                            # Atualiza totais monetários com a receita (negativa)
                            for m_ in months:
                                mk_ = m_['key']
                                r_val = receita_by_month[mk_]
                                row['by_month'][mk_]             = row['by_month'].get(mk_, 0.0) + r_val
                                block['total_by_month'][mk_]     = block['total_by_month'].get(mk_, 0.0) + r_val
                                grand_by_month[mk_]              = grand_by_month.get(mk_, 0.0) + r_val
                            row['total']    += receita_total
                            block['total']  += receita_total
                            grand_total     += receita_total

                        # ── Injeta linha de salário do motorista logo após o caminhão ──
                        mot_nome = vdata.get('nome')
                        if mot_nome:
                            mot_key = _ascii_upper(mot_nome)
                            if mot_key in mot_salary_rows:
                                sal_row = mot_salary_rows[mot_key]
                                new_rows.append(sal_row)
                                # Incorpora salário no total da linha do caminhão (custo líquido
                                # do veículo = despesas + salário motorista − receita de frete)
                                for mk_, v in sal_row['by_month'].items():
                                    row['by_month'][mk_] = row['by_month'].get(mk_, 0.0) + v
                                row['total'] += sal_row['total']
                                # Mantém block/grand corretos (são variáveis independentes
                                # de row['total'] — não há dupla contagem)
                                block['total'] += sal_row['total']
                                for mk_, v in sal_row['by_month'].items():
                                    block['total_by_month'][mk_] = block['total_by_month'].get(mk_, 0.0) + v
                                    grand_by_month[mk_]          = grand_by_month.get(mk_, 0.0) + v
                                grand_total += sal_row['total']
                    block['rows'] = new_rows

            # ── Litros comprados pela empresa selecionada e custo por litro ──
            litros_comprados_by_month = _fetch_litros_comprados(
                conn, data_inicio, data_fim, empresa_ids
            )
            litros_comprados_total = sum(litros_comprados_by_month.values())
            # Encontra total_by_month do bloco CAMINHÕES para calcular custo/litro
            caminhoes_total_by_month = {}
            for _blk in blocks:
                if _blk.get('is_caminhoes'):
                    caminhoes_total_by_month = _blk['total_by_month']
                    break
            custo_por_litro_by_month = {}
            for m in months:
                mk = m['key']
                lit  = litros_comprados_by_month.get(mk, 0.0)
                cost = caminhoes_total_by_month.get(mk, 0.0)
                custo_por_litro_by_month[mk] = (cost / lit) if lit else 0.0
            custo_por_litro_acum = (
                sum(caminhoes_total_by_month.get(m['key'], 0.0) for m in months)
                / litros_comprados_total
            ) if litros_comprados_total else 0.0

            # ── Taxas de cartão (diferença vendas − recebimentos, por bandeira) ──
            # Injetadas no bloco FINANCEIRO como linhas agrupadas por tipo.
            # Só inclui quando nenhum filtro de título está ativo OU quando o
            # título FINANCEIRO está entre os selecionados.
            include_taxas = (
                not titulo_ids
                or any(
                    'FINANCEIRO' in _ascii_upper(_titulo_nome_by_id.get(tid, ''))
                    for tid in titulo_ids
                )
            )
            if include_taxas:
                # Taxas de cartão são sempre calculadas globalmente (sem filtro de
                # empresa) para coincidir com conf_cartoes e garantir que
                # saldo_anterior seja aplicado no primeiro mês (janeiro). Card
                # machines are shared infrastructure across all empresas.
                taxas_data = _fetch_taxas_cartao(
                    conn, data_inicio, data_fim, [], months
                )
                if taxas_data:
                    taxa_rows, taxa_by_month, taxa_total = _build_taxas_cartao_rows(
                        taxas_data, months
                    )
                    if taxa_rows:
                        # Encontra o bloco FINANCEIRO; cria um sintético se não existir
                        fin_block = None
                        for _blk in blocks:
                            if 'FINANCEIRO' in _ascii_upper(_blk.get('titulo_nome', '')):
                                fin_block = _blk
                                break
                        if fin_block is None:
                            fin_block = {
                                'titulo_id':      'taxa_financeiro',
                                'titulo_nome':    'FINANCEIRO',
                                'rows':           [],
                                'total_by_month': {m['key']: 0.0 for m in months},
                                'total':          0.0,
                            }
                            blocks.append(fin_block)

                        fin_block['rows'].extend(taxa_rows)
                        for mk, v in taxa_by_month.items():
                            fin_block['total_by_month'][mk] = (
                                fin_block['total_by_month'].get(mk, 0.0) + v
                            )
                            grand_by_month[mk] = grand_by_month.get(mk, 0.0) + v
                        fin_block['total'] += taxa_total
                        grand_total        += taxa_total
    finally:
        conn.close()

    return render_template(
        'relatorios/conf_despesas.html',
        empresas=empresas,
        titulos=titulos,
        months=months,
        blocks=blocks,
        grand_by_month=grand_by_month,
        grand_total=grand_total,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        titulo_ids=titulo_ids,
        total_lancamentos=total_lancamentos,
        litros_comprados_by_month=litros_comprados_by_month,
        litros_comprados_total=litros_comprados_total,
        custo_por_litro_by_month=custo_por_litro_by_month,
        custo_por_litro_acum=custo_por_litro_acum,
    )
