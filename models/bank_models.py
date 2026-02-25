from datetime import datetime

from . import db


class BankAccount(db.Model):
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    banco_nome = db.Column(db.String(100), nullable=False)
    agencia = db.Column(db.String(20), nullable=True)
    conta = db.Column(db.String(30), nullable=True)
    apelido = db.Column(db.String(100), nullable=True)
    ativo = db.Column(db.SmallInteger, nullable=False, default=1)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    transactions = db.relationship('BankTransaction', back_populates='account', lazy='dynamic')

    def __repr__(self):
        return f'<BankAccount {self.id} - {self.apelido or self.banco_nome}>'


class BankTransaction(db.Model):
    __tablename__ = 'bank_transactions'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id', ondelete='CASCADE'), nullable=False, index=True)
    hash_dedup = db.Column(db.String(64), nullable=False, unique=True)
    data_transacao = db.Column(db.Date, nullable=False, index=True)
    tipo = db.Column(db.Enum('DEBIT', 'CREDIT'), nullable=False)
    valor = db.Column(db.Numeric(15, 2), nullable=False)
    descricao = db.Column(db.String(500), nullable=True)
    cnpj_cpf = db.Column(db.String(18), nullable=True, index=True)
    memo = db.Column(db.String(500), nullable=True)
    fitid = db.Column(db.String(100), nullable=True)
    status = db.Column(db.Enum('pendente', 'conciliado', 'ignorado'), nullable=False, default='pendente', index=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id', ondelete='SET NULL'), nullable=True)
    conciliado_em = db.Column(db.DateTime, nullable=True)
    conciliado_por = db.Column(db.String(100), nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    account = db.relationship('BankAccount', back_populates='transactions')
    fornecedor = db.relationship('Fornecedor', foreign_keys=[fornecedor_id])

    def __repr__(self):
        return f'<BankTransaction {self.id} {self.tipo} {self.valor}>'


class BankSupplierMapping(db.Model):
    __tablename__ = 'bank_supplier_mapping'

    id = db.Column(db.Integer, primary_key=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id', ondelete='CASCADE'), nullable=False, index=True)
    cnpj_cpf = db.Column(db.String(18), nullable=False, unique=True, index=True)
    tipo_chave = db.Column(db.Enum('cnpj', 'cpf', 'texto'), nullable=False, default='cnpj')
    total_conciliacoes = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    fornecedor = db.relationship('Fornecedor', foreign_keys=[fornecedor_id])

    def __repr__(self):
        return f'<BankSupplierMapping {self.cnpj_cpf} → fornecedor {self.fornecedor_id}>'
