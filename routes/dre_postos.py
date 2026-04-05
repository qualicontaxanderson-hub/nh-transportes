"""
DRE Postos — Demonstração do Resultado do Exercício.

Combina num único relatório em formato de matriz mensal:
  1. RECEITAS
     - Vendas de Combustíveis em R$ (lancamentos_caixa_receitas, tipo='VENDAS POSTO')
     - Vendas de Combustíveis em Litros (fifo_resumo_mensal.qtde_saida)
     - Recebimentos de Aluguel (bank_transactions + formas_recebimento)
     - Clientes à Prazo       (bank_transactions + formas_recebimento)
  2. DESPESAS
     - lancamentos_despesas agrupados por Título / Categoria
  3. LUCRO OPERACIONAL = RECEITAS − DESPESAS

Multi-empresa: empresa_ids[] restringe quais empresas contribuem com dados.
Filtros adicionais: titulo_ids[] filtra quais títulos de despesa incluir.
Filtro de formas: forma_ids[] filtra formas de recebimento de banco.

Rota:
  GET /relatorios/dre_postos
"""
import unicodedata
from collections import defaultdict
from datetime import date, datetime

from flask import Blueprint, render_template, request
from flask_login import login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('dre_postos', __name__, url_prefix='/relatorios')

_MES_LABELS = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']


# ──────────────────────────────────────────────────────────────────────────────
# Helpers genéricos
# ──────────────────────────────────────────────────────────────────────────────

def _ascii_upper(s):
    """Converte para maiúsculas e remove acentos para comparação robusta."""
    return (unicodedata.normalize('NFD', (s or '').upper())
            .encode('ascii', 'ignore').decode('ascii'))


def _default_period():
    """Padrão: ano corrente completo (01/01 – 31/12)."""
    hoje = date.today()
    return f'{hoje.year}-01-01', f'{hoje.year}-12-31'


def _make_month_key(year, month):
    """Constrói a chave de mês 'YYYYMM' a partir de inteiros year e month."""
    return f'{int(year)}{int(month):02d}'


def _months_in_range(data_inicio_str, data_fim_str):
    """Retorna lista de dicts {year, month, label, key} para cada mês do intervalo."""
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
            'key':   _make_month_key(y, m),
        })
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


# ──────────────────────────────────────────────────────────────────────────────
# Listas de opções para filtros
# ──────────────────────────────────────────────────────────────────────────────

def _empresas_list(conn):
    """Empresas com produtos (posto) ou contas bancárias cadastradas."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT DISTINCT c.id,
                   COALESCE(c.nome_fantasia, c.razao_social) AS nome
            FROM clientes c
            WHERE EXISTS (
                SELECT 1 FROM cliente_produtos cp
                WHERE cp.cliente_id = c.id AND cp.ativo = 1
            ) OR EXISTS (
                SELECT 1 FROM bank_accounts ba
                WHERE ba.cliente_id = c.id
            )
            ORDER BY nome
        """)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _titulos_list(conn):
    """Títulos de despesas ativos para o filtro de categorias."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome"
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _formas_recebimento_aluguel_prazo(conn):
    """
    Retorna somente formas de recebimento classificadas como ALUGUEL ou
    CLIENTES À PRAZO (mesma lógica de _classify_forma).
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome FROM formas_recebimento ORDER BY nome")
        all_formas = cur.fetchall()
    except Exception:
        all_formas = []
    cur.close()
    return [f for f in all_formas if _classify_forma(f['nome']) is not None]


