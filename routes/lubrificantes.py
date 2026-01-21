from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
import mysql.connector
from datetime import datetime, date, timedelta
from calendar import monthrange

bp = Blueprint('lubrificantes', __name__, url_prefix='/lubrificantes')

def get_db():
    return mysql.connector.connect(
        host='centerbeam.proxy.rlwy.net',
        port=56026,
        user='root',
        password='CYTzzRYLVmEJGDexxXpgepWgpvebdSrV',
        database='railway'
    )

# =============================================
# PÁGINA PRINCIPAL / RESUMO LUBRIFICANTES
# =============================================
@bp.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Filtros de data - PADRÃO: mês/ano atual
    hoje = date.today()
    primeiro_dia_mes = date(hoje.year, hoje.month, 1)
    # Calcula último dia do mês usando monthrange
    ultimo_dia = monthrange(hoje.year, hoje.month)[1]
    ultimo_dia_mes = date(hoje.year, hoje.month, ultimo_dia)
    
    data_inicio = request.args.get('data_inicio', primeiro_dia_mes.strftime('%Y-%m-%d'))
    data_fim = request.args.get('data_fim', ultimo_dia_mes.strftime('%Y-%m-%d'))
    
    # Filtro de cliente
    cliente_id = request.args.get('cliente_id', '')
    
    # Filtro de produto
    produto_id = request.args.get('produto_id', '')
    
    # Busca clientes com produtos configurados no posto
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_lubrificantes = cursor.fetchall()
    
    # Busca produtos de lubrificantes
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        WHERE ativo = 1
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    # Busca saldo inicial (filtrado por cliente e produto se selecionado)
    saldo_query = "SELECT * FROM lubrificantes_saldo_inicial WHERE 1=1"
    params = []
    if cliente_id:
        saldo_query += " AND clienteid = %s"
        params.append(cliente_id)
    if produto_id:
        saldo_query += " AND produtoid = %s"
        params.append(produto_id)
    saldo_query += " ORDER BY data DESC LIMIT 1"
    
    cursor.execute(saldo_query, tuple(params))
    saldo = cursor.fetchone()
    
    # Busca preço vigente (filtrado por cliente e produto se selecionado)
    preco_query = "SELECT * FROM lubrificantes_precos_venda WHERE ativo = 1"
    preco_params = []
    if cliente_id:
        preco_query += " AND clienteid = %s"
        preco_params.append(cliente_id)
    if produto_id:
        preco_query += " AND produtoid = %s"
        preco_params.append(produto_id)
    preco_query += " ORDER BY data_inicio DESC LIMIT 1"
    
    cursor.execute(preco_query, tuple(preco_params))
    preco = cursor.fetchone()
    
    # Busca compras com filtros
    compras_query = """
        SELECT c.id, c.data, c.quantidade, c.preco_unitario, 'COMPRA' as tipo, 
               c.clienteid, c.produtoid, p.nome as produto_nome, c.total_nf
        FROM lubrificantes_compras c
        INNER JOIN lubrificantes_produtos p ON c.produtoid = p.id
        WHERE c.data BETWEEN %s AND %s
    """
    compras_params = [data_inicio, data_fim]
    if cliente_id:
        compras_query += " AND c.clienteid = %s"
        compras_params.append(cliente_id)
    if produto_id:
        compras_query += " AND c.produtoid = %s"
        compras_params.append(produto_id)
    compras_query += " ORDER BY c.data DESC"
    
    cursor.execute(compras_query, tuple(compras_params))
    compras = cursor.fetchall()
    
    # Busca lançamentos/vendas com filtros
    lancamentos_query = """
        SELECT l.id, l.data, l.quantidade, l.preco_venda_aplicado, 
               l.valor_total, 'VENDA' as tipo, l.clienteid, l.produtoid,
               p.nome as produto_nome
        FROM lubrificantes_lancamentos l
        INNER JOIN lubrificantes_produtos p ON l.produtoid = p.id
        WHERE l.data BETWEEN %s AND %s
    """
    lancamentos_params = [data_inicio, data_fim]
    if cliente_id:
        lancamentos_query += " AND l.clienteid = %s"
        lancamentos_params.append(cliente_id)
    if produto_id:
        lancamentos_query += " AND l.produtoid = %s"
        lancamentos_params.append(produto_id)
    lancamentos_query += " ORDER BY l.data DESC"
    
    cursor.execute(lancamentos_query, tuple(lancamentos_params))
    lancamentos = cursor.fetchall()
    
    # Calcula totais de TODAS as compras e vendas (considerando filtros) para o estoque
    total_compras_query = "SELECT COALESCE(SUM(quantidade), 0) as total FROM lubrificantes_compras WHERE 1=1"
    total_params = []
    if cliente_id:
        total_compras_query += " AND clienteid = %s"
        total_params.append(cliente_id)
    if produto_id:
        total_compras_query += " AND produtoid = %s"
        total_params.append(produto_id)
    
    cursor.execute(total_compras_query, tuple(total_params))
    total_compras = float(cursor.fetchone()['total'])
    
    total_vendas_query = "SELECT COALESCE(SUM(quantidade), 0) as total FROM lubrificantes_lancamentos WHERE 1=1"
    total_vendas_params = []
    if cliente_id:
        total_vendas_query += " AND clienteid = %s"
        total_vendas_params.append(cliente_id)
    if produto_id:
        total_vendas_query += " AND produtoid = %s"
        total_vendas_params.append(produto_id)
    
    cursor.execute(total_vendas_query, tuple(total_vendas_params))
    total_vendas = float(cursor.fetchone()['total'])
    
    # Estoque atual = Saldo inicial + Compras - Vendas
    quantidade_inicial = float(saldo['quantidade']) if saldo else 0
    estoque_atual = quantidade_inicial + total_compras - total_vendas
    
    # Unifica movimentações para a tabela
    movimentacoes = []
    
    for compra in compras:
        movimentacoes.append({
            'id': compra['id'],
            'data': compra['data'],
            'tipo': 'COMPRA',
            'produto_nome': compra['produto_nome'],
            'quantidade': float(compra['quantidade']),
            'preco': float(compra['preco_unitario']),
            'valor_total': float(compra['total_nf']),
            'encerrante': None
        })
    
    for lanc in lancamentos:
        movimentacoes.append({
            'id': lanc['id'],
            'data': lanc['data'],
            'tipo': 'VENDA',
            'produto_nome': lanc['produto_nome'],
            'quantidade': float(lanc['quantidade']),
            'preco': float(lanc['preco_venda_aplicado']),
            'valor_total': float(lanc['valor_total']),
            'encerrante': None
        })
    
    # Ordena por data (mais recente primeiro)
    movimentacoes.sort(key=lambda x: x['data'], reverse=True)
    
    # Calcula totais do período filtrado
    total_qtd_compras = sum(m['quantidade'] for m in movimentacoes if m['tipo'] == 'COMPRA')
    total_valor_compras = sum(m['valor_total'] for m in movimentacoes if m['tipo'] == 'COMPRA')
    total_qtd_vendas = sum(m['quantidade'] for m in movimentacoes if m['tipo'] == 'VENDA')
    total_valor_vendas = sum(m['valor_total'] for m in movimentacoes if m['tipo'] == 'VENDA')
    
    cursor.close()
    conn.close()
    
    return render_template(
        'lubrificantes/index.html',
        saldo=saldo,
        preco=preco,
        movimentacoes=movimentacoes,
        estoque_atual=estoque_atual,
        total_qtd_compras=total_qtd_compras,
        total_valor_compras=total_valor_compras,
        total_qtd_vendas=total_qtd_vendas,
        total_valor_vendas=total_valor_vendas,
        filtros={'data_inicio': data_inicio, 'data_fim': data_fim, 'cliente_id': cliente_id, 'produto_id': produto_id},
        clientes_lubrificantes=clientes_lubrificantes,
        produtos=produtos
    )

