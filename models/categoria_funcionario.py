from models import db
import datetime

class CategoriaFuncionario(db.Model):
    __tablename__ = 'categoriasfuncionarios'
    
    id = db.Column(db.Integer, primary_key=True)
    clienteid = db.Column('clienteid', db.Integer, nullable=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.String(255), nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criadoem = db.Column('criadoem', db.DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return f'<CategoriaFuncionario {self.nome}>'
