"""
DRE Postos — Demonstração do Resultado do Exercício.

Combina num único relatório em formato de matriz mensal:
  1. RECEITAS
     - Vendas de Combustíveis em R$ (lancamentos_caixa_receitas, tipo='VENDAS POSTO'/'ARLA'/'LUBRIFICANTES')
     - Vendas de Combustíveis em Litros (vendas_posto)
     - Recebimentos de Aluguel (bank_transactions + formas_recebimento)
     - Clientes à Prazo       (bank_transactions + formas_recebimento)
  2. CMV — CUSTO DA MERCADORIA VENDIDA
     - Estoque Inicial (vendas_posto.estoque_inicial no dia 01 do mês, em Litros e R$)
     - Compras         (fretes, em Litros e R$)
     - Estoque Final   (vendas_posto.estoque_inicial no dia 01 do mês seguinte, em Litros e R$)
     - CMV = Estoque Inicial + Compras − Estoque Final
  3. DESPESAS
     - lancamentos_despesas agrupados por Título / Categoria
  4. LUCRO OPERACIONAL = RECEITAS − CMV − DESPESAS

Multi-empresa: empresa_ids[] restringe quais empresas contribuem com dados.
Filtros adicionais: titulo_ids[] filtra quais títulos de despesa incluir.
Filtro de formas: forma_ids[] filtra formas de recebimento de banco.

Rota:
  GET /relatorios/dre_postos
"""
import logging
import unicodedata
from collections import defaultdict
from datetime import date, datetime

import mysql.connector

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from routes.auth import admin_required
from routes.conf_despesas import (_fetch_taxas_cartao, _aplicar_taxas_operadora,
                                   _empresas_donas)
from utils.db import get_db_connection

bp = Blueprint('dre_postos', __name__, url_prefix='/relatorios')

# MySQL server error numbers used in this module
_MYSQL_ERR_UNKNOWN_COLUMN = 1054  # "Unknown column '…' in field list"

_MES_LABELS = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']

# Matches the same logic used in the lancamentos_caixa lista route:
# include FECHADO, legacy NULL, and ABERTO records that are not auto-generated Troco PIX.
_LC_STATUS_COND = (
    "(lc.status = 'FECHADO'"
    " OR lc.status IS NULL"
    " OR (lc.status = 'ABERTO'"
    "     AND (lc.observacao IS NULL"
    "          OR lc.observacao NOT LIKE 'Lançamento automático - Troco PIX%')))"
)


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
            "SELECT id, nome, COALESCE(ordem, 9999) AS ordem"
            " FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome"
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
        cur.execute("SELECT id, nome, dre_grupo FROM formas_recebimento ORDER BY nome")
        all_formas = cur.fetchall()
    except Exception:
        try:
            cur.execute("SELECT id, nome FROM formas_recebimento ORDER BY nome")
            all_formas = cur.fetchall()
        except Exception:
            all_formas = []
    cur.close()
    return [f for f in all_formas if _classify_forma(f['nome'], f.get('dre_grupo')) is not None]


# ──────────────────────────────────────────────────────────────────────────────
# Configuração por empresa
# ──────────────────────────────────────────────────────────────────────────────

