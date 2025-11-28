from datetime import datetime
from . import db


class Base(db.Model):
    __tablename__ = "bases"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cidade = db.Column(db.String(100), nullable=True)
    observacao = db.Column(db.String(255), nullable=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Base {self.id} - {self.nome}>"
