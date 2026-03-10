from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('clientes', __name__, url_prefix='/clientes')


def _get_grupos_contabeis(cursor):
    """Retorna os grupos contábeis ativos para uso nos formulários."""
    try:
        cursor.execute(
            "SELECT id, codigo, nome FROM plano_contas_grupos WHERE ativo = 1 ORDER BY codigo"
        )
        return cursor.fetchall()
    except Exception:
        return []


@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.*,
               d.nome AS destino_nome,
               d.estado AS destino_estado,
               g.codigo AS grupo_codigo,
               g.nome   AS grupo_nome
        FROM clientes c
        LEFT JOIN destinos d ON d.id = c.destino_id
        LEFT JOIN plano_contas_grupos g ON g.id = c.grupo_contabil_id
        ORDER BY c.razao_social
    """)
    clientes = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('clientes/lista.html', clientes=clientes)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()

        # Pegar valor dos checkboxes - aceita 'on' ou '1'
        paga_comissao_raw = request.form.get('paga_comissao')
        cte_integral_raw = request.form.get('cte_integral')

        paga_comissao = 1 if paga_comissao_raw in ['on', '1', 1, True] else 0
        cte_integral = 1 if cte_integral_raw in ['on', '1', 1, True] else 0

        # Pegar destino_id (município)
        destino_id_raw = request.form.get('destino_id')
        destino_id = int(destino_id_raw) if destino_id_raw else None

        # Pegar grupo contábil
        grupo_id_raw = request.form.get('grupo_contabil_id')
        grupo_contabil_id = int(grupo_id_raw) if grupo_id_raw else None

        cursor.execute("""
            INSERT INTO clientes (
                razao_social, nome_fantasia, cnpj, ie, contato,
                endereco, numero, complemento, bairro, municipio, uf, cep,
                telefone, email, paga_comissao, cte_integral, destino_id, grupo_contabil_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia') or None,
            request.form.get('cnpj') or None,
            request.form.get('ie') or None,
            request.form.get('contato') or None,
            request.form.get('endereco') or None,
            request.form.get('numero') or None,
            request.form.get('complemento') or None,
            request.form.get('bairro') or None,
            request.form.get('municipio') or None,
            request.form.get('uf') or None,
            request.form.get('cep') or None,
            request.form.get('telefone') or None,
            request.form.get('email') or None,
            paga_comissao,
            cte_integral,
            destino_id,
            grupo_contabil_id,
        ))

        conn.commit()
        cursor.close()
        conn.close()

        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('clientes.lista'))

    # GET: carregar destinos (municípios) e grupos contábeis
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, nome, cidade, estado
        FROM destinos
        ORDER BY nome
    """)
    destinos = cursor.fetchall()
    grupos = _get_grupos_contabeis(cursor)
    cursor.close()
    conn.close()

    return render_template('clientes/novo.html', destinos=destinos, grupos=grupos)


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        # Pegar valor dos checkboxes - aceita 'on' ou '1'
        paga_comissao_raw = request.form.get('paga_comissao')
        cte_integral_raw = request.form.get('cte_integral')

        paga_comissao = 1 if paga_comissao_raw in ['on', '1', 1, True] else 0
        cte_integral = 1 if cte_integral_raw in ['on', '1', 1, True] else 0

        # Pegar destino_id (município)
        destino_id_raw = request.form.get('destino_id')
        destino_id = int(destino_id_raw) if destino_id_raw else None

        # Pegar grupo contábil
        grupo_id_raw = request.form.get('grupo_contabil_id')
        grupo_contabil_id = int(grupo_id_raw) if grupo_id_raw else None

        cursor.execute("""
            UPDATE clientes SET razao_social=%s, nome_fantasia=%s, cnpj=%s, ie=%s, contato=%s,
                endereco=%s, numero=%s, complemento=%s, bairro=%s, municipio=%s, uf=%s, cep=%s,
                telefone=%s, email=%s, paga_comissao=%s, cte_integral=%s, destino_id=%s,
                grupo_contabil_id=%s
            WHERE id=%s
        """, (
            request.form.get('razao_social'),
            request.form.get('nome_fantasia') or None,
            request.form.get('cnpj') or None,
            request.form.get('ie') or None,
            request.form.get('contato') or None,
            request.form.get('endereco') or None,
            request.form.get('numero') or None,
            request.form.get('complemento') or None,
            request.form.get('bairro') or None,
            request.form.get('municipio') or None,
            request.form.get('uf') or None,
            request.form.get('cep') or None,
            request.form.get('telefone') or None,
            request.form.get('email') or None,
            paga_comissao,
            cte_integral,
            destino_id,
            grupo_contabil_id,
            id,
        ))

        conn.commit()
        cursor.close()
        conn.close()

        flash('Cliente atualizado com sucesso!', 'success')
        return redirect(url_for('clientes.lista'))

    # GET: buscar cliente
    cursor.execute("SELECT * FROM clientes WHERE id = %s", (id,))
    cliente = cursor.fetchone()

    # GET: buscar destinos (municípios) e grupos contábeis
    cursor.execute("SELECT id, nome, cidade, estado FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    grupos = _get_grupos_contabeis(cursor)
    cursor.close()
    conn.close()

    return render_template('clientes/editar.html', cliente=cliente,
                           destinos=destinos, grupos=grupos)


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))

        conn.commit()
        cursor.close()
        conn.close()

        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir cliente: {str(e)}', 'danger')

    return redirect(url_for('clientes.lista'))
