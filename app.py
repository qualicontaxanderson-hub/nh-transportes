import os
import logging
from logging.handlers import RotatingFileHandler
import pkgutil
import importlib

from flask import Flask, render_template, redirect, url_for, current_app
from flask_login import LoginManager
from utils.formatadores import formatar_moeda


def register_blueprints_from_routes(app):
    """
    Varre o pacote `routes` e tenta importar cada módulo.
    Se o módulo expuser `bp` ou qualquer atributo terminado em '_bp' (Blueprint)
    ele é registrado automaticamente.
    Exceções de import são logadas para diagnóstico (não interrompem o registro).
    """
    ...
    try:
        import routes  # pacote que contém os módulos de rota (routes/*.py)
    except Exception:
        app.logger.warning("Pacote 'routes' não encontrado; nenhum blueprint será registrado automaticamente.")
        return

    for finder, name, ispkg in pkgutil.iter_modules(routes.__path__):
        modname = f"{routes.__name__}.{name}"
        try:
            module = importlib.import_module(modname)
            
            # Procurar por 'bp' ou qualquer variável terminada em '_bp'
            blueprint_found = False
            
            # Primeiro tenta 'bp' padrão
            bp = getattr(module, "bp", None)
            if bp is not None:
                bp_name = getattr(bp, "name", None)
                if bp_name and bp_name in app.blueprints:
                    app.logger.debug("Blueprint '%s' já registrado; ignorando duplicação de %s", bp_name, modname)
                    blueprint_found = True
                else:
                    try:
                        app.register_blueprint(bp)
                        app.logger.info("Blueprint '%s' registrado a partir de %s", getattr(bp, "name", str(bp)), modname)
                        blueprint_found = True
                    except Exception:
                        app.logger.exception("Falha ao registrar blueprint vindo de %s", modname)
            
            # Se não encontrou 'bp', procura por variáveis terminadas em '_bp'
            if not blueprint_found:
                for attr_name in dir(module):
                    if attr_name.endswith('_bp') and not attr_name.startswith('_'):
                        bp_candidate = getattr(module, attr_name, None)
                        if bp_candidate is not None and hasattr(bp_candidate, 'name'):
                            bp_name = getattr(bp_candidate, "name", None)
                            if bp_name and bp_name in app.blueprints:
                                app.logger.debug("Blueprint '%s' já registrado; ignorando duplicação de %s (variável: %s)", 
                                               bp_name, modname, attr_name)
                                blueprint_found = True
                                break
                            try:
                                app.register_blueprint(bp_candidate)
                                app.logger.info("Blueprint '%s' registrado a partir de %s (variável: %s)", 
                                              getattr(bp_candidate, "name", str(bp_candidate)), modname, attr_name)
                                blueprint_found = True
                                break  # Registra apenas o primeiro blueprint encontrado por módulo
                            except Exception:
                                app.logger.exception("Falha ao registrar blueprint '%s' vindo de %s", attr_name, modname)
            
            if not blueprint_found:
                app.logger.debug("Módulo %s não expõe 'bp' ou '*_bp'; ignorando.", modname)
                
        except Exception:
            app.logger.exception("Falha ao importar módulo de rotas %s", modname)


def formatar_moeda(valor):
    """
    Formata um número para representação de moeda BRL (ex.: R$ 1.234,56).
    Retorna '-' para valores None/invalidos.
    """
    try:
        if valor is None or valor == '':
            return '-'
        # tenta converter strings tolerantly
        if isinstance(valor, str):
            s = valor.strip().replace('R$', '').replace('r$', '').replace(' ', '')
            # caso pt-BR com milhar e decimal
            if '.' in s and ',' in s:
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '.')
            num = float(s)
        else:
            num = float(valor)
    except Exception:
        return '-'

    inteiro = int(abs(num))
    centavos = int(round((abs(num) - inteiro) * 100))
    inteiro_str = f"{inteiro:,}".replace(',', '.')
    sinal = '-' if num < 0 else ''
    return f"{sinal}R$ {inteiro_str},{centavos:02d}"


