from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from functools import wraps
from utils.db import get_db_connection

# Model Usuario - existe em models/usuario.py
from models.usuario import Usuario

bp = Blueprint('auth', __name__, url_prefix='/auth')

def admin_required(f):
    """Decorator para rotas que requerem nível ADMIN"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.nivel != 'ADMIN':
            flash('Você não tem permissão para acessar esta página.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Login simples: tenta autenticar usando Usuario.authenticate(username, password).
    Se existir um template 'auth/login.html' será renderizado; caso contrário, faz fallback.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = None
        try:
            user = Usuario.authenticate(username, password)
        except Exception:
            flash('Erro de autenticação.', 'danger')
        if user:
            login_user(user)
            flash('Autenticado com sucesso.', 'success')
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)
        else:
            flash('Usuário ou senha inválidos.', 'danger')

    # GET: renderiza template se existir, senão retorna uma página simples
    try:
        return render_template('auth/login.html')
    except Exception:
        return """
        <h3>Login</h3>
        <form method="post">
            <label>Usuário: <input name="username"></label><br>
            <label>Senha: <input type="password" name="password"></label><br>
            <button type="submit">Entrar</button>
        </form>
        """

@bp.route('/logout')
@login_required
def logout():
    """
    Logout: desconecta o usuário e redireciona para a página de login do blueprint auth.
    Endpoint: 'auth.logout' (use {{ url_for('auth.logout') }} no template).
    """
    logout_user()
    flash('Você saiu.', 'info')
    return redirect(url_for('auth.login'))

# === GESTÃO DE USUÁRIOS (apenas ADMIN) ===

@bp.route('/usuarios')
@admin_required
def listar_usuarios():
    """Lista todos os usuários do sistema"""
    usuarios = Usuario.listar_todos(incluir_inativos=True)
    return render_template('auth/usuarios/listar.html', usuarios=usuarios)

@bp.route('/usuarios/novo', methods=['GET', 'POST'])
@admin_required
def criar_usuario():
    """Cria novo usuário no sistema"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        nome_completo = request.form.get('nome_completo', '').strip()
        nivel = request.form.get('nivel', 'PISTA')
        cliente_id = request.form.get('cliente_id')
        senha = request.form.get('senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        # Validações
        if not username or not nome_completo or not senha:
            flash('Todos os campos obrigatórios devem ser preenchidos.', 'danger')
        elif Usuario.username_existe(username):
            flash('Este nome de usuário já existe.', 'danger')
        elif senha != confirmar_senha:
            flash('As senhas não coincidem.', 'danger')
        elif nivel == 'PISTA' and not cliente_id:
            flash('Usuários PISTA devem ter um posto/cliente associado.', 'danger')
        else:
            try:
                # Se não é PISTA, cliente_id deve ser None
                if nivel != 'PISTA':
                    cliente_id = None
                
                Usuario.criar_usuario(username, nome_completo, nivel, senha, cliente_id)
                flash(f'Usuário {username} criado com sucesso!', 'success')
                return redirect(url_for('auth.listar_usuarios'))
            except Exception as e:
                flash(f'Erro ao criar usuário: {str(e)}', 'danger')
    
    # Buscar lista de clientes para o dropdown
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, razao_social FROM clientes WHERE ativo = 1 ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('auth/usuarios/novo.html', clientes=clientes)

@bp.route('/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
@admin_required
def editar_usuario(user_id):
    """Edita um usuário existente"""
    user_data = Usuario.get_by_id_completo(user_id)
    if not user_data:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('auth.listar_usuarios'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        nome_completo = request.form.get('nome_completo', '').strip()
        nivel = request.form.get('nivel', 'PISTA')
        cliente_id = request.form.get('cliente_id')
        senha = request.form.get('senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        # Validações
        if not username or not nome_completo:
            flash('Usuário e nome completo são obrigatórios.', 'danger')
        elif Usuario.username_existe(username, excluir_id=user_id):
            flash('Este nome de usuário já existe.', 'danger')
        elif nivel == 'PISTA' and not cliente_id:
            flash('Usuários PISTA devem ter um posto/cliente associado.', 'danger')
        elif senha and senha != confirmar_senha:
            flash('As senhas não coincidem.', 'danger')
        else:
            try:
                # Se não é PISTA, cliente_id deve ser None
                if nivel != 'PISTA':
                    cliente_id = None
                
                user = Usuario.get_by_id(user_id)
                if user:
                    user.atualizar(username=username, nome_completo=nome_completo, 
                                 nivel=nivel, cliente_id=cliente_id)
                    
                    # Se forneceu senha, atualiza
                    if senha:
                        user.alterar_senha(senha)
                    
                    flash(f'Usuário {username} atualizado com sucesso!', 'success')
                    return redirect(url_for('auth.listar_usuarios'))
            except Exception as e:
                flash(f'Erro ao atualizar usuário: {str(e)}', 'danger')
    
    # Buscar lista de clientes para o dropdown
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, razao_social FROM clientes WHERE ativo = 1 ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('auth/usuarios/editar.html', usuario=user_data, clientes=clientes)

@bp.route('/usuarios/<int:user_id>/desativar', methods=['POST'])
@admin_required
def desativar_usuario(user_id):
    """Desativa um usuário"""
    if user_id == current_user.id:
        flash('Você não pode desativar seu próprio usuário.', 'danger')
    else:
        user = Usuario.get_by_id(user_id)
        if user:
            user.desativar()
            flash(f'Usuário {user.username} desativado com sucesso.', 'success')
        else:
            flash('Usuário não encontrado.', 'danger')
    return redirect(url_for('auth.listar_usuarios'))

@bp.route('/usuarios/<int:user_id>/ativar', methods=['POST'])
@admin_required
def ativar_usuario(user_id):
    """Ativa um usuário"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET ativo = TRUE WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    flash('Usuário ativado com sucesso.', 'success')
    return redirect(url_for('auth.listar_usuarios'))

# === PERFIL E CONFIGURAÇÕES (todos os usuários) ===

@bp.route('/perfil')
@login_required
def perfil():
    """Página de perfil do usuário logado"""
    user_data = Usuario.get_by_id_completo(current_user.id)
    return render_template('auth/perfil.html', usuario=user_data)

@bp.route('/alterar-senha', methods=['GET', 'POST'])
@login_required
def alterar_senha():
    """Permite ao usuário alterar sua própria senha"""
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual')
        nova_senha = request.form.get('nova_senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        if not senha_atual or not nova_senha or not confirmar_senha:
            flash('Todos os campos são obrigatórios.', 'danger')
        elif not current_user.check_password(senha_atual):
            flash('Senha atual incorreta.', 'danger')
        elif nova_senha != confirmar_senha:
            flash('As novas senhas não coincidem.', 'danger')
        elif len(nova_senha) < 4:
            flash('A senha deve ter pelo menos 4 caracteres.', 'danger')
        else:
            try:
                current_user.alterar_senha(nova_senha)
                flash('Senha alterada com sucesso!', 'success')
                return redirect(url_for('auth.perfil'))
            except Exception as e:
                flash(f'Erro ao alterar senha: {str(e)}', 'danger')
    
    return render_template('auth/alterar_senha.html')
