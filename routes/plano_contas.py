import logging
import re
import unicodedata

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection
from utils.decorators import admin_required


def _gerar_codigo(nome):
    """Gera código curto e legível a partir do nome (máx. 28 chars, ASCII, sem acentos)."""
    s = unicodedata.normalize('NFKD', nome)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    slug = re.sub(r'[^A-Z0-9]', '-', s)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:28]


def _codigo_unico(cursor, base, excluir_id=None):
    """Retorna um código único derivado de base, adicionando sufixo numérico se necessário."""
    qry = "SELECT codigo FROM plano_contas_grupos WHERE codigo LIKE %s"
    params = [base + '%']
    if excluir_id:
        qry += " AND id != %s"
        params.append(excluir_id)
    cursor.execute(qry, params)
    existentes = {row[0] for row in cursor.fetchall()}
    if base not in existentes:
        return base
    n = 2
    while f"{base}-{n}" in existentes:
        n += 1
    return f"{base}-{n}"


_CODIGO_CONTA_RE = re.compile(r'^[0-9]+(\.[0-9]+)*$')


def _validar_codigo_conta(codigo):
    """Retorna True se o código contém apenas dígitos separados por ponto (ex.: 1121 ou 1122.1)."""
    return _CODIGO_CONTA_RE.match(codigo) is not None if codigo else False


def _codigo_conta_duplicado(cursor, grupo_id, codigo, excluir_id=None):
    """Retorna True se já existe uma conta com este código no grupo."""
    qry = "SELECT 1 FROM plano_contas_contas WHERE grupo_id=%s AND codigo=%s"
    params = [grupo_id, codigo]
    if excluir_id:
        qry += " AND id != %s"
        params.append(excluir_id)
    cursor.execute(qry, params)
    return cursor.fetchone() is not None


bp = Blueprint('plano_contas', __name__, url_prefix='/plano-contas')

# Flag per-process: CREATE TABLE IF NOT EXISTS é idempotente; o flag apenas
# evita a query DDL extra em cada request após a primeira execução bem-sucedida.
_tables_ready = False


