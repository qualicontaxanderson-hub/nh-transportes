from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    # pedido que originou o frete (se vier da tela de Pedido)
    pedido_id = request.args.get('pedido_id', type=int)

    if request.method == 'POST':
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            def converter_para_decimal(valor):
                if not valor:
                    return 0
                return float(str(valor).replace('.', '').replace(',', '.'))

            quantidade_tipo = request.form.get('quantidade_tipo')
            if quantidade_tipo == 'personalizada':
                quantidade_id_para_salvar = None
            else:
                quantidade_id_para_salvar = request.form.get('quantidade_id')

            preco_produto_unitario = converter_para_decimal(request.form.get('preco_produto_unitario'))
            total_nf_compra = converter_para_decimal(request.form.get('total_nf_compra'))
            preco_por_litro = converter_para_decimal(request.form.get('preco_por_litro'))
            valor_total_frete = converter_para_decimal(request.form.get('valor_total_frete'))
            comissao_motorista = converter_para_decimal(request.form.get('comissao_motorista'))
            valor_cte = converter_para_decimal(request.form.get('valor_cte'))
            comissao_cte = converter_para_decimal(request.form.get('comissao_cte'))
            lucro = converter_para_decimal(request.form.get('lucro'))

            cursor.execute(
                """
                INSERT INTO fretes (
                    clientes_id, produto_id, fornecedores_id, motoristas_id, veiculos_id,
                    quantidade_id, origem_id, destino_id,
                    preco_produto_unitario, total_nf_compra, preco_por_litro,
                    valor_total_frete, comissao_motorista, valor_cte, comissao_cte, lucro,
                    data_frete, status, observacoes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    request.form.get('clientes_id'),
                    request.form.get('produto_id'),
                    request.form.get('fornecedores_id'),
                    request.form.get('motoristas_id'),
                    request.form.get('veiculos_id'),
                    quantidade_id_para_salvar,
                    request.form.get('origem_id'),
                    request.form.get('destino_id'),
                    preco_produto_unitario,
                    total_nf_compra,
                    preco_por_litro,
                    valor_total_frete,
                    comissao_motorista,
                    valor_cte,
                    comissao_cte,
                    lucro,
                    request.form.get('data_frete'),
                    request.form.get('status'),
                    request.form.get('observacoes')
                )
            )

            # NOVO: se o frete veio de um pedido, marcar o pedido como Faturado
            pedido_id_form = request.form.get('pedido_id')
            if pedido_id_form:
                cursor.execute(
                    "UPDATE pedidos SET status = 'Faturado' WHERE id = %s",
                    (pedido_id_form,)
                )

            conn.commit()
            cursor.close()
            conn.close()
            flash('Frete cadastrado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))

        except Exception as e:
            print(f'Erro ao cadastrar frete: {e}')
            flash(f'Erro ao cadastrar frete: {str(e)}', 'danger')
            return redirect(url_for('fretes.novo'))

    # GET - carregar formulário
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, razao_social, paga_comissao, percentual_cte, cte_integral
            FROM clientes 
            ORDER BY razao_social
            """
        )
        clientes = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, nome 
            FROM produto 
            ORDER BY nome
            """
        )
        produtos = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, razao_social 
            FROM fornecedores 
            ORDER BY razao_social
            """
        )
        fornecedores = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, nome, paga_comissao 
            FROM motoristas 
            ORDER BY nome
            """
        )
        motoristas = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, caminhao, placa 
            FROM veiculos 
            ORDER BY placa
            """
        )
        veiculos = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, valor, descricao 
            FROM quantidades 
            ORDER BY valor
            """
        )
        quantidades = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, nome 
            FROM origens 
            ORDER BY nome
            """
        )
        origens = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, nome 
            FROM destinos 
            ORDER BY nome
            """
        )
        destinos = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, origem_id, destino_id, valor_por_litro 
            FROM rotas 
            WHERE ativo = 1
            """
        )
        rotas = cursor.fetchall()

        rotas_dict = {}
        for rota in rotas:
            chave = f"{rota['origem_id']}_{rota['destino_id']}"
            rotas_dict[chave] = rota['valor_por_litro']

        # Buscar pedidos para importação
        cursor.execute(
            """
            SELECT p.id, p.numero, p.data_pedido, p.status, p.motorista_id, m.nome as motorista_nome
            FROM pedidos p
            LEFT JOIN motoristas m ON p.motorista_id = m.id
            WHERE p.status IN ('Pendente', 'Confirmado')
            ORDER BY p.data_pedido DESC
            """
        )
        pedidos = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template(
            'fretes/novo.html',
            clientes=clientes,
            produtos=produtos,
            fornecedores=fornecedores,
            motoristas=motoristas,
            veiculos=veiculos,
            quantidades=quantidades,
            origens=origens,
            destinos=destinos,
            rotas=rotas,
            rotas_dict=rotas_dict,
            pedidos=pedidos,
            pedido_selecionado_id=pedido_id
        )
    except Exception as e:
        print(f'Erro ao carregar formulário: {e}')
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('index'))

