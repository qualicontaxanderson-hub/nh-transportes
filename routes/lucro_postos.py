"""
Rotas administrativas para o módulo Lucro Postos (FIFO).
Permissão: somente ADMIN.

Rotas:
  GET  /lucro_postos/                         - Lista unificada de estoque inicial (fifo_abertura + estoque_inicial_global)
  GET  /lucro_postos/abertura/<cliente_id>    - Gerenciar abertura FIFO de uma empresa
  POST /lucro_postos/abertura/<cliente_id>/salvar  - Salvar abertura FIFO
  POST /lucro_postos/fechar                   - Fechar mês (gera snapshot)
  POST /lucro_postos/reabrir                  - Reabrir mês (invalida snapshot)
"""
import calendar
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import db
from models.cliente import Cliente
from models.lucro_postos import (FifoAbertura, FifoCompetencia,
                                  FifoResumoMensal, FifoSnapshotLote)
from models.produto import Produto
from routes.auth import admin_required
from utils.db import get_db_connection

logger = logging.getLogger(__name__)

bp = Blueprint('lucro_postos', __name__, url_prefix='/lucro_postos')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ano_mes_atual():
    hoje = date.today()
    return hoje.strftime('%Y-%m')


def _parse_ano_mes(s):
    """'2026-01' -> (2026, 1) ou None."""
    try:
        ano, mes = s.split('-')
        return int(ano), int(mes)
    except Exception:
        return None, None


def _datas_do_mes(ano, mes):
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, 1), date(ano, mes, ultimo_dia)


