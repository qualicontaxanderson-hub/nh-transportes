from models import db
import datetime

class Motorista(db.Model):
    __tablename__ = 'motoristas'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=True)
    cnh = db.Column(db.String(12), unique=True, nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    observacoes = db.Column(db.Text, nullable=True)
    paga_comissao = db.Column(db.Boolean, default=True)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return f'<Motorista {self.nome}>'
