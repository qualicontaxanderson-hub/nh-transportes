from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from models.usuario import Usuario
from models.rota import Rota
from models.motorista import Motorista
from models.fornecedor import Fornecedor
from models.pedido import Pedido
from models.pedido_item import PedidoItem
from models.cliente import Cliente
from models.veiculo import Veiculo
from models.frete import Frete

__all__ = [
    'Usuario',
    'Rota',
    'Motorista',
    'Fornecedor',
    'Pedido',
    'PedidoItem',
    'Cliente',
    'Veiculo',
    'Frete',
    'db',
]
