# ===========================================
# MÓDULO POSTO - Vendas do Posto de Gasolina
# ===========================================

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models import db, Cliente, Produto, ClienteProduto
from datetime import datetime

# Criar blueprint do posto
posto_bp = Blueprint('posto', __name__, url_prefix='/posto')

# Ordem padrão de produtos
ORDEM_PRODUTOS = {
    'ETANOL': 1,
    'GASOLINA': 2,
    'GASOLINA ADITIVADA': 3,
    'S-10': 4,
    'S-500': 5
}

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
# API ENDPOINTS
# ============================================

@posto_bp.route('/api/produtos-cliente/<int:cliente_id>')
@login_required
def api_produtos_cliente(cliente_id):
    """API: Retorna produtos ativos de um cliente em ordem específica"""
    try:
        cliente = Cliente.query.get(cliente_id)
        if not cliente:
            return jsonify({'success': False, 'error': 'Cliente não encontrado'}), 404
        
        # Buscar produtos ativos vinculados ao cliente
        vinculos = ClienteProduto.query.filter_by(
            cliente_id=cliente_id,
            ativo=True
        ).all()
        
        produtos = []
        for vinculo in vinculos:
            produto = Produto.query.get(vinculo.produto_id)
            if produto:
                produtos.append({
                    'id': produto.id,
                    'nome': produto.nome,
                    'descricao': produto.descricao or ''
                })
        
        # Ordenar produtos usando ordem padrão
        produtos = sorted(produtos, key=lambda p: ORDEM_PRODUTOS.get(p['nome'].upper(), 999))
        
        return jsonify({
            'success': True,
            'produtos': produtos
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
        from datetime import date
        
        # Default to current month if no filters provided
        hoje = date.today()
        primeiro_dia_mes = hoje.replace(day=1)
        data_inicio_default = primeiro_dia_mes.strftime('%Y-%m-%d')
        data_fim_default = hoje.strftime('%Y-%m-%d')
        
        # Obter filtros da query string
        filtros = {
            'data_inicio': request.args.get('data_inicio', data_inicio_default),
            'data_fim': request.args.get('data_fim', data_fim_default),
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
                    'cliente_id': venda.cliente_id,
                    'produtos': [],
                    'total_litros': 0,
                    'total_valor': 0
                }
            
            produto_nome = venda.produto.nome if venda.produto else 'Desconhecido'
            vendas_organizadas[key]['produtos'].append({
                'produto': venda.produto,
                'litros': venda.quantidade_litros or 0,
                'valor': venda.valor_total or 0,
                'preco_medio': venda.preco_medio or 0,
                'venda_id': venda.id,  # Adicionar ID da venda para botão editar
                'ordem': ORDEM_PRODUTOS.get(produto_nome.upper(), 999)
            })
            vendas_organizadas[key]['total_litros'] += venda.quantidade_litros or 0
            vendas_organizadas[key]['total_valor'] += venda.valor_total or 0
        
        # Sort products within each day by ordem
        for key in vendas_organizadas:
            vendas_organizadas[key]['produtos'].sort(key=lambda p: p['ordem'])
        
        # Calculate summary by product
        resumo_por_produto = {}
        for venda in vendas:
            produto_nome = venda.produto.nome if venda.produto else 'Desconhecido'
            if produto_nome not in resumo_por_produto:
                resumo_por_produto[produto_nome] = {
                    'litros': 0,
                    'valor_total': 0
                }
            resumo_por_produto[produto_nome]['litros'] += float(venda.quantidade_litros or 0)
            resumo_por_produto[produto_nome]['valor_total'] += float(venda.valor_total or 0)
        
        # Calculate average price for each product
        resumo_lista = []
        for produto_nome, dados in resumo_por_produto.items():
            preco_medio = dados['valor_total'] / dados['litros'] if dados['litros'] > 0 else 0
            resumo_lista.append({
                'produto': produto_nome,
                'litros': dados['litros'],
                'valor_total': dados['valor_total'],
                'preco_medio': preco_medio,
                'ordem': ORDEM_PRODUTOS.get(produto_nome.upper(), 999)
            })
        resumo_lista.sort(key=lambda x: x['ordem'])
        
        # Buscar todos os clientes para o filtro
        clientes = Cliente.query.order_by(Cliente.razao_social).all()
        
        return render_template('posto/vendas_lista.html',
                             vendas_organizadas=vendas_organizadas,
                             filtros=filtros,
                             clientes=clientes,
                             resumo_por_produto=resumo_lista)
    
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
            # Processar formulário - múltiplos produtos de uma vez
            data_movimento = request.form.get('data_movimento')
            cliente_id = request.form.get('cliente_id')
            
            # Processar produtos - o formulário envia quantidade_X e valor_X para cada produto
            vendas_criadas = 0
            produtos = Produto.query.all()
            produtos_ordenados = sorted(produtos, key=lambda p: ORDEM_PRODUTOS.get(p.nome.upper(), 999))
            
            for produto in produtos_ordenados:
                quantidade_key = f'quantidade_{produto.id}'
                valor_key = f'valor_{produto.id}'
                
                quantidade_str = request.form.get(quantidade_key, '').replace('.', '').replace(',', '.')
                valor_str = request.form.get(valor_key, '').replace('R$', '').replace('.', '').replace(',', '.').strip()
                
                if quantidade_str and valor_str:
                    try:
                        quantidade_litros = float(quantidade_str)
                        valor_total = float(valor_str)
                        
                        # Só processar se quantidade e valor forem maiores que 0
                        if quantidade_litros > 0 and valor_total > 0:
                            preco_medio = valor_total / quantidade_litros
                            
                            # Criar nova venda
                            nova_venda = VendasPosto(
                                cliente_id=int(cliente_id) if cliente_id else None,
                                data_movimento=datetime.strptime(data_movimento, '%Y-%m-%d').date(),
                                produto_id=produto.id,
                                vendedor_id=None,  # Vendedor não é usado neste fluxo
                                quantidade_litros=quantidade_litros,
                                preco_medio=preco_medio,
                                valor_total=valor_total
                            )
                            
                            db.session.add(nova_venda)
                            vendas_criadas += 1
                    except (ValueError, ZeroDivisionError) as e:
                        continue  # Ignorar produtos com dados inválidos
            
            if vendas_criadas == 0:
                flash('❌ Nenhum produto foi lançado. Preencha ao menos um produto com quantidade e valor!', 'warning')
                return redirect(url_for('posto.vendas_lancar'))
            
            db.session.commit()
            
            flash(f'✅ {vendas_criadas} venda(s) lançada(s) com sucesso!', 'success')
            return redirect(url_for('posto.vendas_lista'))
        
        # GET - Mostrar formulário
        # Filtrar apenas clientes que têm produtos cadastrados
        clientes_com_produtos = []
        todos_clientes = Cliente.query.order_by(Cliente.razao_social).all()
        
        for cliente in todos_clientes:
            tem_produtos = ClienteProduto.query.filter_by(
                cliente_id=cliente.id,
                ativo=True
            ).first()
            if tem_produtos:
                clientes_com_produtos.append(cliente)
        
        clientes = clientes_com_produtos
        
        # Buscar todos produtos ordenados
        produtos = Produto.query.all()
        produtos = sorted(produtos, key=lambda p: ORDEM_PRODUTOS.get(p.nome.upper(), 999))
        
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


@posto_bp.route('/vendas/editar/<data>/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
def vendas_editar_data(data, cliente_id):
    """Editar todas as vendas de uma data + cliente específicos"""
    try:
        from models.vendas_posto import VendasPosto
        
        # Parse date
        data_movimento = datetime.strptime(data, '%Y-%m-%d').date()
        
        # Buscar todas as vendas desta data + cliente
        vendas = VendasPosto.query.filter_by(
            data_movimento=data_movimento,
            cliente_id=cliente_id
        ).all()
        
        if not vendas:
            flash('❌ Nenhuma venda encontrada para esta data e cliente!', 'warning')
            return redirect(url_for('posto.vendas_lista'))
        
        cliente = Cliente.query.get_or_404(cliente_id)
        
        if request.method == 'POST':
            # Processar atualização de múltiplos produtos
            vendas_atualizadas = 0
            produtos = Produto.query.all()
            produtos_ordenados = sorted(produtos, key=lambda p: ORDEM_PRODUTOS.get(p.nome.upper(), 999))
            
            for produto in produtos_ordenados:
                quantidade_key = f'quantidade_{produto.id}'
                valor_key = f'valor_{produto.id}'
                
                quantidade_str = request.form.get(quantidade_key, '').replace('.', '').replace(',', '.')
                valor_str = request.form.get(valor_key, '').replace('R$', '').replace('.', '').replace(',', '.').strip()
                
                # Buscar venda existente para este produto
                venda_existente = next((v for v in vendas if v.produto_id == produto.id), None)
                
                if quantidade_str and valor_str:
                    try:
                        quantidade_litros = float(quantidade_str)
                        valor_total = float(valor_str)
                        
                        if quantidade_litros > 0 and valor_total > 0:
                            preco_medio = valor_total / quantidade_litros
                            
                            if venda_existente:
                                # Atualizar venda existente
                                venda_existente.quantidade_litros = quantidade_litros
                                venda_existente.preco_medio = preco_medio
                                venda_existente.valor_total = valor_total
                            else:
                                # Criar nova venda (produto foi adicionado)
                                nova_venda = VendasPosto(
                                    cliente_id=cliente_id,
                                    data_movimento=data_movimento,
                                    produto_id=produto.id,
                                    vendedor_id=None,
                                    quantidade_litros=quantidade_litros,
                                    preco_medio=preco_medio,
                                    valor_total=valor_total
                                )
                                db.session.add(nova_venda)
                            vendas_atualizadas += 1
                        elif venda_existente:
                            # Quantidade ou valor zerados - deletar venda
                            db.session.delete(venda_existente)
                    except (ValueError, ZeroDivisionError):
                        continue
                elif venda_existente:
                    # Campos vazios - deletar venda
                    db.session.delete(venda_existente)
            
            if vendas_atualizadas == 0:
                flash('❌ Nenhum produto foi atualizado. Preencha ao menos um produto com quantidade e valor!', 'warning')
                return redirect(url_for('posto.vendas_editar_data', data=data, cliente_id=cliente_id))
            
            db.session.commit()
            flash(f'✅ {vendas_atualizadas} venda(s) atualizada(s) com sucesso!', 'success')
            return redirect(url_for('posto.vendas_lista'))
        
        # GET - Mostrar formulário com vendas preenchidas
        # Buscar produtos do cliente
        vinculos = ClienteProduto.query.filter_by(
            cliente_id=cliente_id,
            ativo=True
        ).all()
        
        produtos_cliente_ids = [v.produto_id for v in vinculos]
        produtos = Produto.query.filter(Produto.id.in_(produtos_cliente_ids)).all()
        produtos = sorted(produtos, key=lambda p: ORDEM_PRODUTOS.get(p.nome.upper(), 999))
        
        # Criar dicionário com valores existentes
        vendas_por_produto = {v.produto_id: v for v in vendas}
        
        # Buscar clientes para o select (mesmo que disabled)
        clientes = Cliente.query.order_by(Cliente.razao_social).all()
        
        return render_template('posto/vendas_lancar.html',
                             modo_edicao_data=True,
                             data_edicao=data_movimento,
                             cliente_edicao=cliente,
                             produtos=produtos,
                             vendas_por_produto=vendas_por_produto,
                             clientes=clientes,
                             hoje=datetime.now())
    
    except Exception as e:
        flash(f'❌ Erro ao editar vendas: {str(e)}', 'danger')
        return redirect(url_for('posto.vendas_lista'))


@posto_bp.route('/vendas/<int:venda_id>/editar', methods=['GET', 'POST'])
@login_required
def vendas_editar(venda_id):
    """Editar uma venda existente (OLD - mantido para compatibilidade)"""
    try:
        from models.vendas_posto import VendasPosto
        
        venda = VendasPosto.query.get_or_404(venda_id)
        
        # Redirecionar para nova rota de edição por data
        return redirect(url_for('posto.vendas_editar_data', 
                               data=venda.data_movimento.strftime('%Y-%m-%d'),
                               cliente_id=venda.cliente_id))
    
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
