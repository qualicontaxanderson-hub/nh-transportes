import logging

import mysql.connector

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('despesas', __name__, url_prefix='/despesas')

# MySQL server error numbers used in this module
_MYSQL_ERR_DUPLICATE_COLUMN = 1060  # "Duplicate column name '…'"

_tables_ready = False


def _ensure_tables():
    """Garante que a tabela categoria_despesa_contas existe. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return
    log = logging.getLogger(__name__)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categoria_despesa_contas (
                id                INT          AUTO_INCREMENT PRIMARY KEY,
                categoria_id      INT          NOT NULL,
                cliente_id        INT          NOT NULL,
                conta_contabil_id INT          NULL,
                UNIQUE KEY uq_cdc_cat_cliente (categoria_id, cliente_id),
                CONSTRAINT fk_cdc_categoria FOREIGN KEY (categoria_id)
                    REFERENCES categorias_despesas(id) ON DELETE CASCADE,
                CONSTRAINT fk_cdc_cliente FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id) ON DELETE CASCADE,
                CONSTRAINT fk_cdc_conta FOREIGN KEY (conta_contabil_id)
                    REFERENCES plano_contas_contas(id) ON DELETE SET NULL
            ) COMMENT='Vínculo por empresa entre categorias de despesas e contas contábeis'
        """)
        # Conta contábil por SUBCATEGORIA (opcional). Quando existe, manda na
        # exportação; quando não, vale a da categoria. Ex.: CASA GOIATUBA vai
        # como 41630 Diversas, mas a subcategoria CONSTRUÇÃO vai como 41306
        # Materiais de Construção.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subcategoria_despesa_contas (
                id                INT          AUTO_INCREMENT PRIMARY KEY,
                subcategoria_id   INT          NOT NULL,
                cliente_id        INT          NOT NULL,
                conta_contabil_id INT          NULL,
                UNIQUE KEY uq_sdc_sub_cliente (subcategoria_id, cliente_id),
                CONSTRAINT fk_sdc_sub FOREIGN KEY (subcategoria_id)
                    REFERENCES subcategorias_despesas(id) ON DELETE CASCADE,
                CONSTRAINT fk_sdc_cliente FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id) ON DELETE CASCADE,
                CONSTRAINT fk_sdc_conta FOREIGN KEY (conta_contabil_id)
                    REFERENCES plano_contas_contas(id) ON DELETE SET NULL
            ) COMMENT='Conta contábil por empresa da subcategoria; vazia = usa a da categoria'
        """)
        # Adiciona coluna exibir_dre se ainda não existir (idempotente)
        try:
            cursor.execute("""
                ALTER TABLE categorias_despesas
                ADD COLUMN exibir_dre TINYINT(1) NOT NULL DEFAULT 1
                COMMENT 'Se 1, a categoria aparece no DRE; se 0, é omitida do DRE'
            """)
        except mysql.connector.errors.DatabaseError as exc:
            if exc.errno != _MYSQL_ERR_DUPLICATE_COLUMN:
                raise
        conn.commit()
        _tables_ready = True
    except Exception:
        log.exception('_ensure_tables despesas: falha ao inicializar tabelas')
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cursor.close()
        conn.close()


def _load_form_data(conn):
    """Carrega empresas e o mapeamento grupo→contas contábeis para o formulário de categoria."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT DISTINCT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome,
                  c.grupo_contabil_id
             FROM clientes c
             INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome"""
    )
    empresas = cursor.fetchall()
    cursor.execute(
        """SELECT c.id, c.grupo_id, c.codigo, c.nome AS conta_nome
             FROM plano_contas_contas c
             JOIN plano_contas_grupos g ON g.id = c.grupo_id
            WHERE c.ativo = 1
            ORDER BY g.codigo, c.codigo"""
    )
    contas_raw = cursor.fetchall()
    cursor.close()
    contas_por_grupo = {}
    for c in contas_raw:
        gid = c['grupo_id']
        if gid not in contas_por_grupo:
            contas_por_grupo[gid] = []
        contas_por_grupo[gid].append({
            'id': c['id'],
            'label': f"{c['codigo']} {c['conta_nome']}",
        })
    return empresas, contas_por_grupo


@bp.route('/')
@login_required
@admin_required
def index():
    """Lista todos os títulos de despesas"""
    _ensure_tables()
    cliente_id = request.args.get('cliente_id', '').strip()
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT t.*,
                   COUNT(DISTINCT c.id) as total_categorias
            FROM titulos_despesas t
            LEFT JOIN categorias_despesas c ON t.id = c.titulo_id AND c.ativo = 1
            WHERE t.ativo = 1
            GROUP BY t.id
            ORDER BY t.ordem, t.nome
        """)
        titulos = cursor.fetchall()
        # Deduplicate by nome in case the table has duplicate rows
        # (migration applied multiple times cria títulos repetidos com ids distintos)
        _seen_titulos: set = set()
        titulos = [t for t in titulos
                   if t['nome'] not in _seen_titulos and not _seen_titulos.add(t['nome'])]

        # Companies with active products for the filter dropdown
        cursor.execute(
            """SELECT DISTINCT c.id,
                      COALESCE(c.nome_fantasia, c.razao_social) AS nome
                 FROM clientes c
                 INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
                ORDER BY nome"""
        )
        empresas = cursor.fetchall()

        # Report: categories + contas contábeis for the selected company
        relatorio = []
        empresa_selecionada = None
        if cliente_id:
            cursor.execute(
                """SELECT t.nome AS titulo_nome,
                          cat.nome AS categoria_nome,
                          pcc.codigo AS conta_codigo,
                          pcc.nome AS conta_nome
                     FROM categorias_despesas cat
                     JOIN titulos_despesas t ON t.id = cat.titulo_id AND t.ativo = 1
                     LEFT JOIN categoria_despesa_contas cdc
                            ON cdc.categoria_id = cat.id AND cdc.cliente_id = %s
                     LEFT JOIN plano_contas_contas pcc ON pcc.id = cdc.conta_contabil_id
                    WHERE cat.ativo = 1
                    ORDER BY t.ordem, t.nome, cat.nome""",
                (int(cliente_id),)
            )
            relatorio = cursor.fetchall()
            for emp in empresas:
                if str(emp['id']) == cliente_id:
                    empresa_selecionada = emp
                    break

        cursor.close()
        conn.close()
        return render_template('despesas/index.html',
                               titulos=titulos,
                               empresas=empresas,
                               relatorio=relatorio,
                               cliente_id=cliente_id,
                               empresa_selecionada=empresa_selecionada)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('index despesas error')
        flash(f'Erro ao carregar despesas: {str(e)}', 'danger')
        return render_template('despesas/index.html',
                               titulos=[],
                               empresas=[],
                               relatorio=[],
                               cliente_id='',
                               empresa_selecionada=None)


