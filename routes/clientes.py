from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required
from urllib.parse import quote

from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('clientes', __name__, url_prefix='/clientes')


def _get_grupos_contabeis(cursor):
    """Retorna os grupos contábeis ativos para uso nos formulários."""
    try:
        cursor.execute(
            "SELECT id, codigo, nome FROM plano_contas_grupos WHERE ativo = 1 ORDER BY codigo"
        )
        return cursor.fetchall()
    except Exception:
        return []


def _str_or_dash(value):
    texto = (str(value).strip() if value is not None else '')
    return texto if texto else '—'


def _montar_endereco_completo(cliente):
    partes = []
    linha_principal = ' '.join([
        p for p in [
            (cliente.get('endereco') or '').strip(),
            (cliente.get('numero') or '').strip()
        ] if p
    ]).strip()
    if linha_principal:
        partes.append(linha_principal)
    if cliente.get('complemento'):
        partes.append(str(cliente['complemento']).strip())
    if cliente.get('bairro'):
        partes.append(str(cliente['bairro']).strip())

    cidade_uf = _cidade_uf(cliente)
    if cidade_uf:
        partes.append(cidade_uf)
    if cliente.get('cep'):
        partes.append(f"CEP {str(cliente['cep']).strip()}")
    return ', '.join([p for p in partes if p]).strip() or '—'


def _montar_endereco_waze(cliente):
    partes = []
    if cliente.get('razao_social'):
        partes.append(str(cliente['razao_social']).strip())
    if cliente.get('endereco'):
        linha_principal = ' '.join([
            p for p in [
                str(cliente['endereco']).strip(),
                str(cliente.get('numero') or '').strip()
            ] if p
        ]).strip()
        if linha_principal:
            partes.append(linha_principal)
    if cliente.get('bairro'):
        partes.append(str(cliente['bairro']).strip())

    cidade = (cliente.get('municipio') or cliente.get('destino_cidade') or '').strip()
    uf = (cliente.get('uf') or cliente.get('destino_estado') or '').strip()
    cidade_estado = ' '.join([p for p in [cidade, uf] if p]).strip()
    if cidade_estado:
        partes.append(cidade_estado)
    if cliente.get('cep'):
        partes.append(str(cliente['cep']).strip())

    consulta = ', '.join([p for p in partes if p]).strip()
    return consulta or _str_or_dash(cliente.get('razao_social'))


def _montar_link_waze(cliente):
    consulta = _montar_endereco_waze(cliente)
    if consulta == '—':
        return 'Endereço não disponível para Waze.'
    return f"https://www.waze.com/ul?q={quote(consulta)}&navigate=yes"


def _montar_mensagem_whatsapp(cliente):
    cidade_uf = _cidade_uf(cliente) or '—'
    endereco = _montar_endereco_completo(cliente)
    link_waze = _montar_link_waze(cliente)
    return '\n'.join([
        "🚛 *DADOS DO CLIENTE*",
        "",
        f"📍 *CIDADE/UF: {cidade_uf}*",
        "",
        f"*Razão Social:* {_str_or_dash(cliente.get('razao_social'))}",
        f"*Nome Fantasia:* {_str_or_dash(cliente.get('nome_fantasia'))}",
        f"*CNPJ:* {_str_or_dash(cliente.get('cnpj'))}",
        f"*Endereço:* {endereco}",
        "",
        "🧭 *Localização no Waze:*",
        link_waze,
    ])


def _cidade_uf(cliente):
    cidade = (cliente.get('municipio') or cliente.get('destino_cidade') or '').strip()
    uf = (cliente.get('uf') or cliente.get('destino_estado') or '').strip()
    return ' / '.join([p for p in [cidade, uf] if p]).strip()


