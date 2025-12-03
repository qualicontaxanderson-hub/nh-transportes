from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection

bp = Blueprint('fretes', __name__, url_prefix='/fretes')


@bp.route('/', methods=['GET'])
@login_required
def lista():
    """
    Lista simples de fretes — usada pelo menu (endpoint 'fretes.lista').
    """
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
    """
    Formulário/ação para criar um novo frete — usado em url_for('fretes.novo').
    Ajuste a lógica conforme sua tabela e template.
    """
    if request.method == 'POST':
        # Exemplo: aqui você insere na tabela fretes usando os dados do form.
        # Preencha os campos reais da sua tabela.
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO fretes (data_frete, status, valor_total_frete, lucro,
                                    clientes_id, fornecedores_id, motoristas_id, veiculos_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    request.form.get('data_frete'),
                    request.form.get('status'),
                    request.form.get('valor_total_frete'),
                    request.form.get('lucro'),
                    request.form.get('clientes_id'),
                    request.form.get('fornecedores_id'),
                    request.form.get('motoristas_id'),
                    request.form.get('veiculos_id'),
                ),
            )
            conn.commit()
            flash('Frete criado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar frete: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()

    # GET: exibe o formulário
    return render_template('fretes/novo.html')
