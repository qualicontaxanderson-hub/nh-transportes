from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user

def admin_required(f):
    """
    Decorator para proteger rotas que requerem nível de administrador
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verifica se o usuário está autenticado
        if not current_user.is_authenticated:
            flash('Você precisa estar logado para acessar esta página.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Verifica se o usuário tem nível admin
        if not hasattr(current_user, 'nivel') or current_user.nivel != 'admin':
            flash('Acesso negado. Esta área é restrita a administradores.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function
