from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
import mysql.connector
from datetime import datetime, date

bp = Blueprint('pedidos', __name__, url_prefix='/pedidos')

def get_db():
    return mysql.connector.connect(
        host="centerbeam.proxy.rlwy.net",
        port=56026,
        user="root",
        password="CYTzzRYLVmEJGDexxXpgepWgpvebdSrV",
        database="railway"
    )

def gerar_numero_pedido():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT numero FROM pedidos ORDER BY id DESC LIMIT 1")
    ultimo = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if ultimo:
        num = int(ultimo['numero'].replace('PED-', '')) + 1
    else:
        num = 1
    return f"PED-{num:05d}"


@bp.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    status = request.args.get('status', '')
    
    sql = """
        SELECT p.*,
               m.nome as motorista_nome,
               v.caminhao as veiculo_nome,
               COUNT(pi.id) as total_itens,
               SUM(pi.quantidade) as total_quantidade,
               SUM(pi.total_nf) as total_valor
        FROM pedidos p
        LEFT JOIN motoristas m ON p.motorista_id = m.id
        LEFT JOIN veiculos v ON p.veiculo_id = v.id
        LEFT JOIN pedidos_itens pi ON p.id = pi.pedido_id
        WHERE 1=1
    """
    params = []
    
    if data_inicio and data_fim:
        sql += " AND p.data_pedido BETWEEN %s AND %s"
        params.extend([data_inicio, data_fim])
    
    if status:
        sql += " AND p.status = %s"
        params.append(status)
    
    sql += " GROUP BY p.id ORDER BY p.data_pedido DESC, p.id DESC"
    
    cursor.execute(sql, params)
    pedidos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template(
        'pedidos/index.html',
        pedidos=pedidos,
        filtros={'data_inicio': data_inicio, 'data_fim': data_fim, 'status': status}
    )


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        data_pedido = request.form['data_pedido']
        motorista_id = request.form.get('motorista_id') or None
        veiculo_id = request.form.get('veiculo_id') or None  # NOVO
        observacoes = request.form.get('observacoes', '')
        numero = gerar_numero_pedido()
        
        cursor.execute("""
            INSERT INTO pedidos (numero, data_pedido, motorista_id, veiculo_id, status, observacoes)
            VALUES (%s, %s, %s, %s, 'Pendente', %s)
        """, (numero, data_pedido, motorista_id, veiculo_id, observacoes))
        
        pedido_id = cursor.lastrowid
        
        # Processar itens
        clientes = request.form.getlist('cliente_id')
        produtos = request.form.getlist('produto_id')
        fornecedores = request.form.getlist('fornecedor_id')
        origens = request.form.getlist('origem_id')
        bases = request.form.getlist('base_id')
        quantidades = request.form.getlist('quantidade')
        quantidade_ids = request.form.getlist('quantidade_id')
        tipos_qtd = request.form.getlist('tipo_quantidade')
        precos = request.form.getlist('preco_unitario')
        totais_nf = request.form.getlist('total_nf')
        formas_pagto = request.form.getlist('forma_pagamento_fornecedor_item')
        pix_aleatorias = request.form.getlist('pix_aleatoria')
        dados_transf_itens = request.form.getlist('dados_transferencia_item')
        
        for i in range(len(clientes)):
            if clientes[i] and produtos[i] and fornecedores[i]:
                qtd_id = quantidade_ids[i] if quantidade_ids[i] else None
                qtd_valor = quantidades[i] if quantidades[i] else 0
                base_id = bases[i] if bases[i] else None
                forma_pagto = formas_pagto[i] if i < len(formas_pagto) else None
                pix_aleatoria = pix_aleatorias[i] if i < len(pix_aleatorias) else None
                dados_transf = dados_transf_itens[i] if i < len(dados_transf_itens) else None
                
                cursor.execute("""
                    INSERT INTO pedidos_itens (
                        pedido_id, cliente_id, produto_id, fornecedor_id, origem_id, base_id,
                        quantidade, quantidade_id, tipo_quantidade, forma_pagamento_fornecedor_item,
                        pix_aleatoria, dados_transferencia_item, preco_unitario, total_nf
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    pedido_id, clientes[i], produtos[i], fornecedores[i], origens[i], base_id,
                    qtd_valor, qtd_id, tipos_qtd[i], forma_pagto, pix_aleatoria, dados_transf,
                    precos[i], totais_nf[i]
                ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash(f'Pedido {numero} criado com sucesso!', 'success')
        return redirect(url_for('pedidos.visualizar', id=pedido_id))
    
    # GET - carregar dados para o formulário
    cursor.execute("SELECT id, razao_social, nome_fantasia, cnpj FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    
    cursor.execute("""
        SELECT id, razao_social, nome_fantasia, chave_pix, dados_bancarios, tipo_pagamento_padrao
        FROM fornecedores ORDER BY razao_social
    """)
    fornecedores = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
    quantidades = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.execute("SELECT id, caminhao, placa FROM veiculos WHERE ativo = 1 ORDER BY caminhao")  # NOVO
    veiculos = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM bases WHERE ativo = 1 ORDER BY nome")
    bases = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    numero_sugerido = gerar_numero_pedido()
    
    return render_template(
        'pedidos/novo.html',
        clientes=clientes,
        produtos=produtos,
        fornecedores=fornecedores,
        origens=origens,
        quantidades=quantidades,
        motoristas=motoristas,
        veiculos=veiculos,  # NOVO
        bases=bases,
        numero_sugerido=numero_sugerido
    )


@bp.route('/visualizar/<int:id>')
@login_required
def visualizar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.*,
               m.nome as motorista_nome,
               v.caminhao as veiculo_nome,
               v.placa as veiculo_placa
        FROM pedidos p
        LEFT JOIN motoristas m ON p.motorista_id = m.id
        LEFT JOIN veiculos v ON p.veiculo_id = v.id
        WHERE p.id = %s
    """, (id,))
    pedido = cursor.fetchone()
    
    if not pedido:
        flash('Pedido não encontrado!', 'danger')
        return redirect(url_for('pedidos.index'))
    
    cursor.execute("""
        SELECT pi.*,
               c.razao_social as cliente_razao,
               c.nome_fantasia as cliente_fantasia,
               c.cnpj as cliente_cnpj,
               p.nome as produto_nome,
               f.razao_social as fornecedor_razao,
               f.nome_fantasia as fornecedor_fantasia,
               o.nome as origem_nome,
               q.descricao as quantidade_descricao,
               b.nome as base_nome
        FROM pedidos_itens pi
        JOIN clientes c ON pi.cliente_id = c.id
        JOIN produto p ON pi.produto_id = p.id
        JOIN fornecedores f ON pi.fornecedor_id = f.id
        JOIN origens o ON pi.origem_id = o.id
        LEFT JOIN quantidades q ON pi.quantidade_id = q.id
        LEFT JOIN bases b ON pi.base_id = b.id
        WHERE pi.pedido_id = %s
        ORDER BY f.nome_fantasia, c.razao_social
    """, (id,))
    itens = cursor.fetchall()
    
    total_quantidade = sum(float(item['quantidade']) for item in itens)
    total_valor = sum(float(item['total_nf']) for item in itens)
    
    itens_por_fornecedor = {}
    for item in itens:
        forn = item['fornecedor_fantasia'] or item['fornecedor_razao']
        if forn not in itens_por_fornecedor:
            itens_por_fornecedor[forn] = []
        itens_por_fornecedor[forn].append(item)
    
    cursor.close()
    conn.close()
    
    return render_template(
        'pedidos/visualizar.html',
        pedido=pedido,
        itens=itens,
        itens_por_fornecedor=itens_por_fornecedor,
        total_quantidade=total_quantidade,
        total_valor=total_valor
    )


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        data_pedido = request.form['data_pedido']
        motorista_id = request.form.get('motorista_id') or None
        veiculo_id = request.form.get('veiculo_id') or None  # NOVO
        status = request.form['status']
        observacoes = request.form.get('observacoes', '')
        
        cursor.execute("""
            UPDATE pedidos
            SET data_pedido=%s, motorista_id=%s, veiculo_id=%s, status=%s, observacoes=%s
            WHERE id=%s
        """, (data_pedido, motorista_id, veiculo_id, status, observacoes, id))
        
        # Deletar e recriar itens
        cursor.execute("DELETE FROM pedidos_itens WHERE pedido_id = %s", (id,))
        
        clientes = request.form.getlist('cliente_id')
        produtos = request.form.getlist('produto_id')
        fornecedores = request.form.getlist('fornecedor_id')
        origens = request.form.getlist('origem_id')
        bases = request.form.getlist('base_id')
        quantidades = request.form.getlist('quantidade')
        quantidade_ids = request.form.getlist('quantidade_id')
        tipos_qtd = request.form.getlist('tipo_quantidade')
        precos = request.form.getlist('preco_unitario')
        totais_nf = request.form.getlist('total_nf')
        formas_pagto = request.form.getlist('forma_pagamento_fornecedor_item')
        pix_aleatorias = request.form.getlist('pix_aleatoria')
        dados_transf_itens = request.form.getlist('dados_transferencia_item')
        
        for i in range(len(clientes)):
            if clientes[i] and produtos[i] and fornecedores[i]:
                qtd_id = quantidade_ids[i] if quantidade_ids[i] else None
                qtd_valor = quantidades[i] if quantidades[i] else 0
                base_id = bases[i] if bases[i] else None
                forma_pagto = formas_pagto[i] if i < len(formas_pagto) else None
                pix_aleatoria = pix_aleatorias[i] if i < len(pix_aleatorias) else None
                dados_transf = dados_transf_itens[i] if i < len(dados_transf_itens) else None
                
                cursor.execute("""
                    INSERT INTO pedidos_itens (
                        pedido_id, cliente_id, produto_id, fornecedor_id, origem_id, base_id,
                        quantidade, quantidade_id, tipo_quantidade, forma_pagamento_fornecedor_item,
                        pix_aleatoria, dados_transferencia_item, preco_unitario, total_nf
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    id, clientes[i], produtos[i], fornecedores[i], origens[i], base_id,
                    qtd_valor, qtd_id, tipos_qtd[i], forma_pagto, pix_aleatoria, dados_transf,
                    precos[i], totais_nf[i]
                ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Pedido atualizado com sucesso!', 'success')
        return redirect(url_for('pedidos.visualizar', id=id))
    
      # GET
    cursor.execute("SELECT * FROM pedidos WHERE id = %s", (id,))
    pedido = cursor.fetchone()
    
    cursor.execute("SELECT * FROM pedidos_itens WHERE pedido_id = %s", (id,))
    itens = cursor.fetchall()
    
    cursor.execute("SELECT id, razao_social, nome_fantasia, cnpj FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    
    cursor.execute("""
        SELECT id, razao_social, nome_fantasia, chave_pix, dados_bancarios, tipo_pagamento_padrao
        FROM fornecedores ORDER BY razao_social
    """)
    fornecedores = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
    quantidades = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.execute("SELECT id, caminhao, placa FROM veiculos WHERE ativo = 1 ORDER BY caminhao")  # NOVO
    veiculos = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM bases WHERE ativo = 1 ORDER BY nome")
    bases = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template(
        'pedidos/editar.html',
        pedido=pedido,
        itens=itens,
        clientes=clientes,
        produtos=produtos,
        fornecedores=fornecedores,
        origens=origens,
        quantidades=quantidades,
        motoristas=motoristas,
        veiculos=veiculos,  # NOVO
        bases=bases
    )


@bp.route('/status/<int:id>/<status>')
@login_required
def alterar_status(id, status):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE pedidos SET status = %s WHERE id = %s", (status, id))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash(f'Status alterado para {status}!', 'success')
    return redirect(url_for('pedidos.visualizar', id=id))


@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM pedidos_itens WHERE pedido_id = %s", (id,))
    cursor.execute("DELETE FROM pedidos WHERE id = %s", (id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Pedido excluído com sucesso!', 'success')
    return redirect(url_for('pedidos.index'))


@bp.route('/api/buscar/<int:id>')
@login_required
def api_buscar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT pi.*,
               c.razao_social AS cliente_razao,
               p.nome AS produto_nome,
               f.razao_social AS fornecedor_razao,
               o.nome AS origem_nome
        FROM pedidos_itens pi
        JOIN clientes c ON pi.cliente_id = c.id
        JOIN produto p ON pi.produto_id = p.id
        JOIN fornecedores f ON pi.fornecedor_id = f.id
        JOIN origens o ON pi.origem_id = o.id
        WHERE pi.pedido_id = %s
    """, (id,))
    
    itens = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    for item in itens:
        item['quantidade'] = float(item['quantidade'])
        item['preco_unitario'] = float(item['preco_unitario'])
        item['total_nf'] = float(item['total_nf'])
    
    return jsonify(itens)

