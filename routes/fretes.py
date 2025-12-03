from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
import re

# Blueprint
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
        # remove "R$" e espaços
        s = s.replace('R$', '').replace('r$', '').replace('R','').replace(' ', '')
        # se tiver tanto ponto quanto vírgula, assumimos pt-BR: ponto = milhar, vírgula = decimal
        if '.' in s and ',' in s:
            s = s.replace('.', '')
            s = s.replace(',', '.')
        else:
            # troca vírgula por ponto (caso venha '10,5' ou '0,10')
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
                   c.razao_social AS cliente,
                   fo.razao_social AS fornecedor,
                   m.nome AS motorista,
                   v.caminhao AS veiculo
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
            # Preferir campos "raw" enviados pelo formulário (se existirem),
            # caso contrário limpar os campos formatados via parse_moeda.
            preco_produto_unitario_raw = request.form.get('preco_produto_unitario_raw')
            if preco_produto_unitario_raw is None or preco_produto_unitario_raw == '':
                preco_produto_unitario_raw = parse_moeda(request.form.get('preco_produto_unitario'))
            else:
                preco_produto_unitario_raw = parse_moeda(preco_produto_unitario_raw)

            preco_por_litro = request.form.get('preco_por_litro_raw')
            if preco_por_litro is None or preco_por_litro == '':
                preco_por_litro = parse_moeda(request.form.get('preco_por_litro'))
            else:
                preco_por_litro = parse_moeda(preco_por_litro)

            total_nf_compra = request.form.get('total_nf_compra')
            total_nf_compra = parse_moeda(total_nf_compra)

            valor_total_frete = request.form.get('valor_total_frete')
            valor_total_frete = parse_moeda(valor_total_frete)

            comissao_motorista = request.form.get('comissao_motorista')
            comissao_motorista = parse_moeda(comissao_motorista)

            valor_cte = request.form.get('valor_cte')
            valor_cte = parse_moeda(valor_cte)

            comissao_cte = request.form.get('comissao_cte')
            comissao_cte = parse_moeda(comissao_cte)

            lucro = request.form.get('lucro')
            lucro = parse_moeda(lucro)

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
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                preco_produto_unitario_raw or 0,
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
        finally:
            cursor.close()
            conn.close()

    # GET: carregar dados para o formulário
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

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

    # montar dict de rotas para o template JS (chave "origem|destino" -> valor_por_litro)
    rotas_dict = {}
    try:
        cursor.execute("SELECT origem_id, destino_id, valor_por_litro FROM rotas WHERE ativo = 1")
        rotas_rows = cursor.fetchall()
        for r in rotas_rows:
            try:
                origem_id = r.get('origem_id') if isinstance(r, dict) else r[0]
                destino_id = r.get('destino_id') if isinstance(r, dict) else r[1]
                valor = r.get('valor_por_litro') if isinstance(r, dict) else r[2]
                key = f"{int(origem_id)}|{int(destino_id)}"
                rotas_dict[key] = float(valor or 0)
            except Exception:
                try:
                    key = f"{r.get('origem_id')}|{r.get('destino_id')}"
                    rotas_dict[key] = float(r.get('valor_por_litro') or 0)
                except Exception:
                    try:
                        parts = list(r)
                        key = f"{int(parts[0])}|{int(parts[1])}"
                        rotas_dict[key] = float(parts[2] or 0)
                    except Exception:
                        pass
    except Exception:
        # se der erro, mantemos rotas_dict vazio (JS trata ROTAS indefinido/{} com fallback)
        rotas_dict = {}

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
    O template envia campos no padrão: itens[<idx>][campo] e campos comuns no formulário.
    Esta função tenta ser tolerante a ausência de alguns campos e recalcula valores quando necessário.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        data_frete = request.form.get('data_frete') or None
        status = request.form.get('status') or 'Pendente'
        motorista_id = request.form.get('motorista_id') or None
        veiculo_id = request.form.get('veiculo_id') or None

        # montar dicionário de itens a partir das chaves do form 'itens[<i>][<campo>]'
        itens = {}
        pattern = re.compile(r'^itens\[(\d+)\]\[(.+)\]$')
        for key, val in request.form.items():
            m = pattern.match(key)
            if m:
                idx = int(m.group(1))
                campo = m.group(2)
                itens.setdefault(idx, {})[campo] = val

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

        # percorrer itens ordenados
        for idx in sorted(itens.keys()):
            item = itens[idx]
            clientes_id = item.get('cliente_id') or None
            produto_id = item.get('produto_id') or None
            fornecedores_id = item.get('fornecedor_id') or None
            origem_id = item.get('origem_id') or None
            destino_id = item.get('destino_id') or item.get('cliente_destino_id') or None
            quantidade = parse_moeda(item.get('quantidade') or 0)
            quantidade_id = item.get('quantidade_id') or None

            # preco unitário (campo enviado como preco_unitario) - pode estar formatado
            preco_unit = parse_moeda(item.get('preco_unitario') or item.get('preco_unitario_raw') or 0)

            # total nf: prefer form value, senão calcule
            total_nf = parse_moeda(item.get('total_nf') or 0)
            if total_nf == 0 and quantidade > 0 and preco_unit > 0:
                total_nf = preco_unit * quantidade

            # preco por litro: prefer valor enviado, senão derive de total_nf / quantidade (se aplicavel)
            preco_por_litro = parse_moeda(item.get('preco_por_litro') or item.get('campo-preco-litro') or 0)
            if (preco_por_litro == 0 or preco_por_litro is None) and quantidade > 0 and total_nf > 0:
                # tentar inferir: se preco_unit foi fornecido como total NF, preco_por_litro = total_nf / quantidade
                preco_por_litro = total_nf / quantidade if quantidade > 0 else 0

            # valor_total_frete: prefer campo, senão quantidade * preco_por_litro
            valor_total_frete = parse_moeda(item.get('valor_total_frete') or 0)
            if (valor_total_frete == 0 or valor_total_frete is None) and quantidade > 0 and preco_por_litro > 0:
                valor_total_frete = quantidade * preco_por_litro

            # valor_cte: prefer enviado, senão calcular via rotas (valor_por_litro * quantidade)
            valor_cte = parse_moeda(item.get('valor_cte') or 0)
            if (valor_cte == 0 or valor_cte is None):
                tarifa = rota_valor_por_litro(origem_id, destino_id)
                valor_cte = quantidade * tarifa if quantidade and tarifa else 0.0

            # comissao_cte = 8% sobre valor_cte
            comissao_cte = round(valor_cte * 0.08, 2)

            # comissao_motorista: se motorista_paga_comissao == 0 -> 0, else regra Q * 0.01
            comissao_motorista = 0.0
            if motorista_paga_comissao and quantidade:
                try:
                    if int(motorista_paga_comissao) == 0:
                        comissao_motorista = 0.0
                    else:
                        comissao_motorista = round(quantidade * 0.01, 2)
                except Exception:
                    comissao_motorista = round(quantidade * 0.01, 2) if quantidade else 0.0

            # lucro = valor_total_frete - comissao_motorista - comissao_cte
            lucro = 0.0
            if valor_total_frete:
                lucro = round(float(valor_total_frete) - float(comissao_motorista) - float(comissao_cte), 2)

            # Inserir no banco (colunas compatíveis com novo())
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
                status,
                request.form.get('observacoes') or '',
                clientes_id,
                fornecedores_id,
                produto_id,
                origem_id,
                destino_id,
                motorista_id,
                veiculo_id,
                quantidade_id or None,
                (item.get('quantidade') or None),
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
        flash('Importação salva: fretes criados com sucesso.', 'success')
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
            # Normalizar valores monetários antes do update
            preco_produto_unitario_raw = request.form.get('preco_produto_unitario_raw')
            if preco_produto_unitario_raw is None or preco_produto_unitario_raw == '':
                preco_produto_unitario_raw = parse_moeda(request.form.get('preco_produto_unitario'))
            else:
                preco_produto_unitario_raw = parse_moeda(preco_produto_unitario_raw)

            preco_por_litro = request.form.get('preco_por_litro_raw')
            if preco_por_litro is None or preco_por_litro == '':
                preco_por_litro = parse_moeda(request.form.get('preco_por_litro'))
            else:
                preco_por_litro = parse_moeda(preco_por_litro)

            total_nf_compra = parse_moeda(request.form.get('total_nf_compra'))
            valor_total_frete = parse_moeda(request.form.get('valor_total_frete'))
            comissao_motorista = parse_moeda(request.form.get('comissao_motorista'))
            valor_cte = parse_moeda(request.form.get('valor_cte'))
            comissao_cte = parse_moeda(request.form.get('comissao_cte'))
            lucro = parse_moeda(request.form.get('lucro'))

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
                preco_produto_unitario_raw or 0,
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
            rotas_rows = cursor.fetchall()
            for r in rotas_rows:
                try:
                    origem_id = r.get('origem_id') if isinstance(r, dict) else r[0]
                    destino_id = r.get('destino_id') if isinstance(r, dict) else r[1]
                    valor = r.get('valor_por_litro') if isinstance(r, dict) else r[2]
                    key = f"{int(origem_id)}|{int(destino_id)}"
                    rotas_dict[key] = float(valor or 0)
                except Exception:
                    try:
                        key = f"{r.get('origem_id')}|{r.get('destino_id')}"
                        rotas_dict[key] = float(r.get('valor_por_litro') or 0)
                    except Exception:
                        try:
                            parts = list(r)
                            key = f"{int(parts[0])}|{int(parts[1])}"
                            rotas_dict[key] = float(parts[2] or 0)
                        except Exception:
                            pass
        except Exception:
            rotas_dict = {}

    finally:
        cursor.close()
        conn.close()

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
