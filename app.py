import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager

def _import_fretes_bp(app):
    candidates = ['fretes', 'routes.fretes']
    for modname in candidates:
        try:
            module = __import__(modname, fromlist=['bp'])
            bp = getattr(module, 'bp', None)
            if bp is not None:
                app.logger.info('Imported fretes blueprint from %s', modname)
                return bp
        except Exception as e:
            app.logger.debug('Import %s failed: %s', modname, e, exc_info=True)
    app.logger.warning('Could not import fretes blueprint from any candidate: %s', candidates)
    return None

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

    # user_loader: usar models.usuario.Usuario.get_by_id (se existir)
    @login_manager.user_loader
    def load_user(user_id):
        """
        Carrega usuário pelo ID usando models.usuario.Usuario.get_by_id.
        Retorna None se o model não existir ou se o usuário não for encontrado.
        """
        try:
            from models.usuario import Usuario
            # user_id pode vir como string; ensure int where appropriate
            try:
                uid = int(user_id)
            except Exception:
                uid = user_id
            if hasattr(Usuario, 'get_by_id'):
                return Usuario.get_by_id(uid)
            # fallbacks (incomum aqui, mas seguro)
            if hasattr(Usuario, 'get'):
                return Usuario.get(uid)
            return None
        except Exception:
            # não deve levantar exceção — retornamos None e deixamos o login flow cuidar
            app.logger.debug('load_user: models.usuario.Usuario não disponível ou falha ao carregar', exc_info=True)
            return None

    # Importar e registrar blueprint 'fretes'
    try:
        fretes_bp = _import_fretes_bp(app)
        if fretes_bp:
            app.register_blueprint(fretes_bp)
            app.logger.info('Blueprint fretes registrado.')
        else:
            app.logger.warning('Blueprint fretes nao registrado; verifique se o módulo existe e expõe "bp".')
    except Exception as e:
        app.logger.exception('Erro ao registrar blueprint fretes: %s', e)
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