# =============================================
# SALDO INICIAL - CRIAR / VISUALIZAR
# =============================================
@bp.route('/saldo-inicial', methods=['GET', 'POST'])
@login_required
def saldo_inicial():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        quantidade = request.form['quantidade']
        custo_medio_compra = request.form['custo_medio_compra']
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.saldo_inicial'))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.saldo_inicial'))

        cursor.execute("""
            INSERT INTO lubrificantes_saldo_inicial 
            (data, produtoid, clienteid, quantidade, custo_medio_compra)
            VALUES (%s, %s, %s, %s, %s)
        """, (data, produto_id, cliente_id, quantidade, custo_medio_compra))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Saldo inicial cadastrado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))

    cursor.execute("SELECT * FROM lubrificantes_saldo_inicial ORDER BY data DESC LIMIT 1")
    saldo = cursor.fetchone()
    
    # Busca clientes configurados
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_lubrificantes = cursor.fetchall()
    
    # Busca produtos de lubrificantes
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        WHERE ativo = 1
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template('lubrificantes/saldo_inicial.html', 
                         saldo=saldo, 
                         clientes_lubrificantes=clientes_lubrificantes,
                         produtos=produtos)

# =============================================
# COMPRAS - CRIAR
# =============================================
@bp.route('/compras', methods=['GET', 'POST'])
@login_required
def compras():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        data = request.form['data']
        quantidade = request.form['quantidade']
        preco_unitario = request.form['preco_unitario']
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        fornecedor_id = request.form.get('fornecedor_id', None)
        numero_nf = request.form.get('numero_nf', None)
        observacoes = request.form.get('observacoes', None)
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.compras'))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.compras'))
        
        # Calcula o total da nota fiscal
        total_nf = float(quantidade) * float(preco_unitario)

        cursor.execute("""
            INSERT INTO lubrificantes_compras 
            (data, produtoid, clienteid, quantidade, preco_unitario, total_nf, fornecedorid, numero_nf, observacoes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (data, produto_id, cliente_id, quantidade, preco_unitario, total_nf, fornecedor_id, numero_nf, observacoes))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Compra registrada com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))
    
    # Busca clientes configurados
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_lubrificantes = cursor.fetchall()
    
    # Busca produtos de lubrificantes
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        WHERE ativo = 1
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    # Busca fornecedores
    cursor.execute("""
        SELECT id, razao_social 
        FROM fornecedores
        ORDER BY razao_social
    """)
    fornecedores = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template('lubrificantes/compras.html', 
                         clientes_lubrificantes=clientes_lubrificantes,
                         produtos=produtos,
                         fornecedores=fornecedores)

# =============================================
# PREÇO DE VENDA - CRIAR
# =============================================
@bp.route('/preco-venda', methods=['GET', 'POST'])
@login_required
def preco_venda():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data_inicio = request.form['data_inicio']
        preco_venda = request.form['preco_venda']
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.preco_venda'))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.preco_venda'))
        
        # Desativa todos os preços anteriores para este produto/cliente
        cursor.execute("""
            UPDATE lubrificantes_precos_venda 
            SET ativo = 0
            WHERE produtoid = %s AND clienteid = %s
        """, (produto_id, cliente_id))

        cursor.execute("""
            INSERT INTO lubrificantes_precos_venda (data_inicio, produtoid, clienteid, preco_venda, ativo)
            VALUES (%s, %s, %s, %s, 1)
        """, (data_inicio, produto_id, cliente_id, preco_venda))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Preço de venda alterado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))

    cursor.execute("""
        SELECT * FROM lubrificantes_precos_venda 
        WHERE ativo = 1
        ORDER BY data_inicio DESC LIMIT 1
    """)
    preco_atual = cursor.fetchone()
    
    # Busca clientes configurados
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_lubrificantes = cursor.fetchall()
    
    # Busca produtos de lubrificantes
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        WHERE ativo = 1
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return render_template('lubrificantes/preco_venda.html', 
                         preco_atual=preco_atual, 
                         clientes_lubrificantes=clientes_lubrificantes,
                         produtos=produtos)

# =============================================
# LANÇAMENTO DIÁRIO - CRIAR
# =============================================
@bp.route('/lancamento', methods=['GET', 'POST'])
@login_required
def lancamento():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        valor_total = float(request.form['valor_total'])
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        observacoes = request.form.get('observacoes', None)
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.lancamento'))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.lancamento'))

        cursor.execute("""
            SELECT id FROM lubrificantes_lancamentos 
            WHERE data = %s AND clienteid = %s AND produtoid = %s
        """, (data, cliente_id, produto_id))
        existe = cursor.fetchone()
        if existe:
            flash('Já existe um lançamento para esta data, cliente e produto!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('lubrificantes.lancamento'))
        
        # Como é lançamento direto de valor, não usamos preço unitário
        # quantidade e preco_venda_aplicado serão 0, apenas valor_total importa
        quantidade = 0
        preco_venda_aplicado = 0

        cursor.execute("""
            INSERT INTO lubrificantes_lancamentos
            (data, produtoid, clienteid, quantidade, preco_venda_aplicado, valor_total, observacoes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (data, produto_id, cliente_id, quantidade, preco_venda_aplicado, valor_total, observacoes))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Lançamento registrado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))

    # GET - Busca dados para exibir no formulário
    # Busca clientes configurados
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_lubrificantes = cursor.fetchall()
    
    # Busca produtos de lubrificantes
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        WHERE ativo = 1
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    # Busca a última data de lançamento
    cursor.execute("""
        SELECT MAX(data) as ultima_data 
        FROM lubrificantes_lancamentos
    """)
    result = cursor.fetchone()
    ultima_data = result['ultima_data'] if result and result['ultima_data'] else None
    
    # Calcula a próxima data sugerida (dia seguinte ao último lançamento ou hoje)
    if ultima_data:
        proxima_data = (ultima_data + timedelta(days=1)).strftime('%Y-%m-%d')
        ultima_data_formatada = ultima_data.strftime('%d/%m/%Y')
    else:
        proxima_data = date.today().strftime('%Y-%m-%d')
        ultima_data_formatada = None

    cursor.close()
    conn.close()

    return render_template(
        'lubrificantes/lancamento.html',
        clientes_lubrificantes=clientes_lubrificantes,
        produtos=produtos,
        proxima_data=proxima_data,
        ultima_data=ultima_data_formatada
    )

