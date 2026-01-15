# ===========================================
# MÓDULO POSTO - Vendas do Posto de Gasolina
# ===========================================

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from models import db, Cliente, Produto, ClienteProduto
from datetime import datetime

# Criar blueprint do posto
posto_bp = Blueprint('posto', __name__, url_prefix='/posto')

# ============================================
# ADMINISTRAÇÃO: GERENCIAR PRODUTOS DO CLIENTE
# ============================================

@posto_bp.route('/admin/clientes')
@login_required
def admin_clientes():
    """Lista clientes para gerenciar produtos"""
    clientes = Cliente.query.order_by(Cliente.razao_social).all()
    
    # Buscar produtos vinculados para cada cliente
    clientes_com_produtos = []
    for cliente in clientes:
        # Buscar produtos ativos vinculados ao cliente
        vinculos = ClienteProduto.query.filter_by(
            cliente_id=cliente.id,
            ativo=True
        ).all()
        
        # Buscar nomes dos produtos
        produtos_nomes = []
        for vinculo in vinculos:
            produto = Produto.query.get(vinculo.produto_id)
            if produto:
                produtos_nomes.append(produto.nome)
        
        clientes_com_produtos.append({
            'cliente': cliente,
            'produtos': produtos_nomes,
            'qtd_produtos': len(produtos_nomes)
        })
    
    return render_template('posto/admin_clientes.html',
                         clientes_com_produtos=clientes_com_produtos)


