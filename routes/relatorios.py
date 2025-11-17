# routes/relatorios.py - COMPLETO E CORRIGIDO
from flask import Blueprint, render_template, request
from utils.db import get_db_connection
from datetime import datetime

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
def index():
    try:
        # Pegar filtros da URL
        data_inicio = request.args.get('data_inicio', '')
        data_fim = request.args.get('data_fim', '')
        ano_mes = request.args.get('ano_mes', '')  # Formato: YYYY-MM

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Construir filtro WHERE dinamicamente
        filtro = "WHERE 1=1"
        params = []

        if data_inicio:
            filtro += " AND f.data_frete >= %s"
            params.append(data_inicio)

        if data_fim:
            filtro += " AND f.data_frete <= %s"
            params.append(data_fim)

        if ano_mes:
            # Formato YYYY-MM
            filtro += " AND DATE_FORMAT(f.data_frete, '%Y-%m') = %s"
            params.append(ano_mes)

        # TOP 10 CLIENTES - Agrupado por cliente (um frete = um registro de cada cliente)
        query_clientes = f"""
            SELECT c.razao_social AS cliente, 
                   COUNT(DISTINCT f.id) AS fretes,
                   SUM(q.valor) AS litros_transportados,
                   SUM(f.valor_total_frete) AS total_frete,
                   SUM(f.comissao_cte) AS total_comissao_cte,
                   SUM(f.lucro) AS lucro
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            {filtro}
            GROUP BY f.clientes_id
            ORDER BY total_frete DESC
            LIMIT 10
        """
        cursor.execute(query_clientes, params)
        por_cliente = cursor.fetchall()

        # Calcular totais para clientes
        total_fretes = sum(item['fretes'] for item in por_cliente) if por_cliente else 0
        total_litros = sum(item['litros_transportados'] for item in por_cliente) if por_cliente else 0
        total_frete_clientes = sum(item['total_frete'] for item in por_cliente) if por_cliente else 0
        total_comissao_cte_clientes = sum(item['total_comissao_cte'] for item in por_cliente) if por_cliente else 0
        total_lucro_clientes = sum(item['lucro'] for item in por_cliente) if por_cliente else 0

        # COMISSÕES DE MOTORISTAS - Com quantidade de fretes e litros
        query_motoristas = f"""
            SELECT m.nome AS motorista, 
                   COUNT(f.id) AS fretes,
                   SUM(q.valor) AS litros_entregues,
                   SUM(f.comissao_motorista) AS total_comissao
            FROM fretes f
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            {filtro}
            GROUP BY f.motoristas_id
            ORDER BY total_comissao DESC
        """
        cursor.execute(query_motoristas, params)
        por_motorista = cursor.fetchall()

        # Calcular totais para motoristas
        total_fretes_mot = sum(item['fretes'] for item in por_motorista) if por_motorista else 0
        total_litros_mot = sum(item['litros_entregues'] for item in por_motorista) if por_motorista else 0
        total_comissao_mot = sum(item['total_comissao'] for item in por_motorista) if por_motorista else 0

        # SITUAÇÃO FINANCEIRA
        query_situacao = f"""
            SELECT f.status AS status, 
                   COUNT(f.id) AS quantidade, 
                   SUM(f.valor_total_frete) AS valor_total
            FROM fretes f
            {filtro}
            GROUP BY f.status
        """
        cursor.execute(query_situacao, params)
        por_situacao = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('relatorios/index.html',
                               por_cliente=por_cliente,
                               total_fretes=total_fretes,
                               total_litros=total_litros,
                               total_frete_clientes=total_frete_clientes,
                               total_comissao_cte_clientes=total_comissao_cte_clientes,
                               total_lucro_clientes=total_lucro_clientes,
                               por_motorista=por_motorista,
                               total_fretes_mot=total_fretes_mot,
                               total_litros_mot=total_litros_mot,
                               total_comissao_mot=total_comissao_mot,
                               por_situacao=por_situacao,
                               data_inicio=data_inicio,
                               data_fim=data_fim,
                               ano_mes=ano_mes)

    except Exception as e:
        print(f"Erro ao carregar relatórios: {e}")
        return render_template('relatorios/index.html',
                               por_cliente=[],
                               total_fretes=0,
                               total_litros=0,
                               total_frete_clientes=0,
                               total_comissao_cte_clientes=0,
                               total_lucro_clientes=0,
                               por_motorista=[],
                               total_fretes_mot=0,
                               total_litros_mot=0,
                               total_comissao_mot=0,
                               por_situacao=[],
                               data_inicio='',
                               data_fim='',
                               ano_mes='')
