# -*- coding: utf-8 -*-
"""
Rotas para o sistema TROCO PIX
Gerencia transações de troco via PIX para frentistas
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from functools import wraps
from decimal import Decimal
from datetime import datetime, timedelta
import json

# Importar função de conexão do banco de dados
from utils.db import get_db_connection
from utils.formatadores import formatar_moeda

# Criar blueprint
troco_pix_bp = Blueprint('troco_pix', __name__, url_prefix='/troco_pix')

# Helper function para converter dados do MySQL para Python
def convert_to_plain_python(obj):
    """Converte tipos especiais do MySQL para tipos Python básicos"""
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(obj, Decimal):
        return float(obj)
    elif obj is None or str(obj) in ['None', '', 'null']:
        return ''
    elif isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except:
            return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_to_plain_python(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_to_plain_python(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    else:
        try:
            return str(obj) if obj else ''
        except:
            return ''

# ==================== ROTAS DE LISTAGEM ====================

@troco_pix_bp.route('/')
@login_required
def listar():
    """Lista todas as transações TROCO PIX (visão Admin)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Buscar transações com joins para obter nomes
        query = """
            SELECT 
                tp.*,
                c.razao_social as posto_nome,
                tpc.nome_completo as cliente_pix_nome,
                tpc.tipo_chave_pix,
                tpc.chave_pix,
                f.nome as frentista_nome
            FROM troco_pix tp
            LEFT JOIN clientes c ON tp.cliente_id = c.id
            LEFT JOIN troco_pix_clientes tpc ON tp.troco_pix_cliente_id = tpc.id
            LEFT JOIN funcionarios f ON tp.funcionario_id = f.id
            ORDER BY tp.data DESC, tp.criado_em DESC
        """
        
        cursor.execute(query)
        transacoes = cursor.fetchall()
        
        # Buscar lista de clientes para filtro
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social 
            FROM clientes c
            ORDER BY c.razao_social
        """)
        clientes = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Calcular resumo por status
        resumo = {
            'pendentes': 0,
            'processados': 0,
            'cancelados': 0
        }
        total_dia = 0
        data_hoje = datetime.now().date()
        
        for t in transacoes:
            status = t.get('status', '').upper()
            if status == 'PENDENTE':
                resumo['pendentes'] += 1
            elif status == 'PROCESSADO':
                resumo['processados'] += 1
            elif status == 'CANCELADO':
                resumo['cancelados'] += 1
            
            # Calcular total do dia (apenas transações não canceladas)
            data_transacao = t.get('data')
            if data_transacao and status != 'CANCELADO':
                # Converter datetime para date se necessário
                if isinstance(data_transacao, datetime):
                    data_transacao = data_transacao.date()
                
                if data_transacao == data_hoje:
                    total_dia += float(t.get('troco_pix', 0) or 0)
        
        # Formatar total do dia para exibição
        total_dia_formatado = formatar_moeda(total_dia)
        
        return render_template('troco_pix/listar.html', 
                             transacoes=transacoes,
                             clientes=clientes,
                             resumo=resumo,
                             total_dia=total_dia_formatado,
                             titulo='TROCO PIX - Administração')
        
    except Exception as e:
        flash(f'Erro ao carregar transações: {str(e)}', 'danger')
        # Redireciona para index para evitar loop infinito em caso de erro persistente
        try:
            return redirect(url_for('fretes.lista'))
        except Exception:
            return redirect(url_for('index'))

@troco_pix_bp.route('/visualizar/<int:troco_pix_id>')
@login_required
def visualizar(troco_pix_id):
    """Visualiza detalhes de uma transação TROCO PIX"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Buscar transação completa
        query = """
            SELECT 
                tp.*,
                c.razao_social as posto_nome,
                tpc.nome_completo as cliente_pix_nome,
                tpc.tipo_chave_pix,
                tpc.chave_pix,
                f.nome as frentista_nome,
                u1.username as criado_por_nome,
                u2.username as atualizado_por_nome
            FROM troco_pix tp
            LEFT JOIN clientes c ON tp.cliente_id = c.id
            LEFT JOIN troco_pix_clientes tpc ON tp.troco_pix_cliente_id = tpc.id
            LEFT JOIN funcionarios f ON tp.funcionario_id = f.id
            LEFT JOIN usuarios u1 ON tp.criado_por = u1.id
            LEFT JOIN usuarios u2 ON tp.atualizado_por = u2.id
            WHERE tp.id = %s
        """
        
        cursor.execute(query, (troco_pix_id,))
        transacao = cursor.fetchone()
        
        if not transacao:
            flash('Transação não encontrada.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('troco_pix.listar'))
        
        cursor.close()
        conn.close()
        
        return render_template('troco_pix/visualizar.html', 
                             transacao=transacao,
                             titulo='Visualizar TROCO PIX')
        
    except Exception as e:
        flash(f'Erro ao visualizar transação: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.listar'))

