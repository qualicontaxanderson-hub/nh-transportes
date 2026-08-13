import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env (se existir)
load_dotenv()

# Importado DEPOIS do load_dotenv(): db_credentials lê os.environ no import.
from utils import db_credentials

class Config:
    # Configurações do Banco de Dados
    # Usa variáveis de ambiente se disponíveis, caso contrário usa valores padrão
    # Valores vindos de utils/db_credentials: fonte UNICA, compartilhada com os
    # scripts de captura de DFe. DB_PASSWORD nao tem valor padrao de proposito --
    # um fallback com senha antiga esconde rotacoes de senha (incidente 27/07).
    DB_HOST = db_credentials.DB_HOST
    DB_PORT = db_credentials.DB_PORT
    DB_USER = db_credentials.DB_USER
    DB_PASSWORD = db_credentials.DB_PASSWORD
    DB_NAME = db_credentials.DB_NAME
    
    # Configurações de Pool de Conexões
    DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', 10))  # Número máximo de conexões no pool
    DB_CONNECT_TIMEOUT = int(os.environ.get('DB_CONNECT_TIMEOUT', 10))  # Timeout de conexão em segundos
    
    # URI do Banco de Dados
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    
    # Chave Secreta — obrigatória via variável de ambiente, sem fallback
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError(
            "A variável de ambiente SECRET_KEY não está definida. "
            "Gere um valor seguro com: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "e configure-o no ambiente antes de iniciar o app."
        )
    
    # Configurações da Aplicação
    APP_NAME = "NH Transportes"
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
    ITEMS_PER_PAGE = 20

    # CSRF (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 28800  # 8 horas — evita expiração em sessões longas

    # Pasta de entrada para arquivos OFX (watch-folder)
    # Configure OFX_INBOX_DIR no ambiente para apontar para qualquer pasta acessível ao servidor.
    # Padrão: /tmp/ofx_inbox  (sempre gravável no Railway/Docker)
    #
    # Exemplo Windows/Dropbox (executando localmente):
    #   OFX_INBOX_DIR=C:\Users\User\Dropbox\BANCOS\OFX\NOVO
    #   OFX_PROCESSED_DIR=C:\Users\User\Dropbox\BANCOS\OFX\IMPORTADOS
    OFX_INBOX_DIR = os.environ.get(
        'OFX_INBOX_DIR',
        '/tmp/ofx_inbox'
    )

    # Pasta de destino para arquivos OFX já importados.
    # Padrão: <OFX_INBOX_DIR>/processados/
    OFX_PROCESSED_DIR = os.environ.get(
        'OFX_PROCESSED_DIR',
        None  # None = usa <OFX_INBOX_DIR>/processados/ (resolvido em runtime)
    )
