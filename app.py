import os
import logging
from logging.handlers import RotatingFileHandler
import pkgutil
import importlib

from flask import Flask, render_template, redirect, url_for, current_app
from flask_login import LoginManager

def register_blueprints_from_routes(app):
    """
    Varre o pacote `routes` e tenta importar cada módulo.
    Se o módulo expuser `bp` ou qualquer atributo terminado em '_bp' (Blueprint) 
    ele é registrado automaticamente.
    Exceções de import são logadas para diagnóstico (não interrompem o registro).
    """
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

    # Registrar automaticamente todos os blueprints dentro de routes/
    register_blueprints_from_routes(app)

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
