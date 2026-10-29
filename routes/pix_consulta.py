"""PIX Consulta — confirmar que um PIX caiu no banco e emitir o comprovante
com protocolo (utils/pix_consulta). Fase 1: só ADMIN (29/10/2026); depois
Gerente/Supervisor e a versão da Pista (só o dia, com o frentista)."""
import re
from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
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


# ── Pista: só o dia, com o frentista; o 2o pedido só diz quem já consultou ──
# Quem entra na tela da Pista. Pronto para SUPERVISOR e PISTA, mas DESLIGADO
# até o treinamento (29/10/2026): para liberar, LIBERAR_PISTA = True. A mesma
# chave põe o item no menu deles (navbar, pix_pista_liberada).
LIBERAR_PISTA = False
NIVEIS_PISTA = {'ADMIN', 'ADMINISTRADOR'} | ({'SUPERVISOR', 'PISTA'} if LIBERAR_PISTA else set())


@bp.app_context_processor
def _menu_pista():
    return {'pix_pista_liberada': LIBERAR_PISTA}


def pista_required(f):
    @wraps(f)
    def dentro(*args, **kwargs):
        nivel = (getattr(current_user, 'nivel', '') or '').strip().upper()
        if nivel not in NIVEIS_PISTA:
            if request.path.endswith('/pista/'):
                flash('Acesso negado.', 'danger')
                return redirect(url_for('index'))
            return jsonify({'erro': 'acesso negado'}), 403
        return f(*args, **kwargs)
    return dentro


def _frentistas(conn):
    """Os mesmos do Troco PIX Pista: ativos e ainda na casa hoje."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, nome FROM funcionarios
                        WHERE ativo = 1 AND (data_saida IS NULL OR data_saida >= %s)
                        ORDER BY nome""", (hoje_brasilia(),))
        return cur.fetchall()
    finally:
        cur.close()


@bp.route('/pista/')
@login_required
@pista_required
def pista():
    conn = get_db_connection()
    try:
        frentistas = _frentistas(conn)
    finally:
        conn.close()
    return render_template('pix_consulta/pista.html', frentistas=frentistas,
                           hoje=hoje_brasilia().strftime('%d/%m/%Y'))


@bp.route('/pista/buscar')
@login_required
@pista_required
def pista_buscar():
    valor = _valor(request.args.get('valor'))
    quem = (request.args.get('quem') or '').strip()
    # a Pista não navega na lista do dia: precisa do valor e de um nome/documento
    if valor is None or len(quem) < 3:
        return jsonify({'erro': 'Digite o valor e um nome (ou CPF/CNPJ) do pagador.'}), 400
    conn = get_db_connection()
    try:
        pix = pix_consulta.buscar(conn, hoje_brasilia(), valor, quem)
        return jsonify({'pix': [pix_consulta.para_pista(p) for p in pix]})
    finally:
        conn.close()


@bp.route('/pista/protocolo', methods=['POST'])
@login_required
@pista_required
def pista_protocolo():
    dados = request.get_json(silent=True) or {}
    try:
        bt_id = int(dados.get('id'))
        frentista_id = int(dados.get('frentista_id'))
    except (TypeError, ValueError):
        return jsonify({'erro': 'Escolha quem está consultando.'}), 400
    conn = get_db_connection()
    try:
        frentista = next((f['nome'] for f in _frentistas(conn) if f['id'] == frentista_id), None)
        if not frentista:
            return jsonify({'erro': 'Escolha quem está consultando.'}), 400
        pix = pix_consulta.um(conn, bt_id=bt_id)
        if not pix or pix['_dia'] != hoje_brasilia():
            return jsonify({'erro': 'PIX não encontrado hoje.'}), 404
        if not pix.get('protocolo'):
            pix, novo = pix_consulta.emitir(
                conn, bt_id, current_user.id,
                getattr(current_user, 'nome_completo', None) or current_user.username,
                'pista', frentista)
        else:
            novo = False
        if not novo:
            # alguém consultou antes (ou no mesmo instante): sem protocolo
            return jsonify({'ja': pix_consulta.para_pista(pix)}), 409
        pix = {k: v for k, v in pix.items() if not k.startswith('_')}
        return jsonify({'pix': pix})
    finally:
        conn.close()
