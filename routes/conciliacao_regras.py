"""CRUD de regras de conciliação automática (bank_conciliacao_regras)."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection

bp = Blueprint('conciliacao_regras', __name__, url_prefix='/banco/regras')


def _get_formas(cursor):
    cursor.execute("SELECT id, nome FROM formas_recebimento WHERE ativo=1 ORDER BY nome")
    return cursor.fetchall()


def _get_fornecedores(cursor):
    cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    return cursor.fetchall()


def _get_clientes(cursor):
    cursor.execute(
        """SELECT DISTINCT c.id, c.razao_social
           FROM clientes c
           INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
           WHERE cp.ativo = 1
           ORDER BY c.razao_social"""
    )
    return cursor.fetchall()


def _get_titulos(cursor):
    cursor.execute(
        """SELECT t.id AS titulo_id, t.nome AS titulo_nome,
                  c.id AS categoria_id, c.nome AS categoria_nome
           FROM titulos_despesas t
           INNER JOIN categorias_despesas c ON c.titulo_id = t.id AND c.ativo = 1
           WHERE t.ativo = 1
           ORDER BY t.ordem, t.nome, c.ordem, c.nome"""
    )
    rows = cursor.fetchall()
    titulos = {}
    for r in rows:
        tid = r['titulo_id']
        if tid not in titulos:
            titulos[tid] = {'id': tid, 'nome': r['titulo_nome'], 'categorias': []}
        titulos[tid]['categorias'].append({'id': r['categoria_id'], 'nome': r['categoria_nome']})
    return list(titulos.values())


@bp.route('/')
@login_required
def lista():
    """Lista todas as regras de conciliação."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT r.*,
                  fr.nome AS forma_nome,
                  f.razao_social AS fornecedor_nome,
                  c.razao_social AS cliente_nome,
                  td.nome AS titulo_nome,
                  cd.nome AS categoria_nome
           FROM bank_conciliacao_regras r
           LEFT JOIN formas_recebimento fr ON fr.id = r.forma_recebimento_id
           LEFT JOIN fornecedores f ON f.id = r.fornecedor_id
           LEFT JOIN clientes c ON c.id = r.cliente_id
           LEFT JOIN titulos_despesas td ON td.id = r.titulo_id
           LEFT JOIN categorias_despesas cd ON cd.id = r.categoria_id
           ORDER BY r.ativo DESC, r.total_aplicacoes DESC, r.id"""
    )
    regras = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/lista.html', regras=regras)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    """Cria nova regra de conciliação."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        padrao           = request.form.get('padrao_descricao', '').strip()
        padrao2          = request.form.get('padrao_secundario', '').strip() or None
        tipo_match       = request.form.get('tipo_match', 'contem')
        tipo_transacao   = request.form.get('tipo_transacao', 'AMBOS')
        forma_id         = request.form.get('forma_recebimento_id') or None
        fornecedor_id    = request.form.get('fornecedor_id') or None
        cliente_id       = request.form.get('cliente_id') or None
        titulo_id        = request.form.get('titulo_id') or None
        categoria_id     = request.form.get('categoria_id') or None

        if not padrao:
            flash('Padrão de descrição é obrigatório.', 'warning')
        else:
            # Verifica se a tabela já possui a coluna padrao_secundario
            try:
                cursor.execute(
                    """INSERT INTO bank_conciliacao_regras
                       (padrao_descricao, padrao_secundario, tipo_match, tipo_transacao,
                        forma_recebimento_id, fornecedor_id, cliente_id, titulo_id, categoria_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (padrao, padrao2, tipo_match, tipo_transacao,
                     forma_id, fornecedor_id, cliente_id, titulo_id, categoria_id),
                )
            except Exception:
                # Fallback para tabela sem novas colunas (antes da migration)
                cursor.execute(
                    """INSERT INTO bank_conciliacao_regras
                       (padrao_descricao, tipo_match, tipo_transacao,
                        forma_recebimento_id, fornecedor_id)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (padrao, tipo_match, tipo_transacao, forma_id, fornecedor_id),
                )
            conn.commit()
            flash('Regra criada com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('conciliacao_regras.lista'))

    formas      = _get_formas(cursor)
    fornecedores = _get_fornecedores(cursor)
    clientes    = _get_clientes(cursor)
    titulos     = _get_titulos(cursor)
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/form.html',
                           regra=None, formas=formas,
                           fornecedores=fornecedores, clientes=clientes,
                           titulos=titulos, acao='Criar')