@bp.route('/titulo/<int:titulo_id>')
@login_required
@admin_required
def titulo_detalhes(titulo_id):
    """Mostra categorias de um título específico"""
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM titulos_despesas WHERE id = %s", (titulo_id,))
    titulo = cursor.fetchone()

    if not titulo:
        flash('Título não encontrado!', 'error')
        cursor.close()
        conn.close()
        return redirect(url_for('despesas.index'))

    empresa_id = current_user.cliente_id if hasattr(current_user, 'cliente_id') else None
    cursor.execute("""
        SELECT c.*,
               COUNT(DISTINCT s.id) as total_subcategorias,
               pcc.codigo as conta_codigo,
               pcc.nome   as conta_nome
        FROM categorias_despesas c
        LEFT JOIN subcategorias_despesas s ON c.id = s.categoria_id AND s.ativo = 1
        LEFT JOIN categoria_despesa_contas cdc
               ON cdc.categoria_id = c.id AND cdc.cliente_id = %s
        LEFT JOIN plano_contas_contas pcc ON pcc.id = cdc.conta_contabil_id
        WHERE c.titulo_id = %s AND c.ativo = 1
        GROUP BY c.id
        ORDER BY c.nome
    """, (empresa_id, titulo_id,))
    categorias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('despesas/titulo_detalhes.html', titulo=titulo, categorias=categorias)


