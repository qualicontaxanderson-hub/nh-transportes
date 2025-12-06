from flask import Blueprint, render_template, redirect, url_for, jsonify

# Blueprint 'bases' — arquivo responsável por páginas básicas (home/health), NÃO registrar 'fretes' aqui.
bp = Blueprint('bases', __name__)


@bp.route('/', methods=['GET'])
def index():
    # Redireciona para a lista de fretes por padrão (ou para uma home se preferir)
    return redirect(url_for('fretes.lista'))


@bp.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')
