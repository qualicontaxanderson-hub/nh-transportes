from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('formas_recebimento', __name__, url_prefix='/formas_recebimento')

_tables_ready = False


def _ensure_tables():
    """Garante que as colunas/tabelas extras de formas_recebimento existem. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Coluna conta_contabil_id em formas_recebimento
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'formas_recebimento'"
            " AND COLUMN_NAME = 'conta_contabil_id'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE formas_recebimento"
                " ADD COLUMN conta_contabil_id INT NULL"
            )
            conn.commit()
        # Tabela junction formas_recebimento_empresas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS formas_recebimento_empresas (
                forma_recebimento_id INT NOT NULL,
                cliente_id           INT NOT NULL,
                PRIMARY KEY (forma_recebimento_id, cliente_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cursor.close()
        _tables_ready = True
    finally:
        conn.close()


@bp.route('/')
@login_required
def lista():
    """Lista todas as formas de recebimento."""
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome, eh_cartao, tipo_cartao, ativo FROM formas_recebimento ORDER BY nome"
    )
    formas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('formas_recebimento/lista.html', formas=formas)


def _load_form_data(conn):
    """Carrega listas de empresas e contas contábeis para os formulários."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, COALESCE(nome_fantasia, razao_social) AS nome FROM clientes ORDER BY nome")
    empresas = cursor.fetchall()
    cursor.execute(
        """SELECT c.id,
                  CONCAT(g.codigo, ' ', g.nome, ' › ', c.codigo, ' ', c.nome) AS label
             FROM plano_contas_contas c
             JOIN plano_contas_grupos g ON g.id = c.grupo_id
            WHERE c.ativo = 1
            ORDER BY g.codigo, c.codigo"""
    )
    contas = cursor.fetchall()
    cursor.close()
    return empresas, contas


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Cria nova forma de recebimento."""
    _ensure_tables()
    conn = get_db_connection()
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        eh_cartao = 1 if request.form.get('eh_cartao') == '1' else 0
        tipo_cartao = request.form.get('tipo_cartao') or None
        if not eh_cartao:
            tipo_cartao = None
        conta_contabil_id = request.form.get('conta_contabil_id') or None
        empresa_ids = request.form.getlist('empresa_ids')
        if not nome:
            flash('Nome é obrigatório.', 'danger')
            empresas, contas = _load_form_data(conn)
            conn.close()
            return render_template('formas_recebimento/novo.html',
                                   empresas=empresas, contas=contas)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO formas_recebimento (nome, eh_cartao, tipo_cartao, ativo, conta_contabil_id)"
                " VALUES (%s, %s, %s, 1, %s)",
                (nome, eh_cartao, tipo_cartao, conta_contabil_id),
            )
            forma_id = cursor.lastrowid
            if empresa_ids:
                cursor.executemany(
                    "INSERT IGNORE INTO formas_recebimento_empresas (forma_recebimento_id, cliente_id) VALUES (%s, %s)",
                    [(forma_id, eid) for eid in empresa_ids],
                )
            conn.commit()
            flash(f'Forma de recebimento "{nome}" criada com sucesso!', 'success')
            return redirect(url_for('formas_recebimento.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar: {e}', 'danger')
        finally:
            cursor.close()
    empresas, contas = _load_form_data(conn)
    conn.close()
    return render_template('formas_recebimento/novo.html', empresas=empresas, contas=contas)


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edita forma de recebimento existente."""
    _ensure_tables()
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
        conta_contabil_id = request.form.get('conta_contabil_id') or None
        empresa_ids = request.form.getlist('empresa_ids')
        if not nome:
            flash('Nome é obrigatório.', 'danger')
        else:
            cursor.execute(
                "UPDATE formas_recebimento SET nome=%s, eh_cartao=%s, tipo_cartao=%s,"
                " ativo=%s, conta_contabil_id=%s WHERE id=%s",
                (nome, eh_cartao, tipo_cartao, ativo, conta_contabil_id, id),
            )
            # Atualiza vínculos com empresas
            cursor.execute(
                "DELETE FROM formas_recebimento_empresas WHERE forma_recebimento_id = %s", (id,)
            )
            if empresa_ids:
                cursor.executemany(
                    "INSERT IGNORE INTO formas_recebimento_empresas (forma_recebimento_id, cliente_id) VALUES (%s, %s)",
                    [(id, eid) for eid in empresa_ids],
                )
            conn.commit()
            flash('Atualizado com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('formas_recebimento.lista'))

    # Empresas já vinculadas
    cursor.execute(
        "SELECT cliente_id FROM formas_recebimento_empresas WHERE forma_recebimento_id = %s", (id,)
    )
    empresas_vinculadas = {row['cliente_id'] for row in cursor.fetchall()}
    cursor.close()
    empresas, contas = _load_form_data(conn)
    conn.close()
    return render_template('formas_recebimento/editar.html',
                           forma=forma,
                           empresas=empresas,
                           contas=contas,
                           empresas_vinculadas=empresas_vinculadas)


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
