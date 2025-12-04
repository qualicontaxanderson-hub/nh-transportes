@bp.route('/salvar_importados', methods=['POST'])
@login_required
def salvar_importados():
    """
    Recebe o form de importação (itens[...] inputs) e persiste cada item como um frete.
    Versão robusta: verifica flag do cliente para 'não paga frete' e força zeros.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        pedido_id = request.form.get('pedido_id')  # hidden do modal
        data_frete = request.form.get('data_frete') or None
        motorista_id = request.form.get('motorista_id') or None
        veiculo_id = request.form.get('veiculo_id') or None

        # descobrir quais índices de itens vieram no form:
        indices = set()
        for key in request.form.keys():
            # form keys no formato itens[<idx>][<campo>]
            if key.startswith('itens['):
                try:
                    inside = key[len('itens['):]
                    idx_str = inside.split(']')[0]
                    idx = int(idx_str)
                    indices.add(idx)
                except Exception:
                    continue
        if not indices:
            flash('Nenhum item encontrado no formulário de importação.', 'warning')
            return redirect(url_for('pedidos.importar_lista'))

        # função utilitária para obter tarifa por litro da rota (fallback consulta DB)
        def rota_valor_por_litro(origem_id, destino_id):
            try:
                if not origem_id or not destino_id:
                    return 0.0
                c = conn.cursor(dictionary=True)
                c.execute("SELECT valor_por_litro FROM rotas WHERE origem_id=%s AND destino_id=%s LIMIT 1",
                          (origem_id, destino_id))
                r = c.fetchone()
                c.close()
                if r and r.get('valor_por_litro') is not None:
                    return float(r.get('valor_por_litro'))
            except Exception:
                pass
            return 0.0

        # flags do modal (motorista) podem vir como inputs escondidos
        motorista_paga_comissao = request.form.get('import_motorista_paga_comissao')
        motorista_paga_comissao = int(motorista_paga_comissao) if motorista_paga_comissao not in (None, '') else 1

        # Inserir todos os itens (usar transação única)
        for idx in sorted(indices):
            # ler explicitamente cada campo do item
            prefix = f'itens[{idx}]'
            clientes_id = request.form.get(f'{prefix}[cliente_id]') or None
            produto_id = request.form.get(f'{prefix}[produto_id]') or None
            fornecedores_id = request.form.get(f'{prefix}[fornecedor_id]') or None
            origem_id = request.form.get(f'{prefix}[origem_id]') or None
            destino_id = request.form.get(f'{prefix}[destino_id]') or request.form.get(f'{prefix}[cliente_destino_id]') or None
            quantidade_raw = request.form.get(f'{prefix}[quantidade]') or '0'
            quantidade = parse_moeda(quantidade_raw)
            quantidade_id = request.form.get(f'{prefix}[quantidade_id]') or None

            # status do item (leitura direta)
            status_item = (request.form.get(f'{prefix}[status]') or 'Pendente').strip()

            preco_unit = parse_moeda(request.form.get(f'{prefix}[preco_unitario]') or request.form.get(f'{prefix}[preco_unitario_raw]') or '0')
            total_nf = parse_moeda(request.form.get(f'{prefix}[total_nf]') or '0')
            if total_nf == 0 and quantidade > 0 and preco_unit > 0:
                total_nf = preco_unit * quantidade

            preco_por_litro = parse_moeda(request.form.get(f'{prefix}[preco_por_litro]') or request.form.get(f'{prefix}[preco_por_litro_raw]') or '0')
            if (preco_por_litro == 0 or preco_por_litro is None) and quantidade > 0 and total_nf > 0:
                preco_por_litro = total_nf / quantidade if quantidade > 0 else 0

            valor_total_frete = parse_moeda(request.form.get(f'{prefix}[valor_total_frete]') or '0')
            if (valor_total_frete == 0 or valor_total_frete is None) and quantidade > 0 and preco_por_litro > 0:
                valor_total_frete = quantidade * preco_por_litro

            valor_cte = parse_moeda(request.form.get(f'{prefix}[valor_cte]') or '0')
            if (valor_cte == 0 or valor_cte is None):
                tarifa = rota_valor_por_litro(origem_id, destino_id)
                valor_cte = quantidade * tarifa if quantidade and tarifa else 0.0

            comissao_cte = round(valor_cte * 0.08, 2)

            # --- NOVO: verificar se o cliente PAGA frete/comissão; se não, forçar zeros ---
            cliente_paga_frete = True
            try:
                if clientes_id:
                    cchk = conn.cursor(dictionary=True)
                    cchk.execute("SELECT paga_frete, paga_comissao, paga_frete AS paga_frete_alt FROM clientes WHERE id=%s LIMIT 1", (clientes_id,))
                    crow = cchk.fetchone()
                    cchk.close()
                    if crow:
                        # detectar campo válido (paga_frete ou paga_comissao)
                        if 'paga_frete' in crow and crow.get('paga_frete') is not None:
                            cliente_paga_frete = bool(crow.get('paga_frete'))
                        elif 'paga_comissao' in crow and crow.get('paga_comissao') is not None:
                            cliente_paga_frete = bool(crow.get('paga_comissao'))
            except Exception:
                cliente_paga_frete = True

            # Se cliente NÃO paga frete, zera preço por litro, valor do frete e comissão do motorista
            if not cliente_paga_frete:
                preco_por_litro = 0
                valor_total_frete = 0
                comissao_motorista = 0.0
            else:
                # comissao_motorista calculada normalmente (se motorista_paga_comissao)
                if motorista_paga_comissao and quantidade:
                    try:
                        if int(motorista_paga_comissao) == 0:
                            comissao_motorista = 0.0
                        else:
                            comissao_motorista = round(quantidade * 0.01, 2)
                    except Exception:
                        comissao_motorista = round(quantidade * 0.01, 2) if quantidade else 0.0
                else:
                    comissao_motorista = 0.0

            # Se cliente paga frete = False, lucro será negativo do CTe/CTe comissao etc.
            lucro = 0.0
            if valor_total_frete:
                lucro = round(float(valor_total_frete) - float(comissao_motorista) - float(comissao_cte), 2)
            else:
                lucro = round(0.0 - float(comissao_cte) - float(comissao_motorista), 2) if (comissao_cte or comissao_motorista) else 0.0

            # inserir no banco
            cursor.execute("""
                INSERT INTO fretes (
                    data_frete, status, observacoes,
                    clientes_id, fornecedores_id, produto_id,
                    origem_id, destino_id,
                    motoristas_id, veiculos_id,
                    quantidade_id, quantidade_manual,
                    preco_produto_unitario, preco_por_litro,
                    total_nf_compra, valor_total_frete,
                    comissao_motorista, valor_cte, comissao_cte, lucro
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                data_frete,
                status_item,
                request.form.get('observacoes') or '',
                clientes_id,
                fornecedores_id,
                produto_id,
                origem_id,
                destino_id,
                motorista_id,
                veiculo_id,
                quantidade_id or None,
                (request.form.get(f'{prefix}[quantidade]') or None),
                preco_unit or 0,
                preco_por_litro or 0,
                total_nf or 0,
                valor_total_frete or 0,
                comissao_motorista or 0,
                valor_cte or 0,
                comissao_cte or 0,
                lucro or 0,
            ))

        # Commit das inserções
        conn.commit()

        # Atualizar pedido para Faturado (somente se veio pedido_id)
        if pedido_id:
            try:
                c2 = conn.cursor()
                c2.execute("UPDATE pedidos SET status = %s WHERE id = %s", ('Faturado', pedido_id))
                conn.commit()
                c2.close()
            except Exception:
                conn.rollback()

        flash('Importação salva: fretes criados com sucesso.', 'success')
        if pedido_id:
            return redirect(url_for('pedidos.visualizar', id=pedido_id))
        return redirect(url_for('fretes.lista'))

    except Exception as e:
        conn.rollback()
        flash(f'Erro ao salvar importados: {e}', 'danger')
        return redirect(url_for('pedidos.importar_lista'))
    finally:
        cursor.close()
        conn.close()
