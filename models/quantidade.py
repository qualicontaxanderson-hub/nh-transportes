from models.base import db, datetime


class Quantidade(db.Model):
    __tablename__ = 'quantidades'
    
    id = db.Column(db.Integer, primary_key=True)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    descricao = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Quantidade {self.valor}>'
