"""
Models para o módulo Lucro Postos (FIFO por camadas de estoque).
Criado: 2026-03-14
"""
from datetime import datetime
from . import db


class FifoAbertura(db.Model):
    """Estoque inicial (abertura FIFO) por cliente+produto.
    Usada como base do 1º mês (ex: 01/01/2026).
    """
    __tablename__ = 'fifo_abertura'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    data_abertura = db.Column(db.Date, nullable=False)
    quantidade = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    custo_unitario = db.Column(db.Numeric(10, 4), nullable=False, default=0)
    observacao = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    criado_por = db.Column(db.Integer, nullable=True)
    atualizado_em = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    atualizado_por = db.Column(db.Integer, nullable=True)

    cliente = db.relationship('Cliente', backref='fifo_aberturas', lazy=True)
    produto = db.relationship('Produto', backref='fifo_aberturas', lazy=True)

    def __repr__(self):
        return f'<FifoAbertura cliente={self.cliente_id} produto={self.produto_id}>'


class FifoCompetencia(db.Model):
    """Controle de competência mensal por cliente (ABERTO / FECHADO)."""
    __tablename__ = 'fifo_competencia'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    ano_mes = db.Column(db.String(7), nullable=False)  # ex: '2026-01'
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum('ABERTO', 'FECHADO'), nullable=False, default='ABERTO')
    versao_atual = db.Column(db.Integer, nullable=False, default=1)
    fechado_em = db.Column(db.DateTime, nullable=True)
    fechado_por = db.Column(db.Integer, nullable=True)
    reaberto_em = db.Column(db.DateTime, nullable=True)
    reaberto_por = db.Column(db.Integer, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    cliente = db.relationship('Cliente', backref='fifo_competencias', lazy=True)
    snapshot_lotes = db.relationship('FifoSnapshotLote', backref='competencia', lazy=True)
    resumos = db.relationship('FifoResumoMensal', backref='competencia', lazy=True)

    def __repr__(self):
        return f'<FifoCompetencia cliente={self.cliente_id} {self.ano_mes} {self.status}>'


class FifoSnapshotLote(db.Model):
    """Camadas FIFO gravadas no momento do fechamento mensal.
    Preservadas para histórico; campo substituido=True indica que uma versão
    mais nova foi gerada (após reabertura e novo fechamento).
    """
    __tablename__ = 'fifo_snapshot_lotes'

    id = db.Column(db.Integer, primary_key=True)
    competencia_id = db.Column(db.Integer, db.ForeignKey('fifo_competencia.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    versao = db.Column(db.Integer, nullable=False, default=1)
    lote_ordem = db.Column(db.Integer, nullable=False)
    quantidade_restante = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    custo_unitario = db.Column(db.Numeric(10, 4), nullable=False, default=0)
    data_origem = db.Column(db.Date, nullable=True)
    substituido = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    produto = db.relationship('Produto', backref='fifo_snapshot_lotes', lazy=True)

    def __repr__(self):
        return f'<FifoSnapshotLote comp={self.competencia_id} prod={self.produto_id} ordem={self.lote_ordem}>'


class FifoResumoMensal(db.Model):
    """Resumo agregado por produto no fechamento mensal.
    Usado para exibição e exportação rápida de meses fechados.
    campo substituido=True indica versão invalidada por reabertura.
    """
    __tablename__ = 'fifo_resumo_mensal'

    id = db.Column(db.Integer, primary_key=True)
    competencia_id = db.Column(db.Integer, db.ForeignKey('fifo_competencia.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    versao = db.Column(db.Integer, nullable=False, default=1)
    qtde_entrada = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    custo_entrada_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    qtde_saida = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    receita_saida_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    cogs_fifo = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    lucro_bruto = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    estoque_final_qtde = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    estoque_final_valor = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    substituido = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    produto = db.relationship('Produto', backref='fifo_resumos', lazy=True)

    def __repr__(self):
        return f'<FifoResumoMensal comp={self.competencia_id} prod={self.produto_id}>'
