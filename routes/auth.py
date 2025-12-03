from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

# Model Usuario - existe em models/usuario.py
from models.usuario import Usuario

bp = Blueprint('auth', __name__, url_prefix='/auth')

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
