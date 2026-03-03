import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('plano_contas', __name__, url_prefix='/plano-contas')

# Flag per-process: CREATE TABLE IF NOT EXISTS é idempotente; o flag apenas
# evita a query DDL extra em cada request após a primeira execução bem-sucedida.
_tables_ready = False


def _ensure_tables():
    """Garante que plano_contas_contas existe — idempotente, seguro de chamar sempre."""
    global _tables_ready
    if _tables_ready:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
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
        logging.getLogger(__name__).exception('_ensure_tables: falha ao criar plano_contas_contas')
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
        codigo    = request.form.get('codigo', '').strip()
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=None,
                                   form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
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
        codigo    = request.form.get('codigo', '').strip()
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None
        ativo     = 1 if request.form.get('ativo') else 0

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=grupo,
                                   form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """UPDATE plano_contas_grupos
                   SET codigo=%s, nome=%s, descricao=%s, ativo=%s
                   WHERE id=%s""",
                (codigo, nome, descricao, ativo, id),
            )
            conn.commit()
            flash('Grupo atualizado com sucesso!', 'success')
            return redirect(url_for('plano_contas.lista'))
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

        novo_codigo = grupo['codigo'] + '_copia'
        novo_nome   = grupo['nome'] + ' (cópia)'

        # Garante código único com uma única query
        base_codigo = novo_codigo
        cur2 = conn.cursor(dictionary=True)
        cur2.execute(
            "SELECT codigo FROM plano_contas_grupos WHERE codigo LIKE %s",
            (base_codigo + '%',),
        )
        codigos_existentes = {row['codigo'] for row in cur2.fetchall()}
        cur2.close()

        sufixo = 1
        while novo_codigo in codigos_existentes:
            sufixo += 1
            novo_codigo = f"{base_codigo}{sufixo}"

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
        flash(f'Grupo clonado com sucesso! Novo código: {novo_codigo}', 'success')
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

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO plano_contas_contas (grupo_id, codigo, nome, descricao) VALUES (%s, %s, %s, %s)",
                (grupo_id, codigo, nome, descricao),
            )
            conn.commit()
            flash('Conta criada com sucesso!', 'success')
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

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
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

