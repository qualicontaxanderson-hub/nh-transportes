from flask import Blueprint, render_template, current_app, url_for, jsonify, request, redirect, flash
from flask_login import login_required, current_user
from utils.db import get_db_connection

bp = Blueprint('bases', __name__)


def safe_url(endpoint, **values):
    """
    Retorna url_for(endpoint, **values) se o endpoint existir no app,
    caso contrário retorna '#'. Evita BuildError no template.
    """
    try:
        if endpoint in current_app.view_functions:
            return url_for(endpoint, **values)
    except Exception:
        pass
    return '#'


@bp.route('/', methods=['GET'])
@login_required
def index():
    # Redirecionar usuários PISTA e SUPERVISOR para suas páginas específicas
    # SUPERVISOR não deve acessar a página inicial, vai direto para lançamentos_caixa
    if current_user.is_authenticated:
        nivel = getattr(current_user, 'nivel', '').strip().upper()
        if nivel == 'PISTA':
            return redirect(url_for('troco_pix.pista'))
        if nivel == 'SUPERVISOR':
            return redirect(url_for('lancamentos_caixa.lista'))
    
    import calendar
    from datetime import datetime, date

    # coletar métricas simples do banco (fallback para 0 em caso de erro)
    totals = {
        'total_clientes': 0,
        'total_fornecedores': 0,
        'total_motoristas': 0,
        'total_fretes': 0,
        'total_pedidos': 0,
        'fretes_mes': 0,
        'pedidos_mes': 0,
        'volume_transportado_mes': 0.0,
        'volume_vendido_mes': 0.0,
        'receita_mes': 0.0,
        'lucro_fretes_mes': 0.0,
    }

    # Dados para gráficos (últimos 6 meses)
    hoje = date.today()
    meses_labels = []
    fretes_por_mes = []
    pedidos_por_mes = []
    volume_por_mes = []
    for i in range(5, -1, -1):
        # calcular mês/ano
        mes_offset = hoje.month - i
        ano_offset = hoje.year
        while mes_offset <= 0:
            mes_offset += 12
            ano_offset -= 1
        meses_labels.append(f"{mes_offset:02d}/{ano_offset}")
        fretes_por_mes.append(0)
        pedidos_por_mes.append(0)
        volume_por_mes.append(0)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(1) FROM clientes")
            totals['total_clientes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_clientes'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM fornecedores")
            totals['total_fornecedores'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_fornecedores'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM motoristas")
            totals['total_motoristas'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_motoristas'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM fretes")
            totals['total_fretes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_fretes'] = 0

        try:
            cursor.execute("SELECT COUNT(1) FROM pedidos")
            totals['total_pedidos'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['total_pedidos'] = 0

        # Fretes do mês atual
        try:
            cursor.execute(
                "SELECT COUNT(1) FROM fretes WHERE YEAR(data_frete)=%s AND MONTH(data_frete)=%s",
                (hoje.year, hoje.month)
            )
            totals['fretes_mes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['fretes_mes'] = 0

        # Pedidos do mês atual
        try:
            cursor.execute(
                "SELECT COUNT(1) FROM pedidos WHERE YEAR(data_pedido)=%s AND MONTH(data_pedido)=%s",
                (hoje.year, hoje.month)
            )
            totals['pedidos_mes'] = int(cursor.fetchone()[0] or 0)
        except Exception:
            totals['pedidos_mes'] = 0

        # Fretes por mês (últimos 6 meses)
        try:
            cursor.execute(
                """SELECT MONTH(data_frete) AS mes, YEAR(data_frete) AS ano, COUNT(1) AS total
                   FROM fretes
                   WHERE data_frete >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
                   GROUP BY ano, mes
                   ORDER BY ano, mes"""
            )
            rows = cursor.fetchall()
            for row in rows:
                mes_ano = f"{int(row[0]):02d}/{int(row[1])}"
                if mes_ano in meses_labels:
                    idx = meses_labels.index(mes_ano)
                    fretes_por_mes[idx] = int(row[2])
        except Exception:
            pass

        # Pedidos por mês (últimos 6 meses)
        try:
            cursor.execute(
                """SELECT MONTH(data_pedido) AS mes, YEAR(data_pedido) AS ano, COUNT(1) AS total
                   FROM pedidos
                   WHERE data_pedido >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
                   GROUP BY ano, mes
                   ORDER BY ano, mes"""
            )
            rows = cursor.fetchall()
            for row in rows:
                mes_ano = f"{int(row[0]):02d}/{int(row[1])}"
                if mes_ano in meses_labels:
                    idx = meses_labels.index(mes_ano)
                    pedidos_por_mes[idx] = int(row[2])
        except Exception:
            pass

        # Volume transportado do mês atual (soma quantidade fretes)
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor)), 0)
                   FROM fretes f
                   LEFT JOIN quantidades q ON f.quantidade_id = q.id
                   WHERE YEAR(f.data_frete)=%s AND MONTH(f.data_frete)=%s""",
                (hoje.year, hoje.month)
            )
            totals['volume_transportado_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['volume_transportado_mes'] = 0.0

        # Volume vendido do mês atual (soma quantidade pedidos_itens)
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(pi.quantidade), 0)
                   FROM pedidos_itens pi
                   JOIN pedidos p ON pi.pedido_id = p.id
                   WHERE YEAR(p.data_pedido)=%s AND MONTH(p.data_pedido)=%s""",
                (hoje.year, hoje.month)
            )
            totals['volume_vendido_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['volume_vendido_mes'] = 0.0

        # Receita do mês atual (valor_total_frete)
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(valor_total_frete), 0) FROM fretes
                   WHERE YEAR(data_frete)=%s AND MONTH(data_frete)=%s""",
                (hoje.year, hoje.month)
            )
            totals['receita_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['receita_mes'] = 0.0

        # Lucro fretes do mês atual
        try:
            cursor.execute(
                """SELECT COALESCE(SUM(lucro), 0) FROM fretes
                   WHERE YEAR(data_frete)=%s AND MONTH(data_frete)=%s""",
                (hoje.year, hoje.month)
            )
            totals['lucro_fretes_mes'] = float(cursor.fetchone()[0] or 0)
        except Exception:
            totals['lucro_fretes_mes'] = 0.0

        # Volume transportado por mês (últimos 6 meses)
        try:
            cursor.execute(
                """SELECT MONTH(f.data_frete) AS mes, YEAR(f.data_frete) AS ano,
                          COALESCE(SUM(COALESCE(f.quantidade_manual, q.valor)), 0) AS total
                   FROM fretes f
                   LEFT JOIN quantidades q ON f.quantidade_id = q.id
                   WHERE f.data_frete >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
                   GROUP BY ano, mes
                   ORDER BY ano, mes"""
            )
            rows = cursor.fetchall()
            for row in rows:
                mes_ano = f"{int(row[0]):02d}/{int(row[1])}"
                if mes_ano in meses_labels:
                    idx = meses_labels.index(mes_ano)
                    volume_por_mes[idx] = float(row[2])
        except Exception:
            pass

    except Exception:
        # se não conseguiu conectar, deixamos os totais em zero
        pass
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    # Construir URLs do relatório de lucro para o mês atual
    primeiro_dia = date(hoje.year, hoje.month, 1)
    ultimo_dia = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
    lucro_mes_url = (
        f"https://app.postonovohorizonte.com.br/relatorios/lucro_postos"
        f"?data_inicio={primeiro_dia.strftime('%Y-%m-%d')}"
        f"&data_fim={ultimo_dia.strftime('%Y-%m-%d')}"
        f"&cliente_ids[]=1&produto_ids[]=1&produto_ids[]=2"
        f"&produto_ids[]=3&produto_ids[]=5&produto_ids[]=4"
    )
    importar_pedido_url = "https://app.postonovohorizonte.com.br/pedidos/importar"

    grafico = {
        'labels': meses_labels,
        'fretes': fretes_por_mes,
        'pedidos': pedidos_por_mes,
        'volume': volume_por_mes,
    }

    # URLs seguras para o template (se endpoint inexistente, retorna '#')
    links = {
        'fretes_novo_url': safe_url('fretes.novo'),
        'pedidos_novo_url': safe_url('pedidos.novo'),
        'clientes_novo_url': safe_url('clientes.novo'),
        'fornecedores_novo_url': safe_url('fornecedores.novo'),
        'clientes_lista_url': safe_url('clientes.lista'),
        'fornecedores_lista_url': safe_url('fornecedores.lista'),
        'motoristas_lista_url': safe_url('motoristas.lista'),
        'fretes_lista_url': safe_url('fretes.lista'),
        'pedidos_index_url': safe_url('pedidos.index') or safe_url('pedidos.lista') or '#',
        'alterar_senha_url': safe_url('auth.alterar_senha'),
        'logout_url': safe_url('auth.logout'),
        'listar_usuarios_url': safe_url('auth.listar_usuarios'),
        'cadastro_url': safe_url('auth.criar_usuario'),
        'relatorios_index_url': safe_url('relatorios.index'),
        'perfil_url': safe_url('auth.perfil'),
        'importar_pedido_url': importar_pedido_url,
        'lucro_mes_url': lucro_mes_url,
    }

    context = {}
    context.update(totals)
    context.update(links)
    context['grafico'] = grafico
    _meses_pt = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                 'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    context['mes_atual'] = f"{_meses_pt[hoje.month - 1]}/{hoje.year}"

    return render_template('dashboard.html', **context)


@bp.route('/bases/', methods=['GET'])
@login_required
def lista():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nome, cidade, observacao, ativo FROM bases ORDER BY nome")
        bases = cursor.fetchall()
    except Exception:
        bases = []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return render_template('bases/index.html', bases=bases)


@bp.route('/bases/nova', methods=['GET', 'POST'])
@login_required
def nova():
    """
    Rota mínima para criação de Base (endpoint 'bases.nova').
    - GET: renderiza o formulário/templates/bases/nova.html
    - POST: comportamento mínimo: redireciona para a lista (implemente o salvamento se desejar)
    """
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        cidade = request.form.get('cidade', '').strip() or None
        observacao = request.form.get('observacao', '').strip() or None
        ativo = 1 if request.form.get('ativo') else 0
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO bases (nome, cidade, observacao, ativo) VALUES (%s, %s, %s, %s)",
                (nome, cidade, observacao, ativo)
            )
            conn.commit()
            flash('Base cadastrada com sucesso!', 'success')
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            flash(f'Erro ao cadastrar base: {str(e)}', 'danger')
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        return redirect(url_for('bases.lista'))
    return render_template('bases/nova.html')


@bp.route('/bases/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            nome = request.form.get('nome', '').strip()
            cidade = request.form.get('cidade', '').strip() or None
            observacao = request.form.get('observacao', '').strip() or None
            ativo = 1 if request.form.get('ativo') else 0
            cursor.execute(
                "UPDATE bases SET nome=%s, cidade=%s, observacao=%s, ativo=%s WHERE id=%s",
                (nome, cidade, observacao, ativo, id)
            )
            conn.commit()
            flash('Base atualizada com sucesso!', 'success')
            return redirect(url_for('bases.lista'))
        cursor.execute("SELECT id, nome, cidade, observacao, ativo FROM bases WHERE id=%s", (id,))
        base = cursor.fetchone()
        if not base:
            flash('Base não encontrada.', 'danger')
            return redirect(url_for('bases.lista'))
        return render_template('bases/editar.html', base=base)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        flash(f'Erro ao editar base: {str(e)}', 'danger')
        return redirect(url_for('bases.lista'))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@bp.route('/bases/excluir/<int:id>', methods=['GET', 'POST'])
@login_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bases WHERE id=%s", (id,))
        conn.commit()
        flash('Base excluída com sucesso!', 'success')
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        flash(f'Erro ao excluir base: {str(e)}', 'danger')
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return redirect(url_for('bases.lista'))


@bp.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')
