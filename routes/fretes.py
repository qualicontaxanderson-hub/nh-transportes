@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            # ===== DEBUG: VERIFICAR DADOS RECEBIDOS =====
            print("=" * 80)
            print("DEBUG - DADOS RECEBIDOS DO FORMULARIO:")
            print(f"  origem_id: {request.form.get('origem_id')}")
            print(f"  destino_id: {request.form.get('destino_id')}")
            print(f"  produto_id: {request.form.get('produto_id')}")
            print(f"  clientes_id: {request.form.get('clientes_id')}")
            print("=" * 80)
            
            # Validar campos obrigatórios
            origem_id = request.form.get('origem_id')
            destino_id = request.form.get('destino_id')
            
            if not destino_id or destino_id == '':
                flash('ERRO: Destino é obrigatório!', 'danger')
                print("ERRO: destino_id está vazio ou None")
                return redirect(url_for('fretes.editar', id=id))
            
            # FUNÇÃO PARA CONVERTER VALORES
            def converter_para_decimal(valor):
                if not valor:
                    return 0
                return float(str(valor).replace('.', '').replace(',', '.'))
            
            # Converter os valores antes de atualizar
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
                    request.form.get('quantidade_id'),
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
        
        # GET - Carrega dados para edição
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
        
        # Criar dicionário de rotas para JavaScript
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
