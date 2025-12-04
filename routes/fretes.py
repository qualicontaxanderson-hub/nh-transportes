from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime

# Blueprint - DECLARE ANTES DE USAR @bp.route
bp = Blueprint('fretes', __name__, url_prefix='/fretes')


def parse_moeda(valor):
    """
    Converte uma string de moeda em float (pt-BR ou en).
    Exemplos:
      'R$ 1.234,56' -> 1234.56
      '1.234,56'     -> 1234.56
      '1234.56'      -> 1234.56
      '0,10'         -> 0.10
      None/''/inválido -> 0.0
    """
    try:
        if valor is None:
            return 0.0
        if isinstance(valor, (int, float)):
            return float(valor)
        s = str(valor).strip()
        if s == '':
            return 0.0
        s = s.replace('R$', '').replace('r$', '').replace('R', '').replace(' ', '')
        if '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '.')
        return float(s)
    except Exception:
        return 0.0


@bp.route('/', methods=['GET'])
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT f.id,
                   f.data_frete,
                   f.status,
                   f.valor_total_frete,
                   f.lucro,
                   COALESCE(c.razao_social, '') AS cliente,
                   COALESCE(fo.razao_social, '') AS fornecedor,
                   COALESCE(m.nome, '') AS motorista,
                   COALESCE(v.caminhao, '') AS veiculo,
                   COALESCE(f.preco_produto_unitario,0) AS preco_produto_unitario,
                   COALESCE(f.preco_por_litro,0) AS preco_por_litro,
                   COALESCE(f.total_nf_compra,0) AS total_nf_compra
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            ORDER BY f.data_frete DESC, f.id DESC
            LIMIT 200
        """)
        fretes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('fretes/lista.html', fretes=fretes)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Normalizar valores recebidos
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

            # Verificar flag do cliente (se não paga frete) e forçar zeros se for o caso
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
            ))
            conn.commit()
            flash('Frete criado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar frete: {e}', 'danger')
            return redirect(url_for('fretes.novo'))
        finally:
            cursor.close()
            conn.close()

    # GET: carregar dados de apoio
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
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

        # montar rotas_dict para o JS
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

    return render_template(
        'fretes/novo.html',
        frete=None,
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

        motorista_paga_comissao = request.form.get('import_motorista_paga_comissao')
        motorista_paga_comissao = int(motorista_paga_comissao) if motorista_paga_comissao not in (None, '') else 1

        for idx in sorted(indices):
            prefix = f'itens[{idx}]'
            clientes_id = request.form.get(f'{prefix}[cliente_id]') or None
            produto_id = request.form.get(f'{prefix}[produto_id]') or None
            fornecedores_id = request.form.get(f'{prefix}[fornecedor_id]') or None
            origem_id = request.form.get(f'{prefix}[origem_id]') or None
            destino_id = request.form.get(f'{prefix}[destino_id]') or request.form.get(f'{prefix}[cliente_destino_id]') or None
            quantidade_raw = request.form.get(f'{prefix}[quantidade]') or '0'
            quantidade = parse_moeda(quantidade_raw)
            quantidade_id = request.form.get(f'{prefix}[quantidade_id]') or None

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

            # verificar se o cliente paga frete/comissão
            cliente_paga_frete = True
            try:
                if clientes_id:
                    cchk = conn.cursor(dictionary=True)
                    cchk.execute("SELECT paga_frete, paga_comissao FROM clientes WHERE id=%s LIMIT 1", (clientes_id,))
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
                comissao_motorista = 0.0
            else:
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

            if valor_total_frete:
                lucro = round(float(valor_total_frete) - float(comissao_motorista) - float(comissao_cte), 2)
            else:
                lucro = round(0.0 - float(comissao_cte) - float(comissao_motorista), 2) if (comissao_cte or comissao_motorista) else 0.0

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

        conn.commit()

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
    try:
        cursor.execute("SELECT * FROM fretes WHERE id = %s", (id,))
        frete = cursor.fetchone()
    except Exception:
        frete = None

    # carregar dados auxiliares
    try:
        cursor.execute("SELECT * FROM clientes ORDER BY razao_social")
    static/js/fretes_calculos.js
Language: 
