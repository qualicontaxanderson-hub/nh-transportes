from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
import re
from utils.db import get_db_connection
from utils.helpers import parse_moeda

bp = Blueprint('fretes', __name__, url_prefix='/fretes')


@bp.route('/', methods=['GET'])
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    cliente_id = request.args.get('cliente_id', '')

    try:
        # montar filtros básicos
        filters = []
        params = []

        if data_inicio:
            try:
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
                f.data_frete,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS datafrete_formatada,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(v.caminhao, '') AS veiculo,
                f.valor_total_frete,
                COALESCE(f.lucro, 0) AS lucro,
                COALESCE(f.status, '') AS status
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            {where_clause}
            ORDER BY f.data_frete DESC, f.id DESC
        """

        cursor.execute(query, tuple(params))
        fretes = cursor.fetchall()

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
    GET: carregar dados auxiliares e tentar pré-selecionar destino a partir do pedido/cliente.
    POST: gravar novo frete ou atualizar se o form enviar id (proteção contra criação duplicada).
    """
    if request.method == 'POST':
        # abrir conexão própria para o POST
        conn = get_db_connection()
        try:
            # Detectar se o form enviou um id de frete (edição disfarçada como novo)
            form_id = request.form.get('id') or request.form.get('frete_id') or request.form.get('fretes_id')
            # ler inputs (idem ao editar)
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

            # quantidade: prefer manual se informado, senão usar quantidade_id (assume hidden/data-quantidade)
            quantidade_manual_raw = request.form.get('quantidade_manual')
            quantidade = None
            try:
                if quantidade_manual_raw is not None and quantidade_manual_raw != '':
                    quantidade = float(quantidade_manual_raw)
                else:
                    qtd_id = request.form.get('quantidade_id')
                    if qtd_id:
                        quantidade = None
            except Exception:
                quantidade = None

            # ler valores já calculados pelo cliente (defaults)
            total_nf_compra = parse_moeda(request.form.get('total_nf_compra')) or ((preco_produto_unitario or 0) * (quantidade or 0))
            valor_total_frete = parse_moeda(request.form.get('valor_total_frete')) or ((preco_por_litro or 0) * (quantidade or 0))
            comissao_motorista = parse_moeda(request.form.get('comissao_motorista')) or 0
            valor_cte = parse_moeda(request.form.get('valor_cte')) or 0
            comissao_cte = parse_moeda(request.form.get('comissao_cte')) or 0
            lucro = parse_moeda(request.form.get('lucro')) or ((valor_total_frete or 0) - (comissao_motorista or 0) - (comissao_cte or 0))

            clientes_id = request.form.get('clientes_id')
            motoristas_id = request.form.get('motoristas_id')

            # determinar cliente_paga_frete (reusar lógica do editar)
            cliente_paga_frete = True
            try:
                if clientes_id:
                    cchk = conn.cursor(dictionary=True)
                    try:
                        cchk.execute("SELECT paga_comissao FROM clientes WHERE id = %s LIMIT 1", (clientes_id,))
                        crow = cchk.fetchone()
                        if crow:
                            cliente_paga_frete = bool(crow.get('paga_comissao') if isinstance(crow, dict) else crow[0])
                    except Exception:
                        cliente_paga_frete = True
                    finally:
                        try:
                            cchk.close()
                        except Exception:
                            pass
            except Exception:
                cliente_paga_frete = True

            # determinar motorista_recebe_comissao (reusar lógica do editar)
            motorista_recebe_comissao = True
            try:
                if motoristas_id:
                    mch = conn.cursor(dictionary=True)
                    try:
                        mch.execute("SELECT paga_comissao FROM motoristas WHERE id = %s LIMIT 1", (motoristas_id,))
                        mrow = mch.fetchone()
                        if mrow:
                            motorista_recebe_comissao = bool(mrow.get('paga_comissao') if isinstance(mrow, dict) else mrow[0])
                    except Exception:
                        motorista_recebe_comissao = True
                    finally:
                        try:
                            mch.close()
                        except Exception:
                            pass
            except Exception:
                motorista_recebe_comissao = True

            # aplicar regra: se cliente não paga => zerar valores faturamento e lucro absoluto 0
            if not cliente_paga_frete:
                valor_total_frete = 0
                comissao_motorista = 0
                lucro = 0
            else:
                # se cliente paga mas motorista não recebe, zera a comissao do motorista
                if not motorista_recebe_comissao:
                    comissao_motorista = 0
                    lucro = (valor_total_frete or 0) - (comissao_motorista or 0) - (comissao_cte or 0)

            # Se o form indicou um id -> fazer UPDATE (evita criar duplicata quando template submete para /novo)
            if form_id:
                try:
                    cursor = conn.cursor()
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
                        request.form.get('clientes_id'),
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
                        int(form_id),
                    ))
                    conn.commit()
                    flash('Frete atualizado com sucesso!', 'success')
                    return redirect(url_for('fretes.lista'))
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    flash(f'Erro ao atualizar frete: {e}', 'danger')
                    return redirect(url_for('fretes.novo'))
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass

            # inserir na tabela fretes (caso form_id não informado)
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO fretes (
                        data_frete, status, observacoes,
                        clientes_id, fornecedores_id, produto_id,
                        origem_id, destino_id, motoristas_id, veiculos_id,
                        quantidade_id, quantidade_manual,
                        preco_produto_unitario, preco_por_litro,
                        total_nf_compra, valor_total_frete, comissao_motorista,
                        valor_cte, comissao_cte, lucro
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
                    motoristas_id,
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
                    lucro or 0
                ))
                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

            flash('Frete criado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f'Erro ao salvar frete: {e}', 'danger')
            return redirect(url_for('fretes.novo'))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # GET: carregar dados auxiliares para o formulário
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # destino_id e paga_comissao aqui são campos da tabela clientes no seu banco atual
        cursor.execute("SELECT id, razao_social, destino_id, paga_comissao, percentual_cte, cte_integral FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

        cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()

        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()

        try:
            cursor.execute("SELECT id, nome, paga_comissao FROM motoristas ORDER BY nome")
            motoristas = cursor.fetchall()
        except Exception:
            cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
            motoristas = cursor.fetchall()

        cursor.execute("SELECT id, caminhao, placa FROM veiculos WHERE ativo = 1 ORDER BY caminhao")
        veiculos = cursor.fetchall()

        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()

        # montar rotas_dict (origem|destino => valor_por_litro)
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

    # Tentar pré-selecionar destino: prioridade pedido_id -> cliente_id (query param)
    selected_destino_id = None
    pedido_id = request.args.get('pedido_id') or None
    cliente_id_param = request.args.get('cliente_id') or None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if pedido_id:
            cursor.execute("""
                SELECT c.destino_id
                FROM pedidositens pi
                JOIN clientes c ON pi.clienteid = c.id
                WHERE pi.pedidoid = %s
                LIMIT 1
            """, (pedido_id,))
            row = cursor.fetchone()
            if row:
                selected_destino_id = row.get('destino_id') if isinstance(row, dict) else row[0]
        if not selected_destino_id and cliente_id_param:
            cursor.execute("SELECT destino_id FROM clientes WHERE id = %s LIMIT 1", (cliente_id_param,))
            row = cursor.fetchone()
            if row:
                selected_destino_id = row.get('destino_id') if isinstance(row, dict) else row[0]
    except Exception:
        selected_destino_id = None
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    frete = None

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
        selected_destino_id=selected_destino_id
    )


@bp.route('/salvar_importados', methods=['POST'])
@login_required
def salvar_importados():
    """
    Recebe formulário de importação (templates/fretes/importar-pedido.html).
    - Por padrão só loga e devolve flash informando quantidade recebida.
    - Se for enviado save=1 no form, tenta gravar (com logging por item e sem abortar todos em erro).
    """
    form = request.form or {}
    current_app.logger.info("[salvar_importados] POST recebida - keys: %s", list(form.keys()))

    for k in form.keys():
        current_app.logger.debug("[salvar_importados] form[%s]=%s", k, form.get(k))

    pattern = re.compile(r'^itens\[(\d+)\]\[(.+)\]$')
    items = {}
    for key in form.keys():
        m = pattern.match(key)
        if m:
            idx = int(m.group(1))
            field = m.group(2)
            items.setdefault(idx, {})[field] = form.get(key)

    total_items = len(items)
    current_app.logger.info("[salvar_importados] Itens detectados: %d", total_items)

    for idx, item in sorted(items.items()):
        current_app.logger.info("[salvar_importados] item[%d] = %s", idx, item)

    if total_items == 0:
        flash('Nenhum item recebido na importação.', 'warning')
        return redirect(url_for('pedidos.importar_lista'))

    do_save = form.get('save') == '1' or form.get('salvar') == '1'

    if not do_save:
        flash(f'Importação recebida: {total_items} item(ns). Implementação de gravação não ativada.', 'success')
        return redirect(url_for('fretes.lista'))

    # Capturar pedido_id do formulário e validar
    pedido_id_raw = form.get('pedido_id')
    current_app.logger.info("[salvar_importados] pedido_id recebido (tipo: %s, vazio: %s)", 
                           type(pedido_id_raw).__name__, 
                           not bool(pedido_id_raw))
    pedido_id = None
    if pedido_id_raw:
        # Verifica se não é string vazia
        if isinstance(pedido_id_raw, str):
            pedido_id_raw = pedido_id_raw.strip()
        if pedido_id_raw:  # Se ainda tem valor após strip (ou não era string)
            try:
                pedido_id = int(pedido_id_raw)
                current_app.logger.info("[salvar_importados] pedido_id convertido para int: %s", pedido_id)
            except (ValueError, TypeError):
                current_app.logger.warning("[salvar_importados] pedido_id inválido (não é número inteiro)")
                pedido_id = None
        else:
            current_app.logger.warning("[salvar_importados] pedido_id é string vazia")
    else:
        current_app.logger.warning("[salvar_importados] pedido_id não fornecido (None ou vazio)")
    
    conn = get_db_connection()
    cur = conn.cursor()
    saved = 0
    failed = []
    try:
        for idx, item in sorted(items.items()):
            try:
                data_frete = item.get('data_frete') or request.form.get('data_frete') or None
                clientes_id = item.get('cliente_id') or None
                motoristas_id = item.get('motorista_id') or request.form.get('motorista_id') or None

                def to_num(v):
                    try:
                        return parse_moeda(v)
                    except Exception:
                        try:
                            return float(v)
                        except Exception:
                            return 0

                valor_total_frete = to_num(item.get('valor_total_frete') or request.form.get('valor_total_frete') or 0)
                comissao_motorista = to_num(item.get('comissao_motorista') or request.form.get('comissao_motorista') or 0)
                valor_cte = to_num(item.get('valor_cte') or request.form.get('valor_cte') or 0)
                comissao_cte = to_num(item.get('comissao_cte') or request.form.get('comissao_cte') or 0)
                lucro = None
                try:
                    lucro = to_num(item.get('lucro')) if item.get('lucro') is not None else None
                except Exception:
                    lucro = None
                if lucro is None:
                    lucro = (valor_total_frete or 0) - (comissao_motorista or 0) - (comissao_cte or 0)

                cur.execute("""
                    INSERT INTO fretes (
                        data_frete, status, observacoes,
                        clientes_id, fornecedores_id, produto_id,
                        origem_id, destino_id, motoristas_id, veiculos_id,
                        quantidade_id, quantidade_manual,
                        preco_produto_unitario, preco_por_litro,
                        total_nf_compra, valor_total_frete, comissao_motorista,
                        valor_cte, comissao_cte, lucro
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    data_frete or None,
                    item.get('status') or 'Importado',
                    item.get('observacoes') or '',
                    clientes_id,
                    item.get('fornecedor_id'),
                    item.get('produto_id'),
                    item.get('origem_id'),
                    item.get('destino_id'),
                    motoristas_id,
                    item.get('veiculo_id') or request.form.get('veiculo_id'),
                    item.get('quantidade_id'),
                    item.get('quantidade'),
                    to_num(item.get('preco_unitario') or 0),
                    to_num(item.get('preco_por_litro') or 0),
                    to_num(item.get('total_nf') or 0),
                    valor_total_frete or 0,
                    comissao_motorista or 0,
                    valor_cte or 0,
                    comissao_cte or 0,
                    lucro or 0
                ))
                conn.commit()
                saved += 1
                current_app.logger.info("[salvar_importados] item[%d] salvo com sucesso (id_tmp=%s)", idx, cur.lastrowid)
            except Exception as e_item:
                conn.rollback()
                current_app.logger.exception("[salvar_importados] erro ao salvar item[%d]: %s", idx, e_item)
                failed.append({'idx': idx, 'error': str(e_item), 'item': item})
        
        # Se todos os itens foram salvos com sucesso e temos um pedido_id, atualizar status para 'Faturado'
        current_app.logger.info("[salvar_importados] Verificando condições: saved=%d, failed=%d, pedido_id=%s", saved, len(failed), pedido_id)
        if saved > 0 and len(failed) == 0 and pedido_id:
            try:
                cur.execute("UPDATE pedidos SET status = %s WHERE id = %s", ('Faturado', pedido_id))
                conn.commit()
                current_app.logger.info("[salvar_importados] Pedido #%s atualizado para status 'Faturado'", pedido_id)
            except Exception as e_status:
                conn.rollback()
                current_app.logger.exception("[salvar_importados] erro ao atualizar status do pedido: %s", e_status)
                flash("Fretes salvos, mas erro ao atualizar status do pedido.", "warning")
        else:
            current_app.logger.warning("[salvar_importados] Status não atualizado - saved=%d, failed=%d, pedido_id=%s", saved, len(failed), pedido_id)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    summary = f"Importação: {total_items} item(ns). Salvos: {saved}. Falharam: {len(failed)}."
    current_app.logger.info("[salvar_importados] resumo: %s", summary)
    if failed:
        current_app.logger.error("[salvar_importados] detalhes falhas: %s", failed)
        flash(f"{summary} Veja logs para detalhes.", "warning")
    else:
        flash(summary, "success")

    return redirect(url_for('fretes.lista'))


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
                    try:
                        cchk.execute("SELECT paga_comissao FROM clientes WHERE id = %s LIMIT 1", (clientes_id,))
                        crow = cchk.fetchone()
                        if crow:
                            cliente_paga_frete = bool(crow.get('paga_comissao') if isinstance(crow, dict) else crow[0])
                    except Exception:
                        cliente_paga_frete = True
                    finally:
                        try:
                            cchk.close()
                        except Exception:
                            pass
            except Exception:
                cliente_paga_frete = True

            motoristas_id = request.form.get('motoristas_id')
            motorista_recebe_comissao = True
            try:
                if motoristas_id:
                    mch = conn.cursor(dictionary=True)
                    try:
                        mch.execute("SELECT paga_comissao FROM motoristas WHERE id = %s LIMIT 1", (motoristas_id,))
                        mrow = mch.fetchone()
                        if mrow:
                            motorista_recebe_comissao = bool(mrow.get('paga_comissao') if isinstance(mrow, dict) else mrow[0])
                    except Exception:
                        motorista_recebe_comissao = True
                    finally:
                        try:
                            mch.close()
                        except Exception:
                            pass
            except Exception:
                motorista_recebe_comissao = True

            if not cliente_paga_frete:
                preco_por_litro = 0
                valor_total_frete = 0
                comissao_motorista = 0
                comissao_cte = comissao_cte or 0
                lucro = 0
            else:
                if cliente_paga_frete and not motorista_recebe_comissao:
                    comissao_motorista = 0
                    lucro = round((valor_total_frete or 0) - float(comissao_motorista or 0) - float(comissao_cte or 0), 2)

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
                request.form.get('clientes_id'),
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

        try:
            cursor.execute("SELECT id, nome, paga_comissao FROM motoristas ORDER BY nome")
            motoristas = cursor.fetchall()
        except Exception:
            cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
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

    if frete is None:
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
