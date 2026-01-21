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
from models.base import Base
from models.produto import Produto
from models.cliente_produto import ClienteProduto
from models.vendas_posto import VendasPosto
from models.bandeira_cartao import BandeiraCartao

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
    'Base',
    'Produto',
    'ClienteProduto',
    'VendasPosto',
    'BandeiraCartao',
    'db',
]
