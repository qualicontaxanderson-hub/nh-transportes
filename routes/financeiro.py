from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime
import pymysql

from utils.db import get_db_connection
# ajuste o caminho abaixo conforme onde você salvar essas funções
from utils.boletos import emitir_boleto_frete, get_efi_client

bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')


@bp.route('/recebimentos')
@login_required
def recebimentos():
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    mes = request.args.get('mes')
    ano = request.args.get('ano')
    status = request.args.get('status')

    hoje = datetime.today()
    mes = int(mes) if mes else hoje.month
    ano = int(ano) if ano else hoje.year

    inicio = datetime(ano, mes, 1).date()
    if mes == 12:
        fim = datetime(ano + 1, 1, 1).date()
    else:
        fim = datetime(ano, mes + 1, 1).date()

    filtros = [inicio, fim]
    where_status = ""
    if status and status != "todos":
        where_status = " AND c.status = %s "
        filtros.append(status)

    try:
        cursor.execute(
            f"""
            SELECT
                c.id,
                c.id_cliente,
                cli.razao_social AS cliente_nome,
                c.valor,
                c.data_vencimento,
                c.status,
                c.charge_id,
                c.link_boleto,
                c.pdf_boleto,
                c.data_emissao
            FROM cobrancas c
            JOIN clientes cli ON cli.id = c.id_cliente
            WHERE c.data_vencimento >= %s
              AND c.data_vencimento < %s
            {where_status}
            ORDER BY c.data_vencimento DESC, c.id DESC
            """,
            filtros
        )
        cobrancas = cursor.fetchall()

        cursor.execute(
            """
            SELECT status, SUM(valor) AS total
            FROM cobrancas
            WHERE data_vencimento >= %s
              AND data_vencimento < %s
            GROUP BY status
            """,
            [inicio, fim]
        )
        totais_brutos = cursor.fetchall()
    except Exception:
        cobrancas = []
        totais_brutos = []
    finally:
        cursor.close()
        conn.close()

    totais = {"waiting": 0, "paid": 0, "canceled": 0}
    for t in totais_brutos:
        st = t.get("status")
        if st in totais:
            totais[st] = t.get("total") or 0

    return render_template(
        'financeiro/recebimentos.html',
        cobrancas=cobrancas,
        totais=totais,
        mes=mes,
        ano=ano,
        status=status or "todos"
    )


@bp.route('/recebimentos/marcar_pago', methods=['POST'])
@login_required
def marcar_pago():
    cobranca_id = request.form.get('cobranca_id')
    if not cobranca_id:
        flash('Cobrança não informada.', 'warning')
        return redirect(url_for('financeiro.recebimentos'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE cobrancas SET status = %s WHERE id = %s",
            ("paid", cobranca_id)
        )
        conn.commit()
        flash(f'Cobrança #{cobranca_id} marcada como paga.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao marcar cobrança como paga: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('financeiro.recebimentos'))


@bp.route('/recebimentos/cancelar', methods=['POST'])
@login_required
def cancelar_cobranca():
    cobranca_id = request.form.get('cobranca_id')
    if not cobranca_id:
        flash('Cobrança não informada.', 'warning')
        return redirect(url_for('financeiro.recebimentos'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE cobrancas SET status = %s WHERE id = %s",
            ("canceled", cobranca_id)
        )
        conn.commit()
        flash(f'Cobrança #{cobranca_id} cancelada.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao cancelar cobrança: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('financeiro.recebimentos'))


@bp.route('/recebimentos/emitir/<int:frete_id>', methods=['POST'])
@login_required
def emitir_boleto_frete_route(frete_id):
    """
    Emite boleto para um frete específico e grava na tabela cobrancas.
    Usa a função emitir_boleto_frete que você já testou com o EFI.
    """
    conn = get_db_connection()
    try:
        cobranca_id, link_boleto = emitir_boleto_frete(conn, frete_id)
        flash(f'Boleto emitido para o frete #{frete_id}.', 'success')
    except Exception as e:
        flash(f'Erro ao emitir boleto para o frete #{frete_id}: {e}', 'danger')
    finally:
        conn.close()

    # pode voltar para fretes ou recebimentos; aqui volta para fretes
    return redirect(url_for('fretes.lista'))