@bp.route('/lista')
@login_required
def lista():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        cliente_id = request.args.get('cliente_id')
        base_sql = """
            SELECT f.*, 
                   c.razao_social AS cliente_nome, 
                   fo.razao_social AS fornecedor_nome, 
                   m.nome AS motorista_nome, 
                   v.placa AS veiculo_placa, 
                   q.valor AS quantidade_valor, 
                   o.nome AS origem_nome, 
                   d.nome AS destino_nome,
                   p.nome AS produto_nome
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            LEFT JOIN produto p ON f.produto_id = p.id
        """
        filtros = []
        parametros = []
        if data_inicio:
            filtros.append("f.data_frete >= %s")
            parametros.append(data_inicio)
        if data_fim:
            filtros.append("f.data_frete <= %s")
            parametros.append(data_fim)
        if cliente_id:
            filtros.append("f.clientes_id = %s")
            parametros.append(cliente_id)
        if filtros:
            base_sql += " WHERE " + " AND ".join(filtros)
        base_sql += " ORDER BY f.data_frete DESC, f.id DESC"
        cursor.execute(base_sql, tuple(parametros))
        fretes = cursor.fetchall()

        sql_clientes = """
            SELECT c.id, c.razao_social, COUNT(f.id) AS qtd_fretes
            FROM fretes f
            JOIN clientes c ON f.clientes_id = c.id
        """
        if filtros:
            sql_clientes += " WHERE " + " AND ".join(filtros)
        sql_clientes += " GROUP BY c.id, c.razao_social ORDER BY c.razao_social"
        cursor.execute(sql_clientes, tuple(parametros))
        clientes_atendidos = cursor.fetchall()

        sql_caminhao = """
            SELECT v.id, v.placa, SUM(q.valor) AS total_quantidade
            FROM fretes f
            JOIN veiculos v ON f.veiculos_id = v.id
            JOIN quantidades q ON f.quantidade_id = q.id
        """
        if filtros:
            sql_caminhao += " WHERE " + " AND ".join(filtros)
        sql_caminhao += " GROUP BY v.id, v.placa ORDER BY v.placa"
        cursor.execute(sql_caminhao, tuple(parametros))
        quantidade_por_caminhao = cursor.fetchall()

        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        lista_clientes = cursor.fetchall()

        cursor.close()
        conn.close()
        return render_template(
            'fretes/lista.html',
            fretes=fretes,
            data_inicio=data_inicio,
            data_fim=data_fim,
            cliente_id=cliente_id,
            clientes_atendidos=clientes_atendidos,
            quantidade_por_caminhao=quantidade_por_caminhao,
            lista_clientes=lista_clientes
        )
    except Exception as e:
        print(f'Erro ao carregar lista de fretes: {e}')
        flash(f'Erro ao carregar lista de fretes: {str(e)}', 'danger')
        return redirect(url_for('index'))

