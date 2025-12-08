from datetime import datetime

from . import db  # importa o db do pacote models


class Fornecedor(db.Model):
    __tablename__ = "fornecedores"

    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(200), nullable=False)
    nome_fantasia = db.Column(db.String(200), nullable=True)
    cnpj = db.Column(db.String(18), nullable=True)
    ie = db.Column(db.String(20), nullable=True)
    endereco = db.Column(db.String(200), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    municipio = db.Column(db.String(100), nullable=True)
    uf = db.Column(db.String(2), nullable=True)
    cep = db.Column(db.String(10), nullable=True)
    nome_vendedor = db.Column(db.String(100), nullable=True)
    telefone = db.Column(db.String(15), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    data_cadastro = db.Column(
        db.DateTime,
        nullable=True,
        default=datetime.utcnow,
    )
    dados_bancarios = db.Column(db.Text, nullable=True)
    chave_pix = db.Column(db.String(100), nullable=True)
    tipo_pagamento_padrao = db.Column(db.String(20), nullable=True)

    def __repr__(self) -> str:
        return f"<Fornecedor {self.id} - {self.razao_social}>"