# ==================== ROTAS DE CRIAÇÃO ====================

@troco_pix_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    """Cria nova transação TROCO PIX"""
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Buscar postos (clientes) que têm produtos configurados
            # Se não houver cliente_produtos configurado, mostra todos os clientes ativos
            cursor.execute("""
                SELECT DISTINCT c.id, c.razao_social 
                FROM clientes c
                LEFT JOIN cliente_produtos cp ON c.id = cp.cliente_id
                WHERE (cp.ativo = 1 OR cp.id IS NULL)
                ORDER BY c.razao_social
            """)
            postos = cursor.fetchall()
            
            # Buscar clientes PIX ativos
            cursor.execute("""
                SELECT id, nome_completo, tipo_chave_pix, chave_pix
                FROM troco_pix_clientes
                WHERE ativo = 1
                ORDER BY nome_completo
            """)
            clientes_pix = cursor.fetchall()
            
            # Buscar frentistas ativos
            cursor.execute("""
                SELECT id, nome
                FROM funcionarios
                WHERE ativo = 1
                ORDER BY nome
            """)
            frentistas = cursor.fetchall()
            
            # Limpar dados antes de serializar
            postos_clean = convert_to_plain_python(list(postos))
            clientes_pix_clean = convert_to_plain_python(list(clientes_pix))
            frentistas_clean = convert_to_plain_python(list(frentistas))
            
            # Serializar para JSON
            postos_json = json.dumps(postos_clean)
            clientes_pix_json = json.dumps(clientes_pix_clean)
            frentistas_json = json.dumps(frentistas_clean)
            
            cursor.close()
            conn.close()
            
            return render_template('troco_pix/novo.html',
                                 postos=postos,
                                 postos_json=postos_json,
                                 clientes_pix=clientes_pix,
                                 clientes_pix_json=clientes_pix_json,
                                 frentistas=frentistas,
                                 frentistas_json=frentistas_json,
                                 edit_mode=False,
                                 titulo='Novo TROCO PIX')
        
        except Exception as e:
            flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
            return redirect(url_for('troco_pix.listar'))
    
    # POST - Criar transação
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obter dados do formulário
        cliente_id = request.form.get('cliente_id')
        data = request.form.get('data')
        venda_abastecimento = request.form.get('venda_abastecimento', 0)
        venda_arla = request.form.get('venda_arla', 0)
        venda_produtos = request.form.get('venda_produtos', 0)
        cheque_tipo = request.form.get('cheque_tipo')
        cheque_data_vencimento = request.form.get('cheque_data_vencimento') or None
        cheque_valor = request.form.get('cheque_valor')
        troco_especie = request.form.get('troco_especie', 0)
        troco_pix = request.form.get('troco_pix', 0)
        troco_credito = request.form.get('troco_credito_vda_programada', 0)
        troco_pix_cliente_id = request.form.get('troco_pix_cliente_id')
        funcionario_id = request.form.get('funcionario_id')
        user_id = current_user.id
        
        # Validações
        if not all([cliente_id, data, cheque_tipo, cheque_valor, troco_pix_cliente_id, funcionario_id]):
            flash('Por favor, preencha todos os campos obrigatórios.', 'warning')
            return redirect(url_for('troco_pix.novo'))
        
        if cheque_tipo == 'A_PRAZO' and not cheque_data_vencimento:
            flash('Para cheque A PRAZO, a data de vencimento é obrigatória.', 'warning')
            return redirect(url_for('troco_pix.novo'))
        
        # Inserir transação
        query = """
            INSERT INTO troco_pix (
                cliente_id, data, 
                venda_abastecimento, venda_arla, venda_produtos,
                cheque_tipo, cheque_data_vencimento, cheque_valor,
                troco_especie, troco_pix, troco_credito_vda_programada,
                troco_pix_cliente_id, funcionario_id,
                status, criado_por
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s
            )
        """
        
        cursor.execute(query, (
            cliente_id, data,
            venda_abastecimento, venda_arla, venda_produtos,
            cheque_tipo, cheque_data_vencimento, cheque_valor,
            troco_especie, troco_pix, troco_credito,
            troco_pix_cliente_id, funcionario_id, user_id
        ))
        
        conn.commit()
        troco_pix_id = cursor.lastrowid
        
        cursor.close()
        conn.close()
        
        flash('TROCO PIX cadastrado com sucesso!', 'success')
        return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
        
    except Exception as e:
        flash(f'Erro ao cadastrar TROCO PIX: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.novo'))

