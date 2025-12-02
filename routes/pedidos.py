# Substitua a função importar_pedido no arquivo routes/pedidos.py pelo conteúdo abaixo
@bp.route('/importar/<int:id>')
@login_required
def importar_pedido(id):
    """
    Renderiza o template de detalhe do pedido para importação.
    Usado como detalhe ao escolher um pedido da lista.
    """
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Pedido + motorista/veiculo
    cursor.execute("""
        SELECT p.*,
               m.nome as motorista_nome,
               v.caminhao as veiculo_nome,
               v.placa as veiculo_placa
        FROM pedidos p
        LEFT JOIN motoristas m ON p.motorista_id = m.id
        LEFT JOIN veiculos v ON p.veiculo_id = v.id
        WHERE p.id = %s
    """, (id,))
    pedido = cursor.fetchone()
    if not pedido:
        cursor.close()
        conn.close()
        flash('Pedido não encontrado!', 'danger')
        return redirect(url_for('pedidos.importar_lista'))

    # Itens do pedido com joins para exibição + destino do cliente
    cursor.execute("""
        SELECT pi.*,
               c.razao_social as cliente_razao,
               c.paga_comissao as cliente_paga_comissao,
               c.percentual_cte as cliente_percentual_cte,
               c.cte_integral as cliente_cte_integral,
               c.destino_id as cliente_destino_id,
               d.nome as destino_nome,
               p.nome as produto_nome,
               f.razao_social as fornecedor_razao,
               o.nome as origem_nome,
               q.descricao as quantidade_descricao
        FROM pedidos_itens pi
        JOIN clientes c ON pi.cliente_id = c.id
        LEFT JOIN destinos d ON c.destino_id = d.id
        JOIN produto p ON pi.produto_id = p.id
        JOIN fornecedores f ON pi.fornecedor_id = f.id
        JOIN origens o ON pi.origem_id = o.id
        LEFT JOIN quantidades q ON pi.quantidade_id = q.id
        WHERE pi.pedido_id = %s
        ORDER BY f.nome_fantasia, c.razao_social
    """, (id,))
    itens = cursor.fetchall()

    # normalizar tipos para o template
    for item in itens:
        item['quantidade'] = float(item['quantidade']) if item.get('quantidade') is not None else 0.0
        item['preco_unitario'] = float(item['preco_unitario']) if item.get('preco_unitario') else 0.0
        item['total_nf'] = float(item['total_nf']) if item.get('total_nf') else 0.0
        item['cliente_paga_comissao'] = int(item.get('cliente_paga_comissao', 1))
        item['cliente_percentual_cte'] = float(item.get('cliente_percentual_cte', 0))
        item['cliente_cte_integral'] = int(item.get('cliente_cte_integral', 0))

    # Buscar rotas ativas e montar rotas_dict com PIPE "origem|destino" -> valor_por_litro
    cursor.execute("SELECT origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
    rotas_rows = cursor.fetchall()
    rotas_dict = {}
    for r in rotas_rows:
        chave = f"{r['origem_id']}|{r['destino_id']}"
        rotas_dict[chave] = float(r['valor_por_litro']) if r.get('valor_por_litro') is not None else 0.0

    cursor.close()
    conn.close()

    # Renderiza o template de importação (detalhe) — passamos rotas_dict
    return render_template('fretes/importar-pedido.html', pedido=pedido, itens=itens, rotas_dict=rotas_dict)
