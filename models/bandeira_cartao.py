from . import db


class BandeiraCartao(db.Model):
    __tablename__ = "bandeiras_cartao"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # DEBITO or CREDITO
    ativo = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<BandeiraCartao {self.id} - {self.nome} {self.tipo}>"