@bp.route('/categoria/<int:categoria_id>')
@login_required
@admin_required
def categoria_detalhes(categoria_id):
    """Mostra subcategorias de uma categoria específica"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.*, t.nome as titulo_nome, t.id as titulo_id
        FROM categorias_despesas c
        LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.id = %s
    """, (categoria_id,))
    categoria = cursor.fetchone()

    if not categoria:
        flash('Categoria não encontrada!', 'error')
        cursor.close()
        conn.close()
        return redirect(url_for('despesas.index'))

    cursor.execute("""
        SELECT * FROM subcategorias_despesas
        WHERE categoria_id = %s AND ativo = 1
        ORDER BY nome
    """, (categoria_id,))
    subcategorias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('despesas/categoria_detalhes.html',
                         categoria=categoria,
                         subcategorias=subcategorias)


# Rotas de gerenciamento de títulos
@bp.route('/titulos/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo_titulo():
    """Criar novo título de despesa"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'POST':
            cursor.execute("""
                INSERT INTO titulos_despesas (nome, descricao, ordem, ativo)
                VALUES (%s, %s, %s, %s)
            """, (
                request.form.get('nome'),
                request.form.get('descricao'),
                request.form.get('ordem', 0),
                1
            ))

            conn.commit()
            flash('Título criado com sucesso!', 'success')
            return redirect(url_for('despesas.index'))

        return render_template('despesas/titulo_form.html', titulo=None)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar título: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/titulos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_titulo(id):
    """Editar título de despesa"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                UPDATE titulos_despesas 
                SET nome = %s, descricao = %s, ordem = %s
                WHERE id = %s
            """, (
                request.form.get('nome'),
                request.form.get('descricao'),
                request.form.get('ordem', 0),
                id
            ))

            conn.commit()
            flash('Título atualizado com sucesso!', 'success')
            return redirect(url_for('despesas.index'))

        cursor.execute("SELECT * FROM titulos_despesas WHERE id = %s", (id,))
        titulo = cursor.fetchone()
        return render_template('despesas/titulo_form.html', titulo=titulo)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar título: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Rotas de gerenciamento de categorias
@bp.route('/categorias/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_categoria():
    """Criar nova categoria de despesa"""
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            titulo_id = request.form.get('titulo_id')
            exibir_dre = 1 if request.form.get('exibir_dre') else 0
            cursor.execute("""
                INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo, exibir_dre)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                titulo_id,
                request.form.get('nome'),
                request.form.get('ordem', 0),
                1,
                exibir_dre,
            ))
            conn.commit()
            nova_id = cursor.lastrowid

            # Salvar vínculos empresa + conta contábil
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO categoria_despesa_contas
                               (categoria_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (nova_id, int(eid), conta_id)
                    )
            conn.commit()

            flash('Categoria criada com sucesso!', 'success')
            return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))

        # Buscar títulos para o dropdown
        cursor.execute("SELECT * FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome")
        titulos = cursor.fetchall()

        empresas, contas_por_grupo = _load_form_data(conn)

        titulo_id = request.args.get('titulo_id')
        return render_template('despesas/categoria_form.html',
                             categoria=None,
                             titulos=titulos,
                             empresas=empresas,
                             contas_por_grupo=contas_por_grupo,
                             vinculos=[],
                             titulo_id_pre=titulo_id)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar categoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/categorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_categoria(id):
    """Editar categoria de despesa"""
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            exibir_dre = 1 if request.form.get('exibir_dre') else 0
            cursor.execute("""
                UPDATE categorias_despesas 
                SET titulo_id = %s, nome = %s, ordem = %s, exibir_dre = %s
                WHERE id = %s
            """, (
                request.form.get('titulo_id'),
                request.form.get('nome'),
                request.form.get('ordem', 0),
                exibir_dre,
                id
            ))
            conn.commit()

            # Atualizar vínculos empresa + conta contábil
            cursor.execute("DELETE FROM categoria_despesa_contas WHERE categoria_id = %s", (id,))
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO categoria_despesa_contas
                               (categoria_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (id, int(eid), conta_id)
                    )
            conn.commit()

            cursor.execute("SELECT titulo_id FROM categorias_despesas WHERE id = %s", (id,))
            result = cursor.fetchone()
            titulo_id = result['titulo_id']

            flash('Categoria atualizada com sucesso!', 'success')
            return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))

        cursor.execute("SELECT * FROM categorias_despesas WHERE id = %s", (id,))
        categoria = cursor.fetchone()

        cursor.execute("SELECT * FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome")
        titulos = cursor.fetchall()

        cursor.execute(
            """SELECT cdc.cliente_id, cdc.conta_contabil_id, c.grupo_contabil_id
                 FROM categoria_despesa_contas cdc
                 JOIN clientes c ON c.id = cdc.cliente_id
                WHERE cdc.categoria_id = %s""",
            (id,)
        )
        vinculos = cursor.fetchall()

        empresas, contas_por_grupo = _load_form_data(conn)

        return render_template('despesas/categoria_form.html',
                             categoria=categoria,
                             titulos=titulos,
                             empresas=empresas,
                             contas_por_grupo=contas_por_grupo,
                             vinculos=vinculos,
                             titulo_id_pre=None)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar categoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Rotas de gerenciamento de subcategorias