def _ensure_tables():
    """Garante que todas as tabelas/colunas do plano de contas existem.

    Idempotente — cria com IF NOT EXISTS / verifica information_schema.
    Chamado automaticamente ao acessar qualquer rota deste blueprint.
    """
    global _tables_ready
    if _tables_ready:
        return
    log = logging.getLogger(__name__)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Tabela de grupos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plano_contas_grupos (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                codigo     VARCHAR(30)  NOT NULL COMMENT 'Código contábil, ex.: 11211',
                nome       VARCHAR(120) NOT NULL COMMENT 'Descrição, ex.: Conta Sicoob',
                descricao  TEXT         NULL,
                ativo      TINYINT(1)   NOT NULL DEFAULT 1,
                created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_pcg_codigo (codigo)
            ) COMMENT='Grupos do Plano de Contas Contábil'
        """)
        conn.commit()

        # 2. Coluna grupo_contabil_id em clientes (idempotente via information_schema)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'clientes'
              AND COLUMN_NAME  = 'grupo_contabil_id'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE clientes ADD COLUMN grupo_contabil_id INT NULL"
            )
            conn.commit()

        # 3. FK clientes → plano_contas_grupos (idempotente)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA    = DATABASE()
              AND TABLE_NAME      = 'clientes'
              AND CONSTRAINT_NAME = 'fk_clientes_grupo_contabil'
        """)
        if cursor.fetchone()[0] == 0:
            try:
                cursor.execute("""
                    ALTER TABLE clientes
                    ADD CONSTRAINT fk_clientes_grupo_contabil
                    FOREIGN KEY (grupo_contabil_id)
                    REFERENCES plano_contas_grupos(id) ON DELETE SET NULL
                """)
                conn.commit()
            except Exception:
                # Pode já existir com outro nome; rollback e continua
                log.debug('_ensure_tables: FK já existe ou não aplicável; ignorando', exc_info=True)
                conn.rollback()

        # 4. Tabela de contas dentro dos grupos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plano_contas_contas (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                grupo_id   INT          NOT NULL COMMENT 'FK para plano_contas_grupos',
                codigo     VARCHAR(30)  NOT NULL COMMENT 'Código contábil, ex.: 1121',
                nome       VARCHAR(120) NOT NULL COMMENT 'Nome da conta, ex.: Banco Bradesco',
                descricao  TEXT         NULL,
                ativo      TINYINT(1)   NOT NULL DEFAULT 1,
                created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_pcc_grupo_codigo (grupo_id, codigo),
                CONSTRAINT fk_pcc_grupo FOREIGN KEY (grupo_id)
                    REFERENCES plano_contas_grupos(id) ON DELETE CASCADE
            ) COMMENT='Contas do Plano de Contas Contábil dentro de cada Grupo'
        """)
        conn.commit()
        _tables_ready = True
    except Exception:
        log.exception('_ensure_tables: falha ao inicializar tabelas do plano de contas')
        try:
            conn.rollback()
        except Exception:
            log.debug('_ensure_tables: rollback também falhou', exc_info=True)
    finally:
        cursor.close()
        conn.close()


def _get_grupos(cursor):
    cursor.execute(
        """SELECT g.id, g.codigo, g.nome, g.descricao, g.ativo,
                  COUNT(DISTINCT c.id)  AS total_contas,
                  COUNT(DISTINCT cl.id) AS total_clientes
           FROM plano_contas_grupos g
           LEFT JOIN plano_contas_contas c  ON c.grupo_id = g.id
           LEFT JOIN clientes cl ON cl.grupo_contabil_id = g.id
           GROUP BY g.id
           ORDER BY g.codigo"""
    )
    return cursor.fetchall()


@bp.route('/')
@login_required
@admin_required
def lista():
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    grupos = _get_grupos(cursor)
    cursor.close()
    conn.close()
    return render_template('plano_contas/lista.html', grupos=grupos)


# ─── Grupo: novo / editar / excluir ─────────────────────────────────────────

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None

        if not nome:
            flash('Nome é obrigatório.', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=None,
                                   form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            codigo = _codigo_unico(cursor, _gerar_codigo(nome))
            logging.getLogger(__name__).debug('novo grupo: nome=%r codigo_gerado=%r', nome, codigo)
            cursor.execute(
                "INSERT INTO plano_contas_grupos (codigo, nome, descricao) VALUES (%s, %s, %s)",
                (codigo, nome, descricao),
            )
            conn.commit()
            novo_id = cursor.lastrowid
            flash('Grupo contábil criado com sucesso! Agora adicione as contas e vincule as empresas.', 'success')
            return redirect(url_for('plano_contas.detalhe', id=novo_id))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar grupo: {e}', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=None,
                                   form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/grupo_form.html', grupo=None, form={})


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
    grupo = cursor.fetchone()
    cursor.close()
    conn.close()

    if not grupo:
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    if request.method == 'POST':
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None
        ativo     = 1 if request.form.get('ativo') else 0

        if not nome:
            flash('Nome é obrigatório.', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=grupo,
                                   form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """UPDATE plano_contas_grupos
                   SET nome=%s, descricao=%s, ativo=%s
                   WHERE id=%s""",
                (nome, descricao, ativo, id),
            )
            conn.commit()
            flash('Grupo atualizado com sucesso!', 'success')
            return redirect(url_for('plano_contas.detalhe', id=id))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar grupo: {e}', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=grupo,
                                   form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/grupo_form.html', grupo=grupo, form=grupo)


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Remove vínculo dos clientes antes de excluir o grupo
        cursor.execute(
            "UPDATE clientes SET grupo_contabil_id = NULL WHERE grupo_contabil_id = %s", (id,)
        )
        cursor.execute("DELETE FROM plano_contas_grupos WHERE id = %s", (id,))
        conn.commit()
        flash('Grupo excluído com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir grupo: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('plano_contas.lista'))


# ─── Grupo: clonar ──────────────────────────────────────────────────────────

@bp.route('/clonar/<int:id>', methods=['POST'])
@login_required
@admin_required
def clonar(id):
    """Clona um grupo e todas as suas contas, gerando um novo código automaticamente."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
        grupo = cursor.fetchone()
        if not grupo:
            flash('Grupo não encontrado.', 'danger')
            return redirect(url_for('plano_contas.lista'))

        novo_nome   = grupo['nome'] + ' (cópia)'
        base_codigo = _gerar_codigo(novo_nome)
        cur2 = conn.cursor()
        novo_codigo = _codigo_unico(cur2, base_codigo)
        cur2.close()

        cur3 = conn.cursor()
        cur3.execute(
            "INSERT INTO plano_contas_grupos (codigo, nome, descricao) VALUES (%s, %s, %s)",
            (novo_codigo, novo_nome, grupo['descricao']),
        )
        novo_grupo_id = cur3.lastrowid

        # Copia as contas do grupo original
        cur3.execute(
            "SELECT codigo, nome, descricao FROM plano_contas_contas WHERE grupo_id = %s",
            (id,),
        )
        contas = cur3.fetchall()
        if contas:
            cur3.executemany(
                "INSERT INTO plano_contas_contas (grupo_id, codigo, nome, descricao) VALUES (%s, %s, %s, %s)",
                [(novo_grupo_id, codigo, nome, descricao) for codigo, nome, descricao in contas],
            )

        conn.commit()
        cur3.close()
        flash(f'Grupo clonado com sucesso!', 'success')
        return redirect(url_for('plano_contas.detalhe', id=novo_grupo_id))
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao clonar grupo: {e}', 'danger')
        return redirect(url_for('plano_contas.lista'))
    finally:
        cursor.close()
        conn.close()


