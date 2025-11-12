import os

class Config:
    DB_HOST = "centerbeam.proxy.rlwy.net"
    DB_PORT = 56026
    DB_USER = "root"
    DB_PASSWORD = "CYTzzRYLVmEJGDexxXpgepWgpvebdSrV"
    DB_NAME = "railway"
    SECRET_KEY = os.environ.get('SECRET_KEY') or "nh-transportes-2025-secret"
    APP_NAME = "NH Transportes"
    DEBUG = False  # Mudei para False em produção
    ITEMS_PER_PAGE = 20
