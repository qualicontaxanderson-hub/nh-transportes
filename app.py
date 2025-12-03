import os
import difflib

from flask import Flask, render_template, redirect, url_for, request, flash, current_app, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from werkzeug.routing import BuildError

# Try to import project-specific modules; if missing, keep None to avoid crash on import
try:
    from utils.db import get_db_connection
except Exception:
    get_db_connection = None

try:
    from models.usuario import Usuario
except Exception:
    Usuario = None

# >>> IMPORTAR formatar_moeda <<<
try:
    from utils.formatadores import formatar_moeda
except Exception:
    formatar_moeda = None

# Create app early so decorators/context processors can reference it
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-prod")

# Se a função existir, registra no Jinja
if formatar_moeda is not None:
    app.jinja_env.globals['formatar_moeda'] = formatar_moeda

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = None

if Usuario is not None:
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return Usuario.get_by_id(int(user_id))
        except Exception:
            return None
else:
    @login_manager.user_loader
    def load_user(user_id):
        return None

# Defensive import of blueprints: try to import modules under routes and register bp if present.
# This avoids app failing to start if a single routes module has an import-time error.
blueprints_to_try = [
    "clientes",
    "fornecedores",
    "veiculos",
    "motoristas",
    "fretes",
    "rotas",
    "origens_destinos",
    "quilometragem",
    "produtos",
    "relatorios",
    "arla",
    "pedidos",
    "bases",
]

import importlib

registered_modules = {}
for name in blueprints_to_try:
    try:
        mod = importlib.import_module(f"routes.{name}")
        registered_modules[name] = mod
    except Exception as e:
        app.logger.warning(f"Could not import routes.{name}: {e}")
        registered_modules[name] = None

# Register any blueprint objects named 'bp' in the imported modules
for name, mod in registered_modules.items():
    try:
        if mod and hasattr(mod, "bp"):
            app.register_blueprint(getattr(mod, "bp"))
            app.logger.debug(f"Registered blueprint: {name}")
        else:
            app.logger.debug(f"Blueprint routes.{name} not registered (module missing or no attribute 'bp').")
    except Exception as e:
        app.logger.exception(f"Error registering blueprint routes.{name}: {e}")

# ---- Robust url_for wrapper to avoid BuildError in templates ----
# We import the real flask url_for under a different name so we can call it here.
from flask import url_for as flask_url_for

def robust_url_for(endpoint, **values):
    """
    Try normal url_for(endpoint, **values). If it raises BuildError,
    try to find a close endpoint name among registered endpoints and use it.
    If nothing works, return '#' (so templates don't raise 500).
    """
    try:
        return flask_url_for(endpoint, **values)
    except BuildError:
        # collect available endpoints
        try:
            endpoints = sorted({r.endpoint for r in current_app.url_map.iter_rules()})
        except Exception:
            endpoints = []
        # try to find close matches
        matches = difflib.get_close_matches(endpoint, endpoints, n=1, cutoff=0.6)
        if matches:
            try:
                return flask_url_for(matches[0], **values)
            except Exception:
                pass
        # as a last fallback, return '#' so link is inert instead of crashing
        return "#"

# override Jinja's url_for global so templates calling url_for(...) use robust_url_for
app.jinja_env.globals['url_for'] = robust_url_for

# -----------------------------------------------------------------

# Context processor: list registered blueprints
@app.context_processor
def inject_registered_blueprints():
    try:
        keys = list(current_app.blueprints.keys())
    except Exception:
        keys = []
    return dict(registered_blueprints=keys)

# Context processor: safe_url_for to try multiple endpoints/param names in templates
@app.context_processor
def inject_helpers():
    def safe_url_for(candidates, **kwargs):
        """
        candidates: list of endpoint strings to try (e.g. ['fretes.importar_pedido','pedidos.importar_pedido'])
        kwargs: possible parameters (e.g. pedido_id=..., id=...)
        Returns first valid url or '#' if none works.
        """
        try:
            for ep in candidates:
                rules = [r for r in current_app.url_map.iter_rules() if r.endpoint == ep]
                if not rules:
                    continue
                rule = rules[0]
                expected = set(rule.arguments or [])
                # If rule expects args but kwargs don't contain them all, skip
                if expected and not expected.issubset(set(kwargs.keys())):
                    continue
                args = {k: v for k, v in kwargs.items() if k in expected}
                try:
                    # If rule expects no args, call without args
                    if not expected:
                        return flask_url_for(ep)
                    return flask_url_for(ep, **args)
                except Exception:
                    continue
        except Exception:
            pass
        return "#"

    return dict(safe_url_for=safe_url_for)

# Health check
@app.route("/health")
def health():
    return jsonify(status="ok")

# Dashboard / index
@app.route("/")
@login_required
def index():
    # Try to fetch some counters if DB helper exists; otherwise render without counts
    stats = {}
    if get_db_connection:
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            for tbl in ("clientes", "fornecedores", "veiculos", "motoristas", "fretes", "pedidos"):
                try:
                    cursor.execute(f"SELECT COUNT(*) as total FROM {tbl}")
                    stats[f"total_{tbl}"] = cursor.fetchone().get("total", 0)
                except Exception:
                    stats[f"total_{tbl}"] = None
        except Exception as e:
            app.logger.warning(f"Could not load dashboard stats: {e}")
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    return render_template("dashboard.html", stats=stats)

# Auth routes (safe if Usuario missing)
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if Usuario is None:
            flash("Módulo de usuário não disponível. Consulte os logs.", "danger")
            return render_template("login.html")

        try:
            user = Usuario.authenticate(username, password)
            if user:
                login_user(user)
                next_page = request.args.get("next")
                return redirect(next_page or url_for("index"))
            else:
                flash("Usuário ou senha inválidos.", "danger")
        except Exception as e:
            app.logger.exception("Erro no login: %s", e)
            flash("Erro ao autenticar. Veja os logs.", "danger")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# Minimal error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    app.logger.exception("Internal server error: %s", e)
    return render_template("500.html"), 500

if __name__ == "__main__":
    # Only for local development
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