def _salvar_contas_subcategoria(cursor, sub_id):
    """Grava os vínculos empresa -> conta da subcategoria. Linha sem conta
    não é gravada: sem vínculo, a exportação usa a conta da categoria."""
    cursor.execute("DELETE FROM subcategoria_despesa_contas WHERE subcategoria_id = %s", (sub_id,))
    for eid, cid in zip(request.form.getlist('empresa_id[]'), request.form.getlist('conta_contabil_id[]')):
        if eid and cid:
            cursor.execute(
                """INSERT INTO subcategoria_despesa_contas (subcategoria_id, cliente_id, conta_contabil_id)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                (sub_id, int(eid), int(cid)))


def _contas_para_form_subcategoria(conn, cursor, sub_id, categoria_id):
    """(empresas, contas_por_grupo, vinculos da subcategoria, contas da categoria)"""
    vinculos = []
    if sub_id:
        cursor.execute(
            """SELECT sdc.cliente_id, sdc.conta_contabil_id, c.grupo_contabil_id
                 FROM subcategoria_despesa_contas sdc
                 JOIN clientes c ON c.id = sdc.cliente_id
                WHERE sdc.subcategoria_id = %s""", (sub_id,))
        vinculos = cursor.fetchall()
    da_categoria = []
    if categoria_id:
        cursor.execute(
            """SELECT COALESCE(c.nome_fantasia, c.razao_social) AS empresa,
                      CONCAT(pc.codigo, ' ', pc.nome) AS conta
                 FROM categoria_despesa_contas cdc
                 JOIN clientes c ON c.id = cdc.cliente_id
                 LEFT JOIN plano_contas_contas pc ON pc.id = cdc.conta_contabil_id
                WHERE cdc.categoria_id = %s""", (categoria_id,))
        da_categoria = cursor.fetchall()
    empresas, contas_por_grupo = _load_form_data(conn)
    return empresas, contas_por_grupo, vinculos, da_categoria


@bp.route('/subcategorias/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_subcategoria():
    """Criar nova subcategoria de despesa"""
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            categoria_id = request.form.get('categoria_id')
            cursor.execute("""
                INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo)
                VALUES (%s, %s, %s, %s)
            """, (
                categoria_id,
                request.form.get('nome'),
                request.form.get('ordem', 0),
                1
            ))
            _salvar_contas_subcategoria(cursor, cursor.lastrowid)

            conn.commit()
            flash('Subcategoria criada com sucesso!', 'success')
            return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))

        categoria_id = request.args.get('categoria_id')

        # Buscar categoria
        if categoria_id:
            cursor.execute("""
                SELECT c.*, t.nome as titulo_nome
                FROM categorias_despesas c
                LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
                WHERE c.id = %s
            """, (categoria_id,))
            categoria = cursor.fetchone()
        else:
            categoria = None

        # Buscar todas categorias para dropdown
        cursor.execute("""
            SELECT c.id, c.nome, t.nome as titulo_nome
            FROM categorias_despesas c
            LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
            WHERE c.ativo = 1
            ORDER BY t.ordem, c.ordem, c.nome
        """)
        categorias = cursor.fetchall()

        empresas, contas_por_grupo, vinculos, da_categoria = _contas_para_form_subcategoria(
            conn, cursor, None, categoria_id)
        return render_template('despesas/subcategoria_form.html',
                             subcategoria=None,
                             categorias=categorias,
                             categoria_pre=categoria,
                             empresas=empresas, contas_por_grupo=contas_por_grupo,
                             vinculos=vinculos, da_categoria=da_categoria)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar subcategoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/subcategorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_subcategoria(id):
    """Editar subcategoria de despesa"""
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                UPDATE subcategorias_despesas 
                SET categoria_id = %s, nome = %s, ordem = %s
                WHERE id = %s
            """, (
                request.form.get('categoria_id'),
                request.form.get('nome'),
                request.form.get('ordem', 0),
                id
            ))
            _salvar_contas_subcategoria(cursor, id)

            conn.commit()

            cursor.execute("SELECT categoria_id FROM subcategorias_despesas WHERE id = %s", (id,))
            result = cursor.fetchone()
            categoria_id = result['categoria_id']

            flash('Subcategoria atualizada com sucesso!', 'success')
            return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))

        cursor.execute("SELECT * FROM subcategorias_despesas WHERE id = %s", (id,))
        subcategoria = cursor.fetchone()

        # Buscar categoria da subcategoria
        cursor.execute("""
            SELECT c.*, t.nome as titulo_nome
            FROM categorias_despesas c
            LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
            WHERE c.id = %s
        """, (subcategoria['categoria_id'],))
        categoria = cursor.fetchone()

        # Buscar todas categorias para dropdown
        cursor.execute("""
            SELECT c.id, c.nome, t.nome as titulo_nome
            FROM categorias_despesas c
            LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
            WHERE c.ativo = 1
            ORDER BY t.ordem, c.ordem, c.nome
        """)
        categorias = cursor.fetchall()

        empresas, contas_por_grupo, vinculos, da_categoria = _contas_para_form_subcategoria(
            conn, cursor, id, subcategoria['categoria_id'])
        return render_template('despesas/subcategoria_form.html',
                             subcategoria=subcategoria,
                             categorias=categorias,
                             categoria_pre=categoria,
                             empresas=empresas, contas_por_grupo=contas_por_grupo,
                             vinculos=vinculos, da_categoria=da_categoria)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar subcategoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Rotas de exclusão (soft delete)