# ─── Grupo: detalhe (contas) ─────────────────────────────────────────────────

@bp.route('/<int:id>/contas')
@login_required
@admin_required
def detalhe(id):
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
    grupo = cursor.fetchone()
    if not grupo:
        cursor.close()
        conn.close()
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    cursor.execute(
        """SELECT * FROM plano_contas_contas
           WHERE grupo_id = %s
           ORDER BY codigo""",
        (id,),
    )
    contas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('plano_contas/detalhe.html', grupo=grupo, contas=contas)


# ─── Conta: nova / editar / excluir ─────────────────────────────────────────

@bp.route('/<int:grupo_id>/contas/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_conta(grupo_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (grupo_id,))
    grupo = cursor.fetchone()
    cursor.close()
    conn.close()

    if not grupo:
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    if request.method == 'POST':
        codigo    = request.form.get('codigo', '').strip()
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None
        acao      = request.form.get('acao', 'salvar')

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)

        if not _validar_codigo_conta(codigo):
            flash('Código inválido — use apenas dígitos e ponto (ex.: 1121 ou 1122.1).', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if _codigo_conta_duplicado(cursor, grupo_id, codigo):
                flash(f'Já existe uma conta com o código {codigo!r} neste grupo.', 'danger')
                return render_template('plano_contas/conta_form.html',
                                       grupo=grupo, conta=None, form=request.form)

            cursor.execute(
                "INSERT INTO plano_contas_contas (grupo_id, codigo, nome, descricao) VALUES (%s, %s, %s, %s)",
                (grupo_id, codigo, nome, descricao),
            )
            conn.commit()
            flash('Conta criada com sucesso!', 'success')
            if acao == 'proxima':
                return redirect(url_for('plano_contas.nova_conta', grupo_id=grupo_id))
            return redirect(url_for('plano_contas.detalhe', id=grupo_id))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar conta: {e}', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/conta_form.html',
                           grupo=grupo, conta=None, form={})


