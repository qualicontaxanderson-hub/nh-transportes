from flask import Blueprint, render_template, request
from utils.db import get_db_connection

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

@bp.route('/')
def index():
    try:
        # Pegar filtros da URL (se houver)
        data_inicio = request.args.get('data_inicio', '')
        data_fim = request.args.get('data_fim', '')
        mes = request.args.get('mes', '')

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

        if mes:
            filtro += " AND MONTH(f.data_frete) = %s"
            params.append(mes)

        # Top 10 Clientes
        query_clientes = f"""
            SELECT c.razao_social AS cliente, COUNT(f.id) AS fretes, 
                   SUM(f.valor_total_frete) AS total, SUM(f.lucro) AS lucro
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            {filtro}
            GROUP BY f.clientes_id
            ORDER BY total DESC
            LIMIT 10
        """
        cursor.execute(query_clientes, params)
        por_cliente = cursor.fetchall()

        # Comissões de Motoristas
        query_motoristas = f"""
            SELECT m.nome AS motorista, COUNT(f.id) AS fretes, 
                   SUM(f.comissao_motorista) AS total_comissao
            FROM fretes f
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            {filtro}
            GROUP BY f.motoristas_id
            ORDER BY total_comissao DESC
        """
        cursor.execute(query_motoristas, params)
        por_motorista = cursor.fetchall()

        # Situação Financeira
        query_situacao = f"""
            SELECT f.status AS status, COUNT(f.id) AS quantidade, 
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
                               por_motorista=por_motorista,
                               por_situacao=por_situacao,
                               data_inicio=data_inicio,
                               data_fim=data_fim,
                               mes=mes)

    except Exception as e:
        print(f"Erro ao carregar relatórios: {e}")
        return render_template('relatorios/index.html',
                               por_cliente=[],
                               por_motorista=[],
                               por_situacao=[],
                               data_inicio='',
                               data_fim='',
                               mes='')