def _ensure_lucro_postos_tables(app):
    """
    Cria as tabelas do módulo Lucro Postos (FIFO) e Estoque Inicial Global se ainda
    não existirem no banco.  Usa CREATE TABLE IF NOT EXISTS para idempotência total —
    seguro executar a cada restart.
    """
    from utils.db import get_db_connection

    # DDLs idempotentes — ordem importa por causa de FK constraints
    statements = [
        # 1. fifo_abertura — estoque inicial por cliente+produto
        """
        CREATE TABLE IF NOT EXISTS `fifo_abertura` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `cliente_id` INT NOT NULL,
            `produto_id` INT NOT NULL,
            `data_abertura` DATE NOT NULL DEFAULT '2026-01-01',
            `quantidade` DECIMAL(12,3) NOT NULL DEFAULT 0,
            `custo_unitario` DECIMAL(10,4) NOT NULL DEFAULT 0,
            `observacao` TEXT NULL,
            `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `criado_por` INT NULL,
            `atualizado_em` DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
            `atualizado_por` INT NULL,
            FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
            FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`) ON DELETE RESTRICT,
            UNIQUE KEY `uk_fifo_abertura_cliente_produto` (`cliente_id`, `produto_id`),
            INDEX `idx_fifo_abertura_cliente` (`cliente_id`),
            INDEX `idx_fifo_abertura_data` (`data_abertura`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        # 2. fifo_competencia — controle ABERTO/FECHADO por mês
        """
        CREATE TABLE IF NOT EXISTS `fifo_competencia` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `cliente_id` INT NOT NULL,
            `ano_mes` VARCHAR(7) NOT NULL,
            `data_inicio` DATE NOT NULL,
            `data_fim` DATE NOT NULL,
            `status` ENUM('ABERTO','FECHADO') NOT NULL DEFAULT 'ABERTO',
            `versao_atual` INT NOT NULL DEFAULT 1,
            `fechado_em` DATETIME NULL,
            `fechado_por` INT NULL,
            `reaberto_em` DATETIME NULL,
            `reaberto_por` INT NULL,
            `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`) ON DELETE RESTRICT,
            UNIQUE KEY `uk_fifo_competencia` (`cliente_id`, `ano_mes`),
            INDEX `idx_fifo_competencia_status` (`status`),
            INDEX `idx_fifo_competencia_cliente` (`cliente_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        # 3. fifo_snapshot_lotes — camadas de estoque no fechamento
        """
        CREATE TABLE IF NOT EXISTS `fifo_snapshot_lotes` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `competencia_id` INT NOT NULL,
            `produto_id` INT NOT NULL,
            `versao` INT NOT NULL DEFAULT 1,
            `lote_ordem` INT NOT NULL,
            `quantidade_restante` DECIMAL(12,3) NOT NULL DEFAULT 0,
            `custo_unitario` DECIMAL(10,4) NOT NULL DEFAULT 0,
            `data_origem` DATE NULL,
            `substituido` TINYINT(1) NOT NULL DEFAULT 0,
            `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (`competencia_id`) REFERENCES `fifo_competencia`(`id`) ON DELETE RESTRICT,
            FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`) ON DELETE RESTRICT,
            INDEX `idx_snapshot_competencia` (`competencia_id`),
            INDEX `idx_snapshot_produto` (`produto_id`),
            INDEX `idx_snapshot_versao` (`versao`),
            INDEX `idx_snapshot_substituido` (`substituido`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        # 4. fifo_resumo_mensal — totais por produto/fechamento
        """
        CREATE TABLE IF NOT EXISTS `fifo_resumo_mensal` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `competencia_id` INT NOT NULL,
            `produto_id` INT NOT NULL,
            `versao` INT NOT NULL DEFAULT 1,
            `qtde_entrada` DECIMAL(12,3) NOT NULL DEFAULT 0,
            `custo_entrada_total` DECIMAL(12,2) NOT NULL DEFAULT 0,
            `qtde_saida` DECIMAL(12,3) NOT NULL DEFAULT 0,
            `receita_saida_total` DECIMAL(12,2) NOT NULL DEFAULT 0,
            `cogs_fifo` DECIMAL(12,2) NOT NULL DEFAULT 0,
            `lucro_bruto` DECIMAL(12,2) NOT NULL DEFAULT 0,
            `estoque_final_qtde` DECIMAL(12,3) NOT NULL DEFAULT 0,
            `estoque_final_valor` DECIMAL(12,2) NOT NULL DEFAULT 0,
            `substituido` TINYINT(1) NOT NULL DEFAULT 0,
            `criado_em` DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (`competencia_id`) REFERENCES `fifo_competencia`(`id`) ON DELETE RESTRICT,
            FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`) ON DELETE RESTRICT,
            INDEX `idx_resumo_competencia` (`competencia_id`),
            INDEX `idx_resumo_produto` (`produto_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        # 5. estoque_inicial_global — registro único imutável por cliente+produto
        """
        CREATE TABLE IF NOT EXISTS `estoque_inicial_global` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `cliente_id` INT NOT NULL,
            `produto_id` INT NOT NULL,
            `data_inicio` DATE NOT NULL,
            `quantidade_inicial` DECIMAL(12,3) NOT NULL DEFAULT 0,
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY `uq_eig_cliente_produto` (`cliente_id`, `produto_id`),
            INDEX (`cliente_id`),
            INDEX (`produto_id`),
            FOREIGN KEY (`cliente_id`) REFERENCES `clientes`(`id`),
            FOREIGN KEY (`produto_id`) REFERENCES `produto`(`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ]

    # Triggers para estoque_inicial_global (não suportam IF NOT EXISTS no MySQL —
    # usamos DROP TRIGGER IF EXISTS antes de cada CREATE)
    trigger_statements = [
        "DROP TRIGGER IF EXISTS `prevent_update_eig`",
        """
        CREATE TRIGGER `prevent_update_eig`
        BEFORE UPDATE ON `estoque_inicial_global`
        FOR EACH ROW
        BEGIN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Updates are not allowed on estoque_inicial_global';
        END
        """,
        "DROP TRIGGER IF EXISTS `prevent_delete_eig`",
        """
        CREATE TRIGGER `prevent_delete_eig`
        BEFORE DELETE ON `estoque_inicial_global`
        FOR EACH ROW
        BEGIN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Deletes are not allowed on estoque_inicial_global';
        END
        """,
    ]

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            for ddl in statements:
                cur.execute(ddl)
            for stmt in trigger_statements:
                cur.execute(stmt)
            conn.commit()
            app.logger.info("Tabelas Lucro Postos (FIFO) e estoque_inicial_global verificadas/criadas.")
        finally:
            cur.close()
            conn.close()
    except Exception:
        app.logger.warning(
            "Falha ao criar tabelas de Lucro Postos na inicialização (não crítico).",
            exc_info=True,
        )


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    
    # Load configuration
    from config import Config
    app.config.from_object(Config)
    
    # Override with environment variable if set
    if os.environ.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

    # Initialize SQLAlchemy
    from models import db
    db.init_app(app)

    # Logging básico (arquivo rotativo)
    if not app.debug and not app.testing:
        log_dir = os.environ.get('LOG_DIR', '.')
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(os.path.join(log_dir, 'app.log'), maxBytes=10*1024*1024, backupCount=5)
        formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)

    # Flask-Login
    login_manager = LoginManager()
    # aponta para o endpoint de login que existe no blueprint 'auth' (auth.login)
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    # user_loader: usar models.usuario.Usuario.get_by_id (se existir)
    @login_manager.user_loader
    def load_user(user_id):
        try:
            from models.usuario import Usuario
            try:
                uid = int(user_id)
            except Exception:
                uid = user_id
            if hasattr(Usuario, 'get_by_id'):
                return Usuario.get_by_id(uid)
            if hasattr(Usuario, 'get'):
                return Usuario.get(uid)
            return None
        except Exception:
            app.logger.debug('load_user: models.usuario.Usuario não disponível ou falha ao carregar', exc_info=True)
            return None

    # Registrar automaticamente todos os blueprints dentro de routes/
    app.logger.info("="*60)
    app.logger.info("Iniciando registro automático de blueprints...")
    app.logger.info("="*60)
    register_blueprints_from_routes(app)
    app.logger.info("="*60)
    app.logger.info("Registro de blueprints concluído!")
    app.logger.info("="*60)

    # Executa migrations opcionais de schema na inicialização do servidor.
    # Garante que as colunas adicionadas em versões recentes (descricao_chave,
    # bank_transaction_id, etc.) existam antes da primeira request, evitando
    # lentidão de 10-30 s no primeiro acesso após cada deployment.
    with app.app_context():
        try:
            from routes.bank_import import _ensure_ld_bank_tx_id, _ensure_descricao_chave
            _ensure_ld_bank_tx_id()
            _ensure_descricao_chave()
            app.logger.info("Migrations de schema de bank_import executadas na inicialização.")
        except Exception:
            app.logger.warning(
                "Migrations de bank_import falharam na inicialização "
                "(não crítico – serão reexecutadas na primeira request).",
                exc_info=True,
            )
            # Reseta os flags de desistência para que a primeira request tente novamente.
            try:
                import routes.bank_import as _bi
                _bi._ld_bank_tx_id_gave_up = False
                _bi._bsm_descricao_chave_gave_up = False
            except Exception:
                pass

    # Cria as tabelas do módulo Lucro Postos (FIFO) e Estoque Inicial Global na
    # primeira inicialização, usando CREATE TABLE IF NOT EXISTS para idempotência.
    with app.app_context():
        _ensure_lucro_postos_tables(app)

    # Registrar filtro e helpers de template
    app.jinja_env.filters['formatar_moeda'] = formatar_moeda

    def _fmtnum(v, dec=3):
        """Formata número em PT-BR com separador de milhar e decimais configuráveis."""
        try:
            num = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return '0'
        fmt = f'{{:,.{dec}f}}'.format(num)
        return fmt.replace(',', 'X').replace('.', ',').replace('X', '.')

    def _fmtmoney(v):
        """Formata valor monetário em PT-BR sem o prefixo R$."""
        try:
            num = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return '0,00'
        fmt = '{:,.2f}'.format(num)
        return fmt.replace(',', 'X').replace('.', ',').replace('X', '.')

    app.jinja_env.filters['fmtnum'] = _fmtnum
    app.jinja_env.filters['fmtmoney'] = _fmtmoney

    @app.context_processor
    def inject_helpers():
        """
        Injetar variáveis úteis nos templates:
         - registered_blueprints: conjunto de nomes de blueprints registrados
         - formatar_moeda: função disponível diretamente se templates chamarem sem filtro
        """
        try:
            registered = set(app.blueprints.keys())
        except Exception:
            registered = set()
        return {
            'registered_blueprints': registered,
            'formatar_moeda': formatar_moeda
        }

    # Rota index simples: tenta redirecionar para fretes.lista se existir
    @app.route('/')
    def index():
        # se existir 'fretes.lista' redireciona, senão mostra mensagem padrão
        try:
            return redirect(url_for('fretes.lista'))
        except Exception:
            return "App funcionando - sem blueprint 'fretes' registrado."

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        try:
            return render_template('404.html'), 404
        except Exception:
            return "404 - Página não encontrada", 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception('Erro interno do servidor: %s', error)
        try:
            return render_template('500.html'), 500
        except Exception:
            return "500 - Erro interno do servidor", 500

    return app


# Expor a app no nível do módulo para compatibilidade com gunicorn app:app
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', '1') == '1')
