# Importar os blueprints das rotas
from .clientes import bp as clientes_bp
from .motoristas import bp as motoristas_bp
from .veiculos import bp as veiculos_bp
from .fornecedores import bp as fornecedores_bp
from .fretes import bp as fretes_bp
from .relatorios import bp as relatorios_bp
from .rotas import bp as rotas_bp
from .origens_destinos import bp as origens_destinos_bp
from .quilometragem import bp as quilometragem_bp
from .produtos import bp as produtos_bp
from .arla import bp as arla_bp
from .pedidos import bp as pedidos_bp

# Aliases para compatibilidade com app.py
from . import clientes
from . import fornecedores
from . import veiculos
from . import motoristas
from . import fretes
from . import rotas
from . import origens_destinos
from . import quilometragem
from . import produtos
from . import relatorios
from . import arla
from . import pedidos
