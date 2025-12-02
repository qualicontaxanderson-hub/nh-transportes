from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('fretes', __name__, url_prefix='/fretes')


# ============================================
# FUNÇÃO DE LIMPEZA DE MOEDA - ADICIONAR AQUI
# ============================================
def limpar_moeda(valor_str):
    """
    Remove formatação brasileira de moeda antes de converter para float
    Exemplo: "R$ 1.250,50" → 1250.50
    """
    if not valor_str or str(valor_str).strip() == '':
        return 0.0
    
    # Remove R$, espaços e formata
    valor = str(valor_str).replace('R$', '').strip()
    valor = valor.replace('.', '')  # Remove separador de milhar
    valor = valor.replace(',', '.')  # Troca vírgula por ponto decimal
    
    try:
        return float(valor)
    except ValueError:
        return 0.0


@bp.route('/importar/<int:pedido_id>')
@login_required
def importar_pedido(pedido_id):
    """Tela de importação: carrega pedido e itens, mostra formulário com múltiplos itens"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # TITLE: Buscar dados do pedido
        cursor.execute("""
            SELECT p.*, 
                   m.nome as motorista_nome,
                   v.caminhao as veiculo_nome,
                   v.placa as veiculo_placa
            FROM pedidos p
            LEFT JOIN motoristas m ON p.motorista_id = m.id
            LEFT JOIN veiculos v ON p.veiculo_id = v.id
            WHERE p.id = %s
        """, (pedido_id,))
        pedido = cursor.fetchone()
        
        if not pedido:
            flash('Pedido não encontrado!', 'danger')
            return redirect(url_for('fretes.novo'))
        
        # TITLE: Buscar itens do pedido com destino do cliente
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
            ORDER BY pi.id
        """, (pedido_id,))
        itens = cursor.fetchall()
        
        if not itens:
            flash('Este pedido não possui itens!', 'warning')
            return redirect(url_for('fretes.novo'))
        
        # TITLE: CORREÇÃO - Buscar rotas com PIPE
        cursor.execute("SELECT id, origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
        rotas = cursor.fetchall()
        rotas_dict = {}
        for rota in rotas:
            chave = f"{rota['origem_id']}|{rota['destino_id']}"  # PIPE
            rotas_dict[chave] = rota['valor_por_litro']
        
        cursor.close()
        conn.close()
        
        return render_template(
            'fretes/importar-pedido.html',
            pedido=pedido,
            itens=itens,
            rotas_dict=rotas_dict
        )
    except Exception as e:
        print(f"Erro ao carregar pedido para importação: {e}")
        flash(f'Erro ao carregar pedido: {str(e)}', 'danger')
        return redirect(url_for('fretes.novo'))


@bp.route('/salvar-importados', methods=['POST'])
@login_required
def salvar_importados():
    """Salva múltiplos fretes de uma vez (vindo da importação do pedido)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        pedido_id = request.form.get('pedido_id')
        data_frete = request.form.get('data_frete')
        motorista_id = request.form.get('motorista_id')
        veiculo_id = request.form.get('veiculo_id')
        
        # TITLE: Listas de dados dos itens
        clientes_ids = request.form.getlist('cliente_id')
        produtos_ids = request.form.getlist('produto_id')
        fornecedores_ids = request.form.getlist('fornecedor_id')
        origens_ids = request.form.getlist('origem_id')
        destinos_ids = request.form.getlist('destino_id')
        quantidades = request.form.getlist('quantidade')
        quantidades_ids = request.form.getlist('quantidade_id')
        precos_unitarios = request.form.getlist('preco_unitario')
        totais_nf = request.form.getlist('total_nf')
        precos_por_litro = request.form.getlist('preco_por_litro')
        valores_totais_frete = request.form.getlist('valor_total_frete')
        comissoes_motorista = request.form.getlist('comissao_motorista')
        valores_cte = request.form.getlist('valor_cte')
        comissoes_cte = request.form.getlist('comissao_cte')
        lucros = request.form.getlist('lucro')
        status_list = request.form.getlist('status')
        
        fretes_criados = 0
        for i in range(len(clientes_ids)):
            qtd_id = quantidades_ids[i] if quantidades_ids[i] else None
            
            # ✅ CORREÇÃO: Usar limpar_moeda() em todos os campos monetários
            cursor.execute("""
                INSERT INTO fretes (
                    clientes_id, produto_id, fornecedores_id, motoristas_id, veiculos_id,
                    quantidade_id, quantidade_manual, origem_id, destino_id,
                    preco_produto_unitario, total_nf_compra, preco_por_litro, valor_total_frete,
                    comissao_motorista, valor_cte, comissao_cte, lucro, data_frete, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                clientes_ids[i],
                produtos_ids[i],
                fornecedores_ids[i],
                motorista_id,
                veiculo_id,
                qtd_id,
                limpar_moeda(quantidades[i]) if not qtd_id else None,
                origens_ids[i],
                destinos_ids[i],
                limpar_moeda(precos_unitarios[i]),      # ✅ CORRIGIDO
                limpar_moeda(totais_nf[i]),             # ✅ CORRIGIDO
                limpar_moeda(precos_por_litro[i]),      # ✅ CORRIGIDO
                limpar_moeda(valores_totais_frete[i]),  # ✅ CORRIGIDO
                limpar_moeda(comissoes_motorista[i]),   # ✅ CORRIGIDO
                limpar_moeda(valores_cte[i]),           # ✅ CORRIGIDO
                limpar_moeda(comissoes_cte[i]),         # ✅ CORRIGIDO
                limpar_moeda(lucros[i]),                # ✅ CORRIGIDO
                data_frete,
                status_list[i]
            ))
            fretes_criados += 1
        
        # TITLE: Atualizar status do pedido para "Faturado"
        cursor.execute("UPDATE pedidos SET status = 'Faturado' WHERE id = %s", (pedido_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash(f'{fretes_criados} fretes criados com sucesso! Pedido marcado como "Faturado".', 'success')
        return redirect(url_for('fretes.lista'))
    except Exception as e:
        print(f"Erro ao salvar fretes importados: {e}")
        flash(f'Erro ao salvar fretes: {str(e)}', 'danger')
        return redirect(url_for('fretes.novo'))


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    pedido_id = request.args.get('pedido_id', type=int)
    
    if request.method == 'POST':
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # TITLE: Tipo de quantidade (personalizada ou padrão)
            quantidade_tipo = request.form.get('quantidade_tipo')
            if quantidade_tipo == 'personalizada':
                quantidade_id_para_salvar = None
            else:
                quantidade_id_para_salvar = request.form.get('quantidade_id')
            
            # ✅ CORREÇÃO: Usar limpar_moeda() em todos os campos monetários
            preco_produto_unitario = limpar_moeda(request.form.get('preco_produto_unitario'))
            total_nf_compra = limpar_moeda(request.form.get('total_nf_compra'))
            preco_por_litro = limpar_moeda(request.form.get('preco_por_litro'))
            valor_total_frete = limpar_moeda(request.form.get('valor_total_frete'))
            comissao_motorista = limpar_moeda(request.form.get('comissao_motorista'))
            valor_cte = limpar_moeda(request.form.get('valor_cte'))
            comissao_cte = limpar_moeda(request.form.get('comissao_cte'))
            lucro = limpar_moeda(request.form.get('lucro'))
            
            cursor.execute("""
                INSERT INTO fretes (
                    clientes_id, produto_id, fornecedores_id, motoristas_id, veiculos_id,
                    quantidade_id, origem_id, destino_id,
                    preco_produto_unitario, total_nf_compra, preco_por_litro, valor_total_frete,
                    comissao_motorista, valor_cte, comissao_cte, lucro, data_frete, status, observacoes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('clientes_id'),
                request.form.get('produto_id'),
                request.form.get('fornecedores_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                quantidade_id_para_salvar,
                request.form.get('origem_id'),
                request.form.get('destino_id'),
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
                request.form.get('observacoes')
            ))
            
            # TITLE: Se veio de um pedido, marcar como "Faturado"
            pedido_id_form = request.form.get('pedido_id')
            if pedido_id_form:
                cursor.execute("UPDATE pedidos SET status = 'Faturado' WHERE id = %s", (pedido_id_form,))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Frete cadastrado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            print(f"Erro ao cadastrar frete: {e}")
            flash(f'Erro ao cadastrar frete: {str(e)}', 'danger')
            return redirect(url_for('fretes.novo'))
    # TITLE: GET - carregar formulário
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT id, razao_social, paga_comissao, percentual_cte, cte_integral, destino_id FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos = cursor.fetchall()
        
        cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()
        
        cursor.execute("SELECT id, nome, paga_comissao FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()
        
        cursor.execute("SELECT id, caminhao, placa FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        
        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()
        
        # TITLE: CORREÇÃO - Buscar rotas com PIPE
        cursor.execute("SELECT id, origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
        rotas = cursor.fetchall()
        rotas_dict = {}
        for rota in rotas:
            chave = f"{rota['origem_id']}|{rota['destino_id']}"  # PIPE
            rotas_dict[chave] = rota['valor_por_litro']
        
        cursor.execute("""
            SELECT p.id, p.numero, p.data_pedido, p.status, p.motorista_id, m.nome as motorista_nome
            FROM pedidos p
            LEFT JOIN motoristas m ON p.motorista_id = m.id
            WHERE p.status IN ('Pendente', 'Confirmado')
            ORDER BY p.data_pedido DESC
        """)
        pedidos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template(
            'fretes/novo.html',
            clientes=clientes,
            produtos=produtos,
            fornecedores=fornecedores,
            motoristas=motoristas,
            veiculos=veiculos,
            quantidades=quantidades,
            origens=origens,
            destinos=destinos,
            rotas=rotas,
            rotas_dict=rotas_dict,
            pedidos=pedidos,
            pedido_selecionado_id=pedido_id
        )
    except Exception as e:
        print(f"Erro ao carregar formulário: {e}")
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('index'))


@bp.route('/lista')
@login_required
def lista():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        cliente_id = request.args.get('cliente_id')
        
        base_sql = """
            SELECT f.*,
                   c.razao_social AS cliente_nome,
                   fo.razao_social AS fornecedor_nome,
                   m.nome AS motorista_nome,
                   v.placa AS veiculo_placa,
                   q.valor AS quantidade_valor,
                   o.nome AS origem_nome,
                   d.nome AS destino_nome,
                   p.nome AS produto_nome
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            LEFT JOIN produto p ON f.produto_id = p.id
        """
        
        filtros = []
        parametros = []
        
        if data_inicio:
            filtros.append("f.data_frete >= %s")
            parametros.append(data_inicio)
        
        if data_fim:
            filtros.append("f.data_frete <= %s")
            parametros.append(data_fim)
        
        if cliente_id:
            filtros.append("f.clientes_id = %s")
            parametros.append(cliente_id)
        
        if filtros:
            base_sql += " WHERE " + " AND ".join(filtros)
        
        base_sql += " ORDER BY f.data_frete DESC, f.id DESC"
        
        cursor.execute(base_sql, tuple(parametros))
        fretes = cursor.fetchall()
        
        # TITLE: Clientes atendidos
        sql_clientes = """
            SELECT c.id, c.razao_social, COUNT(f.id) AS qtd_fretes
            FROM fretes f
            JOIN clientes c ON f.clientes_id = c.id
        """
        if filtros:
            sql_clientes += " WHERE " + " AND ".join(filtros)
        sql_clientes += " GROUP BY c.id, c.razao_social ORDER BY c.razao_social"
        cursor.execute(sql_clientes, tuple(parametros))
        clientes_atendidos = cursor.fetchall()
        
        # TITLE: Quantidade por caminhão
        sql_caminhao = """
            SELECT v.id, v.placa, SUM(q.valor) AS total_quantidade
            FROM fretes f
            JOIN veiculos v ON f.veiculos_id = v.id
            JOIN quantidades q ON f.quantidade_id = q.id
        """
        if filtros:
            sql_caminhao += " WHERE " + " AND ".join(filtros)
        sql_caminhao += " GROUP BY v.id, v.placa ORDER BY v.placa"
        cursor.execute(sql_caminhao, tuple(parametros))
        quantidade_por_caminhao = cursor.fetchall()
        
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        lista_clientes = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template(
            'fretes/lista.html',
            fretes=fretes,
            data_inicio=data_inicio,
            data_fim=data_fim,
            cliente_id=cliente_id,
            clientes_atendidos=clientes_atendidos,
            quantidade_por_caminhao=quantidade_por_caminhao,
            lista_clientes=lista_clientes
        )
    except Exception as e:
        print(f"Erro ao carregar lista de fretes: {e}")
        flash(f'Erro ao carregar lista de fretes: {str(e)}', 'danger')
        return redirect(url_for('index'))


@bp.route('/deletar/<int:id>', methods=['POST', 'GET'])
@login_required
def deletar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fretes WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir frete: {str(e)}', 'danger')
    return redirect(url_for('fretes.lista'))


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            origem_id = request.form.get('origem_id')
            destino_id = request.form.get('destino_id')
            
            if not destino_id or destino_id == '':
                flash('ERRO: Destino é obrigatório!', 'danger')
                return redirect(url_for('fretes.editar', id=id))
            
            # TITLE: Tipo de quantidade (personalizada ou padrão)
            quantidade_tipo = request.form.get('quantidade_tipo', 'padrao')
            if quantidade_tipo == 'personalizada':
                quantidade_id_para_salvar = None
            else:
                quantidade_id_para_salvar = request.form.get('quantidade_id')
            
            # ✅ CORREÇÃO: Usar limpar_moeda() em todos os campos monetários
            preco_produto_unitario = limpar_moeda(request.form.get('preco_produto_unitario'))
            total_nf_compra = limpar_moeda(request.form.get('total_nf_compra'))
            preco_por_litro = limpar_moeda(request.form.get('preco_por_litro'))
            valor_total_frete = limpar_moeda(request.form.get('valor_total_frete'))
            comissao_motorista = limpar_moeda(request.form.get('comissao_motorista'))
            valor_cte = limpar_moeda(request.form.get('valor_cte'))
            comissao_cte = limpar_moeda(request.form.get('comissao_cte'))
            lucro = limpar_moeda(request.form.get('lucro'))
            
            cursor.execute("""
                UPDATE fretes SET
                    clientes_id=%s, produto_id=%s, fornecedores_id=%s, motoristas_id=%s, veiculos_id=%s,
                    quantidade_id=%s, origem_id=%s, destino_id=%s,
                    preco_produto_unitario=%s, total_nf_compra=%s, preco_por_litro=%s, valor_total_frete=%s,
                    comissao_motorista=%s, valor_cte=%s, comissao_cte=%s, lucro=%s,
                    data_frete=%s, status=%s, observacoes=%s
                WHERE id=%s
            """, (
                request.form.get('clientes_id'),
                request.form.get('produto_id'),
                request.form.get('fornecedores_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                quantidade_id_para_salvar,
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
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Frete atualizado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        
        # TITLE: GET - carregar dados do frete
        # PARA (versão correta com rotas_dict)
        # TITLE: GET - carregar dados do frete
        cursor.execute("SELECT * FROM fretes WHERE id = %s", (id,))
        frete = cursor.fetchone()

        cursor.execute("SELECT id, razao_social, paga_comissao, percentual_cte, cte_integral, destino_id FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos = cursor.fetchall()

        cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()

        cursor.execute("SELECT id, nome, paga_comissao FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()

        cursor.execute("SELECT id, caminhao, placa FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()

        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()

        # NOVO: rotas e rotas_dict (PIPE)
        cursor.execute("SELECT id, origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
        rotas = cursor.fetchall()

        rotas_dict = {}
        for rota in rotas:
            chave = f"{rota['origem_id']}|{rota['destino_id']}"  # PIPE
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
        print(f"Erro ao editar frete: {e}")
        flash(f'Erro ao editar frete: {str(e)}', 'danger')
        return redirect(url_for('fretes.lista'))

