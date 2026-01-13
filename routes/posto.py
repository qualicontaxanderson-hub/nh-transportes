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