# =============================================
# LANÇAMENTO DIÁRIO - EDITAR
# =============================================
@bp.route('/lancamento/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_lancamento(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        data = request.form['data']
        valor_total = float(request.form['valor_total'])
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        observacoes = request.form.get('observacoes', None)
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.editar_lancamento', id=id))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.editar_lancamento', id=id))
        
        # Verifica se já existe outro lançamento com a mesma data/cliente/produto
        cursor.execute("""
            SELECT id FROM lubrificantes_lancamentos 
            WHERE data = %s AND clienteid = %s AND produtoid = %s AND id != %s
        """, (data, cliente_id, produto_id, id))
        existe = cursor.fetchone()
        if existe:
            flash('Já existe outro lançamento para esta data, cliente e produto!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('lubrificantes.editar_lancamento', id=id))
        
        # Como é lançamento direto de valor, não usamos preço unitário
        # quantidade e preco_venda_aplicado serão 0, apenas valor_total importa
        quantidade = 0
        preco_venda_aplicado = 0
        
        cursor.execute("""
            UPDATE lubrificantes_lancamentos
            SET data = %s, produtoid = %s, clienteid = %s, 
                quantidade = %s, preco_venda_aplicado = %s, valor_total = %s, observacoes = %s
            WHERE id = %s
        """, (data, produto_id, cliente_id, quantidade, preco_venda_aplicado, valor_total, observacoes, id))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Lançamento atualizado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))
    
    # GET - Busca o lançamento a ser editado
    cursor.execute("""
        SELECT * FROM lubrificantes_lancamentos WHERE id = %s
    """, (id,))
    lancamento = cursor.fetchone()
    
    if not lancamento:
        flash('Lançamento não encontrado!', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('lubrificantes.index'))
    
    # Busca clientes configurados
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        WHERE cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_lubrificantes = cursor.fetchall()
    
    # Busca produtos de lubrificantes
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        WHERE ativo = 1
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template(
        'lubrificantes/editar_lancamento.html',
        lancamento=lancamento,
        clientes_lubrificantes=clientes_lubrificantes,
        produtos=produtos
    )

