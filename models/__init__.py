from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from models.usuario import Usuario
from models.rota import Rota
from models.motorista import Motorista
from models.fornecedor import Fornecedor  # nova model

__all__ = ['Usuario', 'Rota', 'Motorista', 'Fornecedor', 'db']
