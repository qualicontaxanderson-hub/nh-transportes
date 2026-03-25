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
from datetime import date, datetime

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
    Retorna uma tupla (by_caminhao, nome_to_vid):
      by_caminhao  – {caminhao_upper: {nome, veiculo_id}}
      nome_to_vid  – {motorista_nome_upper: veiculo_id}  (reservado para uso futuro)

    Usado para anotar as linhas da seção CAMINHÕES no relatório conf_despesas
    com o badge do nome do motorista.
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT v.id              AS veiculo_id,
               UPPER(v.caminhao) AS caminhao_upper,
               m.nome            AS motorista_nome
        FROM   veiculos  v
        INNER  JOIN motoristas m ON m.veiculo_id = v.id
        WHERE  v.caminhao IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    by_caminhao = {
        r['caminhao_upper']: {'nome': r['motorista_nome'], 'veiculo_id': r['veiculo_id']}
        for r in rows
    }
    nome_to_vid = {
        _ascii_upper(r['motorista_nome']): r['veiculo_id']
        for r in rows
    }
    return by_caminhao, nome_to_vid


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
    iniciando em 1, portanto os IDs colidem (ex.: funcionarios.id=1=BRENA e
    motoristas.id=1=MARCOS ANTONIO coexistem). Por isso:
      - Usamos dois LEFT JOINs (f = funcionarios, m = motoristas).
      - Resolvemos o nome com CASE WHEN m.id IS NOT NULL THEN m.nome ELSE f.nome
        para garantir que entradas de motoristas usem o nome correto mesmo quando
        o mesmo funcionarioid existe em ambas as tabelas (colisão de IDs).
      - COALESCE(f.nome, m.nome) daria o nome errado no caso de colisão, pois
        f.nome seria não-NULL e retornaria o nome do frentista, causando falha
        no lookup nome_to_vid → salary map vazio.
    """
    if not months:
        return []

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
                WHEN m.id IS NOT NULL THEN m.nome
                ELSE f.nome
            END                                                            AS funcionario_nome,
            CASE
                WHEN m.id IS NOT NULL THEN 'MOTORISTA'
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
        LEFT  JOIN funcionarios f ON f.id = lf.funcionarioid
        LEFT  JOIN motoristas   m ON m.id = lf.funcionarioid
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
        func_names[fid]          = nome

        cat_func_tree.setdefault(cat_func, {})
        cat_func_tree[cat_func].setdefault(fid, {})
        cat_func_tree[cat_func][fid].setdefault(rub, {})
        cat_func_tree[cat_func][fid][rub][mk] = (
            cat_func_tree[cat_func][fid][rub].get(mk, 0.0) + val
        )

    combined_by_month = {m['key']: 0.0 for m in months}
    out_blocks        = []

    # Ordena categorias: FRENTISTA antes de MOTORISTA, demais no final
    cat_order = {'FRENTISTA': 0, 'MOTORISTA': 1}
    for cat_func in sorted(cat_func_names, key=lambda c: (cat_order.get(c, 99), c)):
        block_by_month = {m['key']: 0.0 for m in months}
        rows_out       = []

        for fid in sorted(cat_func_tree[cat_func], key=lambda x: func_names.get(x, '')):
            func_nome    = func_names.get(fid, str(fid))
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

        if data_inicio and data_fim:
            months = _months_in_range(data_inicio, data_fim)
            lancamentos = _fetch_lancamentos(
                conn, data_inicio, data_fim, empresa_ids, titulo_ids,
            )
            total_lancamentos = len(lancamentos)
            blocks, grand_by_month, grand_total = _build_category_matrix(
                lancamentos, months
            )

            # ── Adiciona custo de pessoal (lancamentosfuncionarios_v2) ──────
            func_rows = _fetch_func_lancamentos(conn, months, empresa_ids)
            func_blocks, func_by_month, func_total = _build_func_blocks(
                func_rows, months
            )
            blocks.extend(func_blocks)
            for m in months:
                mk = m['key']
                grand_by_month[mk] = grand_by_month.get(mk, 0.0) + func_by_month.get(mk, 0.0)
            grand_total    += func_total
            total_lancamentos += len(func_rows)

            # ── Anota linhas de caminhão com o nome do motorista (badge) ─────
            # Restringe a blocos cujo título contenha "CAMINHÃO"/"CAMINHÕES"
            # para não vazar badges em blocos como INVESTIMENTOS.
            veiculo_mot, _ = _fetch_veiculos_motoristas(conn)
            if veiculo_mot:
                # Pré-compila os padrões regex uma única vez
                veiculo_patterns = {
                    caminhao_up: re.compile(r'\b' + re.escape(caminhao_up) + r'\b')
                    for caminhao_up in veiculo_mot
                }
                for block in blocks:
                    titulo_norm = _ascii_upper(block['titulo_nome'])
                    if 'CAMINHAO' not in titulo_norm and 'CAMINHOES' not in titulo_norm:
                        continue
                    for row in block.get('rows', []):
                        nome_up = row.get('categoria_nome', '').upper()
                        for caminhao_up, vdata in veiculo_mot.items():
                            if veiculo_patterns[caminhao_up].search(nome_up):
                                row['motorista_nome'] = vdata['nome']
                                break
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
    )
