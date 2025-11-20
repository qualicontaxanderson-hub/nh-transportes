from models import db
import datetime

class Produto(db.Model):
    __tablename__ = 'produto'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    descricao = db.Column(db.String(100))
    # Opcional: poderá adicionar outros campos no futuro (ex: ativo, tipo, etc.)

    def __repr__(self):
        return f'<Produto {self.nome}>'
