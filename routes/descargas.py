from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from datetime import datetime, date
from utils.db import get_db_connection
from utils.helpers import parse_moeda
from models import db, Descarga, DescargaEtapa
from decimal import Decimal

bp = Blueprint('descargas', __name__, url_prefix='/descargas')


@bp.route('/', methods=['GET'])
@login_required
def lista():
    """Lista todas as descargas com filtros"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
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
        # Montar filtros
        filters = []
        params = []
        
        if data_inicio:
            try:
                di = datetime.strptime(data_inicio, '%d/%m/%Y').strftime('%Y-%m-%d')
            except Exception:
                di = data_inicio
            filters.append("d.data_descarga >= %s")
            params.append(di)
        
        if data_fim:
            try:
                df = datetime.strptime(data_fim, '%d/%m/%Y').strftime('%Y-%m-%d')
            except Exception:
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
                d.data_carregamento,
                d.data_descarga,
                DATE_FORMAT(d.data_carregamento, '%d/%m/%Y') AS data_carregamento_formatada,
                DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_formatada,
                d.volume_total,
                d.volume_descarregado,
                d.status,
                d.diferenca_sistema,
                d.diferenca_regua,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                f.id AS frete_id
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
        
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
    except Exception as e:
        flash(f'Erro ao carregar descargas: {str(e)}', 'danger')
        descargas = []
        clientes = []
    finally:
        cursor.close()
        conn.close()
    
    return render_template(
        'descargas/lista.html',
        descargas=descargas,
        clientes=clientes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        cliente_id=cliente_id,
        status=status
    )


@bp.route('/novo/<int:frete_id>', methods=['GET', 'POST'])
@login_required
def novo(frete_id):
    """Cria nova descarga a partir de um frete"""
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Coletar dados do formulário
            data_carregamento = request.form.get('data_carregamento')
            data_descarga = request.form.get('data_descarga')
            volume_etapa = float(request.form.get('volume_etapa', 0))
            
            estoque_sistema_antes = request.form.get('estoque_sistema_antes')
            estoque_regua_antes = request.form.get('estoque_regua_antes')
            estoque_sistema_depois = request.form.get('estoque_sistema_depois')
            estoque_regua_depois = request.form.get('estoque_regua_depois')
            
            abastecimento = request.form.get('abastecimento_durante_descarga', 0)
            temperatura = request.form.get('temperatura')
            densidade = request.form.get('densidade')
            observacoes = request.form.get('observacoes')
            
            # Buscar dados do frete
            cursor.execute("""
                SELECT f.*, 
                       COALESCE(f.quantidade_manual, 0) as volume_total
                FROM fretes f 
                WHERE f.id = %s
            """, (frete_id,))
            frete = cursor.fetchone()
            
            if not frete:
                flash('Frete não encontrado!', 'danger')
                return redirect(url_for('descargas.lista'))
            
            volume_total = float(frete['volume_total'])
            
            # Verificar se já existe descarga para este frete
            cursor.execute("SELECT id, volume_descarregado, status FROM descargas WHERE frete_id = %s", (frete_id,))
            descarga_existente = cursor.fetchone()
            
            if descarga_existente:
                # Adicionar etapa à descarga existente
                descarga_id = descarga_existente['id']
                volume_anterior = float(descarga_existente['volume_descarregado'])
                volume_novo = volume_anterior + volume_etapa
                
                # Calcular diferenças para a etapa
                diferenca_sistema = None
                diferenca_regua = None
                
                if estoque_sistema_antes and estoque_sistema_depois:
                    diferenca_sistema = (float(estoque_sistema_depois) - float(estoque_sistema_antes) - 
                                       volume_etapa + float(abastecimento or 0))
                
                if estoque_regua_antes and estoque_regua_depois:
                    diferenca_regua = (float(estoque_regua_depois) - float(estoque_regua_antes) - 
                                     volume_etapa + float(abastecimento or 0))
                
                # Inserir etapa
                cursor.execute("""
                    INSERT INTO descarga_etapas (
                        descarga_id, data_etapa, volume_etapa,
                        estoque_sistema_antes, estoque_regua_antes,
                        estoque_sistema_depois, estoque_regua_depois,
                        abastecimento_durante_etapa,
                        diferenca_sistema, diferenca_regua,
                        observacoes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    descarga_id, data_descarga, volume_etapa,
                    estoque_sistema_antes, estoque_regua_antes,
                    estoque_sistema_depois, estoque_regua_depois,
                    abastecimento,
                    diferenca_sistema, diferenca_regua,
                    observacoes
                ))
                
                # Atualizar descarga principal
                novo_status = 'concluido' if volume_novo >= volume_total else 'parcial'
                cursor.execute("""
                    UPDATE descargas 
                    SET volume_descarregado = %s, status = %s, atualizado_em = NOW()
                    WHERE id = %s
                """, (volume_novo, novo_status, descarga_id))
                
                conn.commit()
                flash(f'Etapa de descarga adicionada com sucesso! Volume total descarregado: {volume_novo} litros', 'success')
            else:
                # Criar nova descarga
                # Calcular diferenças
                diferenca_sistema = None
                diferenca_regua = None
                
                if estoque_sistema_antes and estoque_sistema_depois:
                    diferenca_sistema = (float(estoque_sistema_depois) - float(estoque_sistema_antes) - 
                                       volume_etapa + float(abastecimento or 0))
                
                if estoque_regua_antes and estoque_regua_depois:
                    diferenca_regua = (float(estoque_regua_depois) - float(estoque_regua_antes) - 
                                     volume_etapa + float(abastecimento or 0))
                
                status = 'concluido' if volume_etapa >= volume_total else 'parcial'
                
                cursor.execute("""
                    INSERT INTO descargas (
                        frete_id, data_carregamento, data_descarga, volume_total,
                        estoque_sistema_antes, estoque_regua_antes,
                        estoque_sistema_depois, estoque_regua_depois,
                        abastecimento_durante_descarga,
                        temperatura, densidade,
                        diferenca_sistema, diferenca_regua,
                        status, volume_descarregado, observacoes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    frete_id, data_carregamento, data_descarga, volume_total,
                    estoque_sistema_antes, estoque_regua_antes,
                    estoque_sistema_depois, estoque_regua_depois,
                    abastecimento,
                    temperatura, densidade,
                    diferenca_sistema, diferenca_regua,
                    status, volume_etapa, observacoes
                ))
                
                conn.commit()
                flash('Descarga criada com sucesso!', 'success')
            
            return redirect(url_for('descargas.lista'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar descarga: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()
    
    # GET: Carregar dados do frete
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT 
                f.*,
                DATE_FORMAT(f.data_frete, '%d/%m/%Y') AS data_frete_formatada,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(v.caminhao, '') AS veiculo,
                COALESCE(f.quantidade_manual, 0) as volume_total
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
            return redirect(url_for('fretes.lista'))
        
        # Verificar se já existe descarga
        cursor.execute("""
            SELECT d.*, 
                   (SELECT COUNT(*) FROM descarga_etapas WHERE descarga_id = d.id) as num_etapas
            FROM descargas d 
            WHERE d.frete_id = %s
        """, (frete_id,))
        descarga_existente = cursor.fetchone()
        
        # Buscar etapas se existir descarga
        etapas = []
        if descarga_existente:
            cursor.execute("""
                SELECT *,
                       DATE_FORMAT(data_etapa, '%d/%m/%Y') AS data_etapa_formatada
                FROM descarga_etapas 
                WHERE descarga_id = %s
                ORDER BY data_etapa
            """, (descarga_existente['id'],))
            etapas = cursor.fetchall()
        
    except Exception as e:
        flash(f'Erro ao carregar dados: {str(e)}', 'danger')
        return redirect(url_for('descargas.lista'))
    finally:
        cursor.close()
        conn.close()
    
    return render_template(
        'descargas/novo.html',
        frete=frete,
        descarga_existente=descarga_existente,
        etapas=etapas
    )


@bp.route('/detalhes/<int:descarga_id>', methods=['GET'])
@login_required
def detalhes(descarga_id):
    """Exibe detalhes de uma descarga"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT 
                d.*,
                DATE_FORMAT(d.data_carregamento, '%d/%m/%Y') AS data_carregamento_formatada,
                DATE_FORMAT(d.data_descarga, '%d/%m/%Y') AS data_descarga_formatada,
                COALESCE(c.razao_social, '') AS cliente,
                COALESCE(fo.razao_social, '') AS fornecedor,
                COALESCE(p.nome, '') AS produto,
                COALESCE(m.nome, '') AS motorista,
                COALESCE(v.caminhao, '') AS veiculo,
                f.id AS frete_id
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
            SELECT *,
                   DATE_FORMAT(data_etapa, '%d/%m/%Y') AS data_etapa_formatada
            FROM descarga_etapas 
            WHERE descarga_id = %s
            ORDER BY data_etapa
        """, (descarga_id,))
        etapas = cursor.fetchall()
        
    except Exception as e:
        flash(f'Erro ao carregar descarga: {str(e)}', 'danger')
        return redirect(url_for('descargas.lista'))
    finally:
        cursor.close()
        conn.close()
    
    return render_template(
        'descargas/detalhes.html',
        descarga=descarga,
        etapas=etapas
    )


@bp.route('/whatsapp/<int:descarga_id>', methods=['GET'])
@login_required
def whatsapp(descarga_id):
    """Retorna o texto formatado para WhatsApp"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT 
                d.*,
                DATE_FORMAT(d.data_carregamento, '%d/%m/%y') AS data_carregamento_formatada,
                DATE_FORMAT(d.data_descarga, '%d/%m/%y') AS data_descarga_formatada,
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
        
        # Formatar texto para WhatsApp
        texto = f"""Distribuidora: {descarga['fornecedor']}
Data de carregamento: {descarga['data_carregamento_formatada']}
Data de descarga: {descarga['data_descarga_formatada']}
Produto: {descarga['produto']}
Volume: {descarga['volume_descarregado']:.2f}
Motorista: {descarga['motorista']}
Medida Sistema Antes: {descarga['estoque_sistema_antes'] or ''}
Medida Sistema Depois: {descarga['estoque_sistema_depois'] or ''}
Diferença: {descarga['diferenca_sistema'] or ''}
Temperatura: {descarga['temperatura'] or ''}
Densidade: {descarga['densidade'] or ''}
Medição Régua:
Antes: {descarga['estoque_regua_antes'] or ''}
Depois: {descarga['estoque_regua_depois'] or ''}
Diferença: {descarga['diferenca_regua'] or ''}"""
        
        return jsonify({'texto': texto})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
