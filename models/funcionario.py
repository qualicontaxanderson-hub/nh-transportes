from models import db
import datetime

class Funcionario(db.Model):
    __tablename__ = 'funcionarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    clienteid = db.Column('clienteid', db.Integer, nullable=True)
    categoriaid = db.Column('categoriaid', db.Integer, db.ForeignKey('categoriasfuncionarios.id'), nullable=True)
    cpf = db.Column(db.String(14), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    cargo = db.Column(db.String(100), nullable=True)
    data_admissao = db.Column(db.Date, nullable=True)
    data_saida = db.Column(db.Date, nullable=True)
    salario_base = db.Column(db.Numeric(12, 2), nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criadoem = db.Column('criadoem', db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationship
    categoria = db.relationship('CategoriaFuncionario', backref='funcionarios')
    
    def __repr__(self):
        return f'<Funcionario {self.nome}>'