# ==================== ROTAS DE EDIÇÃO ====================

@troco_pix_bp.route('/editar/<int:troco_pix_id>', methods=['GET', 'POST'])
@login_required
def editar(troco_pix_id):
    """Edita transação TROCO PIX (com validação de 15 minutos para frentistas)"""
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Buscar transação
            cursor.execute("SELECT * FROM troco_pix WHERE id = %s", (troco_pix_id,))
            transacao = cursor.fetchone()
            
            if not transacao:
                flash('Transação não encontrada.', 'warning')
                cursor.close()
                conn.close()
                return redirect(url_for('troco_pix.listar'))
            
            # Verificar permissão de edição (15 minutos para frentistas)
            user_id = current_user.id
            # TODO: Implementar verificação de admin baseado em current_user.nivel
            # Por exemplo: is_admin = (current_user.nivel == 'ADMIN')
            is_admin = session.get('is_admin', False)
            
            if not is_admin:
                tempo_decorrido = datetime.now() - transacao['criado_em']
                if tempo_decorrido > timedelta(minutes=15):
                    flash('Você só pode editar transações até 15 minutos após a criação. Entre em contato com o administrador.', 'warning')
                    return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
            
            # Buscar dados para o formulário
            # Se não houver cliente_produtos configurado, mostra todos os clientes
            cursor.execute("""
                SELECT DISTINCT c.id, c.razao_social 
                FROM clientes c
                LEFT JOIN cliente_produtos cp ON c.id = cp.cliente_id
                WHERE (cp.ativo = 1 OR cp.id IS NULL)
                ORDER BY c.razao_social
            """)
            postos = cursor.fetchall()
            
            cursor.execute("""
                SELECT id, nome_completo, tipo_chave_pix, chave_pix
                FROM troco_pix_clientes
                WHERE ativo = 1
                ORDER BY nome_completo
            """)
            clientes_pix = cursor.fetchall()
            
            cursor.execute("""
                SELECT id, nome
                FROM funcionarios
                WHERE ativo = 1
                ORDER BY nome
            """)
            frentistas = cursor.fetchall()
            
            # Limpar e serializar dados
            transacao_clean = convert_to_plain_python(transacao)
            postos_clean = convert_to_plain_python(list(postos))
            clientes_pix_clean = convert_to_plain_python(list(clientes_pix))
            frentistas_clean = convert_to_plain_python(list(frentistas))
            
            transacao_json = json.dumps(transacao_clean)
            postos_json = json.dumps(postos_clean)
            clientes_pix_json = json.dumps(clientes_pix_clean)
            frentistas_json = json.dumps(frentistas_clean)
            
            cursor.close()
            conn.close()
            
            return render_template('troco_pix/novo.html',
                                 transacao=transacao,
                                 transacao_json=transacao_json,
                                 postos=postos,
                                 postos_json=postos_json,
                                 clientes_pix=clientes_pix,
                                 clientes_pix_json=clientes_pix_json,
                                 frentistas=frentistas,
                                 frentistas_json=frentistas_json,
                                 edit_mode=True,
                                 troco_pix_id=troco_pix_id,
                                 titulo='Editar TROCO PIX')
        
        except Exception as e:
            flash(f'Erro ao carregar transação: {str(e)}', 'danger')
            return redirect(url_for('troco_pix.listar'))
    
    # POST - Atualizar transação
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verificar permissão novamente
        cursor.execute("SELECT criado_em FROM troco_pix WHERE id = %s", (troco_pix_id,))
        result = cursor.fetchone()
        
        if not result:
            flash('Transação não encontrada.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('troco_pix.listar'))
        
        user_id = current_user.id
        # TODO: Implementar verificação de admin baseado em current_user.nivel
        # Por exemplo: is_admin = (current_user.nivel == 'ADMIN')
        is_admin = session.get('is_admin', False)
        
        if not is_admin:
            tempo_decorrido = datetime.now() - result['criado_em']
            if tempo_decorrido > timedelta(minutes=15):
                flash('Tempo limite de edição excedido (15 minutos).', 'warning')
                cursor.close()
                conn.close()
                return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
        
        # Obter dados do formulário
        cliente_id = request.form.get('cliente_id')
        data = request.form.get('data')
        venda_abastecimento = request.form.get('venda_abastecimento', 0)
        venda_arla = request.form.get('venda_arla', 0)
        venda_produtos = request.form.get('venda_produtos', 0)
        cheque_tipo = request.form.get('cheque_tipo')
        cheque_data_vencimento = request.form.get('cheque_data_vencimento') or None
        cheque_valor = request.form.get('cheque_valor')
        troco_especie = request.form.get('troco_especie', 0)
        troco_pix = request.form.get('troco_pix', 0)
        troco_credito = request.form.get('troco_credito_vda_programada', 0)
        troco_pix_cliente_id = request.form.get('troco_pix_cliente_id')
        funcionario_id = request.form.get('funcionario_id')
        
        # Atualizar transação
        query = """
            UPDATE troco_pix SET
                cliente_id = %s, data = %s,
                venda_abastecimento = %s, venda_arla = %s, venda_produtos = %s,
                cheque_tipo = %s, cheque_data_vencimento = %s, cheque_valor = %s,
                troco_especie = %s, troco_pix = %s, troco_credito_vda_programada = %s,
                troco_pix_cliente_id = %s, funcionario_id = %s,
                atualizado_por = %s
            WHERE id = %s
        """
        
        cursor.execute(query, (
            cliente_id, data,
            venda_abastecimento, venda_arla, venda_produtos,
            cheque_tipo, cheque_data_vencimento, cheque_valor,
            troco_especie, troco_pix, troco_credito,
            troco_pix_cliente_id, funcionario_id, user_id,
            troco_pix_id
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('TROCO PIX atualizado com sucesso!', 'success')
        return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
        
    except Exception as e:
        flash(f'Erro ao atualizar TROCO PIX: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.editar', troco_pix_id=troco_pix_id))

# ==================== ROTA DE EXCLUSÃO ====================

@troco_pix_bp.route('/excluir/<int:troco_pix_id>', methods=['POST'])
@login_required
def excluir(troco_pix_id):
    """Exclui transação TROCO PIX (apenas Admin)"""
    try:
        # TODO: Implementar verificação de admin baseado em current_user.nivel
        # Por exemplo: is_admin = (current_user.nivel == 'ADMIN')
        is_admin = session.get('is_admin', False)
        if not is_admin:
            flash('Apenas administradores podem excluir transações.', 'danger')
            return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificar se transação foi importada para caixa
        cursor.execute("""
            SELECT importado_lancamento_caixa, lancamento_caixa_id 
            FROM troco_pix 
            WHERE id = %s
        """, (troco_pix_id,))
        
        result = cursor.fetchone()
        if result and result[0]:  # importado_lancamento_caixa = True
            flash('Esta transação foi importada para o fechamento de caixa e não pode ser excluída. Cancele primeiro no fechamento de caixa.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
        
        # Excluir transação
        cursor.execute("DELETE FROM troco_pix WHERE id = %s", (troco_pix_id,))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        flash('TROCO PIX excluído com sucesso!', 'success')
        return redirect(url_for('troco_pix.listar'))
        
    except Exception as e:
        flash(f'Erro ao excluir TROCO PIX: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))

# ==================== ROTAS DE GESTÃO DE CLIENTES PIX ====================

@troco_pix_bp.route('/clientes')
@login_required
def clientes():
    """Lista clientes PIX"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT *
            FROM troco_pix_clientes
            ORDER BY ativo DESC, nome_completo
        """)
        clientes = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('troco_pix/clientes.html', 
                             clientes=clientes,
                             titulo='Clientes PIX')
        
    except Exception as e:
        flash(f'Erro ao carregar clientes: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.listar'))

@troco_pix_bp.route('/clientes/novo', methods=['GET', 'POST'])
@login_required
def cliente_novo():
    """Cria novo cliente PIX"""
    if request.method == 'GET':
        return render_template('troco_pix/cliente_form.html',
                             edit_mode=False,
                             titulo='Novo Cliente PIX')
    
    # POST - Criar cliente
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        nome_completo = request.form.get('nome_completo')
        tipo_chave_pix = request.form.get('tipo_chave_pix')
        chave_pix = request.form.get('chave_pix')
        ativo = request.form.get('ativo', '1')
        
        if not all([nome_completo, tipo_chave_pix, chave_pix]):
            flash('Por favor, preencha todos os campos obrigatórios.', 'warning')
            return redirect(url_for('troco_pix.cliente_novo'))
        
        cursor.execute("""
            INSERT INTO troco_pix_clientes (nome_completo, tipo_chave_pix, chave_pix, ativo)
            VALUES (%s, %s, %s, %s)
        """, (nome_completo, tipo_chave_pix, chave_pix, ativo))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Cliente PIX cadastrado com sucesso!', 'success')
        return redirect(url_for('troco_pix.clientes'))
        
    except Exception as e:
        flash(f'Erro ao cadastrar cliente: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.cliente_novo'))

@troco_pix_bp.route('/clientes/editar/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
def cliente_editar(cliente_id):
    """Edita cliente PIX"""
    if request.method == 'GET':
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT * FROM troco_pix_clientes WHERE id = %s", (cliente_id,))
            cliente = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if not cliente:
                flash('Cliente não encontrado.', 'warning')
                return redirect(url_for('troco_pix.clientes'))
            
            return render_template('troco_pix/cliente_form.html',
                                 cliente=cliente,
                                 edit_mode=True,
                                 titulo='Editar Cliente PIX')
        
        except Exception as e:
            flash(f'Erro ao carregar cliente: {str(e)}', 'danger')
            return redirect(url_for('troco_pix.clientes'))
    
    # POST - Atualizar cliente
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        nome_completo = request.form.get('nome_completo')
        tipo_chave_pix = request.form.get('tipo_chave_pix')
        chave_pix = request.form.get('chave_pix')
        ativo = request.form.get('ativo', '1')
        
        cursor.execute("""
            UPDATE troco_pix_clientes 
            SET nome_completo = %s, tipo_chave_pix = %s, chave_pix = %s, ativo = %s
            WHERE id = %s
        """, (nome_completo, tipo_chave_pix, chave_pix, ativo, cliente_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Cliente PIX atualizado com sucesso!', 'success')
        return redirect(url_for('troco_pix.clientes'))
        
    except Exception as e:
        flash(f'Erro ao atualizar cliente: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.cliente_editar', cliente_id=cliente_id))

@troco_pix_bp.route('/clientes/excluir/<int:cliente_id>', methods=['POST'])
@login_required
def cliente_excluir(cliente_id):
    """Exclui (desativa) cliente PIX"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Apenas desativa ao invés de excluir (soft delete)
        cursor.execute("UPDATE troco_pix_clientes SET ativo = 0 WHERE id = %s", (cliente_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Cliente PIX desativado com sucesso!', 'success')
        return redirect(url_for('troco_pix.clientes'))
        
    except Exception as e:
        flash(f'Erro ao desativar cliente: {str(e)}', 'danger')
        return redirect(url_for('troco_pix.clientes'))

# ==================== ROTAS PARA FRENTISTAS (PISTA) ====================

@troco_pix_bp.route('/pista')
@login_required
def pista():
    """Visão de frentistas - Mostra apenas transações do posto associado ao usuário"""
    try:
        # Buscar cliente_id do usuário logado
        # (Assumindo que existe uma tabela/campo que associa usuário a cliente)
        user_id = current_user.id
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # TODO: Implementar lógica de associação usuário-cliente
        # Por enquanto, mostrar todas as transações
        query = """
            SELECT 
                tp.*,
                c.razao_social as posto_nome,
                tpc.nome_completo as cliente_pix_nome,
                f.nome as frentista_nome
            FROM troco_pix tp
            LEFT JOIN clientes c ON tp.cliente_id = c.id
            LEFT JOIN troco_pix_clientes tpc ON tp.troco_pix_cliente_id = tpc.id
            LEFT JOIN funcionarios f ON tp.funcionario_id = f.id
            ORDER BY tp.data DESC, tp.criado_em DESC
        """
        
        cursor.execute(query)
        transacoes = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('troco_pix/pista.html', 
                             transacoes=transacoes,
                             titulo='TROCO PIX - Pista')
        
    except Exception as e:
        flash(f'Erro ao carregar transações: {str(e)}', 'danger')
        # Redireciona para index para evitar loop infinito em caso de erro persistente
        try:
            return redirect(url_for('fretes.lista'))
        except Exception:
            return redirect(url_for('index'))
