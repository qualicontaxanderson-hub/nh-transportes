from models import db
import datetime

class Funcionario(db.Model):
    __tablename__ = 'funcionarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    cliente_id = db.Column(db.Integer, nullable=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_funcionarios.id'), nullable=True)
    cpf = db.Column(db.String(14), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    cargo = db.Column(db.String(100), nullable=True)
    data_admissao = db.Column(db.Date, nullable=True)
    data_saida = db.Column(db.Date, nullable=True)
    salario_base = db.Column(db.Numeric(12, 2), nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationship
    categoria = db.relationship('CategoriaFuncionario', backref='funcionarios')
    
    def __repr__(self):
        return f'<Funcionario {self.nome}>'
