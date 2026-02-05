from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from functools import wraps
from utils.db import get_db_connection
import logging

# Model Usuario - existe em models/usuario.py
from models.usuario import Usuario

# Configurar logger
logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__, url_prefix='/auth')

def admin_required(f):
    """Decorator para rotas que requerem nível ADMIN"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        
        # Verificar se o atributo nivel existe
        if not hasattr(current_user, 'nivel'):
            logger.error(f"Usuário {current_user.username if hasattr(current_user, 'username') else 'desconhecido'} não tem atributo 'nivel'")
            flash('Você não tem permissão para acessar esta página.', 'danger')
            return redirect(url_for('index'))
        
        # Aceitar tanto "ADMIN" quanto "Administrador" (compatibilidade)
        nivel = getattr(current_user, 'nivel', '')
        nivel_stripped = nivel.strip() if isinstance(nivel, str) else str(nivel)
        
        # Log detalhado para debug (simplificado para evitar erros de formatação)
        username = getattr(current_user, 'username', 'N/A')
        print(f"[DEBUG ADMIN] Usuario: {username}, Nivel: {nivel}, Stripped: {nivel_stripped}")
        logger.info(f"Verificação admin_required: usuário={username}, nivel='{nivel}', stripped='{nivel_stripped}'")
        
        # Aceitar variações comuns (case-insensitive e com trim) - APENAS ADMIN tem acesso total
        niveis_aceitos = ['ADMIN', 'Administrador', 'admin', 'administrador']
        if nivel_stripped not in niveis_aceitos:
            logger.warning(f"Acesso negado para usuário {getattr(current_user, 'username', 'N/A')} com nivel='{nivel}' (stripped='{nivel_stripped}')")
            flash('Você não tem permissão para acessar esta página. Apenas ADMIN tem acesso.', 'danger')
            return redirect(url_for('index'))
        
        logger.info(f"Acesso permitido para {getattr(current_user, 'username', 'N/A')}")
        return f(*args, **kwargs)
    return decorated_function

def nivel_required(niveis_permitidos):
    """Decorator genérico para rotas que requerem níveis específicos
    
    Args:
        niveis_permitidos: lista de níveis permitidos (ex: ['ADMIN', 'GERENTE'])
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            import logging
            logger = logging.getLogger(__name__)
            
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
            
            # Redirecionar usuários conforme o nível
            nivel = getattr(user, 'nivel', '').strip().upper()
            
            # PISTA vai direto para Troco Pix Pista (funcionalidade limitada)
            if nivel == 'PISTA':
                return redirect(url_for('troco_pix.pista'))
            
            # SUPERVISOR vai para a página inicial (acesso a múltiplas seções)
            # Pode acessar: caixa, cartões, tipos_receita, quilometragem, arla, posto, troco_pix, etc.
            if nivel == 'SUPERVISOR':
                return redirect(url_for('index'))
            
            # ADMIN, GERENTE e outros vão para página solicitada ou index
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
        
        # Para SUPERVISOR, pegar múltiplas empresas
        empresas_ids = request.form.getlist('empresas_ids[]') if nivel == 'SUPERVISOR' else []
        
        # Validações
        if not username or not nome_completo or not senha:
            flash('Todos os campos obrigatórios devem ser preenchidos.', 'danger')
        elif Usuario.username_existe(username):
            flash('Este nome de usuário já existe.', 'danger')
        elif senha != confirmar_senha:
            flash('As senhas não coincidem.', 'danger')
        elif nivel == 'PISTA' and not cliente_id:
            flash('Usuários PISTA devem ter um posto/cliente associado.', 'danger')
        elif nivel == 'SUPERVISOR' and not empresas_ids:
            flash('Usuários SUPERVISOR devem ter pelo menos uma empresa associada.', 'danger')
        else:
            try:
                # Se não é PISTA, cliente_id deve ser None
                if nivel != 'PISTA':
                    cliente_id = None
                
                user_id = Usuario.criar_usuario(username, nome_completo, nivel, senha, cliente_id)
                
                # Se é SUPERVISOR, associar empresas
                if nivel == 'SUPERVISOR' and empresas_ids:
                    Usuario.set_empresas_usuario(user_id, empresas_ids)
                
                flash(f'Usuário {username} criado com sucesso!', 'success')
                return redirect(url_for('auth.listar_usuarios'))
            except Exception as e:
                flash(f'Erro ao criar usuário: {str(e)}', 'danger')
    
    # Buscar lista de clientes para o dropdown (PISTA)
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Buscar empresas com produtos posto (SUPERVISOR)
    empresas_posto = Usuario.get_clientes_produtos_posto()
    
    return render_template('auth/usuarios/novo.html', 
                         clientes=clientes, 
                         empresas_posto=empresas_posto)

