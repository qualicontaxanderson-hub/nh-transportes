from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user, login_required

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


def nivel_required(niveis_permitidos):
    """
    Decorator genérico para rotas que requerem níveis específicos
    
    Args:
        niveis_permitidos: lista de níveis permitidos (ex: ['ADMIN', 'GERENTE', 'SUPERVISOR'])
    
    Exemplo de uso:
        @bp.route('/exemplo')
        @login_required
        @nivel_required(['ADMIN', 'GERENTE', 'SUPERVISOR'])
        def exemplo():
            return "Acesso permitido"
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            import logging
            logger = logging.getLogger(__name__)
            
            # Verificar se o usuário está autenticado
            if not current_user.is_authenticated:
                flash('Você precisa estar logado para acessar esta página.', 'danger')
                return redirect(url_for('auth.login'))
            
            # Verificar se o atributo nivel existe
            if not hasattr(current_user, 'nivel'):
                logger.error(f"Usuário {current_user.username if hasattr(current_user, 'username') else 'desconhecido'} não tem atributo 'nivel'")
                flash('Você não tem permissão para acessar esta página.', 'danger')
                return redirect(url_for('index'))
            
            nivel = getattr(current_user, 'nivel', '').strip().upper()
            
            # Normalizar níveis permitidos
            niveis_norm = [n.strip().upper() for n in niveis_permitidos]
            
            # Aceitar variações de ADMIN
            if nivel.upper() in ['ADMIN', 'ADMINISTRADOR'] and 'ADMIN' in niveis_norm:
                return f(*args, **kwargs)
            
            # Verificar se nível do usuário está na lista permitida
            if nivel not in niveis_norm:
                logger.warning(f"Acesso negado para usuário {getattr(current_user, 'username', 'N/A')} com nivel='{nivel}'. Níveis permitidos: {niveis_permitidos}")
                flash(f'Você não tem permissão para acessar esta página. Requer: {", ".join(niveis_permitidos)}', 'danger')
                return redirect(url_for('index'))
            
            logger.info(f"Acesso permitido para {getattr(current_user, 'username', 'N/A')} (nivel={nivel})")
            return f(*args, **kwargs)
        return decorated_function
    return decorator
