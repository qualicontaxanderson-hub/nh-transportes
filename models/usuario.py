from flask_login import UserMixin
from utils.db import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash

class Usuario(UserMixin):
    def __init__(self, id, username, nome_completo, nivel, ativo=True, senha_hash=None):
        self.id = id
        self.username = username
        self.nome_completo = nome_completo
        self.nome = nome_completo  # Alias para compatibilidade
        self.nivel = nivel
        self.ativo = ativo
        self.senha_hash = senha_hash
        self.password = senha_hash  # Alias para compatibilidade
        self.email = ''  # Campo vazio para compatibilidade

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
    def get_by_username(username):
        """Método adicionado para compatibilidade com app.py"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE username = %s AND ativo = TRUE", (username,))
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
        self.senha_hash = novo_hash
        self.password = novo_hash

    @staticmethod
    def criar_usuario(username, nome_completo, nivel, senha, cliente_id=None):
        conn = get_db_connection()
        cursor = conn.cursor()
        senha_hash = generate_password_hash(senha)
        cursor.execute(
            "INSERT INTO usuarios (username, nome_completo, nivel, ativo, password_hash, cliente_id) VALUES (%s, %s, %s, true, %s, %s)",
            (username, nome_completo, nivel, senha_hash, cliente_id)
        )
        user_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return user_id

    @staticmethod
    def listar_todos(incluir_inativos=True):
        """Lista todos os usuários do sistema"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if incluir_inativos:
            query = """
                SELECT u.*, c.razao_social as cliente_nome
                FROM usuarios u
                LEFT JOIN clientes c ON u.cliente_id = c.id
                ORDER BY u.ativo DESC, u.nome_completo
            """
        else:
            query = """
                SELECT u.*, c.razao_social as cliente_nome
                FROM usuarios u
                LEFT JOIN clientes c ON u.cliente_id = c.id
                WHERE u.ativo = TRUE
                ORDER BY u.nome_completo
            """
        cursor.execute(query)
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return users

    @staticmethod
    def get_by_id_completo(user_id):
        """Busca usuário com informações completas incluindo cliente"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Tentar query com cliente_id primeiro
            try:
                cursor.execute("""
                    SELECT u.*, c.razao_social as cliente_nome
                    FROM usuarios u
                    LEFT JOIN clientes c ON u.cliente_id = c.id
                    WHERE u.id = %s
                """, (user_id,))
            except Exception as e:
                # Se falhar (campo cliente_id não existe), tentar sem ele
                logger.warning(f"Campo cliente_id não existe, buscando sem ele: {str(e)}")
                cursor.execute("""
                    SELECT u.*, NULL as cliente_nome
                    FROM usuarios u
                    WHERE u.id = %s
                """, (user_id,))
            
            user_data = cursor.fetchone()
            cursor.close()
            conn.close()
            return user_data
        except Exception as e:
            logger.error(f"Erro ao buscar usuário completo {user_id}: {str(e)}")
            return None

    def atualizar(self, username=None, nome_completo=None, nivel=None, cliente_id=None):
        """Atualiza os dados do usuário"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if username is not None:
            updates.append("username = %s")
            params.append(username)
            self.username = username
        
        if nome_completo is not None:
            updates.append("nome_completo = %s")
            params.append(nome_completo)
            self.nome_completo = nome_completo
            self.nome = nome_completo
        
        if nivel is not None:
            updates.append("nivel = %s")
            params.append(nivel)
            self.nivel = nivel
        
        if cliente_id is not None or cliente_id == '':
            updates.append("cliente_id = %s")
            params.append(cliente_id if cliente_id else None)
        
        if updates:
            params.append(self.id)
            query = f"UPDATE usuarios SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)
            conn.commit()
        
        cursor.close()
        conn.close()

    def desativar(self):
        """Desativa o usuário"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET ativo = FALSE WHERE id = %s", (self.id,))
        conn.commit()
        cursor.close()
        conn.close()
        self.ativo = False

    def ativar(self):
        """Ativa o usuário"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET ativo = TRUE WHERE id = %s", (self.id,))
        conn.commit()
        cursor.close()
        conn.close()
        self.ativo = True

    @staticmethod
    def username_existe(username, excluir_id=None):
        """Verifica se um username já existe (útil para validação)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        if excluir_id:
            cursor.execute("SELECT id FROM usuarios WHERE username = %s AND id != %s", (username, excluir_id))
        else:
            cursor.execute("SELECT id FROM usuarios WHERE username = %s", (username,))
        existe = cursor.fetchone() is not None
        cursor.close()
        conn.close()
        return existe
