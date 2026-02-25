from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('formas_recebimento', __name__, url_prefix='/formas_recebimento')


@bp.route('/')
@login_required
def lista():
    """Lista todas as formas de recebimento."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome, eh_cartao, tipo_cartao, ativo FROM formas_recebimento ORDER BY nome"
    )
    formas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('formas_recebimento/lista.html', formas=formas)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Cria nova forma de recebimento."""
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        eh_cartao = 1 if request.form.get('eh_cartao') == '1' else 0
        tipo_cartao = request.form.get('tipo_cartao') or None
        if not eh_cartao:
            tipo_cartao = None
        if not nome:
            flash('Nome é obrigatório.', 'danger')
            return redirect(url_for('formas_recebimento.novo'))
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO formas_recebimento (nome, eh_cartao, tipo_cartao) VALUES (%s, %s, %s)",
                (nome, eh_cartao, tipo_cartao),
            )
            conn.commit()
            flash(f'Forma de recebimento "{nome}" criada com sucesso!', 'success')
            return redirect(url_for('formas_recebimento.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
    return render_template('formas_recebimento/novo.html')


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edita forma de recebimento existente."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM formas_recebimento WHERE id = %s", (id,))
    forma = cursor.fetchone()
    if not forma:
        cursor.close()
        conn.close()
        flash('Forma de recebimento não encontrada.', 'danger')
        return redirect(url_for('formas_recebimento.lista'))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        eh_cartao = 1 if request.form.get('eh_cartao') == '1' else 0
        tipo_cartao = request.form.get('tipo_cartao') or None
        if not eh_cartao:
            tipo_cartao = None
        ativo = 1 if request.form.get('ativo') == '1' else 0
        if not nome:
            flash('Nome é obrigatório.', 'danger')
        else:
            cursor.execute(
                "UPDATE formas_recebimento SET nome=%s, eh_cartao=%s, tipo_cartao=%s, ativo=%s WHERE id=%s",
                (nome, eh_cartao, tipo_cartao, ativo, id),
            )
            conn.commit()
            flash('Atualizado com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('formas_recebimento.lista'))

    cursor.close()
    conn.close()
    return render_template('formas_recebimento/editar.html', forma=forma)


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    """Exclui forma de recebimento se não houver vínculos."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Verificar se há transações bancárias vinculadas
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_transactions WHERE forma_recebimento_id = %s",
        (id,)
    )
    if cursor.fetchone()['total'] > 0:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível excluir: há transações bancárias vinculadas a esta forma de recebimento.'})
    # Verificar se há mapeamentos CNPJ vinculados
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_supplier_mapping WHERE forma_recebimento_id = %s",
        (id,)
    )
    if cursor.fetchone()['total'] > 0:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível excluir: há mapeamentos automáticos vinculados. Edite ou remova-os primeiro.'})
    # Verificar se há regras de conciliação vinculadas
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_conciliacao_regras WHERE forma_recebimento_id = %s",
        (id,)
    )
    if cursor.fetchone()['total'] > 0:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível excluir: há regras de conciliação vinculadas. Edite ou remova-as primeiro.'})
    # Sem vínculos — pode excluir
    cursor.execute("DELETE FROM formas_recebimento WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})


@bp.route('/api/listar')
@login_required
def api_listar():
    """API JSON — formas ativas para uso em modais."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome FROM formas_recebimento WHERE ativo=1 ORDER BY nome"
    )
    formas = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(formas)
