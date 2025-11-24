from flask_login import UserMixin
from utils.db import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash

class Usuario(UserMixin):
    def __init__(self, id, username, nome_completo, nivel, ativo=True, senha_hash=None):
        self.id = id
        self.username = username
        self.nome_completo = nome_completo
        self.nivel = nivel
        self.ativo = ativo
        self.senha_hash = senha_hash

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
                ativo=user_data['ativo'],
                senha_hash=user_data['password_hash']
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
                ativo=user_data['ativo'],
                senha_hash=user_data['password_hash']
            )
        return None

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)

    def alterar_senha(self, nova_senha):
        conn = get_db_connection()
        cursor = conn.cursor()
        novo_hash = generate_password_hash(nova_senha)
        cursor.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s", (novo_hash, self.id))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def criar_usuario(username, nome_completo, nivel, senha):
        conn = get_db_connection()
        cursor = conn.cursor()
        senha_hash = generate_password_hash(senha)
        cursor.execute(
            "INSERT INTO usuarios (username, nome_completo, nivel, ativo, password_hash) VALUES (%s, %s, %s, true, %s)",
            (username, nome_completo, nivel, senha_hash)
        )
        conn.commit()
        cursor.close()
        conn.close()