@bp.route('/contas/<int:conta_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_conta(conta_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT c.*, g.nome AS grupo_nome, g.codigo AS grupo_codigo
           FROM plano_contas_contas c
           JOIN plano_contas_grupos g ON g.id = c.grupo_id
           WHERE c.id = %s""",
        (conta_id,),
    )
    conta = cursor.fetchone()
    cursor.close()
    conn.close()

    if not conta:
        flash('Conta não encontrada.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    grupo = {'id': conta['grupo_id'], 'nome': conta['grupo_nome'],
             'codigo': conta['grupo_codigo']}

    if request.method == 'POST':
        codigo    = request.form.get('codigo', '').strip()
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None
        ativo     = 1 if request.form.get('ativo') else 0

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=conta, form=request.form)

        if not _validar_codigo_conta(codigo):
            flash('Código inválido — use apenas dígitos e ponto (ex.: 1121 ou 1122.1).', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=conta, form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if _codigo_conta_duplicado(cursor, conta['grupo_id'], codigo, excluir_id=conta_id):
                flash(f'Já existe outra conta com o código {codigo!r} neste grupo.', 'danger')
                return render_template('plano_contas/conta_form.html',
                                       grupo=grupo, conta=conta, form=request.form)

            cursor.execute(
                """UPDATE plano_contas_contas
                   SET codigo=%s, nome=%s, descricao=%s, ativo=%s
                   WHERE id=%s""",
                (codigo, nome, descricao, ativo, conta_id),
            )
            conn.commit()
            flash('Conta atualizada com sucesso!', 'success')
            return redirect(url_for('plano_contas.detalhe', id=conta['grupo_id']))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar conta: {e}', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=conta, form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/conta_form.html',
                           grupo=grupo, conta=conta, form=conta)


@bp.route('/contas/<int:conta_id>/excluir', methods=['POST'])
@login_required
@admin_required
def excluir_conta(conta_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT grupo_id FROM plano_contas_contas WHERE id = %s", (conta_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        flash('Conta não encontrada.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    grupo_id = row['grupo_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM plano_contas_contas WHERE id = %s", (conta_id,))
        conn.commit()
        flash('Conta excluída com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir conta: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('plano_contas.detalhe', id=grupo_id))


# ─── Grupo: vincular clientes / empresas ─────────────────────────────────────

@bp.route('/clientes/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def vincular_clientes(id):
    """Tela para vincular/desvincular clientes a um grupo contábil."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
    grupo = cursor.fetchone()
    if not grupo:
        cursor.close()
        conn.close()
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    if request.method == 'POST':
        # ids de clientes que devem pertencer ao grupo (checkbox multi)
        ids_selecionados = set(request.form.getlist('cliente_ids'))

        # Busca todos os clientes
        cursor.execute("SELECT id FROM clientes")
        todos = cursor.fetchall()

        cur2 = conn.cursor()
        for c in todos:
            cid = str(c['id'])
            if cid in ids_selecionados:
                cur2.execute(
                    "UPDATE clientes SET grupo_contabil_id = %s WHERE id = %s",
                    (id, c['id']),
                )
            else:
                # Só remove se o cliente pertencia a ESTE grupo
                cur2.execute(
                    "UPDATE clientes SET grupo_contabil_id = NULL WHERE id = %s AND grupo_contabil_id = %s",
                    (c['id'], id),
                )
        conn.commit()
        cur2.close()
        cursor.close()
        conn.close()
        flash('Empresas vinculadas com sucesso!', 'success')
        return redirect(url_for('plano_contas.lista'))

    # GET: lista todos os clientes marcando os já vinculados
    cursor.execute(
        """SELECT id, razao_social, nome_fantasia, grupo_contabil_id
           FROM clientes ORDER BY razao_social""",
    )
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('plano_contas/vincular_clientes.html',
                           grupo=grupo, clientes=clientes)

