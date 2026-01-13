# ===========================================
# MÓDULO POSTO - Vendas do Posto de Gasolina
# ===========================================

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from models import db, Cliente, Produto, ClienteProduto
from datetime import datetime

# Criar blueprint do posto
posto_bp = Blueprint('posto', __name__)

# ============================================
# ADMINISTRAÇÃO: GERENCIAR PRODUTOS DO CLIENTE
# ============================================

@posto_bp.route('/admin/clientes')
@login_required
def admin_clientes():
    """Lista clientes para gerenciar produtos"""
    clientes = Cliente.query.order_by(Cliente.razao_social).all()
    
    # Contar quantos produtos cada cliente tem vinculado
    clientes_com_produtos = []
    for cliente in clientes:
        qtd_produtos = ClienteProduto.query.filter_by(
            cliente_id=cliente.id,
            ativo=True
        ).count()
        
        clientes_com_produtos.append({
            'cliente': cliente,
            'qtd_produtos': qtd_produtos
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
        
        # Buscar todas as vendas ordenadas por data
        vendas = VendasPosto.query.order_by(
            VendasPosto.data_movimento.desc()
        ).all()
        
        # Calcular totais
        total_litros = sum(v.quantidade_litros or 0 for v in vendas)
        total_valor = sum(v.valor_total or 0 for v in vendas)
        
        return render_template('posto/vendas_lista.html',
                             vendas=vendas,
                             total_litros=total_litros,
                             total_valor=total_valor)
    
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
        produtos = Produto.query.filter_by(ativo=True).order_by(Produto.nome).all()
        
        # Buscar vendedores (se o modelo existir)
        try:
            from models.vendedor import Vendedor
            vendedores = Vendedor.query.filter_by(ativo=True).all()
        except:
            vendedores = []
        
        return render_template('posto/vendas_lancar.html',
                             clientes=clientes,
                             produtos=produtos,
                             vendedores=vendedores)
    
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
        produtos = Produto.query.filter_by(ativo=True).order_by(Produto.nome).all()
        
        try:
            from models.vendedor import Vendedor
            vendedores = Vendedor.query.filter_by(ativo=True).all()
        except:
            vendedores = []
        
        return render_template('posto/vendas_lancar.html',
                             venda=venda,
                             clientes=clientes,
                             produtos=produtos,
                             vendedores=vendedores)
    
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