@posto_bp.route('/admin/cliente/<int:cliente_id>/produtos', methods=['GET', 'POST'])
@login_required
def admin_produtos_cliente(cliente_id):
    """Gerenciar produtos que o cliente pode vender"""
    cliente = Cliente.query.get_or_404(cliente_id)
    
    if request.method == 'POST':
        try:
            # Pegar produtos selecionados
            produtos_selecionados = request.form.getlist('produtos')
            produtos_selecionados = [int(p) for p in produtos_selecionados]
            
            # Buscar todos os produtos
            todos_produtos = Produto.query.all()
            
            # Processar cada produto
            for produto in todos_produtos:
                vinculo_existe = ClienteProduto.query.filter_by(
                    cliente_id=cliente_id,
                    produto_id=produto.id
                ).first()
                
                if produto.id in produtos_selecionados:
                    # Deve estar ativo
                    if vinculo_existe:
                        vinculo_existe.ativo = True
                    else:
                        novo_vinculo = ClienteProduto(
                            cliente_id=cliente_id,
                            produto_id=produto.id,
                            ativo=True
                        )
                        db.session.add(novo_vinculo)
                else:
                    # Deve estar inativo
                    if vinculo_existe:
                        vinculo_existe.ativo = False
            
            db.session.commit()
            flash(f'✅ Produtos atualizados para {cliente.razao_social}!', 'success')
            return redirect(url_for('posto.admin_clientes'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erro ao salvar: {str(e)}', 'danger')
    
    # GET - Mostrar formulário
    todos_produtos = Produto.query.order_by(Produto.nome).all()
    
    # Buscar produtos já vinculados
    produtos_vinculados = ClienteProduto.query.filter_by(
        cliente_id=cliente_id,
        ativo=True
    ).all()
    produtos_vinculados_ids = [v.produto_id for v in produtos_vinculados]
    
    return render_template('posto/admin_produtos_cliente.html',
                         cliente=cliente,
                         todos_produtos=todos_produtos,
                         produtos_vinculados_ids=produtos_vinculados_ids)


# ============================================
# VENDAS DO POSTO
# ============================================

@posto_bp.route('/vendas')
@login_required
def vendas_lista():
    """Lista todas as vendas do posto de gasolina"""
    try:
        from models.vendas_posto import VendasPosto
        from collections import defaultdict
        
        # Obter filtros da query string
        filtros = {
            'data_inicio': request.args.get('data_inicio', ''),
            'data_fim': request.args.get('data_fim', ''),
            'cliente_id': request.args.get('cliente_id', '')
        }
        
        # Buscar vendas com filtros
        query = VendasPosto.query
        
        if filtros['data_inicio']:
            query = query.filter(VendasPosto.data_movimento >= filtros['data_inicio'])
        if filtros['data_fim']:
            query = query.filter(VendasPosto.data_movimento <= filtros['data_fim'])
        if filtros['cliente_id']:
            query = query.filter(VendasPosto.cliente_id == int(filtros['cliente_id']))
        
        vendas = query.order_by(VendasPosto.data_movimento.desc()).all()
        
        # Organizar vendas por data e cliente
        vendas_organizadas = {}
        for venda in vendas:
            # Criar chave única: data + cliente_id
            key = f"{venda.data_movimento}_{venda.cliente_id}"
            
            if key not in vendas_organizadas:
                vendas_organizadas[key] = {
                    'data': venda.data_movimento,
                    'cliente': venda.cliente,
                    'produtos': [],
                    'total_litros': 0,
                    'total_valor': 0
                }
            
            vendas_organizadas[key]['produtos'].append({
                'produto': venda.produto,
                'litros': venda.quantidade_litros or 0,
                'valor': venda.valor_total or 0,
                'preco_medio': venda.preco_medio or 0
            })
            vendas_organizadas[key]['total_litros'] += venda.quantidade_litros or 0
            vendas_organizadas[key]['total_valor'] += venda.valor_total or 0
        
        # Buscar todos os clientes para o filtro
        clientes = Cliente.query.order_by(Cliente.razao_social).all()
        
        return render_template('posto/vendas_lista.html',
                             vendas_organizadas=vendas_organizadas,
                             filtros=filtros,
                             clientes=clientes)
    
    except Exception as e:
        flash(f'❌ Erro ao carregar vendas: {str(e)}', 'danger')
        return redirect(url_for('index'))


@posto_bp.route('/vendas/lancar', methods=['GET', 'POST'])
@login_required
def vendas_lancar():
    """Formulário para lançar nova venda do posto"""
    try:
        from models.vendas_posto import VendasPosto
        
        if request.method == 'POST':
            # Processar formulário
            data_movimento = request.form.get('data_movimento')
            cliente_id = request.form.get('cliente_id')
            produto_id = request.form.get('produto_id')
            vendedor_id = request.form.get('vendedor_id') or None
            quantidade_litros = float(request.form.get('quantidade_litros', 0))
            preco_medio = float(request.form.get('preco_medio', 0))
            valor_total = float(request.form.get('valor_total', 0))
            
            # Criar nova venda
            nova_venda = VendasPosto(
                cliente_id=int(cliente_id) if cliente_id else None,
                data_movimento=datetime.strptime(data_movimento, '%Y-%m-%d').date(),
                produto_id=int(produto_id),
                vendedor_id=int(vendedor_id) if vendedor_id else None,
                quantidade_litros=quantidade_litros,
                preco_medio=preco_medio,
                valor_total=valor_total
            )
            
            db.session.add(nova_venda)
            db.session.commit()
            
            flash('✅ Venda lançada com sucesso!', 'success')
            return redirect(url_for('posto.vendas_lista'))
        
        # GET - Mostrar formulário
        clientes = Cliente.query.order_by(Cliente.razao_social).all()
        produtos = Produto.query.order_by(Produto.nome).all()
        
        # Buscar vendedores (usando motoristas como vendedores)
        try:
            from models.motorista import Motorista
            vendedores = Motorista.query.order_by(Motorista.nome).all()
        except Exception as e:
            print(f"Erro ao buscar vendedores: {e}")
            vendedores = []
        
        # Buscar última data de lançamento por cliente
        ultima_data_por_cliente = {}
        for cliente in clientes:
            ultima_venda = VendasPosto.query.filter_by(cliente_id=cliente.id)\
                .order_by(VendasPosto.data_movimento.desc()).first()
            if ultima_venda:
                ultima_data_por_cliente[cliente.id] = ultima_venda.data_movimento.strftime('%Y-%m-%d')
        
        return render_template('posto/vendas_lancar.html',
                             clientes=clientes,
                             produtos=produtos,
                             vendedores=vendedores,
                             ultima_data_por_cliente=ultima_data_por_cliente,
                             hoje=datetime.now())
    
    except Exception as e:
        flash(f'❌ Erro ao processar venda: {str(e)}', 'danger')
        return redirect(url_for('posto.vendas_lista'))


@posto_bp.route('/vendas/<int:venda_id>/editar', methods=['GET', 'POST'])
@login_required
def vendas_editar(venda_id):
    """Editar uma venda existente"""
    try:
        from models.vendas_posto import VendasPosto
        
        venda = VendasPosto.query.get_or_404(venda_id)
        
        if request.method == 'POST':
            # Atualizar venda
            venda.data_movimento = datetime.strptime(
                request.form.get('data_movimento'), '%Y-%m-%d'
            ).date()
            venda.cliente_id = int(request.form.get('cliente_id')) if request.form.get('cliente_id') else None
            venda.produto_id = int(request.form.get('produto_id'))
            venda.vendedor_id = int(request.form.get('vendedor_id')) if request.form.get('vendedor_id') else None
            venda.quantidade_litros = float(request.form.get('quantidade_litros', 0))
            venda.preco_medio = float(request.form.get('preco_medio', 0))
            venda.valor_total = float(request.form.get('valor_total', 0))
            
            db.session.commit()
            
            flash('✅ Venda atualizada com sucesso!', 'success')
            return redirect(url_for('posto.vendas_lista'))
        
        # GET - Mostrar formulário preenchido
        clientes = Cliente.query.order_by(Cliente.razao_social).all()
        produtos = Produto.query.order_by(Produto.nome).all()
        
        try:
            from models.motorista import Motorista
            vendedores = Motorista.query.order_by(Motorista.nome).all()
        except Exception as e:
            print(f"Erro ao buscar vendedores: {e}")
            vendedores = []
        
        # Buscar última data de lançamento por cliente
        ultima_data_por_cliente = {}
        for cliente in clientes:
            ultima_venda = VendasPosto.query.filter_by(cliente_id=cliente.id)\
                .order_by(VendasPosto.data_movimento.desc()).first()
            if ultima_venda:
                ultima_data_por_cliente[cliente.id] = ultima_venda.data_movimento.strftime('%Y-%m-%d')
        
        return render_template('posto/vendas_lancar.html',
                             venda=venda,
                             clientes=clientes,
                             produtos=produtos,
                             vendedores=vendedores,
                             ultima_data_por_cliente=ultima_data_por_cliente,
                             hoje=datetime.now())
    
    except Exception as e:
        flash(f'❌ Erro ao editar venda: {str(e)}', 'danger')
        return redirect(url_for('posto.vendas_lista'))


@posto_bp.route('/vendas/<int:venda_id>/deletar', methods=['POST'])
@login_required
def vendas_deletar(venda_id):
    """Deletar uma venda"""
    try:
        from models.vendas_posto import VendasPosto
        
        venda = VendasPosto.query.get_or_404(venda_id)
        
        db.session.delete(venda)
        db.session.commit()
        
        flash('✅ Venda deletada com sucesso!', 'success')
    
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Erro ao deletar venda: {str(e)}', 'danger')
    
    return redirect(url_for('posto.vendas_lista'))
