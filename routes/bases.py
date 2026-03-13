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
        'alterar_senha_url': safe_url('auth.alterar_senha'),
        'logout_url': safe_url('auth.logout'),
        'listar_usuarios_url': safe_url('auth.listar_usuarios'),
        'cadastro_url': safe_url('auth.criar_usuario'),
        'relatorios_index_url': safe_url('relatorios.index'),
        'perfil_url': safe_url('auth.perfil'),
    }

    context = {}
    context.update(totals)
    context.update(links)

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
