from flask import Blueprint, render_template, redirect, url_for, jsonify

# Blueprint 'bases' — arquivo responsável por páginas básicas (home/health).
bp = Blueprint('bases', __name__)


@bp.route('/', methods=['GET'])
def index():
    # Renderiza a página do dashboard como home
    return render_template('dashboard.html')


@bp.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')
