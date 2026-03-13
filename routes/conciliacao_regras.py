"""CRUD de regras de conciliação automática (bank_conciliacao_regras)."""

import logging
import mysql.connector
import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection

_BRASILIA = pytz.timezone('America/Sao_Paulo')

logger = logging.getLogger(__name__)

bp = Blueprint('conciliacao_regras', __name__, url_prefix='/banco/regras')

_bsm_descricao_chave_ready = False


def _ensure_descricao_chave():
    """Garante que bank_supplier_mapping.descricao_chave existe. Idempotente."""
    global _bsm_descricao_chave_ready
    if _bsm_descricao_chave_ready:
        return
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'bank_supplier_mapping'"
            " AND COLUMN_NAME = 'descricao_chave'"
        )
        col_exists = cursor.fetchone()[0] > 0
        if not col_exists:
            cursor.execute(
                "ALTER TABLE bank_supplier_mapping"
                " ADD COLUMN descricao_chave VARCHAR(100) NOT NULL DEFAULT ''"
                " COMMENT 'Prefixo normalizado da descrição para diferenciar entradas com mesmo CNPJ'"
            )
            try:
                cursor.execute("ALTER TABLE bank_supplier_mapping DROP INDEX uq_bsm_chave")
            except Exception:
                pass
            try:
                cursor.execute(
                    "ALTER TABLE bank_supplier_mapping"
                    " ADD UNIQUE KEY uq_bsm_chave (cnpj_cpf, descricao_chave)"
                )
            except Exception:
                pass
            try:
                cursor.execute("DROP TRIGGER IF EXISTS tr_learn_supplier_mapping")
            except Exception:
                pass
            conn.commit()
            logger.info("_ensure_descricao_chave (conciliacao_regras): coluna e índice criados")
        cursor.close()
        _bsm_descricao_chave_ready = True
    except Exception:
        logger.warning("_ensure_descricao_chave (conciliacao_regras): falhou", exc_info=True)
    finally:
        if conn:
            conn.close()


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


def _get_titulos_simples(cursor):
    """Retorna lista simples de títulos (sem JSON embutido — evita bug de aspas duplas)."""
    cursor.execute(
        "SELECT id, nome FROM titulos_despesas WHERE ativo=1 ORDER BY ordem, nome"
    )
    return cursor.fetchall()


def _get_contas(cursor):
    """Retorna contas bancárias ativas para o select de conta corrente."""
    cursor.execute(
        """SELECT ba.id, CONCAT(ba.banco_nome, ' - ', ba.apelido,
                  ' [', IFNULL(c.razao_social,''), ']') AS label
           FROM bank_accounts ba
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           WHERE ba.ativo = 1
           ORDER BY ba.banco_nome, ba.apelido"""
    )
    return cursor.fetchall()


