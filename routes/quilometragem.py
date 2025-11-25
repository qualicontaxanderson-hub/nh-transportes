from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from config import Config
import mysql.connector

bp = Blueprint('quilometragem', __name__, url_prefix='/quilometragem')

def get_db():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
        port=Config.DB_PORT
    )

def converter_para_decimal(valor):
    if isinstance(valor, str):
        valor = valor.replace('.', '').replace(',', '.')
    return valor

def get_ultimo_km_veiculo(veiculos_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT km_final as ultimo_km
        FROM quilometragem
        WHERE veiculos_id = %s
        ORDER BY data DESC, id DESC
        LIMIT 1
    """, (veiculos_id,))
    resultado = cursor.fetchone()
    if not resultado:
        cursor.execute("""
            SELECT km_inicial as ultimo_km
            FROM quilometragem_inicial
            WHERE veiculos_id = %s
        """, (veiculos_id,))
        resultado = cursor.fetchone()
    cursor.close()
    conn.close()
    return float(resultado['ultimo_km']) if resultado else None

@bp.route('/')
@login_required
def lista():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    veiculos_id = request.args.get('veiculos_id', '')
    motoristas_id = request.args.get('motoristas_id', '')
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    query = """
        SELECT 
            q.id,
            q.data,
            q.km_inicial,
            q.km_final,
            q.km_rodados,
            q.valor_combustivel,
            q.litros_abastecidos,
            q.observacoes,
            v.placa,
            v.modelo,
            m.nome as motorista_nome
        FROM quilometragem q
        LEFT JOIN veiculos v ON q.veiculos_id = v.id
        LEFT JOIN motoristas m ON q.motoristas_id = m.id
        WHERE 1=1
    """
    params = []
    if veiculos_id:
        query += " AND q.veiculos_id = %s"
        params.append(veiculos_id)
    if motoristas_id:
        query += " AND q.motoristas_id = %s"
        params.append(motoristas_id)
    if data_inicio:
        query += " AND q.data >= %s"
        params.append(data_inicio)
    if data_fim:
        query += " AND q.data <= %s"
        params.append(data_fim)
    query += " ORDER BY q.data DESC, q.id DESC"
    cursor.execute(query, params)
    quilometragens = cursor.fetchall()
    cursor.execute("SELECT id, placa, modelo FROM veiculos WHERE ativo = 1 ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.execute("""
        SELECT 
            v.id,
            v.placa,
            v.modelo,
            qi.km_inicial,
            qi.data_cadastro
        FROM veiculos v
        LEFT JOIN quilometragem_inicial qi ON v.id = qi.veiculos_id
        WHERE v.ativo = 1
        ORDER BY v.placa
    """)
    veiculos_km_inicial = cursor.fetchall()
    resumo_query = """
        SELECT 
            v.placa,
            v.modelo,
            SUM(q.litros_abastecidos) as total_litros,
            SUM(q.km_rodados) as total_km
        FROM quilometragem q
        LEFT JOIN veiculos v ON q.veiculos_id = v.id
        WHERE 1=1
    """
    resumo_params = []
    if veiculos_id:
        resumo_query += " AND q.veiculos_id = %s"
        resumo_params.append(veiculos_id)
    if motoristas_id:
        resumo_query += " AND q.motoristas_id = %s"
        resumo_params.append(motoristas_id)
    if data_inicio:
        resumo_query += " AND q.data >= %s"
        resumo_params.append(data_inicio)
    if data_fim:
        resumo_query += " AND q.data <= %s"
        resumo_params.append(data_fim)
    resumo_query += " GROUP BY v.placa, v.modelo ORDER BY v.placa"
    cursor.execute(resumo_query, resumo_params)
    resumo_veiculos = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'quilometragem/lista.html',
        registros=quilometragens,     # <-- nome corrigido para bater com o template!
        veiculos=veiculos,
        motoristas=motoristas,
        veiculos_km_inicial=veiculos_km_inicial,
        filtros={
            'veiculos_id': veiculos_id,
            'motoristas_id': motoristas_id,
            'data_inicio': data_inicio,
            'data_fim': data_fim
        },
        resumo_veiculos=resumo_veiculos
    )

# As demais rotas (novo, editar, etc.) permanecem como você já está usando.
# Não é necessário mudar nada nelas, pois já usam nomes idênticos do backend para o template.