@bp.route('/<int:regra_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(regra_id):
    """Edita regra existente."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    regra = cursor.fetchone()
    if not regra:
        flash('Regra não encontrada.', 'warning')
        cursor.close()
        conn.close()
        return redirect(url_for('conciliacao_regras.lista'))

    if request.method == 'POST':
        padrao         = request.form.get('padrao_descricao', '').strip()
        padrao2        = request.form.get('padrao_secundario', '').strip() or None
        tipo_match     = request.form.get('tipo_match', 'contem')
        tipo_transacao = request.form.get('tipo_transacao', 'AMBOS')
        forma_id       = request.form.get('forma_recebimento_id') or None
        fornecedor_id  = request.form.get('fornecedor_id') or None
        cliente_id     = request.form.get('cliente_id') or None
        titulo_id      = request.form.get('titulo_id') or None
        categoria_id   = request.form.get('categoria_id') or None

        if not padrao:
            flash('Padrão de descrição é obrigatório.', 'warning')
        else:
            try:
                cursor.execute(
                    """UPDATE bank_conciliacao_regras
                       SET padrao_descricao=%s, padrao_secundario=%s, tipo_match=%s,
                           tipo_transacao=%s, forma_recebimento_id=%s, fornecedor_id=%s,
                           cliente_id=%s, titulo_id=%s, categoria_id=%s
                       WHERE id=%s""",
                    (padrao, padrao2, tipo_match, tipo_transacao,
                     forma_id, fornecedor_id, cliente_id, titulo_id, categoria_id,
                     regra_id),
                )
            except Exception:
                cursor.execute(
                    """UPDATE bank_conciliacao_regras
                       SET padrao_descricao=%s, tipo_match=%s, tipo_transacao=%s,
                           forma_recebimento_id=%s, fornecedor_id=%s
                       WHERE id=%s""",
                    (padrao, tipo_match, tipo_transacao, forma_id, fornecedor_id, regra_id),
                )
            conn.commit()
            flash('Regra atualizada!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('conciliacao_regras.lista'))

    formas       = _get_formas(cursor)
    fornecedores = _get_fornecedores(cursor)
    clientes     = _get_clientes(cursor)
    titulos      = _get_titulos(cursor)
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/form.html',
                           regra=regra, formas=formas,
                           fornecedores=fornecedores, clientes=clientes,
                           titulos=titulos, acao='Salvar')


@bp.route('/<int:regra_id>/toggle', methods=['POST'])
@login_required
def toggle(regra_id):
    """Ativa ou desativa uma regra."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT ativo FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    r = cursor.fetchone()
    if r:
        novo_status = 0 if r['ativo'] else 1
        cursor.execute("UPDATE bank_conciliacao_regras SET ativo=%s WHERE id=%s",
                       (novo_status, regra_id))
        conn.commit()
        flash('Regra ' + ('ativada' if novo_status else 'desativada') + '.', 'info')
    cursor.close()
    conn.close()
    return redirect(url_for('conciliacao_regras.lista'))


@bp.route('/<int:regra_id>/excluir', methods=['POST'])
@login_required
def excluir(regra_id):
    """Exclui uma regra (somente se nunca aplicada)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT total_aplicacoes FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    r = cursor.fetchone()
    if r and r['total_aplicacoes'] > 0:
        flash(f'Não é possível excluir: regra já foi aplicada {r["total_aplicacoes"]} vez(es). Use desativar.', 'warning')
    elif r:
        cursor.execute("DELETE FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
        conn.commit()
        flash('Regra excluída.', 'success')
    cursor.close()
    conn.close()
    return redirect(url_for('conciliacao_regras.lista'))


@bp.route('/api/categorias/<int:titulo_id>')
@login_required
def api_categorias(titulo_id):
    """Retorna categorias de um título para o select dinâmico no formulário."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome FROM categorias_despesas WHERE titulo_id=%s AND ativo=1 ORDER BY ordem, nome",
        (titulo_id,),
    )
    cats = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(cats)
