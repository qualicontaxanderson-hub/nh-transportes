"""
routes package initializer

- Expõe aliases (módulos) para compatibilidade com código que importa 'routes.clientes' etc.
- Fornece init_app(app) para registrar blueprints de forma tolerante/centralizada.
"""
import logging

logger = logging.getLogger(__name__)

# --- Safe import helper -----------------------------------------------------
def _safe_import_module(mod_name):
    """
    Importa dinamicamente um submódulo routes.<mod_name>.
    Retorna o módulo ou None em caso de erro.
    """
    try:
        module = __import__(f"{__name__}.{mod_name}", fromlist=[mod_name])
        return module
    except Exception as exc:
        logger.warning("Falha ao importar routes.%s: %s", mod_name, exc)
        return None

def _safe_get_bp(module, attr='bp'):
    if not module:
        return None
    bp = getattr(module, attr, None)
    if bp is None:
        logger.debug("Modulo routes.%s importado mas sem atributo '%s'", module.__name__, attr)
    return bp

# --- Importar módulos e blueprints (tolerante) -----------------------------
_clientes_mod = _safe_import_module('clientes')
_motoristas_mod = _safe_import_module('motoristas')
_veiculos_mod = _safe_import_module('veiculos')
_fornecedores_mod = _safe_import_module('fornecedores')
_fretes_mod = _safe_import_module('fretes')
_relatorios_mod = _safe_import_module('relatorios')
_rotas_mod = _safe_import_module('rotas')
_origens_destinos_mod = _safe_import_module('origens_destinos')
_quilometragem_mod = _safe_import_module('quilometragem')
_produtos_mod = _safe_import_module('produtos')
_arla_mod = _safe_import_module('arla')
_pedidos_mod = _safe_import_module('pedidos')

# blueprint objects (or None)
clientes_bp = _safe_get_bp(_clientes_mod)
motoristas_bp = _safe_get_bp(_motoristas_mod)
veiculos_bp = _safe_get_bp(_veiculos_mod)
fornecedores_bp = _safe_get_bp(_fornecedores_mod)
fretes_bp = _safe_get_bp(_fretes_mod)
relatorios_bp = _safe_get_bp(_relatorios_mod)
rotas_bp = _safe_get_bp(_rotas_mod)
origens_destinos_bp = _safe_get_bp(_origens_destinos_mod)
quilometragem_bp = _safe_get_bp(_quilometragem_mod)
produtos_bp = _safe_get_bp(_produtos_mod)
arla_bp = _safe_get_bp(_arla_mod)
pedidos_bp = _safe_get_bp(_pedidos_mod)

# --- Aliases para compatibilidade com import direto de módulos -------------
# Mantém: from routes import clientes, pedidos, ...
clientes = _clientes_mod
fornecedores = _fornecedores_mod
veiculos = _veiculos_mod
motoristas = _motoristas_mod
fretes = _fretes_mod
rotas = _rotas_mod
origens_destinos = _origens_destinos_mod
quilometragem = _quilometragem_mod
produtos = _produtos_mod
relatorios = _relatorios_mod
arla = _arla_mod
pedidos = _pedidos_mod

# --- Função de registro central --------------------------------------------
def init_app(app):
    """
    Registra todos os blueprints disponíveis (de forma tolerante).
    Chamar routes.init_app(app) no momento de criação da Flask app.
    """
    # coletar blueprints presentes
    bps = [
        clientes_bp, fornecedores_bp, veiculos_bp, motoristas_bp,
        fretes_bp, relatorios_bp, rotas_bp, origens_destinos_bp,
        quilometragem_bp, produtos_bp, arla_bp, pedidos_bp
    ]
    # evitar double-register
    registered = set(app.blueprints.keys())
    for bp in bps:
        if not bp:
            continue
        try:
            if bp.name not in registered:
                app.register_blueprint(bp)
                logger.info("Blueprint registrado: %s", bp.name)
            else:
                logger.debug("Blueprint já registrado: %s", bp.name)
        except Exception as exc:
            logger.exception("Erro ao registrar blueprint %s: %s", getattr(bp, 'name', str(bp)), exc)

# lista pública
__all__ = [
    'init_app',
    # blueprints
    'clientes_bp', 'motoristas_bp', 'veiculos_bp', 'fornecedores_bp',
    'fretes_bp', 'relatorios_bp', 'rotas_bp', 'origens_destinos_bp',
    'quilometragem_bp', 'produtos_bp', 'arla_bp', 'pedidos_bp',
    # module aliases
    'clientes', 'fornecedores', 'veiculos', 'motoristas', 'fretes',
    'rotas', 'origens_destinos', 'quilometragem', 'produtos', 'relatorios',
    'arla', 'pedidos'
]
