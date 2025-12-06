from flask import Blueprint, render_template, redirect, url_for, jsonify

bp = Blueprint('bases', __name__)

@bp.route('/', methods=['GET'])
def index():
    # Redireciona diretamente para o caminho /fretes/ sem depender de url_for
    return redirect('/fretes/')

@bp.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')
