# ===========================================
# MÓDULO DESCARGAS - Controle de Descargas
# ===========================================

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.helpers import parse_moeda
from datetime import datetime, date
from decimal import Decimal

# Criar blueprint de descargas
bp = Blueprint('descargas', __name__, url_prefix='/descargas')


# ============================================
# LISTAR DESCARGAS
# ============================================

@bp.route('/', methods=['GET'])
@login_required
def lista():
    """Lista todas as descargas"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Filtros
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    cliente_id = request.args.get('cliente_id', '')
    status = request.args.get('status', '')
    
    # Se não houver filtro de data, aplicar filtro do mês atual por padrão
    if not data_inicio and not data_fim:
        hoje = date.today()
        primeiro_dia_mes = date(hoje.year, hoje.month, 1)
        data_inicio = primeiro_dia_mes.strftime('%Y-%m-%d')
        data_fim = hoje.strftime('%Y-%m-%d')
    
    try:
        filters = []
        params = []
        
        if data_inicio:
            try:
                di = datetime.strptime(data_inicio, '%d/%m/%Y').strftime('%Y-%m-%d')
            except ValueError:
                di = data_inicio
            filters.append("d.data_descarga >= %s")
            params.append(di)
        
        if data_fim:
            try:
                df = datetime.strptime(data_fim, '%d/%m/%Y').strftime('%Y-%m-%d')
            except ValueError:
                df = data_fim
            filters.append("d.data_descarga <= %s")
            params.append(df)
        
        if cliente_id:
            filters.append("f.clientes_id = %s")
            params.append(cliente_id)
        
        if status:
            filters.append("d.status = %s")
            params.append(status)
        
        where_clause = ""
        if filters:
            where_clause = "WHERE " + " AND ".join(filters)
        
        query = f"""
            SELECT
                d.id,
                d.frete_id,
                d.data_carregamento,
                d.data_descarga,
                DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_formatada,
                d.volume_total,
                d.volume_descarregado,
                d.diferenca_sistema,
                d.diferenca_regua,
                d.status,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista
            FROM descargas d
            INNER JOIN fretes f ON d.frete_id = f.id
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            {where_clause}
            ORDER BY d.data_descarga DESC, d.id DESC
        """
        
        cursor.execute(query, tuple(params))
        descargas = cursor.fetchall()
        
        # Buscar clientes para filtro
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        
        return render_template('descargas/lista.html',
                             descargas=descargas,
                             clientes=clientes,
                             data_inicio=data_inicio,
                             data_fim=data_fim,
                             cliente_id=cliente_id,
                             status_filtro=status)
    
    except Exception as e:
        flash(f'Erro ao listar descargas: {e}', 'danger')
        return render_template('descargas/lista.html', 
                             descargas=[],
                             clientes=[])
    finally:
        cursor.close()
        conn.close()


# ============================================
# SELECIONAR FRETE PARA DESCARGA
# ============================================

@bp.route('/selecionar-frete', methods=['GET'])
@login_required
def selecionar_frete():
    """Mostra modal para selecionar frete para criar descarga"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Buscar fretes que ainda não têm descarga associada
        # e são de clientes configurados para receber informação de descarga
        query = """
            SELECT
                f.id,
                f.data_frete,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_formatada,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(v.caminhao, '') AS veiculo,
                COALESCE(f.quantidade_manual, 0) AS quantidade
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            WHERE f.id NOT IN (SELECT frete_id FROM descargas)
            AND f.status != 'cancelado'
            ORDER BY f.data_frete DESC
            LIMIT 100
        """
        
        cursor.execute(query)
        fretes_disponiveis = cursor.fetchall()
        
        return render_template('descargas/selecionar-frete.html',
                             fretes=fretes_disponiveis)
    
    except Exception as e:
        flash(f'Erro ao buscar fretes: {e}', 'danger')
        return redirect(url_for('descargas.lista'))
    finally:
        cursor.close()
        conn.close()


# ============================================
# NOVA DESCARGA
# ============================================