@bp.route('/')
@login_required
def lista():
    """Lista as regras de conciliação com filtros opcionais."""
    mostrar_inativos = request.args.get('inativos', '0') == '1'
    filtro_banco     = request.args.get('banco', '').strip()
    filtro_empresa   = request.args.get('empresa', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    where  = []
    params = []

    if not mostrar_inativos:
        where.append("r.ativo = 1")

    if filtro_banco:
        where.append("ba.banco_nome = %s")
        params.append(filtro_banco)

    if filtro_empresa:
        where.append("ba.cliente_id = %s")
        params.append(filtro_empresa)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    cursor.execute(
        f"""SELECT r.*,
                  fr.nome AS forma_nome,
                  f.razao_social AS fornecedor_nome,
                  c.razao_social AS cliente_nome,
                  td.nome AS titulo_nome,
                  cd.nome AS categoria_nome,
                  ba.banco_nome AS conta_banco,
                  ba.apelido AS conta_apelido
           FROM bank_conciliacao_regras r
           LEFT JOIN formas_recebimento fr ON fr.id = r.forma_recebimento_id
           LEFT JOIN fornecedores f ON f.id = r.fornecedor_id
           LEFT JOIN clientes c ON c.id = r.cliente_id
           LEFT JOIN titulos_despesas td ON td.id = r.titulo_id
           LEFT JOIN categorias_despesas cd ON cd.id = r.categoria_id
           LEFT JOIN bank_accounts ba ON ba.id = r.account_id
           {where_clause}
           ORDER BY r.padrao_descricao""",
        params or None,
    )
    regras = cursor.fetchall()

    # Opções para os dropdowns de filtro
    cursor.execute(
        "SELECT DISTINCT banco_nome FROM bank_accounts WHERE ativo=1 ORDER BY banco_nome"
    )
    bancos = [row['banco_nome'] for row in cursor.fetchall()]

    cursor.execute(
        """SELECT DISTINCT cl.id, cl.razao_social
           FROM clientes cl
           INNER JOIN bank_accounts ba ON ba.cliente_id = cl.id
           WHERE ba.ativo = 1
           ORDER BY cl.razao_social"""
    )
    empresas = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template(
        'bank_import/regras/lista.html',
        regras=regras,
        bancos=bancos,
        empresas=empresas,
        mostrar_inativos=mostrar_inativos,
        filtro_banco=filtro_banco,
        filtro_empresa=filtro_empresa,
    )


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
        subcategoria_id  = request.form.get('subcategoria_id') or None
        account_id       = request.form.get('account_id') or None

        if not padrao:
            flash('Padrão de descrição é obrigatório.', 'warning')
        else:
            cursor.execute(
                """INSERT INTO bank_conciliacao_regras
                   (padrao_descricao, padrao_secundario, tipo_match, tipo_transacao,
                    forma_recebimento_id, fornecedor_id, cliente_id, titulo_id,
                    categoria_id, subcategoria_id, account_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (padrao, padrao2, tipo_match, tipo_transacao,
                 forma_id, fornecedor_id, cliente_id, titulo_id,
                 categoria_id, subcategoria_id, account_id),
            )
            conn.commit()
            flash('Regra criada com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('conciliacao_regras.lista'))

    formas       = _get_formas(cursor)
    fornecedores = _get_fornecedores(cursor)
    clientes     = _get_clientes(cursor)
    titulos      = _get_titulos_simples(cursor)
    contas       = _get_contas(cursor)
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/form.html',
                           regra=None, formas=formas,
                           fornecedores=fornecedores, clientes=clientes,
                           titulos=titulos, contas=contas, acao='Criar')


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
        subcategoria_id = request.form.get('subcategoria_id') or None
        account_id     = request.form.get('account_id') or None

        if not padrao:
            flash('Padrão de descrição é obrigatório.', 'warning')
        else:
            cursor.execute(
                """UPDATE bank_conciliacao_regras
                   SET padrao_descricao=%s, padrao_secundario=%s, tipo_match=%s,
                       tipo_transacao=%s, forma_recebimento_id=%s, fornecedor_id=%s,
                       cliente_id=%s, titulo_id=%s, categoria_id=%s, subcategoria_id=%s,
                       account_id=%s
                   WHERE id=%s""",
                (padrao, padrao2, tipo_match, tipo_transacao,
                 forma_id, fornecedor_id, cliente_id, titulo_id,
                 categoria_id, subcategoria_id, account_id, regra_id),
            )
            conn.commit()
            flash('Regra atualizada!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('conciliacao_regras.lista'))

    formas       = _get_formas(cursor)
    fornecedores = _get_fornecedores(cursor)
    clientes     = _get_clientes(cursor)
    titulos      = _get_titulos_simples(cursor)
    contas       = _get_contas(cursor)
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/form.html',
                           regra=regra, formas=formas,
                           fornecedores=fornecedores, clientes=clientes,
                           titulos=titulos, contas=contas, acao='Salvar')


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
    """Exclui uma regra; se já aplicada, apenas desativa."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT total_aplicacoes FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    r = cursor.fetchone()
    if r:
        if r['total_aplicacoes'] > 0:
            cursor.execute("UPDATE bank_conciliacao_regras SET ativo=0 WHERE id=%s", (regra_id,))
            conn.commit()
            flash(f'Regra já foi aplicada {r["total_aplicacoes"]} vez(es) — foi desativada.', 'info')
        else:
            cursor.execute("DELETE FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
            conn.commit()
            flash('Regra excluída.', 'success')
    cursor.close()
    conn.close()
    return redirect(url_for('conciliacao_regras.lista'))


@bp.route('/excluir-lote', methods=['POST'])
@login_required
def excluir_lote():
    """Exclui em lote as regras selecionadas; regras já aplicadas são apenas desativadas."""
    ids_raw = request.form.getlist('regra_ids')
    ids = [int(i) for i in ids_raw if i.isdigit()]
    if not ids:
        flash('Nenhuma regra selecionada.', 'warning')
        return redirect(url_for('conciliacao_regras.lista'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ids validated as integers above; f-string only builds %s placeholders, values stay parameterized
    ph = ','.join(['%s'] * len(ids))
    cursor.execute(
        f"SELECT id, total_aplicacoes FROM bank_conciliacao_regras WHERE id IN ({ph})",
        ids,
    )
    rows = cursor.fetchall()

    excluir_ids  = [r['id'] for r in rows if r['total_aplicacoes'] == 0]
    desativar_ids = [r['id'] for r in rows if r['total_aplicacoes'] > 0]

    if excluir_ids:
        ph2 = ','.join(['%s'] * len(excluir_ids))
        cursor.execute(f"DELETE FROM bank_conciliacao_regras WHERE id IN ({ph2})", excluir_ids)
    if desativar_ids:
        ph3 = ','.join(['%s'] * len(desativar_ids))
        cursor.execute(
            f"UPDATE bank_conciliacao_regras SET ativo=0 WHERE id IN ({ph3})",
            desativar_ids,
        )

    conn.commit()
    cursor.close()
    conn.close()

    partes = []
    if excluir_ids:
        partes.append(f'{len(excluir_ids)} regra(s) excluída(s)')
    if desativar_ids:
        partes.append(f'{len(desativar_ids)} regra(s) já aplicada(s) foram desativadas')
    flash('; '.join(partes) + '.', 'success')
    return redirect(url_for('conciliacao_regras.lista'))


@bp.route('/memorias')
@login_required
def memorias():
    """Lista as memorizações de conciliação (bank_supplier_mapping)."""
    _ensure_descricao_chave()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Tried in order from newest schema to oldest; on ProgrammingError errno=1054
    # (unknown column) the next simpler query is attempted so the page stays
    # functional even when optional migration columns (descricao_chave,
    # tipo_debito, conta_destino_id, titulo_id/categoria_id) haven't been
    # applied to the production DB yet.
    _QUERIES = [
        # Level 1 — full schema (all columns added through all migrations)
        (
            "SELECT bsm.id, bsm.cnpj_cpf, bsm.descricao_chave, bsm.tipo_chave,"
            " bsm.total_conciliacoes, bsm.criado_em, bsm.atualizado_em,"
            " f.razao_social AS fornecedor_nome, fr.nome AS forma_nome,"
            " td.nome AS titulo_nome, cd.nome AS categoria_nome,"
            " ba.apelido AS conta_destino_apelido,"
            " ba.banco_nome AS conta_destino_banco, bsm.tipo_debito"
            " FROM bank_supplier_mapping bsm"
            " LEFT JOIN fornecedores f ON f.id = bsm.fornecedor_id"
            " LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id"
            " LEFT JOIN titulos_despesas td ON td.id = bsm.titulo_id"
            " LEFT JOIN categorias_despesas cd ON cd.id = bsm.categoria_id"
            " LEFT JOIN bank_accounts ba ON ba.id = bsm.conta_destino_id"
            " ORDER BY bsm.atualizado_em DESC"
        ),
        # Level 2 — without descricao_chave, tipo_debito, conta_destino_id
        #   (handles migrations 20260223_add_transfer_fields and
        #    20260309_add_descricao_chave not yet applied)
        (
            "SELECT bsm.id, bsm.cnpj_cpf, '' AS descricao_chave, bsm.tipo_chave,"
            " bsm.total_conciliacoes, bsm.criado_em, bsm.atualizado_em,"
            " f.razao_social AS fornecedor_nome, fr.nome AS forma_nome,"
            " td.nome AS titulo_nome, cd.nome AS categoria_nome,"
            " NULL AS conta_destino_apelido, NULL AS conta_destino_banco,"
            " NULL AS tipo_debito"
            " FROM bank_supplier_mapping bsm"
            " LEFT JOIN fornecedores f ON f.id = bsm.fornecedor_id"
            " LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id"
            " LEFT JOIN titulos_despesas td ON td.id = bsm.titulo_id"
            " LEFT JOIN categorias_despesas cd ON cd.id = bsm.categoria_id"
            " ORDER BY bsm.id DESC"
        ),
        # Level 3 — minimal: only columns present since the original schema
        #   (handles 20260223_add_despesa_to_mapping also not yet applied)
        (
            "SELECT bsm.id, bsm.cnpj_cpf, '' AS descricao_chave, bsm.tipo_chave,"
            " bsm.total_conciliacoes, bsm.criado_em, bsm.atualizado_em,"
            " f.razao_social AS fornecedor_nome, fr.nome AS forma_nome,"
            " NULL AS titulo_nome, NULL AS categoria_nome,"
            " NULL AS conta_destino_apelido, NULL AS conta_destino_banco,"
            " NULL AS tipo_debito"
            " FROM bank_supplier_mapping bsm"
            " LEFT JOIN fornecedores f ON f.id = bsm.fornecedor_id"
            " LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id"
            " ORDER BY bsm.id DESC"
        ),
    ]

    memorias_list = []
    try:
        for lvl, sql in enumerate(_QUERIES):
            try:
                cursor.execute(sql)
                memorias_list = cursor.fetchall()
                break
            except mysql.connector.errors.ProgrammingError as _e:
                if _e.errno != 1054 or lvl == len(_QUERIES) - 1:
                    raise
                conn.rollback()
                logger.warning(
                    "memorias: unknown column at level %d, trying simpler query: %s",
                    lvl + 1, _e,
                )
    except Exception:
        logger.exception("Erro ao carregar memorizações de conciliação")
        memorias_list = []
    finally:
        cursor.close()
        conn.close()

    # Converte timestamps UTC → horário de Brasília para exibição
    for m in memorias_list:
        for field in ('atualizado_em', 'criado_em'):
            val = m.get(field)
            if val is not None:
                try:
                    # MySQL datetime sem tzinfo → assume UTC
                    utc_dt = pytz.utc.localize(val) if val.tzinfo is None else val
                    m[field] = utc_dt.astimezone(_BRASILIA)
                except Exception:
                    pass  # mantém o valor original em caso de erro inesperado

    return render_template('bank_import/regras/memorias.html', memorias=memorias_list)


@bp.route('/memorias/<int:memoria_id>/excluir', methods=['POST'])
@login_required
def excluir_memoria(memoria_id):
    """Exclui uma memorização de conciliação."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM bank_supplier_mapping WHERE id = %s", (memoria_id,))
        conn.commit()
        flash('Memorização excluída com sucesso.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir memorização: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('conciliacao_regras.memorias'))



@login_required
def api_criar_subcategoria():
    """Cria uma subcategoria inline durante o preenchimento da regra (AJAX)."""
    data = request.get_json(silent=True) or {}
    categoria_id = data.get('categoria_id')
    nome = (data.get('nome') or '').strip()
    if not categoria_id or not nome:
        return jsonify({'ok': False, 'msg': 'categoria_id e nome são obrigatórios'}), 400
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT INTO subcategorias_despesas (categoria_id, nome, ativo) VALUES (%s,%s,1)",
            (categoria_id, nome),
        )
        conn.commit()
        novo_id = cursor.lastrowid
        return jsonify({'ok': True, 'id': novo_id, 'nome': nome})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/api/categorias/<int:titulo_id>')
@login_required
def api_categorias(titulo_id):
    """Retorna categorias de um título com subcategorias aninhadas."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome FROM categorias_despesas WHERE titulo_id=%s AND ativo=1 ORDER BY ordem, nome",
        (titulo_id,),
    )
    cats = cursor.fetchall()
    # Buscar subcategorias para cada categoria
    for cat in cats:
        try:
            cursor.execute(
                "SELECT id, nome FROM subcategorias_despesas WHERE categoria_id=%s AND ativo=1 ORDER BY nome",
                (cat['id'],),
            )
            cat['subcategorias'] = cursor.fetchall()
        except Exception:
            cat['subcategorias'] = []
    cursor.close()
    conn.close()
    return jsonify(cats)
