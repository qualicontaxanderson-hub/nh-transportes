from flask import Blueprint, render_template, current_app, url_for, jsonify, request, redirect
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
def index():
    # coletar métricas simples do banco (fallback para 0 em caso de erro)
    totals = {
        'total_clientes': 0,
        'total_fornecedores': 0,
        'total_motoristas': 0,
        'total_fretes': 0,
        'total_pedidos': 0,
    }

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

    except Exception:
        # se não conseguiu conectar, deixamos os totais em zero
        pass
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

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
        'alterar_senha_url': safe_url('alterar_senha'),
        'logout_url': safe_url('logout'),
        'listar_usuarios_url': safe_url('listar_usuarios'),
        'cadastro_url': safe_url('cadastro'),
        'relatorios_index_url': safe_url('relatorios.index'),
    }

    context = {}
    context.update(totals)
    context.update(links)

    return render_template('dashboard.html', **context)


@bp.route('/nova', methods=['GET', 'POST'])
def nova():
    """
    Rota mínima para criação de Base (endpoint 'bases.nova').
    - GET: renderiza o formulário/templates/bases/nova.html
    - POST: comportamento mínimo: redireciona para a lista (implemente o salvamento se desejar)
    """
    if request.method == 'POST':
        # implementar criação real aqui se desejar; por enquanto redireciona para a index
        return redirect(url_for('bases.index'))
    return render_template('bases/nova.html')


@bp.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')
