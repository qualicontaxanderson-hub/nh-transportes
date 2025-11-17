from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

# ROTA CADASTRO: /fretes/novo
@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fretes (
                    clientes_id, fornecedores_id, motoristas_id, veiculos_id,
                    quantidade_id, origem_id, destino_id,
                    preco_produto_unitario, total_nf_compra,
                    preco_por_litro, valor_total_frete, comissao_motorista,
                    valor_cte, comissao_cte, lucro,
                    data_frete, status, observacoes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form['clientes_id'],
                request.form['fornecedores_id'],
                request.form['motoristas_id'],
                request.form['veiculos_id'],
                request.form['quantidade_id'],
                request.form['origem_id'],
                request.form['destino_id'],
                request.form['preco_produto_unitario'],
                request.form['total_nf_compra'],
                request.form['preco_por_litro'],
                request.form['valor_total_frete'],
                request.form['comissao_motorista'],
                request.form['valor_cte'],
                request.form['comissao_cte'],
                request.form['lucro'],
                request.form['data_frete'],
                request.form['status'],
                request.form.get('observacoes', '')
            ))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Frete cadastrado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))

        except Exception as e:
            print(f"Erro ao cadastrar frete: {e}")
            flash(f'Erro ao cadastrar frete: {str(e)}', 'danger')
            return redirect(url_for('fretes.novo'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, razao_social, paga_comissao FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()
        cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()
        cursor.execute("SELECT id, placa, modelo FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()
        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()
        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()
        cursor.close()
        conn.close()

        return render_template('fretes/novo.html',
                               clientes=clientes,
                               fornecedores=fornecedores,
                               motoristas=motoristas,
                               veiculos=veiculos,
                               quantidades=quantidades,
                               origens=origens,
                               destinos=destinos)

    except Exception as e:
        print(f"Erro ao carregar formulário: {e}")
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('index'))

# ROTA LISTA: /fretes/lista
@bp.route('/lista')
@login_required
def lista():
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT f.*, c.razao_social as cliente_nome, fo.razao_social as fornecedor_nome, m.nome as motorista_nome, v.placa as veiculo_placa, q.valor as quantidade_valor, o.nome as origem_nome, d.nome as destino_nome \
            FROM fretes f \
            LEFT JOIN clientes c ON f.clientes_id = c.id \
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id \
            LEFT JOIN motoristas m ON f.motoristas_id = m.id \
            LEFT JOIN veiculos v ON f.veiculos_id = v.id \
            LEFT JOIN quantidades q ON f.quantidade_id = q.id \
            LEFT JOIN origens o ON f.origem_id = o.id \
            LEFT JOIN destinos d ON f.destino_id = d.id \
            ORDER BY f.id DESC")
        fretes = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('fretes/lista.html', fretes=fretes)
    except Exception as e:
        print(f"Erro ao carregar lista de fretes: {e}")
        flash(f"Erro ao carregar lista de fretes: {str(e)}", 'danger')
        return redirect(url_for('index'))
