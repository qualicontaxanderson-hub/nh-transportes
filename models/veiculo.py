from . import db


class Veiculo(db.Model):
    __tablename__ = "veiculos"

    id = db.Column(db.Integer, primary_key=True)
    caminhao = db.Column(db.String(20), nullable=False)
    placa = db.Column(db.String(10), nullable=False)
    modelo = db.Column(db.String(30), nullable=True)
    ativo = db.Column(db.Boolean, nullable=True, default=True)

    def __repr__(self) -> str:
        return f"<Veiculo {self.id} - {self.placa}>"