@bp.route('/deletar/<int:id>', methods=['POST', 'GET'])
@login_required
def deletar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fretes WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir frete: {str(e)}', 'danger')
    return redirect(url_for('fretes.lista'))

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            origem_id = request.form.get('origem_id')
            destino_id = request.form.get('destino_id')
            if not destino_id or destino_id == '':
                flash('ERRO: Destino é obrigatório!', 'danger')
                return redirect(url_for('fretes.editar', id=id))
            def converter_para_decimal(valor):
                if not valor:
                    return 0
                return float(str(valor).replace('.', '').replace(',', '.'))
            quantidade_tipo = request.form.get('quantidade_tipo', 'padrao')
            if quantidade_tipo == 'personalizada':
                quantidade_id_para_salvar = None
            else:
                quantidade_id_para_salvar = request.form.get('quantidade_id')
            preco_produto_unitario = converter_para_decimal(request.form.get('preco_produto_unitario'))
            total_nf_compra = converter_para_decimal(request.form.get('total_nf_compra'))
            preco_por_litro = converter_para_decimal(request.form.get('preco_por_litro'))
            valor_total_frete = converter_para_decimal(request.form.get('valor_total_frete'))
            comissao_motorista = converter_para_decimal(request.form.get('comissao_motorista'))
            valor_cte = converter_para_decimal(request.form.get('valor_cte'))
            comissao_cte = converter_para_decimal(request.form.get('comissao_cte'))
            lucro = converter_para_decimal(request.form.get('lucro'))
            cursor.execute(
                """
                UPDATE fretes 
                SET clientes_id=%s, produto_id=%s, fornecedores_id=%s, motoristas_id=%s, veiculos_id=%s, 
                    quantidade_id=%s, origem_id=%s, destino_id=%s, preco_produto_unitario=%s, 
                    total_nf_compra=%s, preco_por_litro=%s, valor_total_frete=%s, 
                    comissao_motorista=%s, valor_cte=%s, comissao_cte=%s, lucro=%s, 
                    data_frete=%s, status=%s, observacoes=%s
                WHERE id=%s
                """,
                (
                    request.form.get('clientes_id'),
                    request.form.get('produto_id'),
                    request.form.get('fornecedores_id'),
                    request.form.get('motoristas_id'),
                    request.form.get('veiculos_id'),
                    quantidade_id_para_salvar,
                    origem_id if origem_id else None,
                    destino_id,
                    preco_produto_unitario,
                    total_nf_compra,
                    preco_por_litro,
                    valor_total_frete,
                    comissao_motorista,
                    valor_cte,
                    comissao_cte,
                    lucro,
                    request.form.get('data_frete'),
                    request.form.get('status'),
                    request.form.get('observacoes'),
                    id
                                    )
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash('Frete atualizado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        cursor.execute("SELECT * FROM fretes WHERE id = %s", (id,))
        frete = cursor.fetchone()
        cursor.execute(
            """
            SELECT id, razao_social, paga_comissao, percentual_cte, cte_integral
            FROM clientes 
            ORDER BY razao_social
            """
        )
        clientes = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, nome 
            FROM produto 
            ORDER BY nome
            """
        )
        produtos = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, razao_social 
            FROM fornecedores 
            ORDER BY razao_social
            """
        )
        fornecedores = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, nome, paga_comissao 
            FROM motoristas 
            ORDER BY nome
            """
        )
        motoristas = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, caminhao, placa 
            FROM veiculos 
            ORDER BY placa
            """
        )
        veiculos = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, valor, descricao 
            FROM quantidades 
            ORDER BY valor
            """
        )
        quantidades = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, nome 
            FROM origens 
            ORDER BY nome
            """
        )
        origens = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, nome 
            FROM destinos 
            ORDER BY nome
            """
        )
        destinos = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, origem_id, destino_id, valor_por_litro 
            FROM rotas 
            WHERE ativo = 1
            """
        )
        rotas = cursor.fetchall()
        rotas_dict = {}
        for rota in rotas:
            chave = f"{rota['origem_id']}_{rota['destino_id']}"
            rotas_dict[chave] = rota['valor_por_litro']
        cursor.close()
        conn.close()
        return render_template(
            'fretes/editar.html',
            frete=frete,
            clientes=clientes,
            produtos=produtos,
            fornecedores=fornecedores,
            motoristas=motoristas,
            veiculos=veiculos,
            quantidades=quantidades,
            origens=origens,
            destinos=destinos,
            rotas=rotas,
            rotas_dict=rotas_dict
        )
    except Exception as e:
        print(f'Erro ao editar frete: {e}')
        flash(f'Erro ao editar frete: {str(e)}', 'danger')
        return redirect(url_for('fretes.lista'))