@bp.route('/titulos/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_titulo(id):
    """Desativar título de despesa"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE titulos_despesas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()

        flash('Título desativado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar título: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('despesas.index'))


@bp.route('/categorias/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_categoria(id):
    """Desativar categoria de despesa"""
    conn = None
    cursor = None
    titulo_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Buscar titulo_id antes de excluir
        cursor.execute("SELECT titulo_id FROM categorias_despesas WHERE id = %s", (id,))
        result = cursor.fetchone()
        titulo_id = result['titulo_id'] if result else None

        cursor.execute("UPDATE categorias_despesas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()

        flash('Categoria desativada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar categoria: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if titulo_id:
        return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))
    return redirect(url_for('despesas.index'))


@bp.route('/subcategorias/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_subcategoria(id):
    """Desativar subcategoria de despesa"""
    conn = None
    cursor = None
    categoria_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Buscar categoria_id antes de excluir
        cursor.execute("SELECT categoria_id FROM subcategorias_despesas WHERE id = %s", (id,))
        result = cursor.fetchone()
        categoria_id = result['categoria_id'] if result else None

        cursor.execute("UPDATE subcategorias_despesas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()

        flash('Subcategoria desativada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar subcategoria: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if categoria_id:
        return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))
    return redirect(url_for('despesas.index'))


# ─── Aprovar contas contábeis, uma a uma ─────────────────────────────────────

_PALAVRAS_VAZIAS = {'DE', 'DA', 'DO', 'DAS', 'DOS', 'E', 'A', 'O', 'EM', 'COM', 'PARA', 'POR', 'S', 'C'}


def _tokens(txt):
    import unicodedata
    t = unicodedata.normalize('NFKD', txt or '').encode('ascii', 'ignore').decode().upper()
    return {w for w in __import__('re').split(r'[^A-Z0-9]+', t) if len(w) > 1 and w not in _PALAVRAS_VAZIAS}


def _sugere(nome, contas):
    """A conta do plano cujo nome mais se parece com `nome` (palavras em comum).
    None quando nada passa de metade das palavras."""
    alvo = _tokens(nome)
    if not alvo:
        return None
    melhor, nota = None, 0.0
    for c in contas:
        comum = len(alvo & c['_tok'])
        if not comum:
            continue
        n = comum / len(alvo) + comum / (len(c['_tok']) or 1) * 0.3
        if n > nota:
            melhor, nota = c, n
    return melhor if nota >= 0.5 else None


@bp.route('/contas/aprovar')
@login_required
@admin_required
def contas_aprovar():
    """Fila para decidir, uma a uma, a conta contábil das subcategorias (e das
    categorias usadas que estão sem conta). Só da empresa escolhida (padrão:
    Posto NH, cliente 1 — o único com plano de contas ligado hoje)."""
    _ensure_tables()
    try:
        cliente_id = int(request.args.get('empresa') or 1)
    except ValueError:
        cliente_id = 1
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, COALESCE(nome_fantasia, razao_social) AS nome, grupo_contabil_id FROM clientes WHERE id = %s",
                    (cliente_id,))
        empresa = cur.fetchone()
        contas = []
        if empresa and empresa['grupo_contabil_id']:
            cur.execute("""SELECT id, codigo, nome, tipo_grupo FROM plano_contas_contas
                            WHERE grupo_id = %s AND ativo = 1 ORDER BY codigo""", (empresa['grupo_contabil_id'],))
            contas = cur.fetchall()
        for c in contas:
            c['_tok'] = _tokens(c['nome'])
        por_id = {c['id']: c for c in contas}
        desp = [c for c in contas if c['tipo_grupo'] in ('DESPESAS', 'CUSTOS')]

        cur.execute("""
            SELECT s.id sid, s.nome sub, c.id cid, c.nome categoria, t.nome titulo,
                   cdc.conta_contabil_id conta_cat,
                   sdc.id decidida, sdc.conta_contabil_id conta_sub,
                   (SELECT COUNT(*) FROM lancamentos_despesas l
                     WHERE l.subcategoria_id = s.id AND l.cliente_id = %s AND l.data >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)) n,
                   (SELECT COALESCE(SUM(valor), 0) FROM lancamentos_despesas l
                     WHERE l.subcategoria_id = s.id AND l.cliente_id = %s AND l.data >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)) v
              FROM subcategorias_despesas s
              JOIN categorias_despesas c ON c.id = s.categoria_id
              JOIN titulos_despesas t ON t.id = c.titulo_id
              LEFT JOIN categoria_despesa_contas cdc ON cdc.categoria_id = c.id AND cdc.cliente_id = %s
              LEFT JOIN subcategoria_despesa_contas sdc ON sdc.subcategoria_id = s.id AND sdc.cliente_id = %s
             WHERE s.ativo = 1 AND c.ativo = 1
             ORDER BY (sdc.id IS NOT NULL), n DESC, t.ordem, c.nome, s.nome""",
                    (cliente_id, cliente_id, cliente_id, cliente_id))
        subs = cur.fetchall()
        for r in subs:
            r['conta_cat_txt'] = ('%s %s' % (por_id[r['conta_cat']]['codigo'], por_id[r['conta_cat']]['nome'])
                                  if r['conta_cat'] in por_id else None)
            r['conta_sub_txt'] = ('%s %s' % (por_id[r['conta_sub']]['codigo'], por_id[r['conta_sub']]['nome'])
                                  if r['conta_sub'] in por_id else None)
            sug = _sugere(r['sub'], desp) or _sugere('%s %s' % (r['categoria'], r['sub']), desp)
            r['sugestao'] = (r['conta_sub'] or (sug['id'] if sug else None) or r['conta_cat'])

        cur.execute("""
            SELECT c.id cid, c.nome categoria, t.nome titulo,
                   COUNT(l.id) n, COALESCE(SUM(l.valor), 0) v
              FROM categorias_despesas c
              JOIN titulos_despesas t ON t.id = c.titulo_id
              JOIN lancamentos_despesas l ON l.categoria_id = c.id AND l.cliente_id = %s
                   AND l.data >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)
              LEFT JOIN categoria_despesa_contas cdc ON cdc.categoria_id = c.id AND cdc.cliente_id = %s
             WHERE c.ativo = 1 AND cdc.conta_contabil_id IS NULL
             GROUP BY c.id, c.nome, t.nome
             ORDER BY v DESC""", (cliente_id, cliente_id))
        cats = cur.fetchall()
        for r in cats:
            sug = _sugere(r['categoria'], desp)
            r['sugestao'] = sug['id'] if sug else None
    finally:
        cur.close()
        conn.close()
    for c in contas:
        c.pop('_tok', None)
    return render_template('despesas/contas_aprovar.html', empresa=empresa, contas=contas,
                           subs=subs, cats=cats,
                           pend_sub=sum(1 for r in subs if not r['decidida']))


@bp.route('/contas/aprovar/salvar', methods=['POST'])
@login_required
@admin_required
def contas_aprovar_salvar():
    """Grava UMA decisão. tipo='sub': conta da subcategoria (conta vazia =
    'usa a da categoria', fica registrada como decidida). tipo='cat': conta da
    categoria que estava sem conta."""
    _ensure_tables()
    d = request.get_json(silent=True) or {}
    try:
        cliente_id = int(d.get('empresa') or 1)
        alvo = int(d.get('id'))
        conta = int(d['conta']) if d.get('conta') else None
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'erro': 'dados inválidos'}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if d.get('tipo') == 'sub':
            cur.execute("""INSERT INTO subcategoria_despesa_contas (subcategoria_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (alvo, cliente_id, conta))
        elif d.get('tipo') == 'cat':
            if not conta:
                return jsonify({'ok': False, 'erro': 'escolha a conta'}), 400
            cur.execute("""INSERT INTO categoria_despesa_contas (categoria_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (alvo, cliente_id, conta))
        else:
            return jsonify({'ok': False, 'erro': 'tipo inválido'}), 400
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'erro': str(e)}), 500
    finally:
        cur.close()
        conn.close()
