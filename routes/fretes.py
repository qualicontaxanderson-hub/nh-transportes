from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime

# Blueprint
bp = Blueprint('fretes', __name__, url_prefix='/fretes')


def parse_moeda(valor):
    """
    Converte uma string de moeda em float (pt-BR ou en).
    Retorna 0.0 em caso de erro.
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
            # ex: "1.234,56"
            s = s.replace('.', '').replace(',', '.')
        else:
            # ex: "1234.56" ou "1234,56"
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
            # Helper para ler moedas (considera raw)
            def _read_moeda(form_key, raw_key=None, default='0'):
                if raw_key:
                    raw = request.form.get(raw_key)
                    if raw is not None and raw != '':
                        return parse_moeda(raw)
                return parse_moeda(request.form.get(form_key) or default)

            preco_produto_unitario = _read_moeda('preco_produto_unitario', 'preco_produto_unitario_raw')
            preco_por_litro = _read_moeda('preco_por_litro', 'preco_por_litro_raw')
            total_nf_compra = parse_moeda(request.form.get('total_nf_compra') or '0')
            valor_total_frete = parse_moeda(request.form.get('valor_total_frete') or '0')
            comissao_motorista = parse_moeda(request.form.get('comissao_motorista') or '0')
            valor_cte = parse_moeda(request.form.get('valor_cte') or '0')
            comissao_cte = parse_moeda(request.form.get('comissao_cte') or '0')
            lucro = parse_moeda(request.form.get('lucro') or '0')

            clientes_id = request.form.get('clientes_id')

            # quantidade (manual ou por quantidade_id)
            quantidade = 0.0
            quantidade_manual = request.form.get('quantidade_manual')
            quantidade_id = request.form.get('quantidade_id')
            if quantidade_manual and quantidade_manual.strip() != '':
                try:
                    quantidade = parse_moeda(quantidade_manual)
                except Exception:
                    quantidade = 0.0
            elif quantidade_id:
                try:
                    qc = conn.cursor(dictionary=True)
                    qc.execute("SELECT valor FROM quantidades WHERE id=%s LIMIT 1", (quantidade_id,))
                    qrow = qc.fetchone()
                    qc.close()
                    if qrow and qrow.get('valor') is not None:
                        quantidade = float(qrow.get('valor'))
                except Exception:
                    quantidade = 0.0

            # Fallbacks
            if (not total_nf_compra or total_nf_compra == 0) and quantidade > 0 and preco_produto_unitario > 0:
                total_nf_compra = round(preco_produto_unitario * quantidade, 2)

            if (not preco_por_litro or preco_por_litro == 0) and quantidade > 0 and total_nf_compra > 0:
                preco_por_litro = round(total_nf_compra / quantidade, 4)

            if (not valor_total_frete or valor_total_frete == 0) and quantidade > 0 and preco_por_litro > 0:
                valor_total_frete = round(preco_por_litro * quantidade, 2)

            # Flags do cliente
            cliente_paga_frete = True
            cliente_cte_integral = False
            if clientes_id:
                try:
                    cchk = conn.cursor(dictionary=True)
                    cchk.execute("SELECT paga_frete, paga_comissao, cte_integral FROM clientes WHERE id = %s LIMIT 1", (clientes_id,))
                    crow = cchk.fetchone()
                    cchk.close()
                    if crow:
                        if crow.get('paga_frete') is not None:
                            cliente_paga_frete = bool(crow.get('paga_frete'))
                        elif crow.get('paga_comissao') is not None:
                            cliente_paga_frete = bool(crow.get('paga_comissao'))
                        cliente_cte_integral = bool(crow.get('cte_integral')) if crow.get('cte_integral') is not None else False
                except Exception:
                    cliente_paga_frete = True

            if not cliente_paga_frete:
                preco_por_litro = 0.0
                valor_total_frete = 0.0
                comissao_motorista = 0.0
                comissao_cte = 0.0
                lucro = 0.0

            # Calcular valor_cte quando necessário
            if cliente_cte_integral:
                valor_cte = round(valor_total_frete if cliente_paga_frete else 0.0, 2)
            else:
                try:
                    rc = conn.cursor(dictionary=True)
                    rc.execute(
                        "SELECT valor_por_litro FROM rotas WHERE origem_id=%s AND destino_id=%s LIMIT 1",
                        (request.form.get('origem_id'), request.form.get('destino_id'))
                    )
                    rrow = rc.fetchone()
                    rc.close()
                    tarifa = float(rrow.get('valor_por_litro')) if (rrow and rrow.get('valor_por_litro') is not None) else 0.0
                    valor_cte = round((quantidade * tarifa) if (quantidade and tarifa) else 0.0, 2)
                except Exception:
                    valor_cte = 0.0

            comissao_cte = round(valor_cte * 0.08, 2)

            # Comissão motorista
            motorista_id = request.form.get('motoristas_id')
            comissao_motorista = 0.0
            if cliente_paga_frete:
                motorista_paga = True
                if motorista_id:
                    try:
                        mc = conn.cursor(dictionary=True)
                        mc.execute("SELECT paga_comissao FROM motoristas WHERE id=%s LIMIT 1", (motorista_id,))
                        mrow = mc.fetchone()
                        mc.close()
                        if mrow and mrow.get('paga_comissao') is not None:
                            motorista_paga = bool(mrow.get('paga_comissao'))
                    except Exception:
                        motorista_paga = True
                if motorista_paga and quantidade:
                    comissao_motorista = round(quantidade * 0.01, 2)
                else:
                    comissao_motorista = 0.0
            else:
                comissao_motorista = 0.0

            # Lucro
            if not cliente_paga_frete:
                lucro = 0.0
            else:
                lucro = round((valor_total_frete or 0) - (comissao_motorista or 0) - (comissao_cte or 0), 2)

            # Inserir
            cursor.execute(
                """
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
                """,
                (
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
                    round(preco_produto_unitario or 0, 3),
                    round(preco_por_litro or 0, 4),
                    round(total_nf_compra or 0, 2),
                    round(valor_total_frete or 0, 2),
                    round(comissao_motorista or 0, 2),
                    round(valor_cte or 0, 2),
                    round(comissao_cte or 0, 2),
                    round(lucro or 0, 2),
                )
            )
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
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        pedido_id = request.form.get('pedido_id')
        data_frete = request.form.get('data_frete') or None
        motorista_id = request.form.get('motorista_id') or None
        veiculo_id = request.form.get('veiculo_id') or None

        # coletar índices
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
            try:
                quantidade = parse_moeda(quantidade_raw)
            except Exception:
                quantidade = 0.0

            quantidade_id = request.form.get(f'{prefix}[quantidade_id]') or None
            status_item = (request.form.get(f'{prefix}[status]') or 'Pendente').strip()

            preco_unit = parse_moeda(request.form.get(f'{prefix}[preco_unitario]') or request.form.get(f'{prefix}[preco_unitario_raw]') or '0')
            total_nf = parse_moeda(request.form.get(f'{prefix}[total_nf]') or '0')
            if total_nf == 0 and quantidade > 0 and preco_unit > 0:
                total_nf = round(preco_unit * quantidade, 2)

            preco_por_litro = parse_moeda(request.form.get(f'{prefix}[preco_por_litro]') or request.form.get(f'{prefix}[preco_por_litro_raw]') or '0')
            if (not preco_por_litro or preco_por_litro == 0) and quantidade > 0 and total_nf > 0:
                preco_por_litro = round(total_nf / quantidade, 4)

            valor_total_frete = parse_moeda(request.form.get(f'{prefix}[valor_total_frete]') or '0')
            if (not valor_total_frete or valor_total_frete == 0) and quantidade > 0 and preco_por_litro > 0:
                valor_total_frete = round(quantidade * preco_por_litro, 2)

            valor_cte = parse_moeda(request.form.get(f'{prefix}[valor_cte]') or '0')
            cliente_cte_integral = False
            cliente_paga_frete = True
            try:
                if clientes_id:
                    cchk = conn.cursor(dictionary=True)
                    cchk.execute("SELECT cte_integral, paga_frete, paga_comissao FROM clientes WHERE id=%s LIMIT 1", (clientes_id,))
                    crow = cchk.fetchone()
                    cchk.close()
                    if crow:
                        cliente_cte_integral = bool(crow.get('cte_integral')) if crow.get('cte_integral') is not None else False
                        cliente_paga_frete = bool(crow.get('paga_frete')) if crow.get('paga_frete') is not None else True
                    else:
                        cliente_paga_frete = True
            except Exception:
                cliente_paga_frete = True
                cliente_cte_integral = False

            if cliente_cte_integral:
                valor_cte = round(valor_total_frete if cliente_paga_frete else 0.0, 2)
            else:
                tarifa = rota_valor_por_litro(origem_id, destino_id)
                valor_cte = round(quantidade * tarifa if quantidade and tarifa else 0.0, 2)

            comissao_cte = round(valor_cte * 0.08, 2)

            if not cliente_paga_frete:
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

            if not cliente_paga_frete:
                valor_total_frete = 0.0
                lucro = 0.0
            else:
                lucro = round(float(valor_total_frete) - float(comissao_motorista) - float(comissao_cte), 2)

            cursor.execute(
                """
                INSERT INTO fretes (
                    data_frete, status, observacoes, clientes_id, fornecedores_id, produto_id,
                    origem_id, destino_id, motoristas_id, veiculos_id, quantidade_id, quantidade_manual,
                    preco_produto_unitario, preco_por_litro, total_nf_compra, valor_total_frete,
                    comissao_motorista, valor_cte, comissao_cte, lucro
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    data_frete,
                    status_item,
                    request.form.get(f'{prefix}[observacoes]') or '',
                    clientes_id,
                    fornecedores_id,
                    produto_id,
                    origem_id,
                    destino_id,
                    motorista_id,
                    veiculo_id,
                    request.form.get(f'{prefix}[quantidade_id]') or None,
                    request.form.get(f'{prefix}[quantidade]') or None,
                    round(preco_unit or 0, 3),
                    round(preco_por_litro or 0, 4),
                    round(total_nf or 0, 2),
                    round(valor_total_frete or 0, 2),
                    round(comissao_motorista or 0, 2),
                    round(valor_cte or 0, 2),
                    round(comissao_cte or 0, 2),
                    round(lucro or 0, 2),
                )
            )
        # fim loop
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


@bp.route('/deletar/<int:id>', methods=['POST'])
@login_required
def deletar(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM fretes WHERE id = %s", (id,))
        conn.commit()
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir frete: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('fretes.lista'))