def _parse_empresa_configs(args, empresa_ids):
    """
    Retorna {eid: config_dict} com as configurações individuais por empresa.

    Formato novo (por empresa):
      cf_{eid}_submitted=1       — sentinel que indica que a config foi enviada
      cf_{eid}_titulos[]         — IDs dos títulos de despesa (vazio = todos)
      cf_{eid}_formas[]          — IDs das formas de recebimento (vazio = todas)
      cf_{eid}_vendas=0|1        — incluir vendas   (hidden 0 + checkbox 1)
      cf_{eid}_aluguel=0|1       — incluir aluguel
      cf_{eid}_prazo=0|1         — incluir clientes à prazo
      cf_{eid}_compras=0|1       — incluir compras (fretes)

    Backward compat: se o sentinel cf_{eid}_submitted não existir,
    usa os parâmetros globais antigos (titulo_ids[], forma_ids[], include_*).
    """
    # Fallback global (parâmetros do formato anterior)
    global_titulo_ids      = [t for t in args.getlist('titulo_ids[]') if t]
    global_forma_ids       = [f for f in args.getlist('forma_ids[]')  if f]
    global_include_vendas  = args.get('include_vendas',  '1') == '1'
    global_include_aluguel = args.get('include_aluguel', '1') == '1'
    global_include_prazo   = args.get('include_prazo',   '1') == '1'
    global_include_compras = args.get('include_compras', '1') == '1'

    configs = {}
    for eid in empresa_ids:
        if f'cf_{eid}_submitted' in args:
            # Configuração nova por empresa
            configs[eid] = {
                'titulo_ids':      [t for t in args.getlist(f'cf_{eid}_titulos[]') if t],
                'forma_ids':       [f for f in args.getlist(f'cf_{eid}_formas[]')  if f],
                'include_vendas':  '1' in args.getlist(f'cf_{eid}_vendas'),
                'include_aluguel': '1' in args.getlist(f'cf_{eid}_aluguel'),
                'include_prazo':   '1' in args.getlist(f'cf_{eid}_prazo'),
                'include_compras': '1' in args.getlist(f'cf_{eid}_compras'),
                'include_cartoes': '1' in args.getlist(f'cf_{eid}_cartoes')
                                   if f'cf_{eid}_cartoes' in args else True,
            }
        else:
            # Fallback para parâmetros globais (compatibilidade com URLs antigas)
            configs[eid] = {
                'titulo_ids':      global_titulo_ids,
                'forma_ids':       global_forma_ids,
                'include_vendas':  global_include_vendas,
                'include_aluguel': global_include_aluguel,
                'include_prazo':   global_include_prazo,
                'include_compras': global_include_compras,
                'include_cartoes': True,
            }
    return configs


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
              AND {_LC_STATUS_COND}
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
# Receitas: Vendas de Combustíveis (por produto — Litros + R$)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_vendas_por_produto(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna vendas por produto por mês via vendas_posto (cobre meses ABERTO e FECHADO).
    Retorna {mk: {produto_nome: {'litros': float, 'reais': float}}}.
    mk = 'YYYYMM'
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f'AND vp.cliente_id IN ({ph_emp})' if ph_emp else ''
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])

    try:
        cur.execute(f"""
            SELECT YEAR(vp.data_movimento)  AS yr,
                   MONTH(vp.data_movimento) AS mo,
                   p.nome                   AS produto_nome,
                   SUM(COALESCE(vp.quantidade_litros, 0)) AS litros,
                   SUM(COALESCE(vp.valor_total, 0))       AS reais
            FROM vendas_posto vp
            INNER JOIN produto p ON p.id = vp.produto_id
            WHERE vp.data_movimento BETWEEN %s AND %s
              {emp_cond}
            GROUP BY yr, mo, p.nome
            ORDER BY yr, mo, p.nome
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result: dict = {}
    for r in rows:
        mk   = _make_month_key(r['yr'], r['mo'])
        prod = r['produto_nome']
        entry = result.setdefault(mk, {}).setdefault(
            prod, {'litros': 0.0, 'reais': 0.0})
        entry['litros'] += float(r['litros'] or 0)
        entry['reais']  += float(r['reais']  or 0)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Receitas: Vendas extras (ARLA, Lubrificantes) — somente R$
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_vendas_extras_caixa(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna ARLA e LUBRIFICANTES de lancamentos_caixa_receitas por mês (somente R$).
    Retorna {mk: {tipo_nome: {'litros': 0.0, 'reais': float}}}.
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f'AND lc.cliente_id IN ({ph_emp})' if ph_emp else ''
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])
    try:
        cur.execute(f"""
            SELECT YEAR(lc.data)  AS yr,
                   MONTH(lc.data) AS mo,
                   UPPER(TRIM(lcr.tipo)) AS tipo_nome,
                   SUM(lcr.valor)        AS reais
            FROM lancamentos_caixa_receitas lcr
            INNER JOIN lancamentos_caixa lc ON lc.id = lcr.lancamento_caixa_id
            WHERE lc.data BETWEEN %s AND %s
              AND {_LC_STATUS_COND}
              AND UPPER(TRIM(lcr.tipo)) IN ('ARLA', 'LUBRIFICANTES')
              {emp_cond}
            GROUP BY yr, mo, tipo_nome
            ORDER BY yr, mo, tipo_nome
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result: dict = {}
    for r in rows:
        mk   = _make_month_key(r['yr'], r['mo'])
        prod = r['tipo_nome']  # 'ARLA' or 'LUBRIFICANTES'
        entry = result.setdefault(mk, {}).setdefault(
            prod, {'litros': 0.0, 'reais': 0.0})
        entry['reais'] += float(r['reais'] or 0)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Compras: fretes por produto (Litros + R$)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_compras(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna compras de combustíveis por produto por mês via tabela fretes.
    Retorna {mk: {produto_nome: {'litros': float, 'reais': float}}}.
    O filtro de empresa usa fretes.clientes_id.
    """
    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond = f'AND f.clientes_id IN ({ph_emp})' if ph_emp else ''
    params = [data_inicio, data_fim] + (list(empresa_ids) if empresa_ids else [])

    try:
        cur.execute(f"""
            SELECT YEAR(f.data_frete)  AS yr,
                   MONTH(f.data_frete) AS mo,
                   COALESCE(p.nome, 'Sem produto') AS produto_nome,
                   SUM(COALESCE(f.quantidade_manual, q.valor, 0)) AS litros,
                   SUM(COALESCE(f.total_nf_compra, 0))            AS reais
            FROM fretes f
            LEFT JOIN produto    p ON p.id = f.produto_id
            LEFT JOIN quantidades q ON q.id = f.quantidade_id
            WHERE f.data_frete BETWEEN %s AND %s
              {emp_cond}
            GROUP BY yr, mo, p.nome
            ORDER BY yr, mo, p.nome
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result: dict = {}
    for r in rows:
        mk   = _make_month_key(r['yr'], r['mo'])
        prod = r['produto_nome']
        entry = result.setdefault(mk, {}).setdefault(
            prod, {'litros': 0.0, 'reais': 0.0})
        entry['litros'] += float(r['litros'] or 0)
        entry['reais']  += float(r['reais']  or 0)
    return result


def _fetch_estoque_mensal(conn, data_inicio, data_fim, empresa_ids, months):
    """
    Retorna estoque inicial (EI) e final (EF) por produto para cada mês do período.

    EI[M] = MAX(vendas_posto.estoque_inicial) no dia 01 do mês M.
    EF[M] = MAX(vendas_posto.estoque_inicial) no dia 01 do mês M+1.
    Valor R$ = litros × custo médio ponderado das compras do período (fretes).

    Retorna {
        'ei': {mk: {produto_nome: {'litros': float, 'reais': float}}},
        'ef': {mk: {produto_nome: {'litros': float, 'reais': float}}},
    }.
    """
    if not months:
        return {'ei': {}, 'ef': {}}

    cur = conn.cursor(dictionary=True)
    ph_emp = ','.join(['%s'] * len(empresa_ids)) if empresa_ids else None
    emp_cond_vp = f'AND vp.cliente_id IN ({ph_emp})' if ph_emp else ''
    emp_cond_f  = f'AND f.clientes_id IN ({ph_emp})' if ph_emp else ''
    emp_params  = list(empresa_ids) if empresa_ids else []

    # Collect all dates needed: 1st of each month + 1st of next month
    date_to_roles: dict = {}
    for m in months:
        yr, mo = m['year'], m['month']
        mk = m['key']
        d_ei = date(yr, mo, 1)
        d_ef = date(yr + 1, 1, 1) if mo == 12 else date(yr, mo + 1, 1)
        date_to_roles.setdefault(d_ei, []).append((mk, 'ei'))
        date_to_roles.setdefault(d_ef, []).append((mk, 'ef'))

    all_dates = sorted(date_to_roles.keys())

    # ── Estoque (litros) por produto por data ────────────────────────────────
    stock_by_date: dict = {}
    try:
        ph_dates = ','.join(['%s'] * len(all_dates))
        params = all_dates + emp_params
        cur.execute(f"""
            SELECT vp.data_movimento,
                   COALESCE(p.nome, 'Sem produto') AS produto_nome,
                   SUM(vp.estoque_inicial)          AS litros
            FROM vendas_posto vp
            LEFT JOIN produto p ON p.id = vp.produto_id
            WHERE vp.data_movimento IN ({ph_dates})
              AND vp.estoque_inicial IS NOT NULL
              {emp_cond_vp}
            GROUP BY vp.data_movimento, p.nome
        """, params)
        for r in cur.fetchall():
            d = r['data_movimento']
            stock_by_date.setdefault(d, {})[r['produto_nome']] = float(r['litros'] or 0)
    except Exception:
        pass

    # ── Custo médio ponderado por produto (R$/litro) via fretes ─────────────
    avg_cost: dict = {}
    try:
        params_f = [data_inicio, data_fim] + emp_params
        cur.execute(f"""
            SELECT COALESCE(p.nome, 'Sem produto')                AS produto_nome,
                   SUM(COALESCE(f.total_nf_compra, 0))            AS total_reais,
                   SUM(COALESCE(f.quantidade_manual, q.valor, 0)) AS total_litros
            FROM fretes f
            LEFT JOIN produto    p ON p.id = f.produto_id
            LEFT JOIN quantidades q ON q.id = f.quantidade_id
            WHERE f.data_frete BETWEEN %s AND %s
              {emp_cond_f}
              AND COALESCE(f.quantidade_manual, q.valor, 0) > 0
            GROUP BY p.nome
        """, params_f)
        for r in cur.fetchall():
            litros = float(r['total_litros'] or 0)
            reais  = float(r['total_reais']  or 0)
            avg_cost[r['produto_nome']] = reais / litros if litros > 0 else 0.0
    except Exception:
        pass

    cur.close()

    # ── Monta resultado EI / EF ──────────────────────────────────────────────
    result_ei: dict = {}
    result_ef: dict = {}
    for d, roles in date_to_roles.items():
        prods = stock_by_date.get(d, {})
        for mk, role in roles:
            target = result_ei if role == 'ei' else result_ef
            for prod, litros in prods.items():
                cost  = avg_cost.get(prod, 0.0)
                entry = target.setdefault(mk, {}).setdefault(
                    prod, {'litros': 0.0, 'reais': 0.0})
                entry['litros'] += litros
                entry['reais']  += litros * cost

    return {'ei': result_ei, 'ef': result_ef}


def _agg_por_produto(agg: dict, new_data: dict) -> None:
    """Agrega new_data {mk: {prod: {litros, reais}}} no dicionário agg (in-place)."""
    for mk, prod_map in new_data.items():
        for prod, vals in prod_map.items():
            entry = agg.setdefault(mk, {}).setdefault(
                prod, {'litros': 0.0, 'reais': 0.0})
            entry['litros'] += vals['litros']
            entry['reais']  += vals['reais']


def _grand_por_produto(por_produto: dict, months) -> dict:
    """Acumula totais por produto em todos os meses. Retorna {prod: {litros, reais}}."""
    grand: dict = {}
    month_keys = {m['key'] for m in months}
    for mk, prod_map in por_produto.items():
        if mk not in month_keys:
            continue
        for prod, vals in prod_map.items():
            entry = grand.setdefault(prod, {'litros': 0.0, 'reais': 0.0})
            entry['litros'] += vals['litros']
            entry['reais']  += vals['reais']
    return grand


# ──────────────────────────────────────────────────────────────────────────────
# Receitas: Recebimentos (Aluguel + Clientes à Prazo)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_forma(nome, dre_grupo=None):
    """Retorna 'aluguel', 'cliente_a_prazo', 'financeira', 'outras' ou None.

    24/11/2026: formas_recebimento.dre_grupo (botão no card da forma) manda:
    'financeira' / 'outras' entram nessas linhas, 'nao' tira do DRE; vazio =
    automático pelo nome (como sempre foi)."""
    g = (dre_grupo or '').strip()
    if g == 'nao':
        return None
    if g in ('financeira', 'outras'):
        return g
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
                   fr.dre_grupo            AS dre_grupo,
                   SUM(bt.valor)           AS total
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.account_id
            JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
            WHERE bt.tipo = 'CREDIT'
              AND bt.status != 'ignorado'
              AND bt.data_transacao BETWEEN %s AND %s
              {emp_clause}
              {forma_clause}
              -- 24/11/2026: frete marcado no DRE entra só o recebido à mão
              -- (PIX/TED do extrato); o boleto é do sistema de frete.
              AND NOT (fr.nome LIKE '%%FRETE%%'
                       AND COALESCE(fr.dre_grupo, '') IN ('financeira', 'outras')
                       AND (bt.descricao LIKE 'Pagamento recebido%%'
                            OR bt.descricao LIKE 'Recebimento de cobran%%'))
            GROUP BY yr, mo, fr.id, fr.nome, fr.dre_grupo
            ORDER BY fr.nome, yr, mo
        """, [data_inicio, data_fim] + emp_params + forma_params)
        rows = cur.fetchall()
    except Exception:
        logging.getLogger(__name__).exception('dre_postos: recebimentos')
        rows = []

    # Sobra da devolução de despesa (resgate de aplicação que voltou com
    # rendimento): crédito − o que abateu da despesa = receita financeira.
    try:
        cur.execute(f"""
            SELECT YEAR(bt.data_transacao) AS yr, MONTH(bt.data_transacao) AS mo,
                   0 AS forma_id, 'Rendimento de aplicação (resgate)' AS forma_nome,
                   'financeira' AS dre_grupo,
                   bt.valor + COALESCE((SELECT SUM(ld.valor) FROM lancamentos_despesas ld
                                         WHERE ld.bank_transaction_id = bt.id), 0) AS total
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.account_id
            WHERE bt.tipo = 'CREDIT' AND bt.status = 'conciliado'
              AND bt.tipo_conciliacao = 'devolucao_despesa'
              AND bt.data_transacao BETWEEN %s AND %s
              {emp_clause}
            HAVING total >= 0.005
        """, [data_inicio, data_fim] + emp_params)
        rows = list(rows) + list(cur.fetchall())
    except Exception:
        logging.getLogger(__name__).exception('dre_postos: sobra de devolução')
    cur.close()

    aluguel_acc:  dict = {}
    prazo_acc:    dict = {}
    fin_acc:      dict = {}
    outras_acc:   dict = {}
    stores = {'aluguel': aluguel_acc, 'cliente_a_prazo': prazo_acc,
              'financeira': fin_acc, 'outras': outras_acc}

    for row in rows:
        grupo = _classify_forma(row['forma_nome'], row.get('dre_grupo'))
        if grupo is None:
            continue
        mk   = _make_month_key(row['yr'], row['mo'])
        val  = float(row['total'] or 0)
        nome = row['forma_nome']
        store = stores[grupo]

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
        'financeira':           _agg(fin_acc),
        'financeira_formas':    _rows(fin_acc),
        'outras':               _agg(outras_acc),
        'outras_formas':        _rows(outras_acc),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Despesas: lancamentos_despesas agrupados por Título / Categoria
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_func_lancamentos_dre(conn, months, empresa_ids):
    """
    Busca lançamentos de funcionários (lancamentosfuncionarios_v2) e os converte
    em dicts sintéticos compatíveis com _build_despesas_blocks.

    Cada funcionário vira uma "categoria" dentro de um bloco cujo nome é a
    categoria funcional pluralizada (FRENTISTAS, OUTROS…).

    Motoristas são excluídos do bloco FUNCIONÁRIOS — o custo de pessoal deles é
    injetado no bloco CAMINHÕES via salary_mk.

    Retorna (func_rows, salary_mk) onde:
      func_rows   – lista de dicts sintéticos para _build_despesas_blocks (sem motoristas)
      salary_mk   – {mk: float} total de salário de motoristas por mês ('YYYYMM')
    """
    if not months:
        return []

    from routes.lancamentos_funcionarios import _ensure_tipo_funcionario
    _ensure_tipo_funcionario(conn)

    mes_list = [f"{m['month']:02d}/{m['year']}" for m in months]
    ph       = ','.join(['%s'] * len(mes_list))
    params: list = list(mes_list)

    where = [f"lf.mes IN ({ph})"]
    if empresa_ids:
        ph2 = ','.join(['%s'] * len(empresa_ids))
        where.append(f"lf.clienteid IN ({ph2})")
        params.extend(empresa_ids)

    sql = f"""
        SELECT lf.funcionarioid,
               CASE
                   WHEN lf.tipo_funcionario = 'motorista' THEN m.nome
                   ELSE f.nome
               END                                    AS funcionario_nome,
               CASE
                   WHEN lf.tipo_funcionario = 'motorista' THEN 'MOTORISTA'
                   ELSE UPPER(COALESCE(f.categoria, 'OUTROS'))
               END                                    AS categoria_func,
               lf.mes,
               COALESCE(lf.valor, 0)                 AS valor
        FROM lancamentosfuncionarios_v2 lf
        LEFT JOIN funcionarios f ON f.id = lf.funcionarioid
                                 AND lf.tipo_funcionario = 'funcionario'
        LEFT JOIN motoristas   m ON m.id = lf.funcionarioid
                                 AND lf.tipo_funcionario = 'motorista'
        WHERE {' AND '.join(where)}
        ORDER BY categoria_func, funcionario_nome, lf.mes
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result:     list = []
    salary_mk:  dict = {}   # mk → total salary de motoristas

    for row in rows:
        mes = row['mes'] or ''
        try:
            parts = mes.split('/')
            mo, yr = int(parts[0]), int(parts[1])
            d = date(yr, mo, 1)
        except Exception:
            continue

        mk       = _make_month_key(yr, mo)
        fid      = row['funcionarioid']
        nome     = row['funcionario_nome'] or str(fid)
        cat_func = row['categoria_func'] or 'OUTROS'
        valor    = float(row['valor'] or 0)

        if cat_func == 'MOTORISTA':
            # Motoristas não aparecem como bloco independente no DRE, mas o
            # salário é acumulado para injeção no bloco CAMINHÕES.
            salary_mk[mk] = salary_mk.get(mk, 0.0) + valor
            continue

        # Pluraliza: FRENTISTA→FRENTISTAS, OUTROS→OUTROS, etc.
        titulo_nome = cat_func + 'S' if not cat_func.endswith('S') else cat_func

        result.append({
            'data':            d,
            'valor':           valor,
            'titulo_id':       f'func_{cat_func.lower()}',
            'titulo_ordem':    9999,
            'titulo_nome':     titulo_nome,
            'categoria_id':    f'func_{cat_func}_{fid}',
            'categoria_ordem': 0,
            'categoria_nome':  nome,
        })
    return result, salary_mk


def _fetch_motorista_salary_empresa_dre(conn, months, empresa_ids):
    """
    Retorna salário total de motoristas por mês para a(s) empresa(s) indicada(s).
    Usado para injetar o custo de pessoal no bloco CAMINHÕES do DRE.
    Retorna {mk: float} onde mk = 'YYYYMM'.
    """
    if not months:
        return {}

    from routes.lancamentos_funcionarios import _ensure_tipo_funcionario
    _ensure_tipo_funcionario(conn)

    mes_list = [f"{m['month']:02d}/{m['year']}" for m in months]
    ph       = ','.join(['%s'] * len(mes_list))
    params: list = list(mes_list)

    where = [f"lf.mes IN ({ph})", "lf.tipo_funcionario = 'motorista'"]
    if empresa_ids:
        ph2 = ','.join(['%s'] * len(empresa_ids))
        where.append(f"lf.clienteid IN ({ph2})")
        params.extend(empresa_ids)

    sql = f"""
        SELECT lf.mes, COALESCE(SUM(lf.valor), 0) AS total
        FROM lancamentosfuncionarios_v2 lf
        WHERE {' AND '.join(where)}
        GROUP BY lf.mes
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result = {}
    for r in rows:
        mes = r['mes'] or ''
        try:
            parts = mes.split('/')
            mk = f"{parts[1]}{int(parts[0]):02d}"
            result[mk] = result.get(mk, 0.0) + float(r['total'] or 0)
        except Exception:
            continue
    return result


def _lookup_caminhoes_titulo(conn):
    """
    Retorna metadados (id, nome, ordem) do título de despesa cujo nome contenha
    'CAMINHÃO' / 'CAMINHAO' (case-insensitive, ignora acentos).

    NÃO filtra por ativo — o título pode estar marcado como inativo no filtro do
    relatório e mesmo assim ter lançamentos que precisam da injeção salary/receita.
    Retorna None se não encontrado.
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nome, COALESCE(ordem, 9999) AS ordem"
            " FROM titulos_despesas"
            " ORDER BY ativo DESC, ordem, id"
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    # há três "CAMINHÕES" (7 ativo; 18 e 27 inativos, vazios): fica o ativo,
    # e 'ids' guarda todos para tirar os lançamentos de qualquer um deles
    cams = [r for r in rows
            if 'CAMINHAO' in _ascii_upper(r['nome'])
            or 'CAMINHOES' in _ascii_upper(r['nome'])]
    if not cams:
        return None
    r = dict(cams[0])
    r['ids'] = {str(c['id']) for c in cams}
    return r


def _fetch_frete_receita_empresa_dre(conn, data_inicio, data_fim, empresa_ids):
    """
    Retorna receita total de fretes por mês para veículos associados aos motoristas
    da(s) empresa(s) indicada(s).

    Usa motoristas.veiculo_id (atribuição permanente do veículo ao motorista),
    exactamente como conf_despesas faz em _fetch_veiculos_motoristas + _fetch_frete_data_by_vehicle.
    lf.caminhaoid NÃO é usado aqui porque frequentemente é NULL e causaria perda
    de receita de frete.

    Retorna {mk: float} onde mk = 'YYYYMM'.
    """
    if not empresa_ids:
        return {}

    ph_emp = ','.join(['%s'] * len(empresa_ids))
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"""
            SELECT DISTINCT m.veiculo_id
            FROM motoristas m
            INNER JOIN lancamentosfuncionarios_v2 lf
                ON lf.funcionarioid = m.id AND lf.tipo_funcionario = 'motorista'
            WHERE lf.clienteid IN ({ph_emp})
              AND m.veiculo_id IS NOT NULL
        """, list(empresa_ids))
        vid_rows = cur.fetchall()
    except Exception:
        cur.close()
        return {}

    if not vid_rows:
        cur.close()
        return {}

    vids   = [r['veiculo_id'] for r in vid_rows]
    ph_v   = ','.join(['%s'] * len(vids))
    try:
        cur.execute(f"""
            SELECT DATE_FORMAT(f.data_frete, '%Y%m')          AS mk,
                   COALESCE(SUM(f.valor_total_frete), 0)      AS receita
            FROM fretes f
            WHERE f.data_frete BETWEEN %s AND %s
              AND f.veiculos_id IN ({ph_v})
            GROUP BY DATE_FORMAT(f.data_frete, '%Y%m')
        """, [data_inicio, data_fim] + vids)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    return {str(r['mk'] or ''): float(r['receita'] or 0) for r in rows}


def _fetch_despesas_lancamentos(conn, data_inicio, data_fim, empresa_ids, titulo_ids):
    """Retorna lançamentos de despesas filtrados com metadados de título e categoria."""
    log = logging.getLogger(__name__)

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

    _base_select = """
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
        WHERE {where_clause}
          {exibir_filter}
        ORDER BY titulo_ordem, t.nome, categoria_ordem, c.nome, ld.data
    """

    def _run(include_exibir_filter):
        # exibir_dre=1 means "show in DRE"; 0 means hidden
        ef = "AND COALESCE(c.exibir_dre, 1) = 1" if include_exibir_filter else ""
        sql = _base_select.format(where_clause=' AND '.join(where), exibir_filter=ef)
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    try:
        return _run(include_exibir_filter=True)
    except mysql.connector.errors.DatabaseError as exc:
        if exc.errno == _MYSQL_ERR_UNKNOWN_COLUMN:
            # exibir_dre column not yet added — fall back to showing all categories
            log.warning('_fetch_despesas_lancamentos: coluna exibir_dre ausente, '
                        'exibindo todas as categorias (migração pendente)')
            try:
                return _run(include_exibir_filter=False)
            except mysql.connector.errors.DatabaseError:
                log.exception('_fetch_despesas_lancamentos: falha no fallback sem exibir_dre')
                return []
        log.exception('_fetch_despesas_lancamentos: erro inesperado (errno=%s)', exc.errno)
        return []
    except Exception:
        log.exception('_fetch_despesas_lancamentos: erro inesperado')
        return []


def _lookup_aluguel_categoria(conn):
    """
    Retorna metadados (tit_id, tit_nome, tit_ordem, cat_id, cat_nome, cat_ordem)
    da primeira categoria de despesa cujo nome seja 'ALUGUEL' (case-insensitive),
    ou None se não existir.
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT c.id   AS cat_id,
                   c.nome AS cat_nome,
                   COALESCE(c.ordem, 9999) AS cat_ordem,
                   t.id   AS tit_id,
                   t.nome AS tit_nome,
                   COALESCE(t.ordem, 9999) AS tit_ordem
            FROM categorias_despesas c
            JOIN titulos_despesas t ON t.id = c.titulo_id
            WHERE UPPER(TRIM(c.nome)) = 'ALUGUEL'
            LIMIT 1
        """)
        row = cur.fetchone()
    except Exception:
        row = None
    cur.close()
    return row


