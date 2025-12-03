import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager

# Tente importar módulos do projeto; se não existirem, mantenha None para evitar ImportError no startup.
try:
    from fretes import bp as fretes_bp
except Exception:
    fretes_bp = None

try:
    from utils.db import get_db_connection
except Exception:
    get_db_connection = None

def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key'),
        # adicione outras configs que seu projeto precise
    )

    # Logging básico (arquivo rotativo)
    if not app.debug and not app.testing:
        log_dir = os.environ.get('LOG_DIR', '.')
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(os.path.join(log_dir, 'app.log'), maxBytes=10*1024*1024, backupCount=5)
        formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)

    # Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'  # ajuste se tiver blueprint auth
    login_manager.init_app(app)

    # Registrar blueprints (se existirem)
    if fretes_bp is not None:
        app.register_blueprint(fretes_bp)
        app.logger.info('Blueprint fretes registrado.')
    else:
        app.logger.warning('Blueprint fretes nao encontrado; verifique imports.')

    # Rota index simples
    @app.route('/')
    def index():
        return redirect(url_for('fretes.lista')) if fretes_bp is not None else "App funcionando - sem blueprint 'fretes' registrado."

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        try:
            return render_template('404.html'), 404
        except Exception:
            # fallback mínimo se template faltar
            return "404 - Página não encontrada", 404

    @app.errorhandler(500)
    def internal_error(error):
        # registrar exceção completa
        app.logger.exception('Erro interno do servidor: %s', error)
        try:
            return render_template('500.html'), 500
        except Exception:
            return "500 - Erro interno do servidor", 500

    return app

if __name__ == '__main__':
    app = create_app()
    # modo dev
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', '1') == '1')
