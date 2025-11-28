from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
import mysql.connector

bp = Blueprint('bases', __name__, url_prefix='/bases')

def get_db():
    return mysql.connector.connect(
        host='centerbeam.proxy.rlwy.net',
        port=56026,
        user='root',
        password='CYTzzRYLVmEJGDexxXpgepWgpvebdSrV',
        database='railway'
    )

# =============================================
# LISTAR BASES
# =============================================
@bp.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nome, cidade, observacao, ativo, criado_em
        FROM bases
        ORDER BY nome
    """)
    bases = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('bases/index.html', bases=bases)

# =============================================
# NOVA BASE
# =============================================
@bp.route('/nova', methods=['GET', 'POST'])
@login_required
def nova():
    if request.method == 'POST':
        nome = request.form.get('nome')
        cidade = request.form.get('cidade') or None
        observacao = request.form.get('observacao') or None
        ativo = 1 if request.form.get('ativo') == 'on' else 1  # padrão ativa

        if not nome:
            flash('Informe o nome da base.', 'danger')
            return redirect(url_for('bases.nova'))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bases (nome, cidade, observacao, ativo)
            VALUES (%s, %s, %s, %s)
        """, (nome, cidade, observacao, ativo))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Base cadastrada com sucesso!', 'success')
        return redirect(url_for('bases.index'))

    return render_template('bases/nova.html')

# =============================================
# EDITAR BASE
# =============================================
@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nome = request.form.get('nome')
        cidade = request.form.get('cidade') or None
        observacao = request.form.get('observacao') or None
        ativo = 1 if request.form.get('ativo') == 'on' else 0

        if not nome:
            flash('Informe o nome da base.', 'danger')
            return redirect(url_for('bases.editar', id=id))

        cursor.execute("""
            UPDATE bases
               SET nome = %s,
                   cidade = %s,
                   observacao = %s,
                   ativo = %s
             WHERE id = %s
        """, (nome, cidade, observacao, ativo, id))
        conn.commit()

        cursor.close()
        conn.close()

        flash('Base atualizada com sucesso!', 'success')
        return redirect(url_for('bases.index'))

    # GET: busca dados da base
    cursor.execute("""
        SELECT id, nome, cidade, observacao, ativo
        FROM bases
        WHERE id = %s
    """, (id,))
    base = cursor.fetchone()

    cursor.close()
    conn.close()

    if not base:
        flash('Base não encontrada.', 'danger')
        return redirect(url_for('bases.index'))

    return render_template('bases/editar.html', base=base)

# =============================================
# EXCLUIR BASE
# =============================================
@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM bases WHERE id = %s", (id,))
    conn.commit()

    cursor.close()
    conn.close()

    flash('Base excluída com sucesso!', 'success')
    return redirect(url_for('bases.index'))
