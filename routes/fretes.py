from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection
from utils.helpers import parse_moeda

bp = Blueprint('fretes', __name__, url_prefix='/fretes')


@bp.route('/', methods=['GET'])
@login_required
def lista():
    """
    Lista de fretes — fornece ao template os campos já com aliases esperados.
    Query com LEFT JOIN para preencher nome do cliente/fornecedor/motorista/veiculo.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    cliente_id = request.args.get('cliente_id', '')

    try:
        # montar filtros básicos (convertendo datas se necessário pode ser feito aqui)
        filters = []
        params = []

        if data_inicio:
            # espera formato dd/mm/YYYY ou YYYY-MM-DD; tentar aceitar ambos (ajuste se necessário)
            try:
                # dd/mm/YYYY -> YYYY-MM-DD
                from datetime import datetime
                di = datetime.strptime(data_inicio, '%d/%m/%Y').strftime('%Y-%m-%d')
            except Exception:
                di = data_inicio
            filters.append("f.data_frete >= %s")
            params.append(di)

        if data_fim:
            try:
                from datetime import datetime
                df = datetime.strptime(data_fim, '%d/%m/%Y').strftime('%Y-%m-%d')
            except Exception:
                df = data_fim
            filters.append("f.data_frete <= %s")
            params.append(df)

        if cliente_id:
            filters.append("f.clientes_id = %s")
            params.append(cliente_id)

        where_clause = ""
        if filters:
            where_clause = "WHERE " + " AND ".join(filters)

        query = f"""
            SELECT
                f.id,
                DATE_FORMAT(f.data_frete, '%%d/%%m/%%Y') AS data_frete,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(ci.razao_social, '') AS cliente_interno,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(v.caminhao, '') AS veiculo,
                COALESCE(f.valor_total_frete, 0) AS valor_total_frete,
                COALESCE(f.lucro, 0) AS lucro,
                COALESCE(f.status, '') AS status
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN clientes ci ON f.clientes_id = ci.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            {where_clause}
            ORDER BY f.data_frete DESC, f.id DESC
        """
        cursor.execute(query, tuple(params))
        fretes = cursor.fetchall()

        # carregar lista de clientes para o filtro no template
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
    except Exception:
        fretes = []
        clientes = []
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    return render_template(
        'fretes/lista.html',
        fretes=fretes,
        clientes=clientes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        cliente_id=cliente_id
    )


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    """
    Rota para criar novo frete.
    - GET: renderiza formulário com dados auxiliares.
    - POST: (mínimo) redireciona para lista; implemente criação real se desejar.
    Observação: passar frete=None para que o template entenda que é criação (não edição).
    """
    if request.method == 'POST':
        # Implementação mínima: você pode inserir no banco aqui.
        flash('Funcionalidade de criação de frete não implementada; formulário válido mas não salva.', 'info')
        return redirect(url_for('fretes.lista'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

        cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()

        cursor.execute("SELECT id, caminhao, placa FROM veiculos WHERE ativo = 1 ORDER BY caminhao")
        veiculos = cursor.fetchall()

        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()

        # montar rotas_dict
        rotas_dict = {}
        try:
            cursor.execute("SELECT origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
            for r in cursor.fetchall():
                try:
                    origem_id = r.get('origem_id') if isinstance(r, dict) else r[0]
                    destino_id = r.get('destino_id') if isinstance(r, dict) else r[1]
                    valor = r.get('valor_por_litro') if isinstance(r, dict) else r[2]
                    key = f"{int(origem_id)}|{int(destino_id)}"
                    rotas_dict[key] = float(valor or 0)
                except Exception:
                    continue
        except Exception:
            rotas_dict = {}
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    # frete None -> template entende como criação
    frete = None
    pedido_id = request.args.get('pedido_id')

    return render_template(
        'fretes/novo.html',
        frete=frete,
        clientes=clientes,
        fornecedores=fornecedores,
        produtos=produtos,
        origens=origens,
        destinos=destinos,
        motoristas=motoristas,
        veiculos=veiculos,
        quantidades=quantidades,
        rotas_dict=rotas_dict,
        pedido_id=pedido_id
    )


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        try:
            preco_produto_unitario_raw = request.form.get('preco_produto_unitario_raw')
            if preco_produto_unitario_raw is None or preco_produto_unitario_raw == '':
                preco_produto_unitario = parse_moeda(request.form.get('preco_produto_unitario'))
            else:
                preco_produto_unitario = parse_moeda(preco_produto_unitario_raw)

            preco_por_litro_raw = request.form.get('preco_por_litro_raw')
            if preco_por_litro_raw is None or preco_por_litro_raw == '':
                preco_por_litro = parse_moeda(request.form.get('preco_por_litro'))
            else:
                preco_por_litro = parse_moeda(preco_por_litro_raw)

            total_nf_compra = parse_moeda(request.form.get('total_nf_compra'))
            valor_total_frete = parse_moeda(request.form.get('valor_total_frete'))
            comissao_motorista = parse_moeda(request.form.get('comissao_motorista'))
            valor_cte = parse_moeda(request.form.get('valor_cte'))
            comissao_cte = parse_moeda(request.form.get('comissao_cte'))
            lucro = parse_moeda(request.form.get('lucro'))

            clientes_id = request.form.get('clientes_id')

            cliente_paga_frete = True
            try:
                if clientes_id:
                    cchk = conn.cursor(dictionary=True)
                    cchk.execute("SELECT paga_frete, paga_comissao FROM clientes WHERE id = %s LIMIT 1", (clientes_id,))
                    crow = cchk.fetchone()
                    cchk.close()
                    if crow:
                        if crow.get('paga_frete') is not None:
                            cliente_paga_frete = bool(crow.get('paga_frete'))
                        elif crow.get('paga_comissao') is not None:
                            cliente_paga_frete = bool(crow.get('paga_comissao'))
            except Exception:
                cliente_paga_frete = True

            if not cliente_paga_frete:
                preco_por_litro = 0
                valor_total_frete = 0
                comissao_motorista = 0
                comissao_cte = 0
                lucro = round(0 - float(comissao_cte or 0) - float(comissao_motorista or 0), 2)

            cursor.execute("""
                UPDATE fretes SET
                    data_frete=%s,
                    status=%s,
                    observacoes=%s,
                    clientes_id=%s,
                    fornecedores_id=%s,
                    produto_id=%s,
                    origem_id=%s,
                    destino_id=%s,
                    motoristas_id=%s,
                    veiculos_id=%s,
                    quantidade_id=%s,
                    quantidade_manual=%s,
                    preco_produto_unitario=%s,
                    preco_por_litro=%s,
                    total_nf_compra=%s,
                    valor_total_frete=%s,
                    comissao_motorista=%s,
                    valor_cte=%s,
                    comissao_cte=%s,
                    lucro=%s
                WHERE id=%s
            """, (
                request.form.get('data_frete'),
                request.form.get('status'),
                request.form.get('observacoes'),
                clientes_id,
                request.form.get('fornecedores_id'),
                request.form.get('produto_id'),
                request.form.get('origem_id'),
                request.form.get('destino_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                request.form.get('quantidade_id') or None,
                request.form.get('quantidade_manual') or None,
                preco_produto_unitario or 0,
                preco_por_litro or 0,
                total_nf_compra or 0,
                valor_total_frete or 0,
                comissao_motorista or 0,
                valor_cte or 0,
                comissao_cte or 0,
                lucro or 0,
                id,
            ))
            conn.commit()
            flash('Frete atualizado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar frete: {e}', 'danger')
            return redirect(url_for('fretes.editar', id=id))
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass

    # GET: carregar frete + dados de apoio
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM fretes WHERE id = %s", (id,))
        frete = cursor.fetchone()
    except Exception:
        frete = None

    # carregar dados auxiliares
    try:
        cursor.execute("SELECT * FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

        cursor.execute("SELECT * FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()

        cursor.execute("SELECT * FROM produto ORDER BY nome")
        produtos = cursor.fetchall()

        cursor.execute("SELECT * FROM origens ORDER BY nome")
        origens = cursor.fetchall()

        cursor.execute("SELECT * FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()

        cursor.execute("SELECT * FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()

        cursor.execute("SELECT * FROM veiculos ORDER BY caminhao")
        veiculos = cursor.fetchall()

        cursor.execute("SELECT * FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()

        # montar rotas_dict também para a página de edição
        rotas_dict = {}
        try:
            cursor.execute("SELECT origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
            for r in cursor.fetchall():
                try:
                    origem_id = r.get('origem_id') if isinstance(r, dict) else r[0]
                    destino_id = r.get('destino_id') if isinstance(r, dict) else r[1]
                    valor = r.get('valor_por_litro') if isinstance(r, dict) else r[2]
                    key = f"{int(origem_id)}|{int(destino_id)}"
                    rotas_dict[key] = float(valor or 0)
                except Exception:
                    continue
        except Exception:
            rotas_dict = {}
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    # Normalizar campos para o template/JS (quando frete existe)
    if frete is None:
        # manter None para indicar criação; template deve checar if frete
        pass
    else:
        frete.setdefault('preco_produto_unitario', frete.get('preco_produto_unitario') or 0)
        frete.setdefault('preco_por_litro', frete.get('preco_por_litro') or 0)
        frete.setdefault('total_nf_compra', frete.get('total_nf_compra') or 0)
        frete.setdefault('valor_total_frete', frete.get('valor_total_frete') or 0)
        frete.setdefault('comissao_motorista', frete.get('comissao_motorista') or 0)
        frete.setdefault('valor_cte', frete.get('valor_cte') or 0)
        frete.setdefault('comissao_cte', frete.get('comissao_cte') or 0)
        frete.setdefault('lucro', frete.get('lucro') or 0)
        frete.setdefault('quantidade_manual', frete.get('quantidade_manual') or '')
        frete.setdefault('quantidade_id', frete.get('quantidade_id') or None)

    return render_template(
        'fretes/novo.html',
        frete=frete,
        clientes=clientes,
        fornecedores=fornecedores,
        produtos=produtos,
        origens=origens,
        destinos=destinos,
        motoristas=motoristas,
        veiculos=veiculos,
        quantidades=quantidades,
        rotas_dict=rotas_dict,
    )


@bp.route('/deletar/<int:id>', methods=['POST'])
@login_required
def deletar(id):
    """
    Exclusão mínima de frete (endpoint 'fretes.deletar') usada pelo template.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM fretes WHERE id = %s", (id,))
        conn.commit()
        flash(f'Frete #{id} excluído.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Erro ao excluir frete: {e}', 'danger')
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass
    return redirect(url_for('fretes.lista'))