# =============================================
# PRODUTOS - LISTAR
# =============================================
@bp.route('/produtos')
@login_required
def produtos():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM lubrificantes_produtos 
        ORDER BY nome
    """)
    produtos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('lubrificantes/produtos.html', produtos=produtos)

# =============================================
# PRODUTOS - CRIAR
# =============================================
@bp.route('/produtos/novo', methods=['GET', 'POST'])
@login_required
def novo_produto():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        nome = request.form['nome'].strip().upper()
        descricao = request.form.get('descricao', '').strip()
        unidade = request.form.get('unidade', 'LITROS')
        ativo = request.form.get('ativo', '1')
        preco_venda = request.form.get('preco_venda', None)
        
        if not nome:
            flash('Nome é obrigatório!', 'danger')
            return redirect(url_for('lubrificantes.novo_produto'))
        
        # Converte preco_venda para None se estiver vazio
        preco_venda_value = float(preco_venda) if preco_venda and preco_venda.strip() else None
        
        cursor.execute("""
            INSERT INTO lubrificantes_produtos (nome, descricao, unidade, ativo, preco_venda)
            VALUES (%s, %s, %s, %s, %s)
        """, (nome, descricao if descricao else None, unidade, int(ativo), preco_venda_value))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Produto cadastrado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.produtos'))
    
    cursor.close()
    conn.close()
    
    return render_template('lubrificantes/novo_produto.html')

# =============================================
# PRODUTOS - EDITAR
# =============================================
@bp.route('/produtos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_produto(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        nome = request.form['nome'].strip().upper()
        descricao = request.form.get('descricao', '').strip()
        unidade = request.form.get('unidade', 'LITROS')
        ativo = request.form.get('ativo', '1')
        preco_venda = request.form.get('preco_venda', None)
        
        if not nome:
            flash('Nome é obrigatório!', 'danger')
            return redirect(url_for('lubrificantes.editar_produto', id=id))
        
        # Converte preco_venda para None se estiver vazio
        preco_venda_value = float(preco_venda) if preco_venda and preco_venda.strip() else None
        
        cursor.execute("""
            UPDATE lubrificantes_produtos 
            SET nome = %s, descricao = %s, unidade = %s, ativo = %s, preco_venda = %s
            WHERE id = %s
        """, (nome, descricao if descricao else None, unidade, int(ativo), preco_venda_value, id))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Produto atualizado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.produtos'))
    
    cursor.execute("SELECT * FROM lubrificantes_produtos WHERE id = %s", (id,))
    produto = cursor.fetchone()
    
    if not produto:
        flash('Produto não encontrado!', 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('lubrificantes.produtos'))
    
    cursor.close()
    conn.close()
    
    return render_template('lubrificantes/editar_produto.html', produto=produto)
