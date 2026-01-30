import os
import logging
from logging.handlers import RotatingFileHandler
import pkgutil
import importlib

from flask import Flask, render_template, redirect, url_for, current_app
from flask_login import LoginManager
from utils.formatadores import formatar_moeda


def register_blueprints_from_routes(app):
    """
    Varre o pacote `routes` e tenta importar cada módulo.
    Se o módulo expuser `bp` ou qualquer atributo terminado em '_bp' (Blueprint)
    ele é registrado automaticamente.
    Exceções de import são logadas para diagnóstico (não interrompem o registro).
    """
    ...
    try:
        import routes  # pacote que contém os módulos de rota (routes/*.py)
    except Exception:
        app.logger.warning("Pacote 'routes' não encontrado; nenhum blueprint será registrado automaticamente.")
        return

    for finder, name, ispkg in pkgutil.iter_modules(routes.__path__):
        modname = f"{routes.__name__}.{name}"
        try:
            module = importlib.import_module(modname)
            
            # Procurar por 'bp' ou qualquer variável terminada em '_bp'
            blueprint_found = False
            
            # Primeiro tenta 'bp' padrão
            bp = getattr(module, "bp", None)
            if bp is not None:
                bp_name = getattr(bp, "name", None)
                if bp_name and bp_name in app.blueprints:
                    app.logger.debug("Blueprint '%s' já registrado; ignorando duplicação de %s", bp_name, modname)
                    blueprint_found = True
                else:
                    try:
                        app.register_blueprint(bp)
                        app.logger.info("Blueprint '%s' registrado a partir de %s", getattr(bp, "name", str(bp)), modname)
                        blueprint_found = True
                    except Exception:
                        app.logger.exception("Falha ao registrar blueprint vindo de %s", modname)
            
            # Se não encontrou 'bp', procura por variáveis terminadas em '_bp'
            if not blueprint_found:
                for attr_name in dir(module):
                    if attr_name.endswith('_bp') and not attr_name.startswith('_'):
                        bp_candidate = getattr(module, attr_name, None)
                        if bp_candidate is not None and hasattr(bp_candidate, 'name'):
                            bp_name = getattr(bp_candidate, "name", None)
                            if bp_name and bp_name in app.blueprints:
                                app.logger.debug("Blueprint '%s' já registrado; ignorando duplicação de %s (variável: %s)", 
                                               bp_name, modname, attr_name)
                                blueprint_found = True
                                break
                            try:
                                app.register_blueprint(bp_candidate)
                                app.logger.info("Blueprint '%s' registrado a partir de %s (variável: %s)", 
                                              getattr(bp_candidate, "name", str(bp_candidate)), modname, attr_name)
                                blueprint_found = True
                                break  # Registra apenas o primeiro blueprint encontrado por módulo
                            except Exception:
                                app.logger.exception("Falha ao registrar blueprint '%s' vindo de %s", attr_name, modname)
            
            if not blueprint_found:
                app.logger.debug("Módulo %s não expõe 'bp' ou '*_bp'; ignorando.", modname)
                
        except Exception:
            app.logger.exception("Falha ao importar módulo de rotas %s", modname)


def formatar_moeda(valor):
    """
    Formata um número para representação de moeda BRL (ex.: R$ 1.234,56).
    Retorna '-' para valores None/invalidos.
    """
    try:
        if valor is None or valor == '':
            return '-'
        # tenta converter strings tolerantly
        if isinstance(valor, str):
            s = valor.strip().replace('R$', '').replace('r$', '').replace(' ', '')
            # caso pt-BR com milhar e decimal
            if '.' in s and ',' in s:
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '.')
            num = float(s)
        else:
            num = float(valor)
    except Exception:
        return '-'

    inteiro = int(abs(num))
    centavos = int(round((abs(num) - inteiro) * 100))
    inteiro_str = f"{inteiro:,}".replace(',', '.')
    sinal = '-' if num < 0 else ''
    return f"{sinal}R$ {inteiro_str},{centavos:02d}"


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    
    # Load configuration
    from config import Config
    app.config.from_object(Config)
    
    # Override with environment variable if set
    if os.environ.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

    # Initialize SQLAlchemy
    from models import db
    db.init_app(app)

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
    # aponta para o endpoint de login que existe no blueprint 'auth' (auth.login)
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    # user_loader: usar models.usuario.Usuario.get_by_id (se existir)
    @login_manager.user_loader
    def load_user(user_id):
        try:
            from models.usuario import Usuario
            try:
                uid = int(user_id)
            except Exception:
                uid = user_id
            if hasattr(Usuario, 'get_by_id'):
                return Usuario.get_by_id(uid)
            if hasattr(Usuario, 'get'):
                return Usuario.get(uid)
            return None
        except Exception:
            app.logger.debug('load_user: models.usuario.Usuario não disponível ou falha ao carregar', exc_info=True)
            return None

    # ========================================================================
    # REGISTRO MANUAL DE BLUEPRINTS CRÍTICOS (antes do auto-discover)
    # ========================================================================
    # Blueprint TROCO PIX - Registrado manualmente para garantir carregamento
    try:
        app.logger.info("Tentando registrar blueprint troco_pix manualmente...")
        from routes.troco_pix import troco_pix_bp
        app.register_blueprint(troco_pix_bp)
        app.logger.info("✅ Blueprint troco_pix registrado com sucesso! URL: /troco_pix")
    except ImportError as e:
        app.logger.warning(f"Blueprint troco_pix não encontrado: {e}")
    except Exception as e:
        app.logger.error(f"Erro ao registrar blueprint troco_pix: {e}")
    # ========================================================================

    # Registrar automaticamente todos os blueprints dentro de routes/
    app.logger.info("="*60)
    app.logger.info("Iniciando registro automático de blueprints...")
    app.logger.info("="*60)
    register_blueprints_from_routes(app)
    app.logger.info("="*60)
    app.logger.info("Registro de blueprints concluído!")
    app.logger.info("="*60)

    # Registrar filtro e helpers de template
    app.jinja_env.filters['formatar_moeda'] = formatar_moeda

    @app.context_processor
    def inject_helpers():
        """
        Injetar variáveis úteis nos templates:
         - registered_blueprints: conjunto de nomes de blueprints registrados
         - formatar_moeda: função disponível diretamente se templates chamarem sem filtro
        """
        try:
            registered = set(app.blueprints.keys())
        except Exception:
            registered = set()
        return {
            'registered_blueprints': registered,
            'formatar_moeda': formatar_moeda
        }

    # Rota index simples: tenta redirecionar para fretes.lista se existir
    @app.route('/')
    def index():
        # se existir 'fretes.lista' redireciona, senão mostra mensagem padrão
        try:
            return redirect(url_for('fretes.lista'))
        except Exception:
            return "App funcionando - sem blueprint 'fretes' registrado."

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
