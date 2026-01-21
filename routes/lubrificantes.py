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
        saldo_query += " AND cliente_id = %s"
        params.append(cliente_id)
    if produto_id:
        saldo_query += " AND produto_id = %s"
        params.append(produto_id)
    saldo_query += " ORDER BY data DESC LIMIT 1"
    
    cursor.execute(saldo_query, tuple(params))
    saldo = cursor.fetchone()
    
    # Busca preço vigente (filtrado por cliente e produto se selecionado)
    preco_query = "SELECT * FROM lubrificantes_precos_venda WHERE 1=1"
    preco_params = []
    if cliente_id:
        preco_query += " AND cliente_id = %s"
        preco_params.append(cliente_id)
    if produto_id:
        preco_query += " AND produto_id = %s"
        preco_params.append(produto_id)
    preco_query += " ORDER BY data_inicio DESC LIMIT 1"
    
    cursor.execute(preco_query, tuple(preco_params))
    preco = cursor.fetchone()
    
    # Busca compras com filtros
    compras_query = """
        SELECT c.id, c.data, c.quantidade, c.preco_compra, 'COMPRA' as tipo, 
               c.cliente_id, c.produto_id, p.nome as produto_nome
        FROM lubrificantes_compras c
        INNER JOIN lubrificantes_produtos p ON c.produto_id = p.id
        WHERE c.data BETWEEN %s AND %s
    """
    compras_params = [data_inicio, data_fim]
    if cliente_id:
        compras_query += " AND c.cliente_id = %s"
        compras_params.append(cliente_id)
    if produto_id:
        compras_query += " AND c.produto_id = %s"
        compras_params.append(produto_id)
    compras_query += " ORDER BY c.data DESC"
    
    cursor.execute(compras_query, tuple(compras_params))
    compras = cursor.fetchall()
    
    # Busca lançamentos/vendas com filtros
    lancamentos_query = """
        SELECT l.id, l.data, l.quantidade_vendida, l.preco_venda_aplicado, 
               l.encerrante_final, 'VENDA' as tipo, l.cliente_id, l.produto_id,
               p.nome as produto_nome
        FROM lubrificantes_lancamentos l
        INNER JOIN lubrificantes_produtos p ON l.produto_id = p.id
        WHERE l.data BETWEEN %s AND %s
    """
    lancamentos_params = [data_inicio, data_fim]
    if cliente_id:
        lancamentos_query += " AND l.cliente_id = %s"
        lancamentos_params.append(cliente_id)
    if produto_id:
        lancamentos_query += " AND l.produto_id = %s"
        lancamentos_params.append(produto_id)
    lancamentos_query += " ORDER BY l.data DESC"
    
    cursor.execute(lancamentos_query, tuple(lancamentos_params))
    lancamentos = cursor.fetchall()
    
    # Calcula totais de TODAS as compras e vendas (considerando filtros) para o estoque
    total_compras_query = "SELECT COALESCE(SUM(quantidade), 0) as total FROM lubrificantes_compras WHERE 1=1"
    total_params = []
    if cliente_id:
        total_compras_query += " AND cliente_id = %s"
        total_params.append(cliente_id)
    if produto_id:
        total_compras_query += " AND produto_id = %s"
        total_params.append(produto_id)
    
    cursor.execute(total_compras_query, tuple(total_params))
    total_compras = float(cursor.fetchone()['total'])
    
    total_vendas_query = "SELECT COALESCE(SUM(quantidade_vendida), 0) as total FROM lubrificantes_lancamentos WHERE 1=1"
    total_vendas_params = []
    if cliente_id:
        total_vendas_query += " AND cliente_id = %s"
        total_vendas_params.append(cliente_id)
    if produto_id:
        total_vendas_query += " AND produto_id = %s"
        total_vendas_params.append(produto_id)
    
    cursor.execute(total_vendas_query, tuple(total_vendas_params))
    total_vendas = float(cursor.fetchone()['total'])
    
    # Estoque atual = Saldo inicial + Compras - Vendas
    volume_inicial = float(saldo['volume_inicial']) if saldo else 0
    estoque_atual = volume_inicial + total_compras - total_vendas
    
    # Unifica movimentações para a tabela
    movimentacoes = []
    
    for compra in compras:
        movimentacoes.append({
            'id': compra['id'],
            'data': compra['data'],
            'tipo': 'COMPRA',
            'produto_nome': compra['produto_nome'],
            'quantidade': float(compra['quantidade']),
            'preco': float(compra['preco_compra']),
            'valor_total': float(compra['quantidade']) * float(compra['preco_compra']),
            'encerrante': None
        })
    
    for lanc in lancamentos:
        movimentacoes.append({
            'id': lanc['id'],
            'data': lanc['data'],
            'tipo': 'VENDA',
            'produto_nome': lanc['produto_nome'],
            'quantidade': float(lanc['quantidade_vendida']),
            'preco': float(lanc['preco_venda_aplicado']),
            'valor_total': float(lanc['quantidade_vendida']) * float(lanc['preco_venda_aplicado']),
            'encerrante': float(lanc['encerrante_final']) if lanc['encerrante_final'] else None
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
        volume_inicial = request.form['volume_inicial']
        preco_medio_compra = request.form['preco_medio_compra']
        encerrante_inicial = request.form.get('encerrante_inicial', None)
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
            (data, produto_id, cliente_id, volume_inicial, preco_medio_compra, encerrante_inicial)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (data, produto_id, cliente_id, volume_inicial, preco_medio_compra, encerrante_inicial))
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
        preco_compra = request.form['preco_compra']
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        fornecedor = request.form.get('fornecedor', None)
        nota_fiscal = request.form.get('nota_fiscal', None)
        observacao = request.form.get('observacao', None)
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.compras'))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.compras'))

        cursor.execute("""
            INSERT INTO lubrificantes_compras 
            (data, produto_id, cliente_id, quantidade, preco_compra, fornecedor, nota_fiscal, observacao)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (data, produto_id, cliente_id, quantidade, preco_compra, fornecedor, nota_fiscal, observacao))
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
    
    cursor.close()
    conn.close()

    return render_template('lubrificantes/compras.html', 
                         clientes_lubrificantes=clientes_lubrificantes,
                         produtos=produtos)

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

        cursor.execute("""
            INSERT INTO lubrificantes_precos_venda (data_inicio, produto_id, cliente_id, preco_venda)
            VALUES (%s, %s, %s, %s)
        """, (data_inicio, produto_id, cliente_id, preco_venda))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Preço de venda alterado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))

    cursor.execute("""
        SELECT * FROM lubrificantes_precos_venda ORDER BY data_inicio DESC LIMIT 1
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
# API - ENCERRANTE ANTERIOR
# =============================================
@bp.route('/api/encerrante-anterior/<int:cliente_id>/<int:produto_id>')
@login_required
def api_encerrante_anterior(cliente_id, produto_id):
    """API: Retorna o encerrante anterior para um cliente e produto"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Buscar último lançamento do cliente e produto
        cursor.execute("""
            SELECT encerrante_final FROM lubrificantes_lancamentos
            WHERE cliente_id = %s AND produto_id = %s
            ORDER BY data DESC LIMIT 1
        """, (cliente_id, produto_id))
        ultimo_lancamento = cursor.fetchone()
        
        if ultimo_lancamento:
            encerrante_anterior = float(ultimo_lancamento['encerrante_final'])
        else:
            # Se não há lançamento, buscar do saldo inicial
            cursor.execute("""
                SELECT encerrante_inicial FROM lubrificantes_saldo_inicial
                WHERE cliente_id = %s AND produto_id = %s
                ORDER BY data DESC LIMIT 1
            """, (cliente_id, produto_id))
            saldo_ini = cursor.fetchone()
            encerrante_anterior = float(saldo_ini['encerrante_inicial']) if (saldo_ini and saldo_ini['encerrante_inicial']) else 0
        
        return jsonify({
            'success': True,
            'encerrante_anterior': encerrante_anterior
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

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
        quantidade_vendida = float(request.form['quantidade_vendida'])
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        encerrante_final = request.form.get('encerrante_final', None)
        observacao = request.form.get('observacao', None)
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('lubrificantes.lancamento'))
        
        if not produto_id:
            flash('Por favor, selecione um produto!', 'danger')
            return redirect(url_for('lubrificantes.lancamento'))

        cursor.execute("""
            SELECT id FROM lubrificantes_lancamentos 
            WHERE data = %s AND cliente_id = %s AND produto_id = %s
        """, (data, cliente_id, produto_id))
        existe = cursor.fetchone()
        if existe:
            flash('Já existe um lançamento para esta data, cliente e produto!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('lubrificantes.lancamento'))

        cursor.execute("""
            SELECT preco_venda FROM lubrificantes_precos_venda 
            WHERE data_inicio <= %s AND cliente_id = %s AND produto_id = %s
            ORDER BY data_inicio DESC LIMIT 1
        """, (data, cliente_id, produto_id))
        preco_row = cursor.fetchone()
        preco_venda = preco_row['preco_venda'] if preco_row else 0

        cursor.execute("""
            INSERT INTO lubrificantes_lancamentos
            (data, produto_id, cliente_id, quantidade_vendida, preco_venda_aplicado, encerrante_final, observacao)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (data, produto_id, cliente_id, quantidade_vendida, preco_venda, encerrante_final, observacao))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Lançamento registrado com sucesso!', 'success')
        return redirect(url_for('lubrificantes.index'))

    # GET - Busca dados para exibir no formulário
    cursor.execute("""
        SELECT preco_venda FROM lubrificantes_precos_venda ORDER BY data_inicio DESC LIMIT 1
    """)
    preco_row = cursor.fetchone()
    preco_venda = float(preco_row['preco_venda']) if preco_row else 0
    
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
        'lubrificantes/lancamento.html',
        preco_venda=preco_venda,
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
        unidade_medida = request.form.get('unidade_medida', 'L')
        ativo = request.form.get('ativo', '1')
        
        if not nome:
            flash('Nome é obrigatório!', 'danger')
            return redirect(url_for('lubrificantes.novo_produto'))
        
        cursor.execute("""
            INSERT INTO lubrificantes_produtos (nome, descricao, unidade_medida, ativo)
            VALUES (%s, %s, %s, %s)
        """, (nome, descricao if descricao else None, unidade_medida, int(ativo)))
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
        unidade_medida = request.form.get('unidade_medida', 'L')
        ativo = request.form.get('ativo', '1')
        
        if not nome:
            flash('Nome é obrigatório!', 'danger')
            return redirect(url_for('lubrificantes.editar_produto', id=id))
        
        cursor.execute("""
            UPDATE lubrificantes_produtos 
            SET nome = %s, descricao = %s, unidade_medida = %s, ativo = %s
            WHERE id = %s
        """, (nome, descricao if descricao else None, unidade_medida, int(ativo), id))
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