@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.*,
               d.nome AS destino_nome,
               d.estado AS destino_estado,
               g.codigo AS grupo_codigo,
               g.nome   AS grupo_nome
        FROM clientes c
        LEFT JOIN destinos d ON d.id = c.destino_id
        LEFT JOIN plano_contas_grupos g ON g.id = c.grupo_contabil_id
        ORDER BY c.razao_social
    """)
    clientes = cursor.fetchall()
    fatur = _faturamento_clientes(cursor)
    cursor.close()
    conn.close()

    maior = max([m['total'] for m in fatur.values()] or [0]) or 1
    for c in clientes:
        fx = fatur.get(c['id']) or {'n': 0, 'total': 0.0, 'ultimo': None}
        c['fre_n'] = fx['n']
        c['fre_total'] = fx['total']
        c['fre_ultimo'] = fx['ultimo']
        c['peso'] = round(100.0 * fx['total'] / maior, 1)

    # O que falta em cada cadastro. Serve pra duas coisas: o selo da linha e
    # o contador do topo. `municipio` entra aqui porque e o endereco que vai
    # no boleto — nao confundir com destino_id, que e a rota do frete.
    faltas = [('cnpj', 'CNPJ'), ('telefone', 'telefone'), ('email', 'e-mail'),
              ('municipio', 'município'), ('endereco', 'endereço')]
    for c in clientes:
        c['faltando'] = [rot for campo, rot in faltas
                         if not (c.get(campo) or '').strip()]
        # So da pra completar pela Receita quem tem CNPJ.
        c['completavel'] = bool((c.get('cnpj') or '').strip()) and bool(c['faltando'])

    totais = {
        'clientes': len(clientes),
        'com_cnpj': sum(1 for c in clientes if (c.get('cnpj') or '').strip()),
        'incompletos': sum(1 for c in clientes if c['faltando']),
        'com_grupo': sum(1 for c in clientes if c.get('grupo_contabil_id')),
        'completaveis': sum(1 for c in clientes if c['completavel']),
        'com_frete': sum(1 for c in clientes if c['fre_n']),
        'faturado': sum(c['fre_total'] for c in clientes),
        'sem_destino': sum(1 for c in clientes if not c.get('destino_id')),
    }
    return render_template('clientes/lista.html', clientes=clientes, totais=totais)


def _faturamento_clientes(cursor):
    """Quanto cada cliente rendeu em frete, e quando foi o ultimo.

    O valor e o do CT-e (`fretes.valor_cte`) — e o que a transportadora
    fatura pelo servico, nao o valor do produto que o cliente comprou.
    """
    try:
        cursor.execute("""
            SELECT f.clientes_id AS cid, COUNT(*) AS n,
                   COALESCE(SUM(f.valor_cte),0) AS total,
                   MAX(DATE(f.data_frete)) AS ultimo
              FROM fretes f
             WHERE f.clientes_id IS NOT NULL
             GROUP BY f.clientes_id
        """)
        return {r['cid']: {'n': int(r['n']), 'total': float(r['total'] or 0),
                           'ultimo': r['ultimo']} for r in cursor.fetchall()}
    except Exception:
        return {}


def _rotas_por_destino(cursor):
    """Quais rotas ativas chegam em cada destino, com o valor por litro.

    Serve pra tela mostrar o que o campo "Destino de frete" de fato faz: e
    dele que sai o preco do CT-e (rotas casa origem x destino). Sem isso o
    select parece so mais um cadastro solto.
    """
    try:
        cursor.execute("""
            SELECT r.destino_id, o.nome AS origem, r.valor_por_litro AS valor
              FROM rotas r
              JOIN origens o ON o.id = r.origem_id
             WHERE r.ativo = 1
             ORDER BY r.destino_id, r.valor_por_litro
        """)
        rows = cursor.fetchall()
    except Exception:
        return {}
    saida = {}
    for r in rows:
        saida.setdefault(r['destino_id'], []).append(
            {'origem': r['origem'], 'valor': float(r['valor'] or 0)})
    return saida


def _falta_no_cadastro(cliente):
    """O que esta em branco e a Receita saberia preencher."""
    rotulos = [('nome_fantasia', 'fantasia'), ('cnpj', 'CNPJ'),
               ('telefone', 'telefone'), ('email', 'e-mail'),
               ('endereco', 'endereço'), ('municipio', 'município'),
               ('uf', 'UF'), ('cep', 'CEP')]
    return [rot for campo, rot in rotulos
            if not ((cliente or {}).get(campo) or '').strip()]


def _consulta_receita(cnpj):
    """Um CNPJ na BrasilAPI. Devolve dict com os campos ou None.

    Mesma fonte que o Fornecedor ja usa. Aqui a consulta e feita no servidor
    (e nao no navegador) porque a tela de completar em massa precisa de
    dezenas de CNPJs numa tacada.
    """
    import json as _j
    import re as _re
    import urllib.request as _u
    so = _re.sub(r'\D', '', cnpj or '')
    if len(so) != 14:
        return None
    try:
        req = _u.Request('https://brasilapi.com.br/api/cnpj/v1/' + so,
                         headers={'User-Agent': 'Mozilla/5.0'})
        with _u.urlopen(req, timeout=12) as r:
            d = _j.loads(r.read().decode('utf-8'))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    return {
        'razao_social': (d.get('razao_social') or '').strip(),
        'nome_fantasia': (d.get('nome_fantasia') or '').strip(),
        'telefone': (d.get('ddd_telefone_1') or '').strip(),
        'email': (d.get('email') or '').strip(),
        'cep': (d.get('cep') or '').strip(),
        'endereco': (d.get('logradouro') or '').strip(),
        'numero': (d.get('numero') or '').strip(),
        'complemento': (d.get('complemento') or '').strip(),
        'bairro': (d.get('bairro') or '').strip(),
        'municipio': (d.get('municipio') or '').strip(),
        'uf': (d.get('uf') or '').strip(),
    }


# Campos que a Receita pode preencher. `destino_id` NAO esta aqui de
# proposito: ele e a rota do frete (origem x destino -> valor por litro do
# CT-e), e escolha sua — a Receita nao tem opiniao sobre isso.
_CAMPOS_RECEITA = ('razao_social', 'nome_fantasia', 'telefone', 'email', 'cep',
                   'endereco', 'numero', 'complemento', 'bairro', 'municipio', 'uf')


@bp.route('/completar-receita', methods=['GET', 'POST'])
@login_required
@admin_required
def completar_receita():
    """Completa cadastros com o que a Receita sabe — SO campo vazio.

    O que voce digitou a mao nunca e sobrescrito: se a Receita traz diferente,
    vira aviso, nao substituicao. Isso importa porque o telefone e o e-mail do
    cadastro sao os de quem voce fala de verdade, e a Receita costuma ter o
    do contador.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            ids = [int(i) for i in request.form.getlist('cliente_ids') if str(i).isdigit()]
            aplicados = 0
            for cid in ids:
                cursor.execute("SELECT * FROM clientes WHERE id = %s", (cid,))
                cli = cursor.fetchone()
                if not cli:
                    continue
                dados = _consulta_receita(cli.get('cnpj'))
                if not dados:
                    continue
                sets, params = [], []
                for campo in _CAMPOS_RECEITA:
                    if not dados.get(campo):
                        continue
                    if (cli.get(campo) or '').strip():
                        continue            # tem valor: NAO mexe
                    sets.append("%s = %%s" % campo)
                    params.append(dados[campo])
                if not sets:
                    continue
                params.append(cid)
                cursor.execute("UPDATE clientes SET %s WHERE id = %%s"
                               % ', '.join(sets), params)
                aplicados += 1
            conn.commit()
            flash('%d cadastro(s) completado(s) pela Receita Federal.' % aplicados,
                  'success')
            return redirect(url_for('clientes.lista'))

        cursor.execute("""SELECT * FROM clientes
                           WHERE cnpj IS NOT NULL AND cnpj <> ''
                           ORDER BY razao_social""")
        todos = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    # So interessa quem tem buraco. Consulta a Receita de cada um pra mostrar
    # o que ELA preencheria — nada e gravado antes de voce aprovar.
    candidatos = []
    for cli in todos:
        faltando = [c for c in _CAMPOS_RECEITA if not (cli.get(c) or '').strip()]
        if not faltando:
            continue
        dados = _consulta_receita(cli.get('cnpj'))
        if not dados:
            candidatos.append({'cliente': cli, 'erro': 'CNPJ não encontrado na Receita',
                               'ganhos': []})
            continue
        ganhos = [{'campo': c, 'valor': dados[c]} for c in faltando if dados.get(c)]
        if ganhos:
            candidatos.append({'cliente': cli, 'erro': None, 'ganhos': ganhos})

    return render_template('clientes/completar_receita.html', candidatos=candidatos)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Pegar valor dos checkboxes - aceita 'on' ou '1'
            paga_comissao_raw = request.form.get('paga_comissao')
            cte_integral_raw = request.form.get('cte_integral')

            paga_comissao = 1 if paga_comissao_raw in ['on', '1', 1, True] else 0
            cte_integral = 1 if cte_integral_raw in ['on', '1', 1, True] else 0

            # Pegar destino_id (município)
            destino_id_raw = request.form.get('destino_id')
            destino_id = int(destino_id_raw) if destino_id_raw else None

            # Pegar grupo contábil
            grupo_id_raw = request.form.get('grupo_contabil_id')
            grupo_contabil_id = int(grupo_id_raw) if grupo_id_raw else None

            cursor.execute("""
                INSERT INTO clientes (
                    razao_social, nome_fantasia, cnpj, ie, contato,
                    endereco, numero, complemento, bairro, municipio, uf, cep,
                    telefone, email, paga_comissao, cte_integral, destino_id, grupo_contabil_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('razao_social'),
                request.form.get('nome_fantasia') or None,
                request.form.get('cnpj') or None,
                request.form.get('ie') or None,
                request.form.get('contato') or None,
                request.form.get('endereco') or None,
                request.form.get('numero') or None,
                request.form.get('complemento') or None,
                request.form.get('bairro') or None,
                request.form.get('municipio') or None,
                request.form.get('uf') or None,
                request.form.get('cep') or None,
                request.form.get('telefone') or None,
                request.form.get('email') or None,
                paga_comissao,
                cte_integral,
                destino_id,
                grupo_contabil_id,
            ))

            conn.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('clientes.lista'))

        # GET: carregar destinos (municípios) e grupos contábeis
        cursor.execute("""
            SELECT id, nome, cidade, estado
            FROM destinos
            ORDER BY nome
        """)
        destinos = cursor.fetchall()
        grupos = _get_grupos_contabeis(cursor)
        return render_template('clientes/novo.html', destinos=destinos,
                               grupos=grupos, rotas=_rotas_por_destino(cursor))
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar cliente: {str(e)}', 'danger')
        return redirect(url_for('clientes.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # Pegar valor dos checkboxes - aceita 'on' ou '1'
            paga_comissao_raw = request.form.get('paga_comissao')
            cte_integral_raw = request.form.get('cte_integral')

            paga_comissao = 1 if paga_comissao_raw in ['on', '1', 1, True] else 0
            cte_integral = 1 if cte_integral_raw in ['on', '1', 1, True] else 0

            # Pegar destino_id (município)
            destino_id_raw = request.form.get('destino_id')
            destino_id = int(destino_id_raw) if destino_id_raw else None

            # Pegar grupo contábil
            grupo_id_raw = request.form.get('grupo_contabil_id')
            grupo_contabil_id = int(grupo_id_raw) if grupo_id_raw else None

            cursor.execute("""
                UPDATE clientes SET razao_social=%s, nome_fantasia=%s, cnpj=%s, ie=%s, contato=%s,
                    endereco=%s, numero=%s, complemento=%s, bairro=%s, municipio=%s, uf=%s, cep=%s,
                    telefone=%s, email=%s, paga_comissao=%s, cte_integral=%s, destino_id=%s,
                    grupo_contabil_id=%s
                WHERE id=%s
            """, (
                request.form.get('razao_social'),
                request.form.get('nome_fantasia') or None,
                request.form.get('cnpj') or None,
                request.form.get('ie') or None,
                request.form.get('contato') or None,
                request.form.get('endereco') or None,
                request.form.get('numero') or None,
                request.form.get('complemento') or None,
                request.form.get('bairro') or None,
                request.form.get('municipio') or None,
                request.form.get('uf') or None,
                request.form.get('cep') or None,
                request.form.get('telefone') or None,
                request.form.get('email') or None,
                paga_comissao,
                cte_integral,
                destino_id,
                grupo_contabil_id,
                id,
            ))

            conn.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('clientes.lista'))

        # GET: buscar cliente
        cursor.execute("SELECT * FROM clientes WHERE id = %s", (id,))
        cliente = cursor.fetchone()

        # GET: buscar destinos (municípios) e grupos contábeis
        cursor.execute("SELECT id, nome, cidade, estado FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()
        grupos = _get_grupos_contabeis(cursor)
        return render_template('clientes/editar.html', cliente=cliente,
                               destinos=destinos, grupos=grupos,
                               rotas=_rotas_por_destino(cursor),
                               faltando=_falta_no_cadastro(cliente))
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar cliente: {str(e)}', 'danger')
        return redirect(url_for('clientes.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))

        conn.commit()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir cliente: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('clientes.lista'))


@bp.route('/mensagem-whatsapp/<int:id>')
@login_required
@admin_required
def mensagem_whatsapp(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.*,
                   d.cidade AS destino_cidade,
                   d.estado AS destino_estado
            FROM clientes c
            LEFT JOIN destinos d ON d.id = c.destino_id
            WHERE c.id = %s
            LIMIT 1
        """, (id,))
        cliente = cursor.fetchone()
        if not cliente:
            return jsonify({'ok': False, 'error': 'Cliente não encontrado.'}), 404
        return jsonify({'ok': True, 'mensagem': _montar_mensagem_whatsapp(cliente)})
    except Exception as e:
        current_app.logger.exception('Erro ao montar mensagem de WhatsApp do cliente id=%s', id)
        return jsonify({'ok': False, 'error': 'Erro interno ao gerar mensagem.'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
