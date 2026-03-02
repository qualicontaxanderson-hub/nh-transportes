from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('plano_contas', __name__, url_prefix='/plano-contas')


def _get_grupos(cursor):
    cursor.execute(
        """SELECT g.id, g.codigo, g.nome, g.descricao, g.ativo,
                  COUNT(c.id) AS total_clientes
           FROM plano_contas_grupos g
           LEFT JOIN clientes c ON c.grupo_contabil_id = g.id
           GROUP BY g.id
           ORDER BY g.codigo"""
    )
    return cursor.fetchall()


@bp.route('/')
@login_required
@admin_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    grupos = _get_grupos(cursor)
    cursor.close()
    conn.close()
    return render_template('plano_contas/lista.html', grupos=grupos)


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
            flash('Grupo contábil criado com sucesso!', 'success')
            return redirect(url_for('plano_contas.lista'))
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
        flash('Clientes vinculados com sucesso!', 'success')
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