# ──────────────────────────────────────────────────────────────────────────────
# Receitas: Vendas de Combustíveis (R$)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_vendas_reais(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna SUM(valor) de lancamentos_caixa_receitas (tipo='VENDAS POSTO')
    por mês.  Retorna {mk: float}.
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f'AND lc.cliente_id IN ({ph_emp})' if ph_emp else ''
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    try:
        cur.execute(f"""
            SELECT YEAR(lc.data) AS yr, MONTH(lc.data) AS mo,
                   SUM(lcr.valor) AS total
            FROM lancamentos_caixa_receitas lcr
            INNER JOIN lancamentos_caixa lc ON lc.id = lcr.lancamento_caixa_id
            WHERE lc.data BETWEEN %s AND %s
              AND lc.status = 'FECHADO'
              AND UPPER(TRIM(lcr.tipo)) = 'VENDAS POSTO'
              {emp_cond}
            GROUP BY yr, mo
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    result = {}
    for r in rows:
        mk = _make_month_key(r['yr'], r['mo'])
        result[mk] = float(r['total'] or 0)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Receitas: Vendas de Combustíveis (Litros)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_vendas_litros(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna litros vendidos por produto por mês via fifo_resumo_mensal.
    Retorna {mk: {produto_nome: float}}.
    mk = 'YYYYMM'  (calculado a partir de fifo_competencia.ano_mes 'YYYY-MM')
    """
    try:
        d_ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        d_fim = datetime.strptime(data_fim,    '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return {}

    ano_mes_ini = f'{d_ini.year}-{d_ini.month:02d}'
    ano_mes_fim = f'{d_fim.year}-{d_fim.month:02d}'

    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f'AND fc.cliente_id IN ({ph_emp})' if ph_emp else ''
    params = [ano_mes_ini, ano_mes_fim] + (list(empresa_ids) if empresa_ids else [])

    try:
        cur.execute(f"""
            SELECT fc.ano_mes,
                   p.nome AS produto_nome,
                   SUM(r.qtde_saida) AS litros
            FROM fifo_resumo_mensal r
            INNER JOIN fifo_competencia fc ON fc.id = r.competencia_id
            INNER JOIN produto p ON p.id = r.produto_id
            WHERE fc.ano_mes BETWEEN %s AND %s
              AND r.substituido = 0
              {emp_cond}
            GROUP BY fc.ano_mes, p.nome
            ORDER BY fc.ano_mes, p.nome
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result = defaultdict(dict)
    for r in rows:
        # 'YYYY-MM' → 'YYYYMM'
        mk = r['ano_mes'].replace('-', '')
        prod = r['produto_nome']
        result[mk][prod] = result[mk].get(prod, 0.0) + float(r['litros'] or 0)
    return dict(result)


# ──────────────────────────────────────────────────────────────────────────────
# Receitas: Recebimentos (Aluguel + Clientes à Prazo)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_forma(nome):
    """Retorna 'aluguel', 'cliente_a_prazo' ou None."""
    u = _ascii_upper(nome)
    if 'RECEBIMENTO DE ALUGUEL' in u:
        return 'aluguel'
    if 'CLIENTE' in u and 'PRAZO' in u:
        return 'cliente_a_prazo'
    return None


def _fetch_recebimentos(conn, data_inicio, data_fim, empresa_ids, forma_ids):
    """
    Retorna recebimentos de aluguel e clientes à prazo do banco por mês.

    Retorna dict:
      {
        'aluguel': {mk: float},
        'aluguel_formas': [{nome, by_month, total}],
        'cliente_a_prazo': {mk: float},
        'cliente_a_prazo_formas': [{nome, by_month, total}],
      }
    """
    cur = conn.cursor(dictionary=True)
    emp_clause = ''
    emp_params: list = []
    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        emp_clause = f'AND ba.cliente_id IN ({ph})'
        emp_params = [int(e) for e in empresa_ids]

    forma_clause = ''
    forma_params: list = []
    if forma_ids:
        ph = ','.join(['%s'] * len(forma_ids))
        forma_clause = f'AND bt.forma_recebimento_id IN ({ph})'
        forma_params = [int(f) for f in forma_ids]

    try:
        cur.execute(f"""
            SELECT YEAR(bt.data_transacao)  AS yr,
                   MONTH(bt.data_transacao) AS mo,
                   fr.id                   AS forma_id,
                   fr.nome                 AS forma_nome,
                   SUM(bt.valor)           AS total
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.account_id
            JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
            WHERE bt.tipo = 'CREDIT'
              AND bt.status != 'ignorado'
              AND bt.data_transacao BETWEEN %s AND %s
              {emp_clause}
              {forma_clause}
            GROUP BY yr, mo, fr.id, fr.nome
            ORDER BY fr.nome, yr, mo
        """, [data_inicio, data_fim] + emp_params + forma_params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    aluguel_acc:  dict = {}
    prazo_acc:    dict = {}

    for row in rows:
        grupo = _classify_forma(row['forma_nome'])
        if grupo is None:
            continue
        mk   = _make_month_key(row['yr'], row['mo'])
        val  = float(row['total'] or 0)
        nome = row['forma_nome']
        store = aluguel_acc if grupo == 'aluguel' else prazo_acc

        if nome not in store:
            store[nome] = {'nome': nome, 'by_month': defaultdict(float), 'total': 0.0}
        store[nome]['by_month'][mk] += val
        store[nome]['total']        += val

    def _agg(acc):
        total_by_mk: dict = defaultdict(float)
        for d in acc.values():
            for mk, v in d['by_month'].items():
                total_by_mk[mk] += v
        return dict(total_by_mk)

    def _rows(acc):
        result = []
        for entry in sorted(acc.values(), key=lambda x: x['nome']):
            result.append({
                'nome':     entry['nome'],
                'by_month': dict(entry['by_month']),
                'total':    entry['total'],
            })
        return result

    return {
        'aluguel':              _agg(aluguel_acc),
        'aluguel_formas':       _rows(aluguel_acc),
        'cliente_a_prazo':      _agg(prazo_acc),
        'cliente_a_prazo_formas': _rows(prazo_acc),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Despesas: lancamentos_despesas agrupados por Título / Categoria
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_despesas_lancamentos(conn, data_inicio, data_fim, empresa_ids, titulo_ids):
    """Retorna lançamentos de despesas filtrados com metadados de título e categoria."""
    where  = ["ld.data BETWEEN %s AND %s"]
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
        SELECT ld.data,
               COALESCE(ld.valor, 0)           AS valor,
               ld.titulo_id,
               COALESCE(t.ordem,  9999)         AS titulo_ordem,
               t.nome                           AS titulo_nome,
               ld.categoria_id,
               COALESCE(c.ordem,  9999)         AS categoria_ordem,
               c.nome                           AS categoria_nome
        FROM lancamentos_despesas ld
        INNER JOIN titulos_despesas    t ON t.id = ld.titulo_id
        INNER JOIN categorias_despesas c ON c.id = ld.categoria_id
        WHERE {' AND '.join(where)}
        ORDER BY titulo_ordem, t.nome, categoria_ordem, c.nome, ld.data
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    return rows


def _build_despesas_blocks(lancamentos, months):
    """
    Constrói blocos de despesas por Título (bloco) → Categoria (linha).

    Retorna (blocks, grand_by_month, grand_total).
    """
    month_keys      = {m['key'] for m in months}
    titulo_meta     = {}   # tit_id → (nome, ordem)
    categoria_meta  = {}   # cat_id → (nome, tit_id, ordem)
    tree: dict      = {}   # tit_id → cat_id → mk → float

    for row in lancamentos:
        tit_id = row['titulo_id']
        cat_id = row['categoria_id']
        d      = row['data']
        if isinstance(d, str):
            try:
                d = datetime.strptime(d, '%Y-%m-%d').date()
            except ValueError:
                continue
        mk = _make_month_key(d.year, d.month)
        if mk not in month_keys:
            continue

        titulo_meta.setdefault(tit_id,    (row['titulo_nome'],    row['titulo_ordem']))
        categoria_meta.setdefault(cat_id, (row['categoria_nome'], tit_id, row['categoria_ordem']))

        tree.setdefault(tit_id, {})
        tree[tit_id].setdefault(cat_id, {})
        tree[tit_id][cat_id][mk] = (
            tree[tit_id][cat_id].get(mk, 0.0) + float(row['valor'])
        )

    grand_by_month = {m['key']: 0.0 for m in months}
    grand_total    = 0.0
    blocks         = []

    for tit_id in sorted(tree, key=lambda x: (titulo_meta[x][1], titulo_meta[x][0])):
        block_by_month = {m['key']: 0.0 for m in months}
        rows_out       = []

        for cat_id in sorted(
            tree[tit_id],
            key=lambda x: (categoria_meta[x][2], categoria_meta[x][0]),
        ):
            cat_by_month = {m['key']: 0.0 for m in months}
            for m in months:
                val = tree[tit_id][cat_id].get(m['key'], 0.0)
                cat_by_month[m['key']]  = val
                block_by_month[m['key']] += val
            cat_total = sum(cat_by_month.values())
            rows_out.append({
                'categoria_id':   cat_id,
                'categoria_nome': categoria_meta[cat_id][0],
                'by_month':       cat_by_month,
                'total':          cat_total,
            })

        block_total = sum(block_by_month.values())
        for mk, v in block_by_month.items():
            grand_by_month[mk] = grand_by_month.get(mk, 0.0) + v
        grand_total += block_total

        blocks.append({
            'titulo_id':        tit_id,
            'titulo_nome':      titulo_meta[tit_id][0],
            'rows':             rows_out,
            'total_by_month':   block_by_month,
            'total':            block_total,
        })

    return blocks, grand_by_month, grand_total


# ──────────────────────────────────────────────────────────────────────────────
# Rota principal
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/dre_postos', methods=['GET'])
@login_required
@admin_required
def dre_postos():
    """DRE Postos — Demonstração do Resultado do Exercício."""
    args = request.args

    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()
    if not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]
    titulo_ids  = [t for t in args.getlist('titulo_ids[]')  if t]
    forma_ids   = [f for f in args.getlist('forma_ids[]')   if f]

    # Flags para incluir/excluir blocos de receita
    include_vendas  = args.get('include_vendas',  '1') == '1'
    include_aluguel = args.get('include_aluguel', '1') == '1'
    include_prazo   = args.get('include_prazo',   '1') == '1'

    conn = get_db_connection()
    try:
        empresas = _empresas_list(conn)
        titulos  = _titulos_list(conn)
        formas   = _formas_recebimento_aluguel_prazo(conn)
        months   = _months_in_range(data_inicio, data_fim)

        # ── Dados ────────────────────────────────────────────────────────────
        vendas_reais_by_month:  dict = {}
        vendas_litros_by_month: dict = {}
        recebimentos:           dict = {
            'aluguel': {}, 'aluguel_formas': [],
            'cliente_a_prazo': {}, 'cliente_a_prazo_formas': [],
        }
        despesas_blocks:           list = []
        grand_despesas_by_month:   dict = {}
        grand_despesas:            float = 0.0

        if months:
            vendas_reais_by_month  = _fetch_vendas_reais(
                conn, data_inicio, data_fim, empresa_ids)
            vendas_litros_by_month = _fetch_vendas_litros(
                conn, data_inicio, data_fim, empresa_ids)
            recebimentos = _fetch_recebimentos(
                conn, data_inicio, data_fim, empresa_ids, forma_ids)

            lancamentos = _fetch_despesas_lancamentos(
                conn, data_inicio, data_fim, empresa_ids, titulo_ids)
            despesas_blocks, grand_despesas_by_month, grand_despesas = (
                _build_despesas_blocks(lancamentos, months)
            )

        # ── Totais de receita por mês ─────────────────────────────────────
        receitas_by_month: dict = {}
        for m in months:
            mk    = m['key']
            total = 0.0
            if include_vendas:
                total += vendas_reais_by_month.get(mk, 0.0)
            if include_aluguel:
                total += recebimentos['aluguel'].get(mk, 0.0)
            if include_prazo:
                total += recebimentos['cliente_a_prazo'].get(mk, 0.0)
            receitas_by_month[mk] = total

        grand_receitas = sum(receitas_by_month.values())

        # ── Lucro = Receitas − Despesas ───────────────────────────────────
        lucro_by_month: dict = {}
        for m in months:
            mk = m['key']
            lucro_by_month[mk] = (
                receitas_by_month.get(mk, 0.0)
                - grand_despesas_by_month.get(mk, 0.0)
            )
        grand_lucro = grand_receitas - grand_despesas

        # ── Acumulados para a coluna TOTAL ────────────────────────────────
        grand_vendas_reais  = sum(
            vendas_reais_by_month.get(m['key'], 0.0) for m in months)
        grand_aluguel       = sum(
            recebimentos['aluguel'].get(m['key'], 0.0) for m in months)
        grand_prazo         = sum(
            recebimentos['cliente_a_prazo'].get(m['key'], 0.0) for m in months)

        # litros acumulados por produto
        grand_vendas_litros: dict = {}
        for m in months:
            for prod, lts in vendas_litros_by_month.get(m['key'], {}).items():
                grand_vendas_litros[prod] = (
                    grand_vendas_litros.get(prod, 0.0) + lts)

    finally:
        conn.close()

    return render_template(
        'relatorios/dre_postos.html',
        # filtros
        empresas=empresas,
        titulos=titulos,
        formas=formas,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        titulo_ids=titulo_ids,
        forma_ids=forma_ids,
        include_vendas=include_vendas,
        include_aluguel=include_aluguel,
        include_prazo=include_prazo,
        # meses
        months=months,
        # receitas
        vendas_reais_by_month=vendas_reais_by_month,
        vendas_litros_by_month=vendas_litros_by_month,
        recebimentos=recebimentos,
        receitas_by_month=receitas_by_month,
        grand_vendas_reais=grand_vendas_reais,
        grand_vendas_litros=grand_vendas_litros,
        grand_aluguel=grand_aluguel,
        grand_prazo=grand_prazo,
        grand_receitas=grand_receitas,
        # despesas
        despesas_blocks=despesas_blocks,
        grand_despesas_by_month=grand_despesas_by_month,
        grand_despesas=grand_despesas,
        # resultado
        lucro_by_month=lucro_by_month,
        grand_lucro=grand_lucro,
    )
