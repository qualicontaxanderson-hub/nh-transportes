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


def supervisor_or_admin_required(f):
    """
    Decorator para proteger rotas que requerem nível SUPERVISOR ou ADMIN
    Usado para as seções que SUPERVISOR tem acesso pleno
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verifica se o usuário está autenticado
        if not current_user.is_authenticated:
            flash('Você precisa estar logado para acessar esta página.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Verifica se o usuário tem nível admin ou supervisor
        if not hasattr(current_user, 'nivel'):
            flash('Acesso negado. Você não tem permissão para acessar esta página.', 'danger')
            return redirect(url_for('index'))
        
        nivel = current_user.nivel.strip().upper()
        
        # Permitir ADMIN (e variações) ou SUPERVISOR
        if nivel not in ['ADMIN', 'ADMINISTRADOR', 'SUPERVISOR']:
            flash('Acesso negado. Esta área requer nível SUPERVISOR ou superior.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function
