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

def gerar_numero_troco_pix(data_transacao):
    """
    Gera número sequencial para TROCO PIX no formato: PIX-DD-MM-YYYY-N1
    
    Args:
        data_transacao: data da transação (string YYYY-MM-DD ou datetime)
    
    Returns:
        String no formato PIX-31-01-2026-N1, PIX-31-01-2026-N2, etc.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Converter data para string no formato esperado se necessário
    if isinstance(data_transacao, str):
        data_obj = datetime.strptime(data_transacao, '%Y-%m-%d')
    else:
        data_obj = data_transacao
    
    data_formatada = data_obj.strftime('%d-%m-%Y')
    prefixo = f"PIX-{data_formatada}"
    
    # Buscar último número sequencial do dia
    cursor.execute("""
        SELECT numero_sequencial 
        FROM troco_pix 
        WHERE data = %s 
        ORDER BY numero_sequencial DESC 
        LIMIT 1
    """, (data_obj.strftime('%Y-%m-%d'),))
    
    ultimo = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if ultimo and ultimo.get('numero_sequencial'):
        # Extrair número da sequência (ex: PIX-31-01-2026-N1 -> 1)
        try:
            partes = ultimo['numero_sequencial'].split('-N')
            if len(partes) == 2:
                num = int(partes[1]) + 1
            else:
                num = 1
        except:
            num = 1
    else:
        num = 1
    
    return f"{prefixo}-N{num}"

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
        
        # Buscar lista de clientes para filtro (apenas com produtos cadastrados)
        cursor.execute("""
            SELECT DISTINCT c.id, c.razao_social 
            FROM clientes c
            INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
            WHERE cp.ativo = 1
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
            from datetime import date
            
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Buscar postos (clientes) que têm produtos configurados
            # Mostra APENAS clientes que têm produtos ativos configurados
            cursor.execute("""
                SELECT DISTINCT c.id, c.razao_social 
                FROM clientes c
                INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
                WHERE cp.ativo = 1
                ORDER BY c.razao_social
            """)
            postos = cursor.fetchall()
            
            # Buscar nome do posto para usuários PISTA/SUPERVISOR
            cliente_nome = None
            # Debug logging
            print(f"[DEBUG TROCO PIX] Usuario: {current_user.username}")
            print(f"[DEBUG TROCO PIX] Nivel: {getattr(current_user, 'nivel', 'NAO TEM ATRIBUTO')}")
            print(f"[DEBUG TROCO PIX] cliente_id: {getattr(current_user, 'cliente_id', 'NAO TEM ATRIBUTO')}")
            
            if hasattr(current_user, 'nivel') and current_user.nivel.upper() in ['PISTA', 'SUPERVISOR']:
                print(f"[DEBUG TROCO PIX] Usuario eh PISTA/SUPERVISOR")
                if hasattr(current_user, 'cliente_id') and current_user.cliente_id:
                    print(f"[DEBUG TROCO PIX] Tem cliente_id: {current_user.cliente_id}")
                    cursor.execute("SELECT razao_social FROM clientes WHERE id = %s", (current_user.cliente_id,))
                    result = cursor.fetchone()
                    if result:
                        cliente_nome = result['razao_social']
                        print(f"[DEBUG TROCO PIX] Nome do posto encontrado: {cliente_nome}")
                    else:
                        print(f"[DEBUG TROCO PIX] Posto nao encontrado para cliente_id: {current_user.cliente_id}")
                else:
                    print(f"[DEBUG TROCO PIX] NAO tem cliente_id ou eh None/vazio")
            else:
                print(f"[DEBUG TROCO PIX] Usuario NAO eh PISTA/SUPERVISOR")
            
            # Buscar clientes PIX ativos (com SEM PIX no topo)
            cursor.execute("""
                SELECT id, nome_completo, tipo_chave_pix, chave_pix
                FROM troco_pix_clientes
                WHERE ativo = 1
                ORDER BY 
                    CASE WHEN nome_completo = 'SEM PIX' THEN 0 ELSE 1 END,
                    nome_completo
            """)
            clientes_pix = cursor.fetchall()
            
            # Buscar frentistas ativos (incluindo cliente_id para filtro se a coluna existir)
            try:
                cursor.execute("""
                    SELECT id, nome, clienteid
                    FROM funcionarios
                    WHERE ativo = 1
                    ORDER BY nome
                """)
                frentistas = cursor.fetchall()
            except Exception as col_error:
                # Se a coluna clienteid não existir, buscar sem ela
                if '1054' in str(col_error) or 'Unknown column' in str(col_error):
                    cursor.execute("""
                        SELECT id, nome
                        FROM funcionarios
                        WHERE ativo = 1
                        ORDER BY nome
                    """)
                    frentistas_temp = cursor.fetchall()
                    # Adicionar clienteid=None manualmente para compatibilidade
                    frentistas = []
                    for f in frentistas_temp:
                        f_dict = dict(f)
                        f_dict['clienteid'] = None
                        frentistas.append(f_dict)
                else:
                    raise col_error
            
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
            
            # Data de hoje
            data_hoje = date.today().strftime('%Y-%m-%d')
            
            return render_template('troco_pix/novo.html',
                                 postos=postos,
                                 postos_json=postos_json,
                                 clientes_pix=clientes_pix,
                                 clientes_pix_json=clientes_pix_json,
                                 funcionarios=frentistas,  # Template usa 'funcionarios'
                                 frentistas=frentistas,  # Mantido para compatibilidade
                                 frentistas_json=frentistas_json,
                                 cliente_nome=cliente_nome,
                                 data_hoje=data_hoje,
                                 edit_mode=False,
                                 titulo='Novo TROCO PIX')
        
        except Exception as e:
            flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
            return redirect(url_for('troco_pix.listar'))
    
    # POST - Criar transação
    try:
        from datetime import date
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obter dados do formulário
        cliente_id = request.form.get('cliente_id')
        data_transacao = request.form.get('data')
        
        # Validação de segurança para usuários PISTA/SUPERVISOR
        if hasattr(current_user, 'nivel') and current_user.nivel.upper() in ['PISTA', 'SUPERVISOR']:
            # PISTA só pode criar para seu cliente vinculado
            if hasattr(current_user, 'cliente_id') and current_user.cliente_id:
                cliente_id = current_user.cliente_id
            else:
                flash('Usuário PISTA deve ter um posto vinculado.', 'danger')
                return redirect(url_for('troco_pix.novo', origem=request.args.get('origem')))
            
            # PISTA só pode criar transações para a data de hoje
            data_transacao = date.today().strftime('%Y-%m-%d')
        
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
        if not all([cliente_id, data_transacao, cheque_tipo, cheque_valor, troco_pix_cliente_id, funcionario_id]):
            flash('Por favor, preencha todos os campos obrigatórios.', 'warning')
            return redirect(url_for('troco_pix.novo'))
        
        if cheque_tipo == 'A_PRAZO' and not cheque_data_vencimento:
            flash('Para cheque A PRAZO, a data de vencimento é obrigatória.', 'warning')
            return redirect(url_for('troco_pix.novo'))
        
        # Gerar número sequencial
        numero_sequencial = gerar_numero_troco_pix(data_transacao)
        
        # Inserir transação
        query = """
            INSERT INTO troco_pix (
                numero_sequencial, cliente_id, data, 
                venda_abastecimento, venda_arla, venda_produtos,
                cheque_tipo, cheque_data_vencimento, cheque_valor,
                troco_especie, troco_pix, troco_credito_vda_programada,
                troco_pix_cliente_id, funcionario_id,
                status, criado_por
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s
            )
        """
        
        cursor.execute(query, (
            numero_sequencial, cliente_id, data_transacao,
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
        # Preservar origem no redirect
        origem = request.args.get('origem') or request.form.get('origem')
        return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id, origem=origem))
        
    except Exception as e:
        flash(f'Erro ao cadastrar TROCO PIX: {str(e)}', 'danger')
        origem = request.args.get('origem') or request.form.get('origem')
        return redirect(url_for('troco_pix.novo', origem=origem))

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
            # Verificar se usuário é administrador
            is_admin = (current_user.nivel == 'ADMIN')
            
            if not is_admin:
                tempo_decorrido = datetime.now() - transacao['criado_em']
                if tempo_decorrido > timedelta(minutes=15):
                    flash('Você só pode editar transações até 15 minutos após a criação. Entre em contato com o administrador.', 'warning')
                    return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id))
            
            # Buscar dados para o formulário
            # Mostra APENAS clientes que têm produtos ativos configurados
            cursor.execute("""
                SELECT DISTINCT c.id, c.razao_social 
                FROM clientes c
                INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
                WHERE cp.ativo = 1
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
            
            # Buscar frentistas ativos (incluindo cliente_id para filtro se a coluna existir)
            try:
                cursor.execute("""
                    SELECT id, nome, clienteid
                    FROM funcionarios
                    WHERE ativo = 1
                    ORDER BY nome
                """)
                frentistas = cursor.fetchall()
            except Exception as col_error:
                # Se a coluna clienteid não existir, buscar sem ela
                if '1054' in str(col_error) or 'Unknown column' in str(col_error):
                    cursor.execute("""
                        SELECT id, nome
                        FROM funcionarios
                        WHERE ativo = 1
                        ORDER BY nome
                    """)
                    frentistas_temp = cursor.fetchall()
                    # Adicionar clienteid=None manualmente para compatibilidade
                    frentistas = []
                    for f in frentistas_temp:
                        f_dict = dict(f)
                        f_dict['clienteid'] = None
                        frentistas.append(f_dict)
                else:
                    raise col_error
            
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
                                 funcionarios=frentistas,  # Template usa 'funcionarios'
                                 frentistas=frentistas,  # Mantido para compatibilidade
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
        # Verificar se usuário é administrador
        is_admin = (current_user.nivel == 'ADMIN')
        
        if not is_admin:
            tempo_decorrido = datetime.now() - result['criado_em']
            if tempo_decorrido > timedelta(minutes=15):
                flash('Tempo limite de edição excedido (15 minutos).', 'warning')
                cursor.close()
                conn.close()
                origem = request.args.get('origem') or request.form.get('origem')
                return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id, origem=origem))
        
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
        # Preservar origem no redirect
        origem = request.args.get('origem') or request.form.get('origem')
        if origem == 'pista':
            return redirect(url_for('troco_pix.pista'))
        else:
            return redirect(url_for('troco_pix.visualizar', troco_pix_id=troco_pix_id, origem=origem))
        
    except Exception as e:
        flash(f'Erro ao atualizar TROCO PIX: {str(e)}', 'danger')
        origem = request.args.get('origem') or request.form.get('origem')
        return redirect(url_for('troco_pix.editar', troco_pix_id=troco_pix_id, origem=origem))

# ==================== ROTA DE EXCLUSÃO ====================

@troco_pix_bp.route('/excluir/<int:troco_pix_id>', methods=['POST'])
@login_required
def excluir(troco_pix_id):
    """Exclui transação TROCO PIX (apenas Admin)"""
    try:
        # Verificar se usuário é administrador
        is_admin = (current_user.nivel == 'ADMIN')
        if not is_admin:
            flash('Apenas administradores podem excluir transações.', 'danger')
            return redirect(url_for('troco_pix.listar'))
        
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
        return redirect(url_for('troco_pix.listar'))

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
        return_to = request.args.get('return_to')
        return render_template('troco_pix/cliente_form.html',
                             edit_mode=False,
                             titulo='Novo Cliente PIX',
                             return_to=return_to)
    
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
        
        # Redirecionar para a página de origem se especificada
        return_to = request.form.get('return_to') or request.args.get('return_to')
        if return_to:
            return redirect(return_to)
        
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
            
            return_to = request.args.get('return_to')
            return render_template('troco_pix/cliente_form.html',
                                 cliente=cliente,
                                 edit_mode=True,
                                 titulo='Editar Cliente PIX',
                                 return_to=return_to)
        
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
        
        # Redirecionar para a página de origem se especificada
        return_to = request.form.get('return_to') or request.args.get('return_to')
        if return_to:
            return redirect(return_to)
        
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
        from datetime import date
        
        # Buscar cliente_id do usuário logado
        user_id = current_user.id
        
        # Pegar filtros de data da URL (se existirem)
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        
        # Se não tem filtro, usar data de hoje por padrão
        if not data_inicio and not data_fim:
            data_hoje = date.today()
            data_inicio = data_hoje.strftime('%Y-%m-%d')
            data_fim = data_hoje.strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Construir query base
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
            WHERE 1=1
        """
        
        params = []
        
        # Filtrar por posto se usuário é PISTA
        if hasattr(current_user, 'nivel') and current_user.nivel == 'PISTA':
            if hasattr(current_user, 'cliente_id') and current_user.cliente_id:
                query += " AND tp.cliente_id = %s"
                params.append(current_user.cliente_id)
            else:
                # Usuário PISTA sem cliente_id associado - não mostrar nada
                query += " AND 1=0"
        
        # Filtrar por data
        if data_inicio:
            query += " AND tp.data >= %s"
            params.append(data_inicio)
        if data_fim:
            query += " AND tp.data <= %s"
            params.append(data_fim)
        
        query += " ORDER BY tp.data DESC, tp.criado_em DESC"
        
        cursor.execute(query, params)
        transacoes = cursor.fetchall()
        
        # Calcular transações de hoje e total
        data_hoje = date.today()
        transacoes_hoje = [t for t in transacoes if t.get('data') == data_hoje]
        total_troco_pix_hoje = sum(t.get('troco_pix', 0) or 0 for t in transacoes_hoje)
        
        cursor.close()
        conn.close()
        
        return render_template('troco_pix/pista.html', 
                             transacoes=transacoes,
                             transacoes_hoje=transacoes_hoje,
                             total_troco_pix_hoje=total_troco_pix_hoje,
                             titulo='TROCO PIX - Pista')
        
    except Exception as e:
        flash(f'Erro ao carregar transações: {str(e)}', 'danger')
        # Redireciona para index para evitar loop infinito em caso de erro persistente
        try:
            return redirect(url_for('fretes.lista'))
        except Exception:
            return redirect(url_for('index'))


# ==================== CONTEXT PROCESSOR ====================

@troco_pix_bp.app_context_processor
def utility_processor():
    """
    Adiciona funções utilitárias aos templates do blueprint TROCO PIX
    
    Funções disponíveis nos templates:
    - pode_editar(transacao): Verifica se usuário pode editar uma transação
    """
    
    def pode_editar(transacao):
        """
        Verifica se o usuário atual pode editar a transação
        
        Regras de negócio:
        - Administradores (nivel='ADMIN') podem sempre editar
        - Frentistas (nivel='PISTA') podem editar apenas:
          * Transações do mesmo posto (cliente_id)
          * Até 15 minutos após a criação
        
        Args:
            transacao (dict): Dicionário com dados da transação incluindo:
                - cliente_id: ID do posto/cliente
                - criado_em: Timestamp de criação
        
        Returns:
            bool: True se pode editar, False caso contrário
        """
        try:
            # Administradores podem sempre editar
            if hasattr(current_user, 'nivel') and current_user.nivel == 'ADMIN':
                return True
            
            # Para frentistas (PISTA), verificar posto e tempo
            if hasattr(current_user, 'nivel') and current_user.nivel == 'PISTA':
                # Verificar se é do mesmo posto
                if hasattr(current_user, 'cliente_id') and current_user.cliente_id:
                    if current_user.cliente_id != transacao.get('cliente_id'):
                        return False
                
                # Verificar tempo (15 minutos)
                if transacao.get('criado_em'):
                    tempo_decorrido = datetime.now() - transacao['criado_em']
                    return tempo_decorrido <= timedelta(minutes=15)
                
                # Se não tem criado_em, não pode editar por segurança
                return False
            
            # Por padrão, não permitir edição
            return False
            
        except Exception as e:
            # Em caso de erro, não permitir edição por segurança
            print(f"Erro ao verificar permissão de edição: {e}")
            return False
    
    return dict(pode_editar=pode_editar)