def _clientes_posto():
    """Retorna clientes que têm pelo menos um produto vinculado (posto)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT DISTINCT c.id, c.razao_social, c.nome_fantasia
            FROM clientes c
            INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY c.razao_social
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _produtos_do_cliente(cliente_id):
    """Produtos ativos vinculados ao cliente no posto."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT p.id, p.nome
            FROM produto p
            INNER JOIN cliente_produtos cp ON cp.produto_id = p.id
            WHERE cp.cliente_id = %s AND cp.ativo = 1
            ORDER BY p.nome
        """, (cliente_id,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _calcular_fifo(camadas_iniciais, compras, vendas):
    """
    Calcula FIFO para uma lista de camadas, compras e vendas de um produto.

    camadas_iniciais: list of {'qtde': float, 'custo': float}
    compras: list of {'data': date, 'qtde': float, 'custo': float}
    vendas:  list of {'data': date, 'qtde': float, 'valor_total': float}

    Retorna: (resultado_dict, camadas_finais)
    """
    layers = [{'qtde': Decimal(str(c['qtde'])), 'custo': Decimal(str(c['custo']))}
              for c in camadas_iniciais if float(c['qtde']) > 0]

    qtde_entrada = Decimal('0')
    custo_entrada = Decimal('0')
    qtde_saida = Decimal('0')
    receita = Decimal('0')
    cogs = Decimal('0')

    # Agrupar por data
    from collections import defaultdict
    comp_by_date = defaultdict(list)
    for c in sorted(compras, key=lambda x: x['data']):
        comp_by_date[c['data']].append(c)
    vend_by_date = defaultdict(list)
    for v in sorted(vendas, key=lambda x: x['data']):
        vend_by_date[v['data']].append(v)

    all_dates = sorted(set(list(comp_by_date.keys()) + list(vend_by_date.keys())))

    for data in all_dates:
        # Processar compras (adicionar camadas, mais antigas primeiro dentro do dia)
        for comp in comp_by_date.get(data, []):
            qtde = Decimal(str(comp['qtde']))
            custo = Decimal(str(comp['custo']))
            if qtde > 0:
                layers.append({'qtde': qtde, 'custo': custo})
                qtde_entrada += qtde
                custo_entrada += qtde * custo

        # Processar vendas (consumir camadas FIFO)
        for vend in vend_by_date.get(data, []):
            qtde_vender = Decimal(str(vend['qtde']))
            valor = Decimal(str(vend['valor_total']))
            if qtde_vender <= 0:
                continue
            qtde_saida += qtde_vender
            receita += valor

            restante = qtde_vender
            while restante > Decimal('0.001') and layers:
                layer = layers[0]
                if layer['qtde'] <= restante + Decimal('0.001'):
                    cogs += layer['qtde'] * layer['custo']
                    restante -= layer['qtde']
                    layers.pop(0)
                else:
                    cogs += restante * layer['custo']
                    layer['qtde'] -= restante
                    restante = Decimal('0')

    estoque_final_qtde = sum(l['qtde'] for l in layers)
    estoque_final_valor = sum(l['qtde'] * l['custo'] for l in layers)

    resultado = {
        'qtde_entrada': float(qtde_entrada),
        'custo_entrada_total': float(custo_entrada),
        'custo_entrada_unit': float(custo_entrada / qtde_entrada) if qtde_entrada > 0 else 0.0,
        'qtde_saida': float(qtde_saida),
        'receita_saida': float(receita),
        'preco_medio_saida': float(receita / qtde_saida) if qtde_saida > 0 else 0.0,
        'cogs': float(cogs),
        'lucro': float(receita - cogs),
        'estoque_final_qtde': float(estoque_final_qtde),
        'estoque_final_valor': float(estoque_final_valor),
        'estoque_final_custo_unit': float(estoque_final_valor / estoque_final_qtde) if estoque_final_qtde > 0 else 0.0,
    }
    return resultado, layers


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route('/')
@admin_required
def index():
    """Lista os registros de Estoque Inicial combinando fifo_abertura e estoque_inicial_global."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT fa.cliente_id, fa.produto_id,
                   fa.data_abertura AS data_inicio,
                   fa.quantidade AS quantidade_inicial,
                   fa.custo_unitario,
                   fa.criado_em AS created_at,
                   c.razao_social AS cliente_nome, c.nome_fantasia,
                   p.nome AS produto_nome
            FROM fifo_abertura fa
            INNER JOIN clientes c ON c.id = fa.cliente_id
            INNER JOIN produto p ON p.id = fa.produto_id

            UNION ALL

            SELECT eig.cliente_id, eig.produto_id,
                   eig.data_inicio,
                   eig.quantidade_inicial,
                   NULL AS custo_unitario,
                   eig.created_at,
                   c.razao_social AS cliente_nome, c.nome_fantasia,
                   p.nome AS produto_nome
            FROM estoque_inicial_global eig
            INNER JOIN clientes c ON c.id = eig.cliente_id
            INNER JOIN produto p ON p.id = eig.produto_id

            ORDER BY data_inicio DESC, cliente_nome, produto_nome
        """)
        entradas = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return render_template(
        'lucro_postos/index.html',
        entradas=entradas,
    )


# ---------------------------------------------------------------------------
# Abertura FIFO
# ---------------------------------------------------------------------------

@bp.route('/abertura/<int:cliente_id>', methods=['GET'])
@admin_required
def abertura(cliente_id):
    """Exibe abertura FIFO de um cliente."""
    cliente = Cliente.query.get_or_404(cliente_id)
    produtos = _produtos_do_cliente(cliente_id)
    aberturas = {
        a.produto_id: a
        for a in FifoAbertura.query.filter_by(cliente_id=cliente_id).all()
    }
    return render_template(
        'lucro_postos/abertura_form.html',
        cliente=cliente,
        produtos=produtos,
        aberturas=aberturas,
    )


@bp.route('/abertura/<int:cliente_id>/salvar', methods=['POST'])
@admin_required
def abertura_salvar(cliente_id):
    """Salva (INSERT ou UPDATE) abertura FIFO de um cliente."""
    cliente = Cliente.query.get_or_404(cliente_id)
    produtos = _produtos_do_cliente(cliente_id)

    data_abertura_str = request.form.get('data_abertura', '2026-01-01')
    try:
        data_abertura = datetime.strptime(data_abertura_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Data de abertura inválida.', 'danger')
        return redirect(url_for('lucro_postos.abertura', cliente_id=cliente_id))

    erros = []
    for prod in produtos:
        pid = prod['id']
        qtde_str = request.form.get(f'quantidade_{pid}', '0').strip().replace(',', '.')
        custo_str = request.form.get(f'custo_unitario_{pid}', '0').strip().replace(',', '.')
        try:
            qtde = Decimal(qtde_str) if qtde_str else Decimal('0')
            custo = Decimal(custo_str) if custo_str else Decimal('0')
        except InvalidOperation:
            erros.append(f'Valor inválido para produto {prod["nome"]}.')
            continue

        abertura_obj = FifoAbertura.query.filter_by(
            cliente_id=cliente_id, produto_id=pid
        ).first()
        if abertura_obj:
            abertura_obj.quantidade = qtde
            abertura_obj.custo_unitario = custo
            abertura_obj.data_abertura = data_abertura
            abertura_obj.atualizado_em = datetime.utcnow()
            abertura_obj.atualizado_por = current_user.id
        else:
            novo = FifoAbertura(
                cliente_id=cliente_id,
                produto_id=pid,
                data_abertura=data_abertura,
                quantidade=qtde,
                custo_unitario=custo,
                criado_por=current_user.id,
            )
            db.session.add(novo)

    if erros:
        for e in erros:
            flash(e, 'warning')
    else:
        try:
            db.session.commit()
            flash(f'Abertura FIFO de {cliente.razao_social} salva com sucesso.', 'success')
        except Exception as exc:
            db.session.rollback()
            logger.error('Erro ao salvar abertura FIFO: %s', exc)
            flash('Erro ao salvar abertura FIFO.', 'danger')

    return redirect(url_for('lucro_postos.abertura', cliente_id=cliente_id))


# ---------------------------------------------------------------------------
# Fechar mês
# ---------------------------------------------------------------------------

@bp.route('/fechar', methods=['POST'])
@admin_required
def fechar():
    """Fecha o mês para um cliente: gera snapshot FIFO e marca como FECHADO."""
    cliente_id = request.form.get('cliente_id', type=int)
    ano_mes = request.form.get('ano_mes', '').strip()
    if not cliente_id or not ano_mes:
        flash('Parâmetros inválidos.', 'danger')
        return redirect(url_for('lucro_postos.index'))

    ano, mes = _parse_ano_mes(ano_mes)
    if not ano:
        flash('Mês/ano inválido.', 'danger')
        return redirect(url_for('lucro_postos.index'))

    data_inicio, data_fim = _datas_do_mes(ano, mes)

    # Verificar se já existe e está ABERTO
    comp = FifoCompetencia.query.filter_by(
        cliente_id=cliente_id, ano_mes=ano_mes
    ).first()
    if comp and comp.status == 'FECHADO':
        flash('Mês já está fechado. Reabra antes de fechar novamente.', 'warning')
        return redirect(url_for('lucro_postos.index', ano_mes=ano_mes))

    # Calcular FIFO para todos os produtos do cliente no período
    produtos = _produtos_do_cliente(cliente_id)
    if not produtos:
        flash('Nenhum produto vinculado a este cliente.', 'warning')
        return redirect(url_for('lucro_postos.index', ano_mes=ano_mes))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        resultado_por_produto = {}
        camadas_finais_por_produto = {}

        for prod in produtos:
            pid = prod['id']

            # Obter camadas base (snapshot anterior ou abertura)
            camadas_base = _obter_camadas_base(cur, cliente_id, pid, ano, mes)

            # Obter compras do período
            cur.execute("""
                SELECT f.data_frete AS data,
                       COALESCE(f.quantidade_manual, q.valor, 0) AS qtde,
                       COALESCE(f.preco_produto_unitario, 0) AS custo
                FROM fretes f
                LEFT JOIN quantidades q ON f.quantidade_id = q.id
                WHERE f.clientes_id = %s
                  AND f.produto_id = %s
                  AND f.data_frete BETWEEN %s AND %s
                  AND COALESCE(f.quantidade_manual, q.valor, 0) > 0
                ORDER BY f.data_frete
            """, (cliente_id, pid, data_inicio, data_fim))
            compras = cur.fetchall()

            # Obter vendas do período
            cur.execute("""
                SELECT data_movimento AS data,
                       SUM(COALESCE(quantidade_litros, 0)) AS qtde,
                       SUM(COALESCE(valor_total, 0)) AS valor_total
                FROM vendas_posto
                WHERE cliente_id = %s
                  AND produto_id = %s
                  AND data_movimento BETWEEN %s AND %s
                GROUP BY data_movimento
                ORDER BY data_movimento
            """, (cliente_id, pid, data_inicio, data_fim))
            vendas = cur.fetchall()

            resultado, camadas = _calcular_fifo(camadas_base, compras, vendas)
            resultado_por_produto[pid] = resultado
            camadas_finais_por_produto[pid] = camadas
    finally:
        cur.close()
        conn.close()

    # Gravar no banco (transação SQLAlchemy)
    try:
        versao = 1
        if comp:
            # Invalidar snapshot anterior
            versao = comp.versao_atual + 1
            FifoSnapshotLote.query.filter_by(
                competencia_id=comp.id,
                substituido=False
            ).update({'substituido': True})
            FifoResumoMensal.query.filter_by(
                competencia_id=comp.id,
                substituido=False
            ).update({'substituido': True})
            comp.status = 'FECHADO'
            comp.versao_atual = versao
            comp.fechado_em = datetime.utcnow()
            comp.fechado_por = current_user.id
        else:
            comp = FifoCompetencia(
                cliente_id=cliente_id,
                ano_mes=ano_mes,
                data_inicio=data_inicio,
                data_fim=data_fim,
                status='FECHADO',
                versao_atual=versao,
                fechado_em=datetime.utcnow(),
                fechado_por=current_user.id,
            )
            db.session.add(comp)
            db.session.flush()  # garante comp.id

        # Inserir novos snapshot_lotes e resumos
        for prod in produtos:
            pid = prod['id']
            for ordem, lote in enumerate(camadas_finais_por_produto.get(pid, []), start=1):
                sl = FifoSnapshotLote(
                    competencia_id=comp.id,
                    produto_id=pid,
                    versao=versao,
                    lote_ordem=ordem,
                    quantidade_restante=Decimal(str(lote['qtde'])),
                    custo_unitario=Decimal(str(lote['custo'])),
                )
                db.session.add(sl)

            res = resultado_por_produto.get(pid, {})
            rm = FifoResumoMensal(
                competencia_id=comp.id,
                produto_id=pid,
                versao=versao,
                qtde_entrada=res.get('qtde_entrada', 0),
                custo_entrada_total=res.get('custo_entrada_total', 0),
                qtde_saida=res.get('qtde_saida', 0),
                receita_saida_total=res.get('receita_saida', 0),
                cogs_fifo=res.get('cogs', 0),
                lucro_bruto=res.get('lucro', 0),
                estoque_final_qtde=res.get('estoque_final_qtde', 0),
                estoque_final_valor=res.get('estoque_final_valor', 0),
            )
            db.session.add(rm)

        db.session.commit()
        flash(f'Mês {ano_mes} fechado com sucesso.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Erro ao fechar mês %s para cliente %s: %s', ano_mes, cliente_id, exc)
        flash('Erro ao fechar mês. Tente novamente.', 'danger')

    return redirect(url_for('lucro_postos.index', ano_mes=ano_mes))


# ---------------------------------------------------------------------------
# Reabrir mês
# ---------------------------------------------------------------------------

@bp.route('/reabrir', methods=['POST'])
@admin_required
def reabrir():
    """Reabre o mês para um cliente: mantém histórico e retorna a ABERTO."""
    cliente_id = request.form.get('cliente_id', type=int)
    ano_mes = request.form.get('ano_mes', '').strip()
    if not cliente_id or not ano_mes:
        flash('Parâmetros inválidos.', 'danger')
        return redirect(url_for('lucro_postos.index'))

    comp = FifoCompetencia.query.filter_by(
        cliente_id=cliente_id, ano_mes=ano_mes
    ).first()
    if not comp or comp.status != 'FECHADO':
        flash('Competência não encontrada ou já está aberta.', 'warning')
        return redirect(url_for('lucro_postos.index', ano_mes=ano_mes))

    try:
        comp.status = 'ABERTO'
        comp.reaberto_em = datetime.utcnow()
        comp.reaberto_por = current_user.id
        db.session.commit()
        flash(f'Mês {ano_mes} reaberto. Faça as correções e feche novamente.', 'success')
    except Exception as exc:
        db.session.rollback()
        logger.error('Erro ao reabrir mês %s para cliente %s: %s', ano_mes, cliente_id, exc)
        flash('Erro ao reabrir mês.', 'danger')

    return redirect(url_for('lucro_postos.index', ano_mes=ano_mes))


# ---------------------------------------------------------------------------
# Helper interno: camadas base para FIFO
# ---------------------------------------------------------------------------

def _obter_camadas_base(cur, cliente_id, produto_id, ano, mes):
    """
    Obtém as camadas FIFO de base para o mês (ano, mes):
    1. Tenta buscar snapshot do último mês FECHADO anterior.
    2. Se não encontrar, usa a abertura FIFO.
    3. Se nenhuma, retorna lista vazia.
    """
    # Mês anterior
    if mes == 1:
        ano_ant, mes_ant = ano - 1, 12
    else:
        ano_ant, mes_ant = ano, mes - 1
    ano_mes_ant = f'{ano_ant:04d}-{mes_ant:02d}'

    cur.execute("""
        SELECT fc.id, fc.versao_atual
        FROM fifo_competencia fc
        WHERE fc.cliente_id = %s AND fc.ano_mes = %s AND fc.status = 'FECHADO'
        LIMIT 1
    """, (cliente_id, ano_mes_ant))
    comp_ant = cur.fetchone()

    if comp_ant:
        cur.execute("""
            SELECT quantidade_restante AS qtde, custo_unitario AS custo
            FROM fifo_snapshot_lotes
            WHERE competencia_id = %s
              AND produto_id = %s
              AND versao = %s
              AND substituido = 0
              AND quantidade_restante > 0
            ORDER BY lote_ordem
        """, (comp_ant['id'], produto_id, comp_ant['versao_atual']))
        lotes = cur.fetchall()
        if lotes:
            return [{'qtde': float(l['qtde']), 'custo': float(l['custo'])} for l in lotes]

    # Fallback: abertura FIFO
    cur.execute("""
        SELECT quantidade AS qtde, custo_unitario AS custo
        FROM fifo_abertura
        WHERE cliente_id = %s AND produto_id = %s
    """, (cliente_id, produto_id))
    ab = cur.fetchone()
    if ab and float(ab['qtde']) > 0:
        return [{'qtde': float(ab['qtde']), 'custo': float(ab['custo'])}]

    return []
