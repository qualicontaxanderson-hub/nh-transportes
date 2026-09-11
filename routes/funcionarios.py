from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('funcionarios', __name__, url_prefix='/funcionarios')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Desligado NAO e o mesmo que apagado. Quem saiu continua no cadastro —
    # com a data da saida — porque os lancamentos dele seguem valendo nos meses
    # em que trabalhou. O que a saida faz e tirar a pessoa das listas de
    # ESCOLHA dali em diante.
    cursor.execute("""
        SELECT f.*,
               c.razao_social AS posto_nome
          FROM funcionarios f
          LEFT JOIN clientes c ON c.id = COALESCE(f.id_cliente, f.clienteid)
         WHERE f.ativo = 1
         ORDER BY (f.data_saida IS NOT NULL), f.nome
    """)
    funcionarios = cursor.fetchall()

    hoje = date.today()
    totais = {
        'todos': len(funcionarios),
        'trabalhando': sum(1 for f in funcionarios if not f.get('data_saida')),
        'desligados': sum(1 for f in funcionarios if f.get('data_saida')),
    }
    cursor.close()
    conn.close()
    return render_template('funcionarios/lista.html', funcionarios=funcionarios,
                           totais=totais, hoje=hoje)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                INSERT INTO funcionarios (
                    nome, id_cliente, tipo, cpf, telefone, email, 
                    cargo, data_admissao, salario_base, categoria, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('nome'),
                request.form.get('clienteid') or None,
                'FUNCIONARIO',
                request.form.get('cpf'),
                request.form.get('telefone'),
                request.form.get('email'),
                request.form.get('cargo'),
                request.form.get('data_admissao') or None,
                request.form.get('salario_base') or None,
                request.form.get('categoria'),
                1
            ))
            conn.commit()
            flash('Funcionário cadastrado com sucesso!', 'success')
            return redirect(url_for('funcionarios.lista'))

        # Get categories for dropdown
        cursor.execute("SELECT * FROM categoriasfuncionarios WHERE ativo = 1 ORDER BY nome")
        categorias = cursor.fetchall()
        # Only show clients that have products configured (cliente_produtos)
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social as nome 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        return render_template('funcionarios/novo.html', categorias=categorias, clientes=clientes)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar funcionário: {str(e)}', 'danger')
        return redirect(url_for('funcionarios.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                UPDATE funcionarios SET
                    nome=%s, id_cliente=%s, categoria=%s, cpf=%s, telefone=%s,
                    email=%s, cargo=%s, data_admissao=%s, salario_base=%s,
                    data_saida=%s
                WHERE id=%s
            """, (
                request.form.get('nome'),
                request.form.get('clienteid') or None,
                request.form.get('categoria'),
                request.form.get('cpf'),
                request.form.get('telefone'),
                request.form.get('email'),
                request.form.get('cargo'),
                request.form.get('data_admissao') or None,
                request.form.get('salario_base') or None,
                request.form.get('data_saida') or None,
                id
            ))
            conn.commit()
            flash('Funcionário atualizado com sucesso!', 'success')
            return redirect(url_for('funcionarios.lista'))

        cursor.execute("SELECT * FROM funcionarios WHERE id = %s", (id,))
        funcionario = cursor.fetchone()
        cursor.execute("SELECT * FROM categoriasfuncionarios WHERE ativo = 1 ORDER BY nome")
        categorias = cursor.fetchall()
        # Only show clients that have products configured (cliente_produtos)
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social as nome 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        return render_template('funcionarios/editar.html', funcionario=funcionario, categorias=categorias, clientes=clientes)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar funcionário: {str(e)}', 'danger')
        return redirect(url_for('funcionarios.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@bp.route('/desligar/<int:id>', methods=['POST'])
@login_required
@admin_required
def desligar(id):
    """Marca a data em que a pessoa deixou a casa.

    Nao apaga nem esconde nada do que ja aconteceu: os lancamentos dos meses em
    que ela trabalhou continuam iguais, e ela continua aparecendo nos
    relatorios desses meses. O que a data faz e tirar a pessoa das listas de
    ESCOLHA a partir dali — o troco PIX de amanha nao oferece mais quem saiu, e
    a folha de 08/2026 nao oferece mais quem saiu em 07/2026.
    """
    data = (request.form.get('data_saida') or '').strip()
    if not data:
        flash('Informe a data em que a pessoa foi desligada.', 'warning')
        return redirect(url_for('funcionarios.lista'))
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT nome, data_admissao FROM funcionarios WHERE id = %s",
                       (id,))
        f = cursor.fetchone()
        if not f:
            flash('Funcionário não encontrado.', 'danger')
            return redirect(url_for('funcionarios.lista'))
        # Sair antes de entrar nao existe: seria um desligamento que apagaria a
        # pessoa de meses em que ela de fato trabalhou.
        if f.get('data_admissao') and str(data) < str(f['data_admissao']):
            flash('A data de saída é anterior à de admissão (%s).'
                  % f['data_admissao'].strftime('%d/%m/%Y'), 'warning')
            return redirect(url_for('funcionarios.editar', id=id))
        cursor.execute("UPDATE funcionarios SET data_saida = %s WHERE id = %s",
                       (data, id))
        conn.commit()
        flash('%s foi desligado em %s. Os lançamentos dos meses trabalhados '
              'continuam como estão.'
              % (f['nome'], '/'.join(reversed(data.split('-')))), 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash('Erro ao desligar: %s' % e, 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('funcionarios.lista'))


@bp.route('/readmitir/<int:id>', methods=['POST'])
@login_required
@admin_required
def readmitir(id):
    """Tira a data de saida — para quando a pessoa volta, ou a data foi errada."""
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT nome FROM funcionarios WHERE id = %s", (id,))
        f = cursor.fetchone()
        cursor.execute("UPDATE funcionarios SET data_saida = NULL WHERE id = %s",
                       (id,))
        conn.commit()
        flash('%s voltou para a lista de quem está trabalhando.'
              % ((f or {}).get('nome') or 'Funcionário'), 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash('Erro ao readmitir: %s' % e, 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('funcionarios.lista'))


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Soft delete
        cursor.execute("UPDATE funcionarios SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()
        flash('Funcionário desativado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar funcionário: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('funcionarios.lista'))

@bp.route('/vincular-veiculo/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def vincular_veiculo(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            cursor.execute("""
                INSERT INTO funcionariomotoristaveiculos (
                    funcionarioid, veiculoid, datainicio, datafim, principal, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                id,
                request.form.get('veiculoid'),
                request.form.get('datainicio'),
                request.form.get('datafim') or None,
                1 if request.form.get('principal') == '1' else 0,
                1
            ))
            conn.commit()
            flash('Veículo vinculado com sucesso!', 'success')
            return redirect(url_for('funcionarios.editar', id=id))

        cursor.execute("SELECT * FROM funcionarios WHERE id = %s", (id,))
        funcionario = cursor.fetchone()
        cursor.execute("SELECT * FROM veiculos WHERE ativo = 1 ORDER BY caminhao")
        veiculos = cursor.fetchall()
        return render_template('funcionarios/vincular_veiculo.html', funcionario=funcionario, veiculos=veiculos)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao vincular veículo: {str(e)}', 'danger')
        return redirect(url_for('funcionarios.editar', id=id))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