@bp.route('/nova/<int:frete_id>', methods=['GET', 'POST'])
@login_required
def nova(frete_id):
    """Cria nova descarga a partir de um frete"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'GET':
        try:
            # Buscar dados do frete
            cursor.execute("""
                SELECT
                    f.id,
                    f.data_frete,
                    DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_formatada,
                    f.clientes_id,
                    f.fornecedores_id,
                    f.motoristas_id,
                    f.veiculos_id,
                    f.produto_id,
                    COALESCE(f.quantidade_manual, 0) AS quantidade,
                    COALESCE(c.razao_social, '') AS cliente,
                    COALESCE(fo.razao_social, '') AS fornecedor,
                    COALESCE(p.nome, '') AS produto,
                    COALESCE(m.nome, '') AS motorista,
                    COALESCE(v.caminhao, '') AS veiculo
                FROM fretes f
                LEFT JOIN clientes c ON f.clientes_id = c.id
                LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
                LEFT JOIN produto p ON f.produto_id = p.id
                LEFT JOIN motoristas m ON f.motoristas_id = m.id
                LEFT JOIN veiculos v ON f.veiculos_id = v.id
                WHERE f.id = %s
            """, (frete_id,))
            
            frete = cursor.fetchone()
            
            if not frete:
                flash('Frete não encontrado!', 'danger')
                return redirect(url_for('descargas.lista'))
            
            # Verificar se já existe descarga para este frete
            cursor.execute("SELECT id FROM descargas WHERE frete_id = %s", (frete_id,))
            if cursor.fetchone():
                flash('Já existe uma descarga para este frete!', 'warning')
                return redirect(url_for('descargas.lista'))
            
            return render_template('descargas/nova.html', frete=frete)
        
        except Exception as e:
            flash(f'Erro ao carregar frete: {e}', 'danger')
            return redirect(url_for('descargas.lista'))
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass
    
    else:  # POST
        try:
            # Coletar dados do formulário
            data_carregamento = request.form.get('data_carregamento')
            data_descarga = request.form.get('data_descarga')
            volume_total = parse_moeda(request.form.get('volume_total', '0'))
            
            estoque_sistema_antes = parse_moeda(request.form.get('estoque_sistema_antes', ''))
            estoque_regua_antes = parse_moeda(request.form.get('estoque_regua_antes', ''))
            estoque_sistema_depois = parse_moeda(request.form.get('estoque_sistema_depois', ''))
            estoque_regua_depois = parse_moeda(request.form.get('estoque_regua_depois', ''))
            
            abastecimento_durante = parse_moeda(request.form.get('abastecimento_durante_descarga', '0'))
            temperatura = parse_moeda(request.form.get('temperatura', ''))
            densidade = parse_moeda(request.form.get('densidade', ''))
            
            volume_descarregado = parse_moeda(request.form.get('volume_descarregado', '0'))
            observacoes = request.form.get('observacoes', '')
            
            # Calcular diferenças
            diferenca_sistema = None
            diferenca_regua = None
            
            if estoque_sistema_antes and estoque_sistema_depois and volume_descarregado:
                diferenca_sistema = (
                    estoque_sistema_depois - 
                    estoque_sistema_antes - 
                    volume_descarregado + 
                    (abastecimento_durante or 0)
                )
            
            if estoque_regua_antes and estoque_regua_depois and volume_descarregado:
                diferenca_regua = (
                    estoque_regua_depois - 
                    estoque_regua_antes - 
                    volume_descarregado + 
                    (abastecimento_durante or 0)
                )
            
            # Determinar status
            status = 'pendente'
            if volume_descarregado >= volume_total:
                status = 'completo'
            elif volume_descarregado > 0:
                status = 'em_andamento'
            
            # Inserir descarga
            cursor.execute("""
                INSERT INTO descargas (
                    frete_id, data_carregamento, data_descarga, volume_total,
                    estoque_sistema_antes, estoque_regua_antes,
                    estoque_sistema_depois, estoque_regua_depois,
                    abastecimento_durante_descarga, temperatura, densidade,
                    diferenca_sistema, diferenca_regua,
                    status, volume_descarregado, observacoes
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s
                )
            """, (
                frete_id, data_carregamento, data_descarga, volume_total,
                estoque_sistema_antes, estoque_regua_antes,
                estoque_sistema_depois, estoque_regua_depois,
                abastecimento_durante, temperatura, densidade,
                diferenca_sistema, diferenca_regua,
                status, volume_descarregado, observacoes
            ))
            
            descarga_id = cursor.lastrowid
            conn.commit()
            
            flash('Descarga criada com sucesso!', 'success')
            return redirect(url_for('descargas.editar', descarga_id=descarga_id))
        
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f'Erro ao criar descarga: {e}', 'danger')
            return redirect(url_for('descargas.lista'))
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass


# ============================================
# EDITAR DESCARGA
# ============================================

@bp.route('/editar/<int:descarga_id>', methods=['GET', 'POST'])
@login_required
def editar(descarga_id):
    """Edita uma descarga existente e gerencia etapas"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'GET':
        try:
            # Buscar dados da descarga
            cursor.execute("""
                SELECT
                    d.*,
                    DATE_FORMAT(d.data_carregamento, '%Y-%m-%d') AS data_carregamento_input,
                    DATE_FORMAT(d.data_descarga, '%Y-%m-%d') AS data_descarga_input,
                    DATE_FORMAT(d.data_carregamento, '%d/%m/%Y') AS data_carregamento_formatada,
                    DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_formatada,
                    f.data_frete,
                    COALESCE(c.razao_social, '') AS cliente,
                    COALESCE(fo.razao_social, '') AS fornecedor,
                    COALESCE(p.nome, '') AS produto,
                    COALESCE(m.nome, '') AS motorista,
                    COALESCE(v.caminhao, '') AS veiculo
                FROM descargas d
                INNER JOIN fretes f ON d.frete_id = f.id
                LEFT JOIN clientes c ON f.clientes_id = c.id
                LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
                LEFT JOIN produto p ON f.produto_id = p.id
                LEFT JOIN motoristas m ON f.motoristas_id = m.id
                LEFT JOIN veiculos v ON f.veiculos_id = v.id
                WHERE d.id = %s
            """, (descarga_id,))
            
            descarga = cursor.fetchone()
            
            if not descarga:
                flash('Descarga não encontrada!', 'danger')
                return redirect(url_for('descargas.lista'))
            
            # Buscar etapas
            cursor.execute("""
                SELECT
                    *,
                    DATE_FORMAT(data_etapa, '%d/%m/%Y') AS data_etapa_formatada
                FROM descarga_etapas
                WHERE descarga_id = %s
                ORDER BY data_etapa, id
            """, (descarga_id,))
            
            etapas = cursor.fetchall()
            
            return render_template('descargas/editar.html',
                                 descarga=descarga,
                                 etapas=etapas)
        
        except Exception as e:
            flash(f'Erro ao carregar descarga: {e}', 'danger')
            return redirect(url_for('descargas.lista'))
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass
    
    else:  # POST
        try:
            # Atualizar dados da descarga
            data_carregamento = request.form.get('data_carregamento')
            data_descarga = request.form.get('data_descarga')
            
            estoque_sistema_antes = parse_moeda(request.form.get('estoque_sistema_antes', ''))
            estoque_regua_antes = parse_moeda(request.form.get('estoque_regua_antes', ''))
            estoque_sistema_depois = parse_moeda(request.form.get('estoque_sistema_depois', ''))
            estoque_regua_depois = parse_moeda(request.form.get('estoque_regua_depois', ''))
            
            abastecimento_durante = parse_moeda(request.form.get('abastecimento_durante_descarga', '0'))
            temperatura = parse_moeda(request.form.get('temperatura', ''))
            densidade = parse_moeda(request.form.get('densidade', ''))
            
            observacoes = request.form.get('observacoes', '')
            
            # Buscar volume total e volume descarregado atual
            cursor.execute("""
                SELECT volume_total, volume_descarregado 
                FROM descargas 
                WHERE id = %s
            """, (descarga_id,))
            
            descarga_data = cursor.fetchone()
            if not descarga_data:
                flash('Descarga não encontrada!', 'danger')
                return redirect(url_for('descargas.lista'))
            
            volume_total = descarga_data['volume_total']
            volume_descarregado = descarga_data['volume_descarregado']
            
            # Calcular diferenças
            diferenca_sistema = None
            diferenca_regua = None
            
            if estoque_sistema_antes and estoque_sistema_depois and volume_descarregado:
                diferenca_sistema = (
                    estoque_sistema_depois - 
                    estoque_sistema_antes - 
                    volume_descarregado + 
                    (abastecimento_durante or 0)
                )
            
            if estoque_regua_antes and estoque_regua_depois and volume_descarregado:
                diferenca_regua = (
                    estoque_regua_depois - 
                    estoque_regua_antes - 
                    volume_descarregado + 
                    (abastecimento_durante or 0)
                )
            
            # Determinar status
            status = 'pendente'
            if volume_descarregado >= volume_total:
                status = 'completo'
            elif volume_descarregado > 0:
                status = 'em_andamento'
            
            # Atualizar descarga
            cursor.execute("""
                UPDATE descargas SET
                    data_carregamento = %s,
                    data_descarga = %s,
                    estoque_sistema_antes = %s,
                    estoque_regua_antes = %s,
                    estoque_sistema_depois = %s,
                    estoque_regua_depois = %s,
                    abastecimento_durante_descarga = %s,
                    temperatura = %s,
                    densidade = %s,
                    diferenca_sistema = %s,
                    diferenca_regua = %s,
                    status = %s,
                    observacoes = %s
                WHERE id = %s
            """, (
                data_carregamento, data_descarga,
                estoque_sistema_antes, estoque_regua_antes,
                estoque_sistema_depois, estoque_regua_depois,
                abastecimento_durante, temperatura, densidade,
                diferenca_sistema, diferenca_regua,
                status, observacoes,
                descarga_id
            ))
            
            conn.commit()
            flash('Descarga atualizada com sucesso!', 'success')
            return redirect(url_for('descargas.editar', descarga_id=descarga_id))
        
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f'Erro ao atualizar descarga: {e}', 'danger')
            return redirect(url_for('descargas.editar', descarga_id=descarga_id))
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass


