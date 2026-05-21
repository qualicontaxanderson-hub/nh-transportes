from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required
from urllib.parse import quote

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


def _str_or_dash(value):
    texto = (str(value).strip() if value is not None else '')
    return texto if texto else '—'


def _montar_endereco_completo(cliente):
    partes = []
    linha_principal = ' '.join([
        p for p in [
            (cliente.get('endereco') or '').strip(),
            (cliente.get('numero') or '').strip()
        ] if p
    ]).strip()
    if linha_principal:
        partes.append(linha_principal)
    if cliente.get('complemento'):
        partes.append(str(cliente['complemento']).strip())
    if cliente.get('bairro'):
        partes.append(str(cliente['bairro']).strip())

    cidade_uf = _cidade_uf(cliente)
    if cidade_uf:
        partes.append(cidade_uf)
    if cliente.get('cep'):
        partes.append(f"CEP {str(cliente['cep']).strip()}")
    return ', '.join([p for p in partes if p]).strip() or '—'


def _montar_endereco_waze(cliente):
    partes = []
    if cliente.get('razao_social'):
        partes.append(str(cliente['razao_social']).strip())
    if cliente.get('endereco'):
        linha_principal = ' '.join([
            p for p in [
                str(cliente['endereco']).strip(),
                str(cliente.get('numero') or '').strip()
            ] if p
        ]).strip()
        if linha_principal:
            partes.append(linha_principal)
    if cliente.get('bairro'):
        partes.append(str(cliente['bairro']).strip())

    cidade = (cliente.get('municipio') or cliente.get('destino_cidade') or '').strip()
    uf = (cliente.get('uf') or cliente.get('destino_estado') or '').strip()
    cidade_estado = ' '.join([p for p in [cidade, uf] if p]).strip()
    if cidade_estado:
        partes.append(cidade_estado)
    if cliente.get('cep'):
        partes.append(str(cliente['cep']).strip())

    consulta = ', '.join([p for p in partes if p]).strip()
    return consulta or _str_or_dash(cliente.get('razao_social'))


def _montar_link_waze(cliente):
    consulta = _montar_endereco_waze(cliente)
    if consulta == '—':
        return 'Endereço não disponível para Waze.'
    return f"https://www.waze.com/ul?q={quote(consulta)}&navigate=yes"


def _montar_mensagem_whatsapp(cliente):
    cidade_uf = _cidade_uf(cliente) or '—'
    endereco = _montar_endereco_completo(cliente)
    link_waze = _montar_link_waze(cliente)
    return '\n'.join([
        "🚛 *DADOS DO CLIENTE*",
        "",
        f"📍 *CIDADE/UF: {cidade_uf}*",
        "",
        f"*Razão Social:* {_str_or_dash(cliente.get('razao_social'))}",
        f"*Nome Fantasia:* {_str_or_dash(cliente.get('nome_fantasia'))}",
        f"*CNPJ:* {_str_or_dash(cliente.get('cnpj'))}",
        f"*Endereço:* {endereco}",
        "",
        "🧭 *Localização no Waze:*",
        link_waze,
    ])


def _cidade_uf(cliente):
    cidade = (cliente.get('municipio') or cliente.get('destino_cidade') or '').strip()
    uf = (cliente.get('uf') or cliente.get('destino_estado') or '').strip()
    return ' / '.join([p for p in [cidade, uf] if p]).strip()


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
    conn = None
    cursor = None
    try:
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
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('clientes.lista'))

        # GET: carregar destinos (municípios) e grupos contábeis
        cursor.execute("""
            SELECT id, nome, cidade, estado
            FROM destinos
            ORDER BY nome
        """)
        destinos = cursor.fetchall()
        grupos = _get_grupos_contabeis(cursor)
        return render_template('clientes/novo.html', destinos=destinos, grupos=grupos)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar cliente: {str(e)}', 'danger')
        return redirect(url_for('clientes.lista'))
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
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('clientes.lista'))

        # GET: buscar cliente
        cursor.execute("SELECT * FROM clientes WHERE id = %s", (id,))
        cliente = cursor.fetchone()

        # GET: buscar destinos (municípios) e grupos contábeis
        cursor.execute("SELECT id, nome, cidade, estado FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()
        grupos = _get_grupos_contabeis(cursor)
        return render_template('clientes/editar.html', cliente=cliente,
                               destinos=destinos, grupos=grupos)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar cliente: {str(e)}', 'danger')
        return redirect(url_for('clientes.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))

        conn.commit()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir cliente: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('clientes.lista'))


@bp.route('/mensagem-whatsapp/<int:id>')
@login_required
def mensagem_whatsapp(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.*,
                   d.cidade AS destino_cidade,
                   d.estado AS destino_estado
            FROM clientes c
            LEFT JOIN destinos d ON d.id = c.destino_id
            WHERE c.id = %s
            LIMIT 1
        """, (id,))
        cliente = cursor.fetchone()
        if not cliente:
            return jsonify({'ok': False, 'error': 'Cliente não encontrado.'}), 404
        return jsonify({'ok': True, 'mensagem': _montar_mensagem_whatsapp(cliente)})
    except Exception as e:
        current_app.logger.exception('Erro ao montar mensagem de WhatsApp do cliente id=%s', id)
        return jsonify({'ok': False, 'error': 'Erro interno ao gerar mensagem.'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
