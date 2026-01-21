from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
import mysql.connector
from datetime import datetime, date, timedelta
from calendar import monthrange

bp = Blueprint('arla', __name__, url_prefix='/arla')

def get_db():
    return mysql.connector.connect(
        host='centerbeam.proxy.rlwy.net',
        port=56026,
        user='root',
        password='CYTzzRYLVmEJGDexxXpgepWgpvebdSrV',
        database='railway'
    )

# =============================================
# PÁGINA PRINCIPAL / RESUMO ARLA
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
    
    # Busca clientes com ARLA configurado
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        INNER JOIN produto p ON cp.produto_id = p.id
        WHERE p.nome = 'ARLA' AND cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_arla = cursor.fetchall()
    
    # Busca saldo inicial (filtrado por cliente se selecionado)
    if cliente_id:
        cursor.execute("""
            SELECT * FROM arla_saldo_inicial 
            WHERE cliente_id = %s 
            ORDER BY data DESC LIMIT 1
        """, (cliente_id,))
    else:
        cursor.execute("""
            SELECT * FROM arla_saldo_inicial ORDER BY data DESC LIMIT 1
        """)
    saldo = cursor.fetchone()
    
    # Busca preço vigente (filtrado por cliente se selecionado)
    if cliente_id:
        cursor.execute("""
            SELECT * FROM arla_precos_venda 
            WHERE cliente_id = %s 
            ORDER BY data_inicio DESC LIMIT 1
        """, (cliente_id,))
    else:
        cursor.execute("""
            SELECT * FROM arla_precos_venda ORDER BY data_inicio DESC LIMIT 1
        """)
    preco = cursor.fetchone()
    
    # Busca compras com filtros
    if cliente_id:
        cursor.execute("""
            SELECT id, data, quantidade, preco_compra, 'COMPRA' as tipo, cliente_id
            FROM arla_compras
            WHERE data BETWEEN %s AND %s AND cliente_id = %s
            ORDER BY data DESC
        """, (data_inicio, data_fim, cliente_id))
    else:
        cursor.execute("""
            SELECT id, data, quantidade, preco_compra, 'COMPRA' as tipo, cliente_id
            FROM arla_compras
            WHERE data BETWEEN %s AND %s
            ORDER BY data DESC
        """, (data_inicio, data_fim))
    compras = cursor.fetchall()
    
    # Busca lançamentos/vendas com filtros
    if cliente_id:
        cursor.execute("""
            SELECT id, data, quantidade_vendida, preco_venda_aplicado, encerrante_final, 'VENDA' as tipo, cliente_id
            FROM arla_lancamentos
            WHERE data BETWEEN %s AND %s AND cliente_id = %s
            ORDER BY data DESC
        """, (data_inicio, data_fim, cliente_id))
    else:
        cursor.execute("""
            SELECT id, data, quantidade_vendida, preco_venda_aplicado, encerrante_final, 'VENDA' as tipo, cliente_id
            FROM arla_lancamentos
            WHERE data BETWEEN %s AND %s
            ORDER BY data DESC
        """, (data_inicio, data_fim))
    lancamentos = cursor.fetchall()
    
    # Calcula totais de TODAS as compras e vendas (considerando filtro de cliente) para o estoque
    if cliente_id:
        cursor.execute("SELECT COALESCE(SUM(quantidade), 0) as total FROM arla_compras WHERE cliente_id = %s", (cliente_id,))
        total_compras = float(cursor.fetchone()['total'])
        
        cursor.execute("SELECT COALESCE(SUM(quantidade_vendida), 0) as total FROM arla_lancamentos WHERE cliente_id = %s", (cliente_id,))
        total_vendas = float(cursor.fetchone()['total'])
    else:
        cursor.execute("SELECT COALESCE(SUM(quantidade), 0) as total FROM arla_compras")
        total_compras = float(cursor.fetchone()['total'])
        
        cursor.execute("SELECT COALESCE(SUM(quantidade_vendida), 0) as total FROM arla_lancamentos")
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
            'quantidade': float(lanc['quantidade_vendida']),
            'preco': float(lanc['preco_venda_aplicado']),
            'valor_total': float(lanc['quantidade_vendida']) * float(lanc['preco_venda_aplicado']),
            'encerrante': float(lanc['encerrante_final'])
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
        'arla/index.html',
        saldo=saldo,
        preco=preco,
        movimentacoes=movimentacoes,
        estoque_atual=estoque_atual,
        total_qtd_compras=total_qtd_compras,
        total_valor_compras=total_valor_compras,
        total_qtd_vendas=total_qtd_vendas,
        total_valor_vendas=total_valor_vendas,
        filtros={'data_inicio': data_inicio, 'data_fim': data_fim, 'cliente_id': cliente_id},
        clientes_arla=clientes_arla
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
        encerrante_inicial = request.form['encerrante_inicial']
        cliente_id = request.form.get('cliente_id')
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('arla.saldo_inicial'))

        cursor.execute("""
            INSERT INTO arla_saldo_inicial (data, volume_inicial, preco_medio_compra, encerrante_inicial, cliente_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (data, volume_inicial, preco_medio_compra, encerrante_inicial, cliente_id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Saldo inicial cadastrado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_saldo_inicial ORDER BY data DESC LIMIT 1")
    saldo = cursor.fetchone()
    
    # Busca clientes com ARLA configurado
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        INNER JOIN produto p ON cp.produto_id = p.id
        WHERE p.nome = 'ARLA' AND cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_arla = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('arla/saldo_inicial.html', saldo=saldo, clientes_arla=clientes_arla)

# =============================================
# SALDO INICIAL - EDITAR
# =============================================
@bp.route('/editar-saldo-inicial/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_saldo_inicial(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        volume_inicial = request.form['volume_inicial']
        preco_medio_compra = request.form['preco_medio_compra']
        encerrante_inicial = request.form['encerrante_inicial']

        cursor.execute("""
            UPDATE arla_saldo_inicial
            SET data = %s, volume_inicial = %s, preco_medio_compra = %s, encerrante_inicial = %s
            WHERE id = %s
        """, (data, volume_inicial, preco_medio_compra, encerrante_inicial, id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Saldo inicial atualizado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_saldo_inicial WHERE id = %s", (id,))
    saldo = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('arla/editar_saldo_inicial.html', saldo=saldo)

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
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('arla.compras'))

        cursor.execute("""
            INSERT INTO arla_compras (data, quantidade, preco_compra, cliente_id)
            VALUES (%s, %s, %s, %s)
        """, (data, quantidade, preco_compra, cliente_id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Compra registrada com sucesso!', 'success')
        return redirect(url_for('arla.index'))
    
    # Busca clientes com ARLA configurado
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        INNER JOIN produto p ON cp.produto_id = p.id
        WHERE p.nome = 'ARLA' AND cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_arla = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('arla/compras.html', clientes_arla=clientes_arla)

# =============================================
# COMPRAS - EDITAR
# =============================================
@bp.route('/editar-compra/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_compra(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        quantidade = request.form['quantidade']
        preco_compra = request.form['preco_compra']

        cursor.execute("""
            UPDATE arla_compras
            SET data = %s, quantidade = %s, preco_compra = %s
            WHERE id = %s
        """, (data, quantidade, preco_compra, id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Compra atualizada com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_compras WHERE id = %s", (id,))
    compra = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('arla/editar_compra.html', compra=compra)

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
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('arla.preco_venda'))

        cursor.execute("""
            INSERT INTO arla_precos_venda (data_inicio, preco_venda, cliente_id)
            VALUES (%s, %s, %s)
        """, (data_inicio, preco_venda, cliente_id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Preço de venda alterado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("""
        SELECT * FROM arla_precos_venda ORDER BY data_inicio DESC LIMIT 1
    """)
    preco_atual = cursor.fetchone()
    
    # Busca clientes com ARLA configurado
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        INNER JOIN produto p ON cp.produto_id = p.id
        WHERE p.nome = 'ARLA' AND cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_arla = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('arla/preco_venda.html', preco_atual=preco_atual, clientes_arla=clientes_arla)

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
        encerrante_final = float(request.form['encerrante_final'])
        cliente_id = request.form.get('cliente_id')
        
        if not cliente_id:
            flash('Por favor, selecione um cliente!', 'danger')
            return redirect(url_for('arla.lancamento'))

        cursor.execute("SELECT id FROM arla_lancamentos WHERE data = %s AND cliente_id = %s", (data, cliente_id))
        existe = cursor.fetchone()
        if existe:
            flash('Já existe um lançamento para esta data e cliente!', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('arla.lancamento'))

        cursor.execute("""
            SELECT encerrante_final FROM arla_lancamentos
            WHERE data < %s AND cliente_id = %s
            ORDER BY data DESC LIMIT 1
        """, (data, cliente_id))
        ante = cursor.fetchone()
        
        encerrante_anterior = ante['encerrante_final'] if ante else None
        
        if encerrante_anterior is None:
            cursor.execute("""
                SELECT encerrante_inicial FROM arla_saldo_inicial
                WHERE data <= %s AND cliente_id = %s ORDER BY data DESC LIMIT 1
            """, (data, cliente_id))
            saldo_ini = cursor.fetchone()
            encerrante_anterior = saldo_ini['encerrante_inicial'] if saldo_ini else 0

        quantidade_vendida = encerrante_final - float(encerrante_anterior)

        cursor.execute("""
            SELECT preco_venda FROM arla_precos_venda 
            WHERE data_inicio <= %s AND cliente_id = %s
            ORDER BY data_inicio DESC LIMIT 1
        """, (data, cliente_id))
        preco_row = cursor.fetchone()
        preco_venda = preco_row['preco_venda'] if preco_row else 0

        cursor.execute("""
            INSERT INTO arla_lancamentos
            (data, encerrante_final, quantidade_vendida, preco_venda_aplicado, cliente_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (data, encerrante_final, quantidade_vendida, preco_venda, cliente_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Lançamento registrado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    # GET - Busca dados para exibir no formulário
    cursor.execute("""
        SELECT * FROM arla_lancamentos ORDER BY data DESC LIMIT 1
    """)
    ultimo_lancamento = cursor.fetchone()

    if ultimo_lancamento:
        encerrante_anterior = float(ultimo_lancamento['encerrante_final'])
    else:
        cursor.execute("""
            SELECT encerrante_inicial FROM arla_saldo_inicial ORDER BY data DESC LIMIT 1
        """)
        saldo_ini = cursor.fetchone()
        encerrante_anterior = float(saldo_ini['encerrante_inicial']) if saldo_ini else 0

    cursor.execute("""
        SELECT preco_venda FROM arla_precos_venda ORDER BY data_inicio DESC LIMIT 1
    """)
    preco_row = cursor.fetchone()
    preco_venda = float(preco_row['preco_venda']) if preco_row else 0
    
    # Busca clientes com ARLA configurado
    cursor.execute("""
        SELECT DISTINCT c.id, c.razao_social 
        FROM clientes c
        INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
        INNER JOIN produto p ON cp.produto_id = p.id
        WHERE p.nome = 'ARLA' AND cp.ativo = 1
        ORDER BY c.razao_social
    """)
    clientes_arla = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'arla/lancamento.html',
        ultimo_lancamento=ultimo_lancamento,
        encerrante_anterior=encerrante_anterior,
        preco_venda=preco_venda,
        clientes_arla=clientes_arla
    )


# =============================================
# LANÇAMENTO DIÁRIO - EDITAR (COM INTERVENÇÃO MANUAL)
# =============================================
@bp.route('/editar-lancamento/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_lancamento(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        encerrante_final = float(request.form['encerrante_final'])
        
        # Verifica se é intervenção manual
        intervencao_manual = request.form.get('intervencao_manual') == '1'
        
        if intervencao_manual:
            # Modo intervenção: usuário define quantidade_vendida manualmente
            quantidade_vendida = float(request.form['quantidade_vendida_manual'])
        else:
            # Modo normal: calcula baseado no encerrante
            cursor.execute("""
                SELECT encerrante_final FROM arla_lancamentos
                WHERE data < %s AND id != %s
                ORDER BY data DESC LIMIT 1
            """, (data, id))
            ante = cursor.fetchone()
            
            encerrante_anterior = ante['encerrante_final'] if ante else None
            
            if encerrante_anterior is None:
                cursor.execute("""
                    SELECT encerrante_inicial FROM arla_saldo_inicial
                    WHERE data <= %s ORDER BY data DESC LIMIT 1
                """, (data,))
                saldo_ini = cursor.fetchone()
                encerrante_anterior = saldo_ini['encerrante_inicial'] if saldo_ini else 0

            quantidade_vendida = encerrante_final - float(encerrante_anterior)

        cursor.execute("""
            SELECT preco_venda FROM arla_precos_venda WHERE data_inicio <= %s
            ORDER BY data_inicio DESC LIMIT 1
        """, (data,))
        preco_row = cursor.fetchone()
        preco_venda = preco_row['preco_venda'] if preco_row else 0

        cursor.execute("""
            UPDATE arla_lancamentos
            SET data = %s, encerrante_final = %s, quantidade_vendida = %s, preco_venda_aplicado = %s
            WHERE id = %s
        """, (data, encerrante_final, quantidade_vendida, preco_venda, id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Lançamento atualizado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_lancamentos WHERE id = %s", (id,))
    lancamento = cursor.fetchone()
    
    # Busca encerrante anterior para cálculo
    cursor.execute("""
        SELECT encerrante_final FROM arla_lancamentos
        WHERE data < %s AND id != %s
        ORDER BY data DESC LIMIT 1
    """, (lancamento['data'], id))
    ante = cursor.fetchone()
    encerrante_anterior = ante['encerrante_final'] if ante else None
    
    if encerrante_anterior is None:
        cursor.execute("""
            SELECT encerrante_inicial FROM arla_saldo_inicial
            WHERE data <= %s ORDER BY data DESC LIMIT 1
        """, (lancamento['data'],))
        saldo_ini = cursor.fetchone()
        encerrante_anterior = saldo_ini['encerrante_inicial'] if saldo_ini else 0
    
    cursor.close()
    conn.close()

    return render_template('arla/editar_lancamento.html', 
                          lancamento=lancamento, 
                          encerrante_anterior=encerrante_anterior)