# ============================================
# ADICIONAR ETAPA DE DESCARGA
# ============================================

@bp.route('/<int:descarga_id>/adicionar-etapa', methods=['POST'])
@login_required
def adicionar_etapa(descarga_id):
    """Adiciona uma etapa de descarga parcial"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Coletar dados da etapa
        data_etapa = request.form.get('data_etapa')
        volume_etapa = parse_moeda(request.form.get('volume_etapa', '0'))
        
        estoque_sistema_antes = parse_moeda(request.form.get('etapa_estoque_sistema_antes', ''))
        estoque_regua_antes = parse_moeda(request.form.get('etapa_estoque_regua_antes', ''))
        estoque_sistema_depois = parse_moeda(request.form.get('etapa_estoque_sistema_depois', ''))
        estoque_regua_depois = parse_moeda(request.form.get('etapa_estoque_regua_depois', ''))
        
        abastecimento_durante = parse_moeda(request.form.get('etapa_abastecimento_durante', '0'))
        observacoes_etapa = request.form.get('etapa_observacoes', '')
        
        # Calcular diferenças da etapa
        diferenca_sistema = None
        diferenca_regua = None
        
        if estoque_sistema_antes and estoque_sistema_depois and volume_etapa:
            diferenca_sistema = (
                estoque_sistema_depois - 
                estoque_sistema_antes - 
                volume_etapa + 
                (abastecimento_durante or 0)
            )
        
        if estoque_regua_antes and estoque_regua_depois and volume_etapa:
            diferenca_regua = (
                estoque_regua_depois - 
                estoque_regua_antes - 
                volume_etapa + 
                (abastecimento_durante or 0)
            )
        
        # Inserir etapa
        cursor.execute("""
            INSERT INTO descarga_etapas (
                descarga_id, data_etapa, volume_etapa,
                estoque_sistema_antes, estoque_regua_antes,
                estoque_sistema_depois, estoque_regua_depois,
                abastecimento_durante_etapa,
                diferenca_sistema, diferenca_regua,
                observacoes
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
        """, (
            descarga_id, data_etapa, volume_etapa,
            estoque_sistema_antes, estoque_regua_antes,
            estoque_sistema_depois, estoque_regua_depois,
            abastecimento_durante,
            diferenca_sistema, diferenca_regua,
            observacoes_etapa
        ))
        
        # Atualizar volume descarregado total
        cursor.execute("""
            SELECT SUM(volume_etapa) as total_etapas
            FROM descarga_etapas
            WHERE descarga_id = %s
        """, (descarga_id,))
        
        result = cursor.fetchone()
        total_etapas = result['total_etapas'] or 0
        
        # Buscar volume total da descarga
        cursor.execute("""
            SELECT volume_total
            FROM descargas
            WHERE id = %s
        """, (descarga_id,))
        
        descarga_data = cursor.fetchone()
        volume_total = descarga_data['volume_total']
        
        # Determinar status
        status = 'pendente'
        if total_etapas >= volume_total:
            status = 'completo'
        elif total_etapas > 0:
            status = 'em_andamento'
        
        # Atualizar descarga
        cursor.execute("""
            UPDATE descargas SET
                volume_descarregado = %s,
                status = %s
            WHERE id = %s
        """, (total_etapas, status, descarga_id))
        
        conn.commit()
        flash('Etapa de descarga adicionada com sucesso!', 'success')
        
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Erro ao adicionar etapa: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('descargas.editar', descarga_id=descarga_id))


# ============================================
# COPIAR PARA WHATSAPP
# ============================================

@bp.route('/<int:descarga_id>/whatsapp', methods=['GET'])
@login_required
def whatsapp(descarga_id):
    """Gera texto formatado para copiar no WhatsApp"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Buscar dados completos da descarga
        cursor.execute("""
            SELECT
                d.*,
                DATE_FORMAT(d.data_carregamento, '%d/%m/%y') AS data_carregamento_fmt,
                DATE_FORMAT(d.data_descarga, '%d/%m/%y') AS data_descarga_fmt,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista
            FROM descargas d
            INNER JOIN fretes f ON d.frete_id = f.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN produto p ON f.produto_id = p.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            WHERE d.id = %s
        """, (descarga_id,))
        
        descarga = cursor.fetchone()
        
        if not descarga:
            return jsonify({'error': 'Descarga não encontrada'}), 404
        
        # Formatar valores
        def fmt_valor(val):
            if val is None:
                return ''
            return f"{float(val):.0f}"
        
        # Criar texto para WhatsApp
        texto = f"""Distribuidora: {descarga['fornecedor']}
Data de carregamento: {descarga['data_carregamento_fmt']}
Data de descarga: {descarga['data_descarga_fmt']}
Produto: {descarga['produto']}
Volume: {fmt_valor(descarga['volume_total'])}
Motorista: {descarga['motorista']}

Medida Sistema
Antes: {fmt_valor(descarga['estoque_sistema_antes'])}
Depois: {fmt_valor(descarga['estoque_sistema_depois'])}
Diferença: {fmt_valor(descarga['diferenca_sistema'])}

Temperatura: {fmt_valor(descarga['temperatura'])}
Densidade: {fmt_valor(descarga['densidade']) if descarga['densidade'] else ''}

Medição Régua:
Antes: {fmt_valor(descarga['estoque_regua_antes'])}
Depois: {fmt_valor(descarga['estoque_regua_depois'])}
Diferença: {fmt_valor(descarga['diferenca_regua'])}"""
        
        return jsonify({'texto': texto})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
