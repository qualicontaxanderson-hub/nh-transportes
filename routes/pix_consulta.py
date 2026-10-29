"""PIX Consulta — confirmar que um PIX caiu no banco e emitir o comprovante
com protocolo (utils/pix_consulta). Fase 1: só ADMIN (29/10/2026); depois
Gerente/Supervisor e a versão da Pista (só o dia, com o frentista)."""
import re
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from utils import pix_consulta
from utils.db import get_db_connection
from utils.decorators import admin_required
from utils.fuso import hoje_brasilia

bp = Blueprint('pix_consulta', __name__, url_prefix='/banco/pix-consulta')


def _valor(s):
    s = (s or '').strip().replace('R$', '').replace(' ', '')
    if not s:
        return None
    # 1.500,00 / 1500,00 / 1.500 (milhar) / 1500
    if ',' in s or re.fullmatch(r'\d{1,3}(\.\d{3})+', s):
        s = s.replace('.', '').replace(',', '.')
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _dia(s):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return hoje_brasilia()


@bp.route('/')
@login_required
@admin_required
def index():
    return render_template('pix_consulta/index.html', hoje=hoje_brasilia().isoformat())


@bp.route('/buscar')
@login_required
@admin_required
def buscar():
    conn = get_db_connection()
    try:
        dia = _dia(request.args.get('dia'))
        pix = pix_consulta.buscar(conn, dia, _valor(request.args.get('valor')),
                                  request.args.get('quem'))
        return jsonify({'pix': pix})
    finally:
        conn.close()


@bp.route('/protocolo', methods=['POST'])
@login_required
@admin_required
def protocolo():
    dados = request.get_json(silent=True) or {}
    try:
        bt_id = int(dados.get('id'))
    except (TypeError, ValueError):
        return jsonify({'erro': 'PIX inválido'}), 400
    conn = get_db_connection()
    try:
        pix, novo = pix_consulta.emitir(
            conn, bt_id, current_user.id,
            getattr(current_user, 'nome_completo', None) or current_user.username, 'admin')
        if not pix:
            return jsonify({'erro': 'PIX não encontrado'}), 404
        return jsonify({'pix': pix, 'novo': novo})
    finally:
        conn.close()


@bp.route('/protocolo/<codigo>')
@login_required
@admin_required
def achar_protocolo(codigo):
    conn = get_db_connection()
    try:
        pix = pix_consulta.um(conn, protocolo=codigo.strip().upper())
        return jsonify({'pix': pix})
    finally:
        conn.close()


@bp.route('/hoje')
@login_required
@admin_required
def consultas_do_dia():
    conn = get_db_connection()
    try:
        return jsonify({'pix': pix_consulta.de_hoje(conn, _dia(request.args.get('dia')))})
    finally:
        conn.close()
