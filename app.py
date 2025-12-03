import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager

def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key'),
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
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    # Tentar importar e registrar blueprint 'fretes' aqui, com logging detalhado
    try:
        from fretes import bp as fretes_bp
        app.register_blueprint(fretes_bp)
        app.logger.info('Blueprint fretes registrado.')
    except Exception as e:
        # registra stacktrace completo para debugar o motivo do import/registro falhar
        app.logger.exception('Falha ao importar/registrar blueprint "fretes": %s', e)
        fretes_bp = None

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
            return "404 - Página não encontrada", 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception('Erro interno do servidor: %s', error)
        try:
            return render_template('500.html'), 500
        except Exception:
            return "500 - Erro interno do servidor", 500

    return app

# Expor a app no nível do módulo para compatibilidade com gunicorn app:app
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', '1') == '1')
