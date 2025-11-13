from flask_login import UserMixin
from utils.db import get_db_connection
from werkzeug.security import check_password_hash

class Usuario(UserMixin):
    def __init__(self, id, username, nome_completo, nivel, ativo=True):
        self.id = id
        self.username = username
        self.nome_completo = nome_completo
        self.nivel = nivel
        self.ativo = ativo
    
    @staticmethod
    def get_by_id(user_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE id = %s AND ativo = TRUE", (user_id,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user_data:
            return Usuario(
                id=user_data['id'],
                username=user_data['username'],
                nome_completo=user_data['nome_completo'],
                nivel=user_data['nivel'],
                ativo=user_data['ativo']
            )
        return None
    
    @staticmethod
    def authenticate(username, password):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE username = %s AND ativo = TRUE", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            return Usuario(
                id=user_data['id'],
                username=user_data['username'],
                nome_completo=user_data['nome_completo'],
                nivel=user_data['nivel'],
                ativo=user_data['ativo']
            )
        return None
    
    def is_admin(self):
        return self.nivel == 'admin'
