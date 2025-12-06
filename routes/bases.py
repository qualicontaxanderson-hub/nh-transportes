from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime

# Corrigido: blueprint renomeado para 'bases' para evitar duplicação com 'fretes'
bp = Blueprint('bases', __name__, url_prefix='/bases')


def parse_moeda(valor):
    """
    Converte uma string de moeda em float (pt-BR ou en).
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

            # Determinar quantidade (manual ou via quantidade_id)
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

            # total_nf_compra fallback
            if (not total_nf_compra or total_nf_compra == 0) and quantidade > 0 and preco_produto_unitario > 0:
                total_nf_compra = round(preco_produto_unitario * quantidade, 2)

            # preco_por_litro fallback (a partir de total_nf_compra)
            if (not preco_por_litro or preco_por_litro == 0) and quantidade > 0 and total_nf_compra > 0:
                preco_por_litro = round(total_nf_compra / quantidade, 4)

            # valor_total_frete fallback
            if (not valor_total_frete or valor_total_frete == 0) and quantidade > 0 and preco_por_litro > 0:
                valor_total_frete = round(preco_por_litro * quantidade, 2)

            # Verificar flags do cliente (se não paga frete) e cte_integral
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

            # Se cliente não paga frete -> forçar zeros
            if not cliente_paga_frete:
                preco_por_litro = 0.0
                valor_total_frete = 0.0
                comissao_motorista = 0.0
                comissao_cte = 0.0
                lucro = 0.0

            # Calcular valor_cte: CTe integral ou tarifa por rota
            if cliente_cte_integral:
                valor_cte = round(valor_total_frete if cliente_paga_frete else 0.0, 2)
            else:
                try:
                    rc = conn.cursor(dictionary=True)
                    rc.execute("SELECT valor_por_litro FROM rotas WHERE origem_id=%s AND destino_id=%s LIMIT 1", (request.form.get('origem_id'), request.form.get('destino_id')))
                    rrow = rc.fetchone()
                    rc.close()
                    tarifa = float(rrow.get('valor_por_litro')) if (rrow and rrow.get('valor_por_litro') is not None) else 0.0
                    valor_cte = round((quantidade * tarifa) if (quantidade and tarifa) else 0.0, 2)
                except Exception:
                    valor_cte = 0.0

            comissao_cte = round(valor_cte * 0.08, 2)

            # Comissão motorista (somente se cliente paga e motorista recebe comissão)
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
                round(preco_produto_unitario or 0, 3),
                round(preco_por_litro or 0, 4),
                round(total_nf_compra or 0, 2),
                round(valor_total_frete or 0, 2),
                round(comissao_motorista or 0, 2),
                round(valor_cte or 0, 2),
                round(comissao_cte or 0, 2),
                round(lucro or 0, 2),
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
