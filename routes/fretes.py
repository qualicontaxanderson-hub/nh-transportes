from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

# Import helpers (adicionados para resolver NameError)
from utils.db import get_db_connection
from utils.helpers import parse_moeda

# Atenção: get_db_connection e parse_moeda devem estar definidos em outro módulo do projeto.
# Ajuste os imports acima conforme a estrutura do seu repositório se necessário.

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

@bp.route('/', methods=['GET'])
@login_required
def lista():
    """
    Endpoint 'fretes.lista' — serve templates/fretes/lista.html.
    Implementação mínima: carrega fretes e clientes (usados no filtro) e passa
    os parâmetros de filtro (data_inicio, data_fim, cliente_id) para o template.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    cliente_id = request.args.get('cliente_id', '')

    try:
        # Query simples — ajustar filtros/colunas conforme seu esquema se desejar.
        cursor.execute("SELECT * FROM fretes ORDER BY data_frete DESC, id DESC")
        fretes = cursor.fetchall()

        # Carregar lista de clientes para o filtro no template
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
    except Exception:
        fretes = []
        clientes = []
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'fretes/lista.html',
        fretes=fretes,
        clientes=clientes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        cliente_id=cliente_id
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
            cursor.close()
            conn.close()

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
        cursor.close()
        conn.close()

    # Normalizar campos para o template/JS
    if frete is None:
        frete = {}
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
