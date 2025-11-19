from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


from models.usuario import Usuario

__all__ = ['Usuario, 'db'']
