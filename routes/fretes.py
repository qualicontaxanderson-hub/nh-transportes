# url=https://github.com/qualicontaxanderson-hub/nh-transportes/blob/main/routes/fretes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
import re

bp = Blueprint('fretes', __name__, url_prefix='/fretes')


# ============================================
# FUNÇÃO DE LIMPEZA DE MOEDA
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
        
        # --- Tenta ler formato plano (cliente_id, produto_id, ...) ---
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
        
        # --- Se veio no formato aninhado itens[0][campo], reconstruir arrays ---
        if not clientes_ids:
            pattern = re.compile(r'^itens\[(\d+)\]\[(.+)\]$')
            # coletar todas as chaves do form que batam
            data = {}
            for k, v in request.form.items():
                m = pattern.match(k)
                if m:
                    idx = int(m.group(1))
                    campo = m.group(2)
                    data.setdefault(idx, {})[campo] = v
            if data:
                # ordenar por índice e construir listas
                max_idx = max(data.keys())
                clientes_ids, produtos_ids, fornecedores_ids, origens_ids, destinos_ids = [], [], [], [], []
                quantidades, quantidades_ids, precos_unitarios, totais_nf = [], [], [], []
                precos_por_litro, valores_totais_frete, comissoes_motorista = [], [], []
                valores_cte, comissoes_cte, lucros, status_list = [], [], [], []
                for i in sorted(data.keys()):
                    row = data[i]
                    clientes_ids.append(row.get('cliente_id', ''))
                    produtos_ids.append(row.get('produto_id', ''))
                    fornecedores_ids.append(row.get('fornecedor_id', ''))
                    origens_ids.append(row.get('origem_id', ''))
                    destinos_ids.append(row.get('destino_id', ''))
                    quantidades.append(row.get('quantidade', '0'))
                    quantidades_ids.append(row.get('quantidade_id', '') or '')
                    precos_unitarios.append(row.get('preco_unitario', '0'))
                    totais_nf.append(row.get('total_nf', '0'))
                    precos_por_litro.append(row.get('preco_por_litro', '0'))
                    valores_totais_frete.append(row.get('valor_total_frete', '0'))
                    comissoes_motorista.append(row.get('comissao_motorista', '0'))
                    valores_cte.append(row.get('valor_cte', '0'))
                    comissoes_cte.append(row.get('comissao_cte', '0'))
                    lucros.append(row.get('lucro', '0'))
                    status_list.append(row.get('status', 'Pendente'))
        
        fretes_criados = 0
        for i in range(len(clientes_ids)):
            # proteger índices curtos
            try:
                cliente_i = clientes_ids[i]
            except IndexError:
                cliente_i = ''
            if not cliente_i:
                # pular linhas vazias (caso houve mismatch)
                continue
            qtd_id = quantidades_ids[i] if i < len(quantidades_ids) and quantidades_ids[i] else None
            # usar limpar_moeda para todos campos monetários
            cursor.execute("""
                INSERT INTO fretes (
                    clientes_id, produto_id, fornecedores_id, motoristas_id, veiculos_id,
                    quantidade_id, quantidade_manual, origem_id, destino_id,
                    preco_produto_unitario, total_nf_compra, preco_por_litro, valor_total_frete,
                    comissao_motorista, valor_cte, comissao_cte, lucro, data_frete, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                clientes_ids[i],
                produtos_ids[i] if i < len(produtos_ids) else None,
                fornecedores_ids[i] if i < len(fornecedores_ids) else None,
                motorista_id,
                veiculo_id,
                qtd_id,
                limpar_moeda(quantidades[i]) if not qtd_id and i < len(quantidades) else None,
                origens_ids[i] if i < len(origens_ids) else None,
                destinos_ids[i] if i < len(destinos_ids) else None,
                limpar_moeda(precos_unitarios[i]) if i < len(precos_unitarios) else 0.0,
                limpar_moeda(totais_nf[i]) if i < len(totais_nf) else 0.0,
                limpar_moeda(precos_por_litro[i]) if i < len(precos_por_litro) else 0.0,
                limpar_moeda(valores_totais_frete[i]) if i < len(valores_totais_frete) else 0.0,
                limpar_moeda(comissoes_motorista[i]) if i < len(comissoes_motorista) else 0.0,
                limpar_moeda(valores_cte[i]) if i < len(valores_cte) else 0.0,
                limpar_moeda(comissoes_cte[i]) if i < len(comissoes_cte) else 0.0,
                limpar_moeda(lucros[i]) if i < len(lucros) else 0.0,
                data_frete,
                status_list[i] if i < len(status_list) else 'Pendente'
            ))
            fretes_criados += 1
        
        # Atualizar status do pedido para "Faturado" SOMENTE se criamos fretes
        if fretes_criados > 0 and pedido_id:
            cursor.execute("UPDATE pedidos SET status = 'Faturado' WHERE id = %s", (pedido_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash(f'{fretes_criados} fretes criados com sucesso!{"" if fretes_criados>0 else " Nenhum frete criado."}', 'success' if fretes_criados>0 else 'warning')
        return redirect(url_for('fretes.lista'))
    except Exception as e:
        print(f"Erro ao salvar fretes importados: {e}")
        flash(f'Erro ao salvar fretes: {str(e)}', 'danger')
        return redirect(url_for('fretes.novo'))
