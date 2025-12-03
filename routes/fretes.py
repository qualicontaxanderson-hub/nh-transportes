from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

# Blueprint
bp = Blueprint('fretes', __name__, url_prefix='/fretes')


@bp.route('/', methods=['GET'])
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT f.id,
                   f.data_frete,
                   f.status,
                   f.valor_total_frete,
                   f.lucro,
                   c.razao_social AS cliente,
                   fo.razao_social AS fornecedor,
                   m.nome AS motorista,
                   v.caminhao AS veiculo
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            ORDER BY f.data_frete DESC, f.id DESC
            LIMIT 200
        """)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('fretes/lista.html', fretes=fretes)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO fretes (
                    data_frete, status, observacoes,
                    clientes_id, fornecedores_id, produto_id,
                    origem_id, destino_id,
                    motoristas_id, veiculos_id,
                    quantidade_id, quantidade_manual,
                    preco_produto_unitario, preco_por_litro,
                    total_nf_compra, valor_total_frete,
                    comissao_motorista, valor_cte, comissao_cte, lucro
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                request.form.get('data_frete'),
                request.form.get('status'),
                request.form.get('observacoes'),
                request.form.get('clientes_id'),
                request.form.get('fornecedores_id'),
                request.form.get('produto_id'),
                request.form.get('origem_id'),
                request.form.get('destino_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                request.form.get('quantidade_id') or None,
                request.form.get('quantidade_manual') or None,
                request.form.get('preco_produto_unitario_raw') or 0,
                request.form.get('preco_por_litro') or 0,
                request.form.get('total_nf_compra') or 0,
                request.form.get('valor_total_frete') or 0,
                request.form.get('comissao_motorista') or 0,
                request.form.get('valor_cte') or 0,
                request.form.get('comissao_cte') or 0,
                request.form.get('lucro') or 0,
            ))
            conn.commit()
            flash('Frete criado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar frete: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    # GET: carregar dados para o formulário
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()

    cursor.execute("SELECT * FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()

    cursor.execute("SELECT * FROM produtos ORDER BY nome")
    produtos = cursor.fetchall()

    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()

    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()

    cursor.execute("SELECT * FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()

    cursor.execute("SELECT * FROM veiculos ORDER BY caminhao")
    veiculos = cursor.fetchall()

    cursor.execute("SELECT * FROM quantidades ORDER BY valor")
    quantidades = cursor.fetchall()

    rotas_dict = {}  # pode preencher depois com suas rotas

    cursor.close()
    conn.close()

    return render_template(
        'fretes/novo.html',
        frete=None,
        clientes=clientes,
        fornecedores=fornecedores,
        produtos=produtos,
        origens=origens,
        destinos=destinos,
        motoristas=motoristas,
        veiculos=veiculos,
        quantidades=quantidades,
        rotas_dict=rotas_dict,
    )


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        try:
            cursor.execute("""
                UPDATE fretes SET
                    data_frete=%s,
                    status=%s,
                    observacoes=%s,
                    clientes_id=%s,
                    fornecedores_id=%s,
                    produto_id=%s,
                    origem_id=%s,
                    destino_id=%s,
                    motoristas_id=%s,
                    veiculos_id=%s,
                    quantidade_id=%s,
                    quantidade_manual=%s,
                    preco_produto_unitario=%s,
                    preco_por_litro=%s,
                    total_nf_compra=%s,
                    valor_total_frete=%s,
                    comissao_motorista=%s,
                    valor_cte=%s,
                    comissao_cte=%s,
                    lucro=%s
                WHERE id=%s
            """, (
                request.form.get('data_frete'),
                request.form.get('status'),
                request.form.get('observacoes'),
                request.form.get('clientes_id'),
                request.form.get('fornecedores_id'),
                request.form.get('produto_id'),
                request.form.get('origem_id'),
                request.form.get('destino_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                request.form.get('quantidade_id') or None,
                request.form.get('quantidade_manual') or None,
                request.form.get('preco_produto_unitario_raw') or 0,
                request.form.get('preco_por_litro') or 0,
                request.form.get('total_nf_compra') or 0,
                request.form.get('valor_total_frete') or 0,
                request.form.get('comissao_motorista') or 0,
                request.form.get('valor_cte') or 0,
                request.form.get('comissao_cte') or 0,
                request.form.get('lucro') or 0,
                id,
            ))
            conn.commit()
            flash('Frete atualizado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar frete: {e}', 'danger')
            return redirect(url_for('fretes.editar', id=id))
        finally:
            cursor.close()
            conn.close()

    # GET: carregar frete + dados de apoio
    try:
        cursor.execute("SELECT * FROM fretes WHERE id = %s", (id,))
        frete = cursor.fetchone()

        cursor.execute("SELECT * FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

        cursor.execute("SELECT * FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()

        cursor.execute("SELECT * FROM produtos ORDER BY nome")
        produtos = cursor.fetchall()

        cursor.execute("SELECT * FROM origens ORDER BY nome")
        origens = cursor.fetchall()

        cursor.execute("SELECT * FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()

        cursor.execute("SELECT * FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()

        cursor.execute("SELECT * FROM veiculos ORDER BY caminhao")
        veiculos = cursor.fetchall()

        cursor.execute("SELECT * FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    rotas_dict = {}

    return render_template(
        'fretes/novo.html',
        frete=frete,
        clientes=clientes,
        fornecedores=fornecedores,
        produtos=produtos,
        origens=origens,
        destinos=destinos,
        motoristas=motoristas,
        veiculos=veiculos,
        quantidades=quantidades,
        rotas_dict=rotas_dict,
    )


@bp.route('/deletar/<int:id>', methods=['POST'])
@login_required
def deletar(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM fretes WHERE id = %s", (id,))
        conn.commit()
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir frete: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('fretes.lista'))
