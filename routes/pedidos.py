from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
import mysql.connector
from datetime import datetime, date

bp = Blueprint('pedidos', __name__, url_prefix='/pedidos')

def get_db():
    return mysql.connector.connect(
        host='centerbeam.proxy.rlwy.net',
        port=56026,
        user='root',
        password='CYTzzRYLVmEJGDexxXpgepWgpvebdSrV',
        database='railway'
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

# =============================================
# LISTAR PEDIDOS
# =============================================
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
               COUNT(pi.id) as total_itens,
               SUM(pi.quantidade) as total_quantidade,
               SUM(pi.total_nf) as total_valor
        FROM pedidos p
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
    
    return render_template('pedidos/index.html', 
                           pedidos=pedidos,
                           filtros={'data_inicio': data_inicio, 'data_fim': data_fim, 'status': status})

# =============================================
# NOVO PEDIDO
# =============================================
@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        data_pedido = request.form['data_pedido']
        observacoes = request.form.get('observacoes', '')
        numero = gerar_numero_pedido()
        
        cursor.execute("""
            INSERT INTO pedidos (numero, data_pedido, status, observacoes)
            VALUES (%s, %s, 'Pendente', %s)
        """, (numero, data_pedido, observacoes))
        pedido_id = cursor.lastrowid
        
        clientes = request.form.getlist('cliente_id[]')
        produtos = request.form.getlist('produto_id[]')
        fornecedores = request.form.getlist('fornecedor_id[]')
        origens = request.form.getlist('origem_id[]')
        quantidades = request.form.getlist('quantidade[]')
        quantidade_ids = request.form.getlist('quantidade_id[]')
        tipos_qtd = request.form.getlist('tipo_quantidade[]')
        precos = request.form.getlist('preco_unitario[]')
        totais_nf = request.form.getlist('total_nf[]')
        
        for i in range(len(clientes)):
            if clientes[i] and produtos[i] and fornecedores[i]:
                # Pegar quantidade do listbox ou manual
                qtd_id = quantidade_ids[i] if quantidade_ids[i] else None
                qtd_valor = quantidades[i] if quantidades[i] else 0
                
                cursor.execute("""
                    INSERT INTO pedidos_itens 
                    (pedido_id, cliente_id, produto_id, fornecedor_id, origem_id, 
                     quantidade, quantidade_id, tipo_quantidade, preco_unitario, total_nf)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (pedido_id, clientes[i], produtos[i], fornecedores[i], origens[i],
                      qtd_valor, qtd_id, tipos_qtd[i], precos[i], totais_nf[i]))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash(f'Pedido {numero} criado com sucesso!', 'success')
        return redirect(url_for('pedidos.visualizar', id=pedido_id))
    
    cursor.execute("SELECT id, razao_social, nome_fantasia, cnpj FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    
    cursor.execute("SELECT id, razao_social, nome_fantasia FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
    quantidades = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    numero_sugerido = gerar_numero_pedido()
    
    return render_template('pedidos/novo.html',
                           clientes=clientes,
                           produtos=produtos,
                           fornecedores=fornecedores,
                           origens=origens,
                           quantidades=quantidades,
                           numero_sugerido=numero_sugerido)

# =============================================
# VISUALIZAR PEDIDO
# =============================================
@bp.route('/visualizar/<int:id>')
@login_required
def visualizar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM pedidos WHERE id = %s", (id,))
    pedido = cursor.fetchone()
    
    if not pedido:
        flash('Pedido não encontrado!', 'danger')
        return redirect(url_for('pedidos.index'))
    
    cursor.execute("""
        SELECT pi.*, 
               c.razao_social as cliente_razao, c.nome_fantasia as cliente_fantasia, c.cnpj as cliente_cnpj,
               p.nome as produto_nome,
               f.razao_social as fornecedor_razao, f.nome_fantasia as fornecedor_fantasia,
               o.nome as origem_nome,
               q.descricao as quantidade_descricao
        FROM pedidos_itens pi
        JOIN clientes c ON pi.cliente_id = c.id
        JOIN produto p ON pi.produto_id = p.id
        JOIN fornecedores f ON pi.fornecedor_id = f.id
        JOIN origens o ON pi.origem_id = o.id
        LEFT JOIN quantidades q ON pi.quantidade_id = q.id
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
    
    return render_template('pedidos/visualizar.html',
                           pedido=pedido,
                           itens=itens,
                           itens_por_fornecedor=itens_por_fornecedor,
                           total_quantidade=total_quantidade,
                           total_valor=total_valor)

# =============================================
# EDITAR PEDIDO
# =============================================
@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        data_pedido = request.form['data_pedido']
        status = request.form['status']
        observacoes = request.form.get('observacoes', '')
        
        cursor.execute("""
            UPDATE pedidos SET data_pedido = %s, status = %s, observacoes = %s
            WHERE id = %s
        """, (data_pedido, status, observacoes, id))
        
        cursor.execute("DELETE FROM pedidos_itens WHERE pedido_id = %s", (id,))
        
        clientes = request.form.getlist('cliente_id[]')
        produtos = request.form.getlist('produto_id[]')
        fornecedores = request.form.getlist('fornecedor_id[]')
        origens = request.form.getlist('origem_id[]')
        quantidades = request.form.getlist('quantidade[]')
        quantidade_ids = request.form.getlist('quantidade_id[]')
        tipos_qtd = request.form.getlist('tipo_quantidade[]')
        precos = request.form.getlist('preco_unitario[]')
        totais_nf = request.form.getlist('total_nf[]')
        
        for i in range(len(clientes)):
            if clientes[i] and produtos[i] and fornecedores[i]:
                qtd_id = quantidade_ids[i] if quantidade_ids[i] else None
                qtd_valor = quantidades[i] if quantidades[i] else 0
                
                cursor.execute("""
                    INSERT INTO pedidos_itens 
                    (pedido_id, cliente_id, produto_id, fornecedor_id, origem_id, 
                     quantidade, quantidade_id, tipo_quantidade, preco_unitario, total_nf)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (id, clientes[i], produtos[i], fornecedores[i], origens[i],
                      qtd_valor, qtd_id, tipos_qtd[i], precos[i], totais_nf[i]))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Pedido atualizado com sucesso!', 'success')
        return redirect(url_for('pedidos.visualizar', id=id))
    
    cursor.execute("SELECT * FROM pedidos WHERE id = %s", (id,))
    pedido = cursor.fetchone()
    
    cursor.execute("SELECT * FROM pedidos_itens WHERE pedido_id = %s", (id,))
    itens = cursor.fetchall()
    
    cursor.execute("SELECT id, razao_social, nome_fantasia, cnpj FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    
    cursor.execute("SELECT id, razao_social, nome_fantasia FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
    quantidades = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('pedidos/editar.html',
                           pedido=pedido,
                           itens=itens,
                           clientes=clientes,
                           produtos=produtos,
                           fornecedores=fornecedores,
                           origens=origens,
                           quantidades=quantidades)

# =============================================
# ALTERAR STATUS
# =============================================
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

# =============================================
# EXCLUIR PEDIDO
# =============================================
@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pedidos WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Pedido excluído com sucesso!', 'success')
    return redirect(url_for('pedidos.index'))

# =============================================
# API - BUSCAR PEDIDOS PARA IMPORTAR NO FRETE
# =============================================
@bp.route('/api/buscar/<int:id>')
@login_required
def api_buscar(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT pi.*, 
               c.razao_social as cliente_razao,
               p.nome as produto_nome,
               f.razao_social as fornecedor_razao,
               o.nome as origem_nome
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