def _fetch_despesas_retirada_aluguel_caixa(conn, data_inicio, data_fim, empresa_ids,
                                           aluguel_cat):
    """
    Busca pagamentos de RETIRADA ALUGUEL feitos em caixa
    (lancamentos_caixa_comprovacao com formas_pagamento_caixa.tipo='RETIRADA_PAGAMENTO'
    e lcc.descricao='RETIRADA ALUGUEL') e retorna linhas no mesmo formato que
    _fetch_despesas_lancamentos, usando os metadados de aluguel_cat.

    Isso garante que o aluguel pago em espécie aparece na mesma linha ALUGUEL
    do bloco DESPESAS do DRE, ao lado do aluguel pago via banco.
    """
    if not aluguel_cat:
        return []

    emp_clause = ''
    params: list = [data_inicio, data_fim]
    if empresa_ids:
        ph = ','.join(['%s'] * len(empresa_ids))
        emp_clause = f'AND lc.cliente_id IN ({ph})'
        params.extend([int(e) for e in empresa_ids])

    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"""
            SELECT lc.data,
                   SUM(lcc.valor) AS valor
            FROM lancamentos_caixa_comprovacao lcc
            INNER JOIN lancamentos_caixa lc ON lc.id = lcc.lancamento_caixa_id
            LEFT  JOIN formas_pagamento_caixa fp ON fp.id = lcc.forma_pagamento_id
            WHERE lc.data BETWEEN %s AND %s
              AND {_LC_STATUS_COND}
              {emp_clause}
              AND fp.tipo = 'RETIRADA_PAGAMENTO'
              AND UPPER(TRIM(COALESCE(lcc.descricao, ''))) = 'RETIRADA ALUGUEL'
            GROUP BY lc.data
            ORDER BY lc.data
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()

    result = []
    for row in rows:
        result.append({
            'data':           row['data'],
            'valor':          float(row['valor'] or 0),
            'titulo_id':      aluguel_cat['tit_id'],
            'titulo_ordem':   aluguel_cat['tit_ordem'],
            'titulo_nome':    aluguel_cat['tit_nome'],
            'categoria_id':   aluguel_cat['cat_id'],
            'categoria_ordem': aluguel_cat['cat_ordem'],
            'categoria_nome': aluguel_cat['cat_nome'],
        })
    return result


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
# Caminhões: custo dos transportes sem cobrança (Conf. Transportes)
# ──────────────────────────────────────────────────────────────────────────────

def _sem_cobranca_por_empresa(data_inicio, data_fim):
    """{cliente_id(str): {'nome', 'custo': {mk: R$}, 'custo_tot', 'litros_tot'}}
    — a mesma conta da linha "Custo dos sem cobrança" da Conf. Transportes."""
    from routes.conf_transportes import apurar
    out = {}
    try:
        for sc in apurar(data_inicio, data_fim)['sem_cobranca']:
            if sc.get('cid'):
                out[str(sc['cid'])] = {'nome': sc['nome'], 'custo': dict(sc['custo']),
                                       'custo_tot': sc['custo_tot'], 'litros_tot': sc['litros_tot']}
    except Exception:
        logging.getLogger(__name__).exception('dre_postos: custo dos sem cobrança')
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Período relativo (o filtro salvo "Ano atual" continua atual no ano que vem)
# ──────────────────────────────────────────────────────────────────────────────

_PERIODOS = ('mes', 'mesant', 'tri', 'ano', 'anoant', '12m')


def _periodo_relativo(per, hoje=None):
    from calendar import monthrange
    hoje = hoje or date.today()
    y, m = hoje.year, hoje.month

    def fim_mes(yy, mm):
        return date(yy, mm, monthrange(yy, mm)[1])

    if per == 'mes':
        a, b = date(y, m, 1), fim_mes(y, m)
    elif per == 'mesant':
        yy, mm = (y, m - 1) if m > 1 else (y - 1, 12)
        a, b = date(yy, mm, 1), fim_mes(yy, mm)
    elif per == 'tri':
        q = (m - 1) // 3 * 3 + 1
        a, b = date(y, q, 1), fim_mes(y, q + 2)
    elif per == 'anoant':
        a, b = date(y - 1, 1, 1), date(y - 1, 12, 31)
    elif per == '12m':
        yy, mm = (y - 1, m + 1) if m < 12 else (y, 1)
        a, b = date(yy, mm, 1), fim_mes(y, m)
    else:
        a, b = date(y, 1, 1), date(y, 12, 31)
    return a.isoformat(), b.isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# Filtros salvos (no banco, por usuário — antes ficavam só no navegador)
# ──────────────────────────────────────────────────────────────────────────────

_DDL_FILTROS = """
CREATE TABLE IF NOT EXISTS dre_filtros (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id  INT          NOT NULL,
    nome        VARCHAR(80)  NOT NULL,
    params      TEXT         NOT NULL,
    padrao      TINYINT(1)   NOT NULL DEFAULT 0,
    criado_em   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_usuario_nome (usuario_id, nome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
_filtros_tabela_ok = False


def _filtros_tabela(conn):
    """CREATE TABLE faz commit implícito: chamar fora de transação."""
    global _filtros_tabela_ok
    if not _filtros_tabela_ok:
        c = conn.cursor()
        c.execute(_DDL_FILTROS)
        c.close()
        _filtros_tabela_ok = True


def _usuario_id():
    try:
        return int(current_user.get_id())
    except (TypeError, ValueError, AttributeError):
        return 0


def _limpa_params(txt):
    """Só o que o formulário do DRE manda (sem csrf, sem lixo)."""
    from urllib.parse import parse_qsl, urlencode
    txt = (txt or '').strip().lstrip('?')
    ok = []
    for k, v in parse_qsl(txt, keep_blank_values=True):
        if k in ('data_inicio', 'data_fim', 'per', 'empresa_ids[]') or k.startswith('cf_'):
            ok.append((k, v))
    return urlencode(ok)


def _filtros_do_usuario(conn):
    _filtros_tabela(conn)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, params, padrao FROM dre_filtros WHERE usuario_id = %s"
                    " ORDER BY padrao DESC, nome", (_usuario_id(),))
        return cur.fetchall()
    finally:
        cur.close()


@bp.route('/dre_postos/filtros/salvar', methods=['POST'])
@login_required
@admin_required
def dre_filtro_salvar():
    nome = (request.form.get('nome') or '').strip()[:80]
    params = _limpa_params(request.form.get('params'))
    padrao = request.form.get('padrao') == '1'
    volta = url_for('dre_postos.dre_postos') + ('?' + params if params else '')
    if not nome:
        flash('Dê um nome ao filtro.', 'warning')
        return redirect(volta)
    conn = get_db_connection()
    try:
        _filtros_tabela(conn)
        cur = conn.cursor()
        uid = _usuario_id()
        if padrao:
            cur.execute("UPDATE dre_filtros SET padrao = 0 WHERE usuario_id = %s", (uid,))
        cur.execute("""INSERT INTO dre_filtros (usuario_id, nome, params, padrao) VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE params = VALUES(params), padrao = VALUES(padrao)""",
                    (uid, nome, params, 1 if padrao else 0))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    flash('Filtro "%s" salvo%s.' % (nome, ' e marcado como padrão' if padrao else ''), 'success')
    return redirect(volta)


@bp.route('/dre_postos/filtros/<int:fid>/<acao>', methods=['POST'])
@login_required
@admin_required
def dre_filtro_acao(fid, acao):
    volta = request.form.get('volta') or url_for('dre_postos.dre_postos')
    if not volta.startswith('/') or volta.startswith('//'):
        volta = url_for('dre_postos.dre_postos')
    conn = get_db_connection()
    try:
        _filtros_tabela(conn)
        cur = conn.cursor()
        uid = _usuario_id()
        if acao == 'excluir':
            cur.execute("DELETE FROM dre_filtros WHERE id = %s AND usuario_id = %s", (fid, uid))
            flash('Filtro excluído.', 'success')
        elif acao == 'padrao':
            cur.execute("SELECT padrao FROM dre_filtros WHERE id = %s AND usuario_id = %s", (fid, uid))
            r = cur.fetchone()
            cur.execute("UPDATE dre_filtros SET padrao = 0 WHERE usuario_id = %s", (uid,))
            if r and not r[0]:
                cur.execute("UPDATE dre_filtros SET padrao = 1 WHERE id = %s AND usuario_id = %s", (fid, uid))
                flash('Este filtro abre sozinho quando você entra no DRE.', 'success')
            else:
                flash('Nenhum filtro padrão agora.', 'success')
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return redirect(volta)


@bp.route('/dre_postos/filtros/importar', methods=['POST'])
@login_required
@admin_required
def dre_filtro_importar():
    """Traz para o banco os filtros que estavam só no navegador (localStorage)."""
    import json
    try:
        lista = json.loads(request.form.get('dados') or '[]')
    except ValueError:
        lista = []
    n = 0
    conn = get_db_connection()
    try:
        _filtros_tabela(conn)
        cur = conn.cursor()
        for it in lista[:50]:
            nome = str(it.get('nome') or '').strip()[:80]
            params = _limpa_params(it.get('params'))
            if nome and params:
                cur.execute("""INSERT IGNORE INTO dre_filtros (usuario_id, nome, params)
                               VALUES (%s, %s, %s)""", (_usuario_id(), nome, params))
                n += cur.rowcount
        conn.commit()
        cur.close()
    finally:
        conn.close()
    flash('%d filtro(s) do navegador agora estão salvos no sistema.' % n, 'success')
    volta = request.form.get('volta') or ''
    if not volta.startswith('/') or volta.startswith('//'):
        volta = url_for('dre_postos.dre_postos')
    return redirect(volta)


# ──────────────────────────────────────────────────────────────────────────────
# Rota principal
# ──────────────────────────────────────────────────────────────────────────────

@bp.route('/dre_postos', methods=['GET'])
@login_required
@admin_required
def dre_postos():
    """DRE Postos — Demonstração do Resultado do Exercício."""
    args = request.args

    # Sem nada na URL: abre o filtro marcado como padrão (se houver)
    if not args:
        try:
            _c = get_db_connection()
            try:
                padrao = next((f for f in _filtros_do_usuario(_c) if f['padrao']), None)
            finally:
                _c.close()
            if padrao and padrao['params']:
                return redirect(url_for('dre_postos.dre_postos') + '?' + padrao['params'])
        except Exception:
            logging.getLogger(__name__).exception('dre_postos: filtro padrão')

    data_inicio = args.get('data_inicio', '').strip()
    data_fim    = args.get('data_fim',    '').strip()
    per = args.get('per', '').strip()
    if per in _PERIODOS:
        data_inicio, data_fim = _periodo_relativo(per)
    elif not data_inicio and not data_fim:
        data_inicio, data_fim = _default_period()

    empresa_ids = [e for e in args.getlist('empresa_ids[]') if e]

    conn = get_db_connection()
    try:
        filtros_salvos = _filtros_do_usuario(conn)
        empresas = _empresas_list(conn)
        titulos  = _titulos_list(conn)
        formas   = _formas_recebimento_aluguel_prazo(conn)
        months   = _months_in_range(data_inicio, data_fim)

        empresas_por_id = {str(e['id']): e['nome'] for e in empresas}

        # ── Configurações por empresa ─────────────────────────────────────
        empresa_configs = _parse_empresa_configs(args, empresa_ids)

        # Versão JSON-serializável para o template/JS
        empresa_configs_for_js = {
            eid: {
                'titulo_ids':      cfg['titulo_ids'],
                'forma_ids':       cfg['forma_ids'],
                'include_vendas':  cfg['include_vendas'],
                'include_aluguel': cfg['include_aluguel'],
                'include_prazo':   cfg['include_prazo'],
                'include_compras': cfg['include_compras'],
                'include_cartoes': cfg['include_cartoes'],
            }
            for eid, cfg in empresa_configs.items()
        }

        # Flags agregadas (True se ao menos uma empresa inclui o bloco)
        any_include_vendas  = any(
            cfg['include_vendas']  for cfg in empresa_configs.values()
        ) if empresa_configs else False
        any_include_aluguel = any(
            cfg['include_aluguel'] for cfg in empresa_configs.values()
        ) if empresa_configs else False
        any_include_prazo   = any(
            cfg['include_prazo']   for cfg in empresa_configs.values()
        ) if empresa_configs else False
        any_include_compras = any(
            cfg['include_compras'] for cfg in empresa_configs.values()
        ) if empresa_configs else False

        # ── Acumuladores por empresa ──────────────────────────────────────
        agg_vendas_reais: dict    = defaultdict(float)
        agg_vendas_por_produto: dict = {}   # {mk: {prod: {litros, reais}}} — apenas combustíveis
        agg_arla_mk: dict         = defaultdict(float)   # ARLA por mês (R$)
        agg_lubrif_mk: dict       = defaultdict(float)   # LUBRIFICANTES por mês (R$)
        agg_compras_por_produto: dict = {}  # {mk: {prod: {litros, reais}}}
        agg_estoque_ei: dict      = {}   # {mk: {prod: {litros, reais}}}
        agg_estoque_ef: dict      = {}   # {mk: {prod: {litros, reais}}}
        agg_aluguel_mk: dict      = defaultdict(float)
        agg_prazo_mk: dict        = defaultdict(float)
        agg_aluguel_formas: dict  = {}   # nome → {by_month, total}
        agg_prazo_formas: dict    = {}
        agg_extra = {'financeira': (defaultdict(float), {}),   # (por mês, por forma)
                     'outras':     (defaultdict(float), {})}
        all_lancamentos: list     = []

        # Lookup da categoria ALUGUEL para mapear retiradas de caixa
        aluguel_cat = _lookup_aluguel_categoria(conn)

        # Mapa título_id → nome (para detectar o título FUNCIONÁRIOS por nome)
        _titulo_nome_by_id = {str(t['id']): t['nome'] for t in titulos}

        # Metadados do título CAMINHÕES (para injeção de motoristas e receita)
        # Usa lookup direto sem filtro ativo=1 — o título pode estar inativo no
        # filtro do relatório mas ainda ter lançamentos que precisam do ajuste.
        _caminhoes_tit = _lookup_caminhoes_titulo(conn)
        sem_cob_cache = None          # Conf. Transportes, calculado só se precisar
        caminhoes_sc: list = []       # empresas com custo de transporte sem cobrança

        if months and empresa_configs:
            for eid, cfg in empresa_configs.items():
                eid_list = [eid]

                # Vendas (R$ total + por produto)
                if cfg['include_vendas']:
                    for mk, v in _fetch_vendas_reais(
                            conn, data_inicio, data_fim, eid_list).items():
                        agg_vendas_reais[mk] += v
                    _agg_por_produto(
                        agg_vendas_por_produto,
                        _fetch_vendas_por_produto(
                            conn, data_inicio, data_fim, eid_list))
                    # ARLA e LUBRIFICANTES — mantidos separados
                    for mk, prods in _fetch_vendas_extras_caixa(
                            conn, data_inicio, data_fim, eid_list).items():
                        agg_arla_mk[mk]   += prods.get('ARLA',          {}).get('reais', 0.0)
                        agg_lubrif_mk[mk] += prods.get('LUBRIFICANTES', {}).get('reais', 0.0)

                # Compras (fretes) + Estoque para CMV
                if cfg['include_compras']:
                    _agg_por_produto(
                        agg_compras_por_produto,
                        _fetch_compras(conn, data_inicio, data_fim, eid_list))
                    estoque = _fetch_estoque_mensal(
                        conn, data_inicio, data_fim, eid_list, months)
                    _agg_por_produto(agg_estoque_ei, estoque['ei'])
                    _agg_por_produto(agg_estoque_ef, estoque['ef'])

                # Recebimentos bancários
                receb = _fetch_recebimentos(
                    conn, data_inicio, data_fim, eid_list, cfg['forma_ids'])

                if cfg['include_aluguel']:
                    for mk, v in receb['aluguel'].items():
                        agg_aluguel_mk[mk] += v
                    for f in receb['aluguel_formas']:
                        n = f['nome']
                        if n not in agg_aluguel_formas:
                            agg_aluguel_formas[n] = {
                                'nome':     n,
                                'by_month': defaultdict(float),
                                'total':    0.0,
                            }
                        for mk, v in f['by_month'].items():
                            agg_aluguel_formas[n]['by_month'][mk] += v
                        agg_aluguel_formas[n]['total'] += f['total']

                if cfg['include_prazo']:
                    for mk, v in receb['cliente_a_prazo'].items():
                        agg_prazo_mk[mk] += v
                    for f in receb['cliente_a_prazo_formas']:
                        n = f['nome']
                        if n not in agg_prazo_formas:
                            agg_prazo_formas[n] = {
                                'nome':     n,
                                'by_month': defaultdict(float),
                                'total':    0.0,
                            }
                        for mk, v in f['by_month'].items():
                            agg_prazo_formas[n]['by_month'][mk] += v
                        agg_prazo_formas[n]['total'] += f['total']

                # Receitas financeiras / Outras receitas: entram pela marcação
                # da forma (Cadastros › Formas de Recebimento), sem chave aqui.
                for g, (g_mk, g_formas) in agg_extra.items():
                    for mk, v in receb[g].items():
                        g_mk[mk] += v
                    for f in receb[g + '_formas']:
                        d = g_formas.setdefault(f['nome'], {'nome': f['nome'],
                                                            'by_month': defaultdict(float), 'total': 0.0})
                        for mk, v in f['by_month'].items():
                            d['by_month'][mk] += v
                        d['total'] += f['total']

                # Despesas (lançamentos bancários)
                lancamentos = _fetch_despesas_lancamentos(
                    conn, data_inicio, data_fim, eid_list, cfg['titulo_ids'])
                # 23/11/2026: os lançamentos do título CAMINHÕES são a frota
                # inteira; no DRE da empresa entra só o que o transporte sem
                # cobrança custou a ela (Conf. Transportes), logo abaixo.
                if _caminhoes_tit is not None:
                    lancamentos = [r for r in lancamentos
                                   if str(r.get('titulo_id')) not in _caminhoes_tit['ids']]
                all_lancamentos.extend(lancamentos)

                # Despesas de caixa: RETIRADA ALUGUEL
                # Incluir se: a categoria ALUGUEL existe E (sem filtro de título
                # OU o título da categoria ALUGUEL está no filtro da empresa)
                titulo_ids_set = set(str(t) for t in cfg['titulo_ids'])
                aluguel_titulo_ok = (
                    aluguel_cat is not None
                    and (not titulo_ids_set
                         or str(aluguel_cat['tit_id']) in titulo_ids_set)
                )
                if aluguel_titulo_ok:
                    retirada_rows = _fetch_despesas_retirada_aluguel_caixa(
                        conn, data_inicio, data_fim, eid_list, aluguel_cat)
                    all_lancamentos.extend(retirada_rows)

                # Despesas de pessoal: lancamentosfuncionarios_v2
                # Incluir se: sem filtro de título OU algum título selecionado
                # corresponde a "FUNCIONÁRIOS".
                # _fetch_func_lancamentos_dre também devolve salary_mk com os
                # salários de motoristas (mesmo query, evita segunda viagem ao DB
                # e elimina o risco de falha silenciosa da query separada).
                include_func = (
                    not titulo_ids_set
                    or any(
                        'FUNCIONARI' in _ascii_upper(_titulo_nome_by_id.get(tid, ''))
                        for tid in titulo_ids_set
                    )
                )
                if include_func:
                    func_rows, _ = _fetch_func_lancamentos_dre(conn, months, eid_list)
                    all_lancamentos.extend(func_rows)

                # CAMINHÕES = custo dos transportes sem cobrança desta empresa
                # (o mesmo número da linha "Custo dos sem cobrança" da Conf.
                # Transportes). Motoristas e receita de frete já estão nessa conta.
                caminhoes_ok = (
                    _caminhoes_tit is not None
                    and (not titulo_ids_set
                         or bool(_caminhoes_tit['ids'] & titulo_ids_set))
                )
                if caminhoes_ok:
                    if sem_cob_cache is None:
                        sem_cob_cache = _sem_cobranca_por_empresa(data_inicio, data_fim)
                    sc = sem_cob_cache.get(str(eid))
                    if sc:
                        ct = _caminhoes_tit
                        caminhoes_sc.append({'eid': str(eid), 'nome': empresas_por_id.get(str(eid), sc['nome']),
                                             'litros_tot': sc['litros_tot'], 'custo_tot': sc['custo_tot']})
                        for m in months:
                            v = sc['custo'].get(m['key'], 0.0)
                            if abs(v) < 0.005:
                                continue
                            all_lancamentos.append({
                                'data':            date(m['year'], m['month'], 1),
                                'valor':           v,
                                'titulo_id':       ct['id'],
                                'titulo_ordem':    int(ct['ordem']),
                                'titulo_nome':     ct['nome'],
                                'categoria_id':    'cam_sc_%s' % eid,
                                'categoria_ordem': 0,
                                'categoria_nome':  'Transportes sem cobrança — %s'
                                                   % empresas_por_id.get(str(eid), sc['nome']),
                            })

        def _sorted_formas_list(acc):
            return sorted(
                [{'nome': n, 'by_month': dict(d['by_month']), 'total': d['total']}
                 for n, d in acc.items()],
                key=lambda x: x['nome'],
            )

        recebimentos = {
            'aluguel':                dict(agg_aluguel_mk),
            'aluguel_formas':         _sorted_formas_list(agg_aluguel_formas),
            'cliente_a_prazo':        dict(agg_prazo_mk),
            'cliente_a_prazo_formas': _sorted_formas_list(agg_prazo_formas),
            'financeira':             dict(agg_extra['financeira'][0]),
            'financeira_formas':      _sorted_formas_list(agg_extra['financeira'][1]),
            'outras':                 dict(agg_extra['outras'][0]),
            'outras_formas':          _sorted_formas_list(agg_extra['outras'][1]),
        }

        vendas_reais_by_month  = dict(agg_vendas_reais)
        vendas_por_produto     = agg_vendas_por_produto
        compras_por_produto    = agg_compras_por_produto

        despesas_blocks, grand_despesas_by_month, grand_despesas = (
            _build_despesas_blocks(all_lancamentos, months)
        )

        # ── Taxas de cartão (CARTÕES) — filtradas pelas empresas selecionadas ──
        # Quando o usuário filtra por empresa(s) específica(s), exibe apenas as
        # taxas de cartão cujas vendas/recebimentos pertencem àquelas empresas.
        # Empresas sem maquininha vinculada resultam em _taxas_list vazio e a
        # linha CARTÕES não aparece no DRE.  Quando nenhuma empresa é filtrada
        # (todos), comporta-se como antes (global).
        # 21/11/2026: a MESMA conta da Conferência de Despesas — global (a
        # maquininha é do Posto NH), corrigida pelo arquivo da operadora
        # (SIPAG/X7/Baratão) e pelo Sicredi até jul/2026. Só entra se alguma
        # empresa do filtro é dona das vendas de cartão.
        # 23/11/2026: sem empresa escolhida não há cartão (antes aparecia sozinho
        # com o resto vazio); Fresh/Prest não têm maquininha e não veem; com
        # todas as donas no filtro é a conta da Conf. Despesas, com só uma
        # delas, apenas as vendas dela.
        _taxas_list = []
        if months and empresa_ids:
            _emp_cartao, _ = _empresas_donas(conn, data_inicio, data_fim)
            _sel_cartao = {str(e) for e in empresa_ids
                           if empresa_configs.get(e, {}).get('include_cartoes', True)}
            _donas_sel = _emp_cartao & _sel_cartao
            if _donas_sel:
                _escopo = [] if _emp_cartao <= _sel_cartao else sorted(_donas_sel)
                _taxas_list = _fetch_taxas_cartao(conn, data_inicio, data_fim, _escopo, months)
                if _taxas_list and not _escopo:
                    _taxas_list = _aplicar_taxas_operadora(
                        conn, _taxas_list, data_inicio, data_fim, months)
        cartoes_by_month: dict = {m['key']: 0.0 for m in months}
        for band in _taxas_list:
            for mk, fee in band['fee_by_month'].items():
                if mk in cartoes_by_month:
                    cartoes_by_month[mk] += fee
        grand_cartoes: float = sum(cartoes_by_month.values())
        # Incorpora as taxas no total de despesas para que TOTAL DESPESAS e
        # LUCRO reflitam o custo real das taxas de cartão.
        for mk in cartoes_by_month:
            grand_despesas_by_month[mk] = (
                grand_despesas_by_month.get(mk, 0.0) + cartoes_by_month[mk]
            )
        grand_despesas += grand_cartoes

        # ── Compras por mês (total R$) ────────────────────────────────────
        compras_by_month: dict = {}
        for m in months:
            mk = m['key']
            compras_by_month[mk] = sum(
                v['reais']
                for v in compras_por_produto.get(mk, {}).values()
            )
        grand_compras = sum(compras_by_month.values())

        # ── CMV = Estoque Inicial + Compras − Estoque Final ───────────────
        estoque_ei_by_month: dict = {}
        estoque_ef_by_month: dict = {}
        for m in months:
            mk = m['key']
            estoque_ei_by_month[mk] = sum(
                v['reais'] for v in agg_estoque_ei.get(mk, {}).values())
            estoque_ef_by_month[mk] = sum(
                v['reais'] for v in agg_estoque_ef.get(mk, {}).values())

        cmv_by_month: dict = {}
        for m in months:
            mk = m['key']
            cmv_by_month[mk] = (
                estoque_ei_by_month.get(mk, 0.0)
                + compras_by_month.get(mk, 0.0)
                - estoque_ef_by_month.get(mk, 0.0)
            )
        grand_cmv = sum(cmv_by_month.values())

        grand_estoque_ei = _grand_por_produto(agg_estoque_ei, months)
        grand_estoque_ef = _grand_por_produto(agg_estoque_ef, months)
        grand_estoque_ei_total = sum(v['reais'] for v in grand_estoque_ei.values())
        grand_estoque_ef_total = sum(v['reais'] for v in grand_estoque_ef.values())

        # ── Totais de receita por mês ─────────────────────────────────────
        receitas_by_month: dict = {}
        for m in months:
            mk    = m['key']
            total = 0.0
            total += vendas_reais_by_month.get(mk, 0.0)
            total += agg_arla_mk.get(mk, 0.0)
            total += agg_lubrif_mk.get(mk, 0.0)
            total += recebimentos['aluguel'].get(mk, 0.0)
            total += recebimentos['cliente_a_prazo'].get(mk, 0.0)
            total += recebimentos['financeira'].get(mk, 0.0)
            total += recebimentos['outras'].get(mk, 0.0)
            receitas_by_month[mk] = total

        grand_receitas = sum(receitas_by_month.values())

        # ── Lucro = Receitas − CMV − Despesas ─────────────────────────────
        lucro_by_month: dict = {}
        for m in months:
            mk = m['key']
            lucro_by_month[mk] = (
                receitas_by_month.get(mk, 0.0)
                - cmv_by_month.get(mk, 0.0)
                - grand_despesas_by_month.get(mk, 0.0)
            )
        grand_lucro = grand_receitas - grand_cmv - grand_despesas

        # ── Lucro acumulado (YTD) ─────────────────────────────────────────
        lucro_acumulado_by_month: dict = {}
        _acum = 0.0
        for m in months:
            _acum += lucro_by_month.get(m['key'], 0.0)
            lucro_acumulado_by_month[m['key']] = _acum

        # ── Totais acumulados ─────────────────────────────────────────────
        grand_vendas_reais = sum(
            vendas_reais_by_month.get(m['key'], 0.0) for m in months)
        grand_arla    = sum(agg_arla_mk.get(m['key'], 0.0)   for m in months)
        grand_lubrif  = sum(agg_lubrif_mk.get(m['key'], 0.0) for m in months)
        grand_aluguel      = sum(
            recebimentos['aluguel'].get(m['key'], 0.0) for m in months)
        grand_prazo        = sum(
            recebimentos['cliente_a_prazo'].get(m['key'], 0.0) for m in months)
        grand_financeira   = sum(
            recebimentos['financeira'].get(m['key'], 0.0) for m in months)
        grand_outras       = sum(
            recebimentos['outras'].get(m['key'], 0.0) for m in months)

        grand_vendas_por_produto  = _grand_por_produto(vendas_por_produto,  months)
        grand_compras_por_produto = _grand_por_produto(compras_por_produto, months)

    finally:
        conn.close()

    return render_template(
        'relatorios/dre_postos.html',
        # filtros / estado do formulário
        empresas=empresas,
        titulos=titulos,
        formas=formas,
        data_inicio=data_inicio,
        data_fim=data_fim,
        empresa_ids=empresa_ids,
        empresa_configs_for_js=empresa_configs_for_js,
        empresas_por_id=empresas_por_id,
        per=per if per in _PERIODOS else '',
        filtros_salvos=filtros_salvos,
        caminhoes_sc=caminhoes_sc,
        caminhoes_titulo_id=str(_caminhoes_tit['id']) if _caminhoes_tit else '',
        # flags agregadas para controle de exibição das linhas
        any_include_vendas=any_include_vendas,
        any_include_aluguel=any_include_aluguel,
        any_include_prazo=any_include_prazo,
        any_include_compras=any_include_compras,
        # meses
        months=months,
        # receitas
        vendas_reais_by_month=vendas_reais_by_month,
        vendas_por_produto=vendas_por_produto,
        grand_vendas_por_produto=grand_vendas_por_produto,
        arla_by_month=dict(agg_arla_mk),
        lubrif_by_month=dict(agg_lubrif_mk),
        grand_arla=grand_arla,
        grand_lubrif=grand_lubrif,
        recebimentos=recebimentos,
        receitas_by_month=receitas_by_month,
        grand_vendas_reais=grand_vendas_reais,
        grand_aluguel=grand_aluguel,
        grand_prazo=grand_prazo,
        grand_financeira=grand_financeira,
        grand_outras=grand_outras,
        grand_receitas=grand_receitas,
        # compras (componente do CMV)
        compras_por_produto=compras_por_produto,
        grand_compras_por_produto=grand_compras_por_produto,
        compras_by_month=compras_by_month,
        grand_compras=grand_compras,
        # CMV
        estoque_ei=agg_estoque_ei,
        estoque_ef=agg_estoque_ef,
        estoque_ei_by_month=estoque_ei_by_month,
        estoque_ef_by_month=estoque_ef_by_month,
        grand_estoque_ei=grand_estoque_ei,
        grand_estoque_ef=grand_estoque_ef,
        grand_estoque_ei_total=grand_estoque_ei_total,
        grand_estoque_ef_total=grand_estoque_ef_total,
        cmv_by_month=cmv_by_month,
        grand_cmv=grand_cmv,
        # despesas
        despesas_blocks=despesas_blocks,
        cartoes_by_month=cartoes_by_month,
        grand_cartoes=grand_cartoes,
        cartoes_taxas_list=_taxas_list,
        grand_despesas_by_month=grand_despesas_by_month,
        grand_despesas=grand_despesas,
        # resultado
        lucro_by_month=lucro_by_month,
        lucro_acumulado_by_month=lucro_acumulado_by_month,
        grand_lucro=grand_lucro,
    )
