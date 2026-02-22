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
        "SELECT id, nome, descricao, ativo, criado_em FROM formas_recebimento ORDER BY nome"
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
        descricao = request.form.get('descricao', '').strip() or None
        if not nome:
            flash('Nome é obrigatório.', 'danger')
            return redirect(url_for('formas_recebimento.novo'))
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO formas_recebimento (nome, descricao) VALUES (%s, %s)",
                (nome, descricao),
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
        descricao = request.form.get('descricao', '').strip() or None
        ativo = 1 if request.form.get('ativo') == '1' else 0
        if not nome:
            flash('Nome é obrigatório.', 'danger')
        else:
            cursor.execute(
                "UPDATE formas_recebimento SET nome=%s, descricao=%s, ativo=%s WHERE id=%s",
                (nome, descricao, ativo, id),
            )
            conn.commit()
            flash('Atualizado com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('formas_recebimento.lista'))

    cursor.close()
    conn.close()
    return render_template('formas_recebimento/editar.html', forma=forma)


@bp.route('/toggle/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle(id):
    """Ativa ou desativa forma de recebimento."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT ativo FROM formas_recebimento WHERE id=%s", (id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não encontrado'})
    novo_status = 0 if row['ativo'] else 1
    cursor.execute("UPDATE formas_recebimento SET ativo=%s WHERE id=%s", (novo_status, id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True, 'ativo': novo_status})


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
