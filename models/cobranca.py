from datetime import datetime
from . import db


class Cobranca(db.Model):
    """Modelo para cobranças (PIX/Boleto) via EFI Bank"""
    __tablename__ = "cobrancas"

    id = db.Column(db.Integer, primary_key=True)

    # Relacionamentos
    frete_id = db.Column(db.Integer, nullable=True)
    cliente_id = db.Column(db.Integer, nullable=True)

    # Dados do pagador
    pagador_nome = db.Column(db.String(200), nullable=False)
    pagador_cpf_cnpj = db.Column(db.String(18), nullable=False)
    pagador_email = db.Column(db.String(100), nullable=True)
    pagador_telefone = db.Column(db.String(20), nullable=True)
    pagador_endereco = db.Column(db.String(255), nullable=True)
    pagador_cidade = db.Column(db.String(100), nullable=True)
    pagador_uf = db.Column(db.String(2), nullable=True)
    pagador_cep = db.Column(db.String(10), nullable=True)

    # Dados da cobrança
    tipo = db.Column(db.String(10), nullable=False, default='pix')
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    descricao = db.Column(db.String(255), nullable=False)

    # Dados EFI - PIX
    txid = db.Column(db.String(35), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    qrcode_base64 = db.Column(db.Text, nullable=True)
    pix_copia_cola = db.Column(db.Text, nullable=True)

    # Dados EFI - Boleto
    nosso_numero = db.Column(db.String(20), nullable=True)
    codigo_barras = db.Column(db.String(60), nullable=True)
    linha_digitavel = db.Column(db.String(60), nullable=True)
    link_boleto = db.Column(db.String(255), nullable=True)

    # Controle
    status = db.Column(db.String(20), nullable=False, default='pendente')
    data_vencimento = db.Column(db.Date, nullable=True)
    data_pagamento = db.Column(db.DateTime, nullable=True)
    valor_pago = db.Column(db.Numeric(10, 2), nullable=True)

    # Resposta da API
    efi_response = db.Column(db.JSON, nullable=True)
    mensagem_erro = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Cobranca {self.id} - {self.tipo} - R${self.valor}>"


class EfiConfig(db.Model):
    """Modelo para configuração da API EFI Bank"""
    __tablename__ = "efi_config"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(100), nullable=False)
    client_secret = db.Column(db.String(255), nullable=False)
    certificado_pem = db.Column(db.Text, nullable=True)
    chave_pix = db.Column(db.String(100), nullable=True)
    ambiente = db.Column(db.String(10), nullable=False, default='sandbox')
    webhook_url = db.Column(db.String(255), nullable=True)
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<EfiConfig {self.id} - {self.ambiente}>"
