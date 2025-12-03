"""
Rotas para gestão de cobranças (PIX/Boleto) via EFI Bank
NH Transportes - Sistema de Gestão de Fretes
"""

import json
import base64
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.efi_api import get_efi_api, get_efi_config, EfiAPI

bp = Blueprint('cobrancas', __name__, url_prefix='/cobrancas')


@bp.route('/')
@login_required
def lista():
    """Lista todas as cobranças."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Filtros
        status = request.args.get('status', '')
        tipo = request.args.get('tipo', '')
        cliente_id = request.args.get('cliente_id', '')

        query = """
            SELECT c.*, 
                   cl.razao_social as cliente_nome,
                   f.id as frete_numero
            FROM cobrancas c
            LEFT JOIN clientes cl ON c.cliente_id = cl.id
            LEFT JOIN fretes f ON c.frete_id = f.id
            WHERE 1=1
        """
        params = []

        if status:
            query += " AND c.status = %s"
            params.append(status)
        if tipo:
            query += " AND c.tipo = %s"
            params.append(tipo)
        if cliente_id:
            query += " AND c.cliente_id = %s"
            params.append(cliente_id)

        query += " ORDER BY c.created_at DESC LIMIT 200"

        cursor.execute(query, params)
        cobrancas = cursor.fetchall()

        # Busca clientes para filtro
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    return render_template(
        'cobrancas/lista.html',
        cobrancas=cobrancas,
        clientes=clientes,
        filtro_status=status,
        filtro_tipo=tipo,
        filtro_cliente=cliente_id
    )


@bp.route('/nova', methods=['GET', 'POST'])
@login_required
def nova():
    """Cria uma nova cobrança."""
    if request.method == 'POST':
        # Verifica se API está configurada
        efi = get_efi_api()
        if not efi:
            flash('API EFI não configurada. Configure primeiro em Configurações.', 'danger')
            return redirect(url_for('cobrancas.configuracao'))

        tipo = request.form.get('tipo', 'pix')
        valor = float(request.form.get('valor', 0).replace(',', '.'))
        descricao = request.form.get('descricao', '')

        # Dados do pagador
        pagador_nome = request.form.get('pagador_nome', '')
        pagador_cpf_cnpj = request.form.get('pagador_cpf_cnpj', '')
        pagador_email = request.form.get('pagador_email', '')
        pagador_telefone = request.form.get('pagador_telefone', '')
        pagador_endereco = request.form.get('pagador_endereco', '')
        pagador_cidade = request.form.get('pagador_cidade', '')
        pagador_uf = request.form.get('pagador_uf', '')
        pagador_cep = request.form.get('pagador_cep', '')

        # Relacionamentos opcionais
        cliente_id = request.form.get('cliente_id') or None
        frete_id = request.form.get('frete_id') or None

        # Data de vencimento (para boleto)
        data_vencimento = request.form.get('data_vencimento') or None

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Cria a cobrança na API EFI
            if tipo == 'pix':
                resultado = efi.criar_cobranca_pix(
                    valor=valor,
                    descricao=descricao,
                    pagador_cpf=pagador_cpf_cnpj,
                    pagador_nome=pagador_nome
                )
            else:  # boleto
                resultado = efi.criar_boleto(
                    valor=valor,
                    descricao=descricao,
                    pagador_nome=pagador_nome,
                    pagador_cpf_cnpj=pagador_cpf_cnpj,
                    pagador_endereco=pagador_endereco,
                    pagador_cidade=pagador_cidade,
                    pagador_uf=pagador_uf,
                    pagador_cep=pagador_cep,
                    vencimento=data_vencimento
                )

            if resultado.get('sucesso'):
                # Salva no banco de dados
                cursor.execute("""
                    INSERT INTO cobrancas (
                        frete_id, cliente_id,
                        pagador_nome, pagador_cpf_cnpj, pagador_email, pagador_telefone,
                        pagador_endereco, pagador_cidade, pagador_uf, pagador_cep,
                        tipo, valor, descricao,
                        txid, location, qrcode_base64, pix_copia_cola,
                        nosso_numero, codigo_barras, linha_digitavel, link_boleto,
                        status, data_vencimento, efi_response
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                """, (
                    frete_id, cliente_id,
                    pagador_nome, pagador_cpf_cnpj, pagador_email, pagador_telefone,
                    pagador_endereco, pagador_cidade, pagador_uf, pagador_cep,
                    tipo, valor, descricao,
                    resultado.get('txid'),
                    resultado.get('location'),
                    resultado.get('qrcode_base64'),
                    resultado.get('pix_copia_cola'),
                    resultado.get('nosso_numero'),
                    resultado.get('codigo_barras'),
                    resultado.get('linha_digitavel'),
                    resultado.get('link_boleto'),
                    'aguardando',
                    data_vencimento or resultado.get('vencimento'),
                    json.dumps(resultado.get('resposta_completa', {}))
                ))
                conn.commit()

                cobranca_id = cursor.lastrowid
                flash('Cobrança criada com sucesso!', 'success')
                return redirect(url_for('cobrancas.detalhes', id=cobranca_id))

            else:
                flash(f'Erro ao criar cobrança: {resultado.get("erro")}', 'danger')

        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar cobrança: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    # GET: Carrega dados para o formulário
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id, razao_social, cpf_cnpj, telefone, email, endereco, municipio, uf, cep FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()

        cursor.execute("SELECT id, data_frete, valor_total_frete, clientes_id FROM fretes WHERE status != 'pago' ORDER BY id DESC LIMIT 100")
        fretes = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    # Verifica se API está configurada
    config = get_efi_config()

    return render_template(
        'cobrancas/nova.html',
        clientes=clientes,
        fretes=fretes,
        config_existe=config is not None
    )


@bp.route('/<int:id>')
@login_required
def detalhes(id):
    """Exibe detalhes de uma cobrança."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT c.*, 
                   cl.razao_social as cliente_nome,
                   f.id as frete_numero,
                   f.valor_total_frete as frete_valor
            FROM cobrancas c
            LEFT JOIN clientes cl ON c.cliente_id = cl.id
            LEFT JOIN fretes f ON c.frete_id = f.id
            WHERE c.id = %s
        """, (id,))
        cobranca = cursor.fetchone()

        if not cobranca:
            flash('Cobrança não encontrada.', 'warning')
            return redirect(url_for('cobrancas.lista'))

    finally:
        cursor.close()
        conn.close()

    return render_template('cobrancas/detalhes.html', cobranca=cobranca)


@bp.route('/<int:id>/atualizar-status', methods=['POST'])
@login_required
def atualizar_status(id):
    """Atualiza o status de uma cobrança consultando a API EFI."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM cobrancas WHERE id = %s", (id,))
        cobranca = cursor.fetchone()

        if not cobranca:
            return jsonify({'sucesso': False, 'erro': 'Cobrança não encontrada'}), 404

        if cobranca['tipo'] != 'pix' or not cobranca.get('txid'):
            return jsonify({'sucesso': False, 'erro': 'Apenas cobranças PIX podem ser atualizadas via API'}), 400

        efi = get_efi_api()
        if not efi:
            return jsonify({'sucesso': False, 'erro': 'API EFI não configurada'}), 500

        resultado = efi.consultar_pix(cobranca['txid'])

        if resultado.get('sucesso'):
            dados = resultado.get('dados', {})
            novo_status = dados.get('status', cobranca['status'])

            # Mapeia status da EFI para nosso sistema
            status_map = {
                'ATIVA': 'aguardando',
                'CONCLUIDA': 'pago',
                'REMOVIDA_PELO_USUARIO_RECEBEDOR': 'cancelado',
                'REMOVIDA_PELO_PSP': 'cancelado'
            }
            novo_status = status_map.get(novo_status, novo_status.lower())

            # Atualiza no banco
            cursor.execute("""
                UPDATE cobrancas 
                SET status = %s, 
                    updated_at = NOW(),
                    efi_response = %s
                WHERE id = %s
            """, (novo_status, json.dumps(dados), id))

            # Se pago, atualiza data de pagamento
            if novo_status == 'pago':
                pix_array = dados.get('pix', [])
                if pix_array:
                    valor_pago = float(pix_array[0].get('valor', 0))
                    cursor.execute("""
                        UPDATE cobrancas 
                        SET data_pagamento = NOW(),
                            valor_pago = %s
                        WHERE id = %s
                    """, (valor_pago, id))

            conn.commit()
            return jsonify({'sucesso': True, 'status': novo_status})

        else:
            return jsonify({'sucesso': False, 'erro': resultado.get('erro')}), 500

    except Exception as e:
        conn.rollback()
        return jsonify({'sucesso': False, 'erro': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar(id):
    """Cancela uma cobrança."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE cobrancas 
            SET status = 'cancelado', updated_at = NOW()
            WHERE id = %s AND status IN ('pendente', 'aguardando')
        """, (id,))
        conn.commit()

        if cursor.rowcount > 0:
            flash('Cobrança cancelada com sucesso.', 'success')
        else:
            flash('Não foi possível cancelar a cobrança.', 'warning')

    except Exception as e:
        conn.rollback()
        flash(f'Erro ao cancelar cobrança: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('cobrancas.lista'))


@bp.route('/configuracao', methods=['GET', 'POST'])
@login_required
def configuracao():
    """Página de configuração da API EFI."""
    # Verifica se é admin (se existir nível de usuário)
    if hasattr(current_user, 'nivel') and current_user.nivel != 'admin':
        flash('Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
        return redirect(url_for('cobrancas.lista'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        client_id = request.form.get('client_id', '').strip()
        client_secret = request.form.get('client_secret', '').strip()
        chave_pix = request.form.get('chave_pix', '').strip()
        ambiente = request.form.get('ambiente', 'sandbox')
        webhook_url = request.form.get('webhook_url', '').strip()

        # Certificado (arquivo ou texto)
        certificado_pem = None
        if 'certificado_file' in request.files:
            cert_file = request.files['certificado_file']
            if cert_file and cert_file.filename:
                cert_content = cert_file.read()
                certificado_pem = base64.b64encode(cert_content).decode('utf-8')

        if not certificado_pem:
            certificado_pem = request.form.get('certificado_pem', '').strip()

        try:
            # Verifica se já existe configuração
            cursor.execute("SELECT id FROM efi_config WHERE ativo = TRUE LIMIT 1")
            config_existente = cursor.fetchone()

            if config_existente:
                # Atualiza
                update_query = """
                    UPDATE efi_config SET 
                        client_id = %s,
                        client_secret = %s,
                        chave_pix = %s,
                        ambiente = %s,
                        webhook_url = %s,
                        updated_at = NOW()
                """
                params = [client_id, client_secret, chave_pix, ambiente, webhook_url]

                if certificado_pem:
                    update_query += ", certificado_pem = %s"
                    params.append(certificado_pem)

                update_query += " WHERE id = %s"
                params.append(config_existente['id'])

                cursor.execute(update_query, params)
            else:
                # Insere nova
                cursor.execute("""
                    INSERT INTO efi_config (
                        client_id, client_secret, certificado_pem,
                        chave_pix, ambiente, webhook_url, ativo
                    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                """, (client_id, client_secret, certificado_pem, chave_pix, ambiente, webhook_url))

            conn.commit()
            flash('Configuração salva com sucesso!', 'success')

        except Exception as e:
            conn.rollback()
            flash(f'Erro ao salvar configuração: {e}', 'danger')

    # Carrega configuração atual
    try:
        cursor.execute("SELECT * FROM efi_config WHERE ativo = TRUE ORDER BY id DESC LIMIT 1")
        config = cursor.fetchone()
    except Exception:
        config = None
    finally:
        cursor.close()
        conn.close()

    return render_template('cobrancas/configuracao.html', config=config)


@bp.route('/api/cliente/<int:id>')
@login_required
def api_cliente(id):
    """API para buscar dados de um cliente."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT id, razao_social, nome_fantasia, cnpj, telefone, email,
                   endereco, municipio, uf, cep
            FROM clientes WHERE id = %s
        """, (id,))
        cliente = cursor.fetchone()

        if cliente:
            return jsonify(cliente)
        else:
            return jsonify({'erro': 'Cliente não encontrado'}), 404

    finally:
        cursor.close()
        conn.close()


@bp.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint para receber notificações da API EFI.
    Atualiza status das cobranças automaticamente.
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'status': 'erro', 'mensagem': 'Dados inválidos'}), 400

        # Log do webhook
        current_app = request.environ.get('flask.app') or __import__('flask').current_app
        current_app.logger.info(f"Webhook EFI recebido: {json.dumps(data)}")

        # Processa notificação de PIX
        pix_array = data.get('pix', [])
        for pix in pix_array:
            txid = pix.get('txid')
            if txid:
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        UPDATE cobrancas 
                        SET status = 'pago',
                            data_pagamento = NOW(),
                            valor_pago = %s,
                            updated_at = NOW()
                        WHERE txid = %s AND status != 'pago'
                    """, (float(pix.get('valor', 0)), txid))
                    conn.commit()
                finally:
                    cursor.close()
                    conn.close()

        return jsonify({'status': 'ok'})

    except Exception as e:
        return jsonify({'status': 'erro', 'mensagem': str(e)}), 500