@bp.route('/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
@admin_required
def editar_usuario(user_id):
    """Edita um usuário existente"""
    # Print statements para garantir visibilidade mesmo se logging falhar
    print(f"[DEBUG EDITAR] Função editar_usuario chamada para user_id={user_id}")
    print(f"[DEBUG EDITAR] Request method: {request.method}")
    
    # WRAPPER GLOBAL - Captura QUALQUER erro na função
    try:
        print(f"[DEBUG EDITAR] Dentro do try block, iniciando edição")
        logger.info(f"[EDITAR] Iniciando edição do usuário {user_id}")
        
        # Buscar dados do usuário
        try:
            user_data = Usuario.get_by_id_completo(user_id)
            logger.info(f"[EDITAR] Dados do usuário carregados: {user_data is not None}")
            
            if not user_data:
                flash('Usuário não encontrado.', 'danger')
                return redirect(url_for('auth.listar_usuarios'))
        except Exception as e:
            logger.error(f"[EDITAR] Erro ao buscar usuário {user_id}: {str(e)}", exc_info=True)
            flash(f'Erro ao carregar dados do usuário: {str(e)}', 'danger')
            return redirect(url_for('auth.listar_usuarios'))
        
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            nome_completo = request.form.get('nome_completo', '').strip()
            nivel = request.form.get('nivel', 'PISTA')
            cliente_id = request.form.get('cliente_id')
            senha = request.form.get('senha')
            confirmar_senha = request.form.get('confirmar_senha')
            
            # Para SUPERVISOR, pegar múltiplas empresas
            empresas_ids = request.form.getlist('empresas_ids[]') if nivel == 'SUPERVISOR' else []
            
            # Validações
            if not username or not nome_completo:
                flash('Usuário e nome completo são obrigatórios.', 'danger')
            elif Usuario.username_existe(username, excluir_id=user_id):
                flash('Este nome de usuário já existe.', 'danger')
            elif nivel == 'PISTA' and not cliente_id:
                flash('Usuários PISTA devem ter um posto/cliente associado.', 'danger')
            elif nivel == 'SUPERVISOR' and not empresas_ids:
                flash('Usuários SUPERVISOR devem ter pelo menos uma empresa associada.', 'danger')
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
                        
                        # Se é SUPERVISOR, atualizar empresas associadas
                        if nivel == 'SUPERVISOR':
                            Usuario.set_empresas_usuario(user_id, empresas_ids)
                        else:
                            # Se mudou de SUPERVISOR para outro nível, limpar associações
                            Usuario.set_empresas_usuario(user_id, [])
                        
                        # Se forneceu senha, atualiza
                        if senha:
                            user.alterar_senha(senha)
                        
                        flash(f'Usuário {username} atualizado com sucesso!', 'success')
                        return redirect(url_for('auth.listar_usuarios'))
                except Exception as e:
                    logger.error(f"[EDITAR] Erro ao atualizar usuário {user_id}: {str(e)}")
                    flash(f'Erro ao atualizar usuário: {str(e)}', 'danger')
        
        # Buscar lista de clientes para o dropdown
        try:
            logger.info("[EDITAR] Buscando lista de clientes...")
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
            clientes = cursor.fetchall()
            cursor.close()
            conn.close()
            logger.info(f"[EDITAR] Clientes carregados: {len(clientes)}")
        except Exception as e:
            logger.error(f"[EDITAR] Erro ao buscar clientes: {str(e)}", exc_info=True)
            clientes = []
        
        # Buscar empresas com produtos posto (SUPERVISOR)
        empresas_posto = Usuario.get_clientes_produtos_posto()
        
        # Buscar empresas já associadas ao usuário SUPERVISOR
        empresas_selecionadas = Usuario.get_empresas_usuario(user_id)
        empresas_selecionadas_ids = [e['id'] for e in empresas_selecionadas]
        
        try:
            logger.info("[EDITAR] Renderizando template de edição...")
            return render_template('auth/usuarios/editar.html', 
                                 usuario=user_data, 
                                 clientes=clientes,
                                 empresas_posto=empresas_posto,
                                 empresas_selecionadas_ids=empresas_selecionadas_ids)
        except Exception as e:
            logger.error(f"[EDITAR] Erro ao renderizar template: {str(e)}", exc_info=True)
            flash(f'Erro ao carregar página de edição: {str(e)}', 'danger')
            return redirect(url_for('auth.listar_usuarios'))
    
    except Exception as e:
        # WRAPPER GLOBAL - Captura QUALQUER erro não tratado
        print(f"[DEBUG EDITAR] ERRO FATAL CAPTURADO: {str(e)}")
        print(f"[DEBUG EDITAR] Tipo do erro: {type(e).__name__}")
        logger.error(f"[EDITAR] ERRO FATAL na função editar_usuario: {str(e)}", exc_info=True)
        flash(f'Erro fatal ao editar usuário: {str(e)}', 'danger')
        return redirect(url_for('auth.listar_usuarios'))

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
