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
from models.receita import Receita
from models.lancamento_receita import LancamentoReceita
from models.forma_pagamento_caixa import FormaPagamentoCaixa
from models.categoria_despesa import CategoriaDespesa
from models.subcategoria_despesa import SubcategoriaDespesa
from models.lancamento_caixa import LancamentoCaixa, LancamentoCaixaReceita, LancamentoCaixaComprovacao

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
    'Receita',
    'LancamentoReceita',
    'FormaPagamentoCaixa',
    'CategoriaDespesa',
    'SubcategoriaDespesa',
    'LancamentoCaixa',
    'LancamentoCaixaReceita',
    'LancamentoCaixaComprovacao',
    'db',
]
