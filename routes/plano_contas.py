import logging
import re
import unicodedata

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required

from utils.db import get_db_connection
from utils.decorators import admin_required


def _gerar_codigo(nome):
    """Gera código curto e legível a partir do nome (máx. 28 chars, ASCII, sem acentos)."""
    s = unicodedata.normalize('NFKD', nome)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    slug = re.sub(r'[^A-Z0-9]', '-', s)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:28]


def _codigo_unico(cursor, base, excluir_id=None):
    """Retorna um código único derivado de base, adicionando sufixo numérico se necessário."""
    qry = "SELECT codigo FROM plano_contas_grupos WHERE codigo LIKE %s"
    params = [base + '%']
    if excluir_id:
        qry += " AND id != %s"
        params.append(excluir_id)
    cursor.execute(qry, params)
    existentes = {row[0] for row in cursor.fetchall()}
    if base not in existentes:
        return base
    n = 2
    while f"{base}-{n}" in existentes:
        n += 1
    return f"{base}-{n}"


_CODIGO_CONTA_RE = re.compile(r'^[0-9]+(\.[0-9]+)*$')


def _validar_codigo_conta(codigo):
    """Retorna True se o código contém apenas dígitos separados por ponto (ex.: 1121 ou 1122.1)."""
    return _CODIGO_CONTA_RE.match(codigo) is not None if codigo else False


def _codigo_conta_duplicado(cursor, grupo_id, codigo, excluir_id=None):
    """Retorna True se já existe uma conta com este código no grupo."""
    qry = "SELECT 1 FROM plano_contas_contas WHERE grupo_id=%s AND codigo=%s"
    params = [grupo_id, codigo]
    if excluir_id:
        qry += " AND id != %s"
        params.append(excluir_id)
    cursor.execute(qry, params)
    return cursor.fetchone() is not None


bp = Blueprint('plano_contas', __name__, url_prefix='/plano-contas')

# Flag per-process: CREATE TABLE IF NOT EXISTS é idempotente; o flag apenas
# evita a query DDL extra em cada request após a primeira execução bem-sucedida.
_tables_ready = False


def _ensure_tables():
    """Garante que todas as tabelas/colunas do plano de contas existem.

    Idempotente — cria com IF NOT EXISTS / verifica information_schema.
    Chamado automaticamente ao acessar qualquer rota deste blueprint.
    """
    global _tables_ready
    if _tables_ready:
        return
    log = logging.getLogger(__name__)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Tabela de grupos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plano_contas_grupos (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                codigo     VARCHAR(30)  NOT NULL COMMENT 'Código contábil, ex.: 11211',
                nome       VARCHAR(120) NOT NULL COMMENT 'Descrição, ex.: Conta Sicoob',
                descricao  TEXT         NULL,
                ativo      TINYINT(1)   NOT NULL DEFAULT 1,
                created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_pcg_codigo (codigo)
            ) COMMENT='Grupos do Plano de Contas Contábil'
        """)
        conn.commit()

        # 2. Coluna grupo_contabil_id em clientes (idempotente via information_schema)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'clientes'
              AND COLUMN_NAME  = 'grupo_contabil_id'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE clientes ADD COLUMN grupo_contabil_id INT NULL"
            )
            conn.commit()

        # 3. FK clientes → plano_contas_grupos (idempotente)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA    = DATABASE()
              AND TABLE_NAME      = 'clientes'
              AND CONSTRAINT_NAME = 'fk_clientes_grupo_contabil'
        """)
        if cursor.fetchone()[0] == 0:
            try:
                cursor.execute("""
                    ALTER TABLE clientes
                    ADD CONSTRAINT fk_clientes_grupo_contabil
                    FOREIGN KEY (grupo_contabil_id)
                    REFERENCES plano_contas_grupos(id) ON DELETE SET NULL
                """)
                conn.commit()
            except Exception:
                # Pode já existir com outro nome; rollback e continua
                log.debug('_ensure_tables: FK já existe ou não aplicável; ignorando', exc_info=True)
                conn.rollback()

        # 4. Tabela de contas dentro dos grupos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plano_contas_contas (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                grupo_id   INT          NOT NULL COMMENT 'FK para plano_contas_grupos',
                codigo     VARCHAR(30)  NOT NULL COMMENT 'Código contábil, ex.: 1121',
                nome       VARCHAR(120) NOT NULL COMMENT 'Nome da conta, ex.: Banco Bradesco',
                descricao  TEXT         NULL,
                ativo      TINYINT(1)   NOT NULL DEFAULT 1,
                created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_pcc_grupo_codigo (grupo_id, codigo),
                CONSTRAINT fk_pcc_grupo FOREIGN KEY (grupo_id)
                    REFERENCES plano_contas_grupos(id) ON DELETE CASCADE
            ) COMMENT='Contas do Plano de Contas Contábil dentro de cada Grupo'
        """)
        conn.commit()

        # 5. Coluna tipo_grupo em plano_contas_contas (idempotente)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'plano_contas_contas'
              AND COLUMN_NAME  = 'tipo_grupo'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE plano_contas_contas "
                "ADD COLUMN tipo_grupo VARCHAR(30) NOT NULL DEFAULT 'OUTROS' "
                "COMMENT 'Classificação: ATIVO, PASSIVO, RECEITAS, DESPESAS, CUSTOS, OUTROS'"
            )
            conn.commit()

        # 6. Contas-título (sintéticas) — só organizam a tela em cards; ficam
        #    fora de plano_contas_contas para não aparecerem como opção de
        #    lançamento nas outras telas.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plano_contas_titulos (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                grupo_id      INT          NOT NULL,
                classificacao VARCHAR(30)  NOT NULL,
                nome          VARCHAR(120) NOT NULL,
                UNIQUE KEY uq_pct (grupo_id, classificacao),
                CONSTRAINT fk_pct_grupo FOREIGN KEY (grupo_id)
                    REFERENCES plano_contas_grupos(id) ON DELETE CASCADE
            ) COMMENT='Contas-título (sintéticas) do plano: só organizam a tela, não recebem lançamento'
        """)
        conn.commit()

        # 7. Classificação do contador na conta (ex.: 1-1-01-02-02)
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'plano_contas_contas'
              AND COLUMN_NAME  = 'classificacao'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE plano_contas_contas ADD COLUMN classificacao VARCHAR(30) NULL "
                "COMMENT 'Classificação do contador, ex.: 1-1-01-02-02'"
            )
            conn.commit()

        _tables_ready = True
    except Exception:
        log.exception('_ensure_tables: falha ao inicializar tabelas do plano de contas')
        try:
            conn.rollback()
        except Exception:
            log.debug('_ensure_tables: rollback também falhou', exc_info=True)
    finally:
        cursor.close()
        conn.close()


def _get_grupos(cursor):
    cursor.execute(
        """SELECT g.id, g.codigo, g.nome, g.descricao, g.ativo,
                  COUNT(DISTINCT c.id)  AS total_contas,
                  COUNT(DISTINCT cl.id) AS total_clientes
           FROM plano_contas_grupos g
           LEFT JOIN plano_contas_contas c  ON c.grupo_id = g.id
           LEFT JOIN clientes cl ON cl.grupo_contabil_id = g.id
           GROUP BY g.id
           ORDER BY g.codigo"""
    )
    return cursor.fetchall()


@bp.route('/')
@login_required
@admin_required
def lista():
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    grupos = _get_grupos(cursor)
    cursor.close()
    conn.close()
    return render_template('plano_contas/lista.html', grupos=grupos)


# ─── Grupo: novo / editar / excluir ─────────────────────────────────────────

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None

        if not nome:
            flash('Nome é obrigatório.', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=None,
                                   form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            codigo = _codigo_unico(cursor, _gerar_codigo(nome))
            logging.getLogger(__name__).debug('novo grupo: nome=%r codigo_gerado=%r', nome, codigo)
            cursor.execute(
                "INSERT INTO plano_contas_grupos (codigo, nome, descricao) VALUES (%s, %s, %s)",
                (codigo, nome, descricao),
            )
            conn.commit()
            novo_id = cursor.lastrowid
            flash('Grupo contábil criado com sucesso! Agora adicione as contas e vincule as empresas.', 'success')
            return redirect(url_for('plano_contas.detalhe', id=novo_id))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar grupo: {e}', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=None,
                                   form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/grupo_form.html', grupo=None, form={})


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
    grupo = cursor.fetchone()
    cursor.close()
    conn.close()

    if not grupo:
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    if request.method == 'POST':
        nome      = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip() or None
        ativo     = 1 if request.form.get('ativo') else 0

        if not nome:
            flash('Nome é obrigatório.', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=grupo,
                                   form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """UPDATE plano_contas_grupos
                   SET nome=%s, descricao=%s, ativo=%s
                   WHERE id=%s""",
                (nome, descricao, ativo, id),
            )
            conn.commit()
            flash('Grupo atualizado com sucesso!', 'success')
            return redirect(url_for('plano_contas.detalhe', id=id))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar grupo: {e}', 'danger')
            return render_template('plano_contas/grupo_form.html', grupo=grupo,
                                   form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/grupo_form.html', grupo=grupo, form=grupo)


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Remove vínculo dos clientes antes de excluir o grupo
        cursor.execute(
            "UPDATE clientes SET grupo_contabil_id = NULL WHERE grupo_contabil_id = %s", (id,)
        )
        cursor.execute("DELETE FROM plano_contas_grupos WHERE id = %s", (id,))
        conn.commit()
        flash('Grupo excluído com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir grupo: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('plano_contas.lista'))


# ─── Grupo: clonar ──────────────────────────────────────────────────────────

@bp.route('/clonar/<int:id>', methods=['POST'])
@login_required
@admin_required
def clonar(id):
    """Clona um grupo e todas as suas contas, gerando um novo código automaticamente."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
        grupo = cursor.fetchone()
        if not grupo:
            flash('Grupo não encontrado.', 'danger')
            return redirect(url_for('plano_contas.lista'))

        novo_nome   = grupo['nome'] + ' (cópia)'
        base_codigo = _gerar_codigo(novo_nome)
        cur2 = conn.cursor()
        novo_codigo = _codigo_unico(cur2, base_codigo)
        cur2.close()

        cur3 = conn.cursor()
        cur3.execute(
            "INSERT INTO plano_contas_grupos (codigo, nome, descricao) VALUES (%s, %s, %s)",
            (novo_codigo, novo_nome, grupo['descricao']),
        )
        novo_grupo_id = cur3.lastrowid

        # Copia as contas do grupo original
        cur3.execute(
            "SELECT codigo, nome, descricao FROM plano_contas_contas WHERE grupo_id = %s",
            (id,),
        )
        contas = cur3.fetchall()
        if contas:
            cur3.executemany(
                "INSERT INTO plano_contas_contas (grupo_id, codigo, nome, descricao) VALUES (%s, %s, %s, %s)",
                [(novo_grupo_id, codigo, nome, descricao) for codigo, nome, descricao in contas],
            )

        conn.commit()
        cur3.close()
        flash(f'Grupo clonado com sucesso!', 'success')
        return redirect(url_for('plano_contas.detalhe', id=novo_grupo_id))
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao clonar grupo: {e}', 'danger')
        return redirect(url_for('plano_contas.lista'))
    finally:
        cursor.close()
        conn.close()


# ─── Grupo: detalhe (contas) ─────────────────────────────────────────────────

# Onde uma conta do plano pode estar ligada. (tabela, coluna, como descrever)
# Conta ligada em qualquer um destes lugares está "em uso": não sai pela tela.
_USOS = [
    ("categoria_despesa_contas", "conta_contabil_id",
     """SELECT CONCAT('Categoria de despesa ', c.nome, ' (', COALESCE(cl.nome_fantasia, cl.razao_social), ')')
          FROM categoria_despesa_contas x JOIN categorias_despesas c ON c.id = x.categoria_id
          LEFT JOIN clientes cl ON cl.id = x.cliente_id WHERE x.conta_contabil_id = %s"""),
    ("categorias_despesas", "conta_contabil_id",
     "SELECT CONCAT('Categoria de despesa ', nome) FROM categorias_despesas WHERE conta_contabil_id = %s"),
    ("fornecedor_empresas", "conta_contabil_id",
     """SELECT CONCAT('Fornecedor ', f.razao_social, ' (', COALESCE(cl.nome_fantasia, cl.razao_social), ')')
          FROM fornecedor_empresas x JOIN fornecedores f ON f.id = x.fornecedor_id
          LEFT JOIN clientes cl ON cl.id = x.cliente_id WHERE x.conta_contabil_id = %s"""),
    ("formas_recebimento", "conta_contabil_id",
     "SELECT CONCAT('Forma de recebimento ', nome) FROM formas_recebimento WHERE conta_contabil_id = %s"),
    ("formas_recebimento_empresas", "conta_contabil_id",
     """SELECT CONCAT('Forma de recebimento ', f.nome, ' (', COALESCE(cl.nome_fantasia, cl.razao_social), ')')
          FROM formas_recebimento_empresas x JOIN formas_recebimento f ON f.id = x.forma_recebimento_id
          LEFT JOIN clientes cl ON cl.id = x.cliente_id WHERE x.conta_contabil_id = %s"""),
    ("produto", "conta_contabil_id",
     "SELECT CONCAT('Produto ', nome) FROM produto WHERE conta_contabil_id = %s"),
    ("produto_empresas", "conta_contabil_id",
     """SELECT CONCAT('Produto ', p.nome, ' (', COALESCE(cl.nome_fantasia, cl.razao_social), ')')
          FROM produto_empresas x JOIN produto p ON p.id = x.produto_id
          LEFT JOIN clientes cl ON cl.id = x.cliente_id WHERE x.conta_contabil_id = %s"""),
    ("bank_accounts", "plano_contas_conta_id",
     "SELECT CONCAT('Conta bancária ', apelido) FROM bank_accounts WHERE plano_contas_conta_id = %s"),
    ("bank_accounts", "conta_coligada_debito_id",
     "SELECT CONCAT('Coligada (débito) da conta ', apelido) FROM bank_accounts WHERE conta_coligada_debito_id = %s"),
    ("bank_accounts", "conta_coligada_credito_id",
     "SELECT CONCAT('Coligada (crédito) da conta ', apelido) FROM bank_accounts WHERE conta_coligada_credito_id = %s"),
    ("bank_account_coligadas", "conta_debito_id",
     """SELECT CONCAT('Coligada (débito) da conta ', b.apelido) FROM bank_account_coligadas x
          JOIN bank_accounts b ON b.id = x.bank_account_id WHERE x.conta_debito_id = %s"""),
    ("bank_account_coligadas", "conta_credito_id",
     """SELECT CONCAT('Coligada (crédito) da conta ', b.apelido) FROM bank_account_coligadas x
          JOIN bank_accounts b ON b.id = x.bank_account_id WHERE x.conta_credito_id = %s"""),
]


def _ids_em_uso(cursor):
    """Ids de plano_contas_contas ligados em algum lugar (_USOS). Tabela que
    não existe neste banco é pulada."""
    ids = set()
    for tabela, coluna, _ in _USOS:
        try:
            cursor.execute(f"SELECT DISTINCT {coluna} FROM {tabela} WHERE {coluna} IS NOT NULL")
            ids.update(r[0] if not isinstance(r, dict) else r[coluna] for r in cursor.fetchall())
        except Exception:
            logging.getLogger(__name__).debug('_ids_em_uso: %s.%s indisponível', tabela, coluna, exc_info=True)
    return ids


def _onde_usada(cursor, conta_id):
    saida = []
    for tabela, coluna, sql in _USOS:
        try:
            cursor.execute(sql, (conta_id,))
            saida += [list(r.values())[0] if isinstance(r, dict) else r[0] for r in cursor.fetchall()]
        except Exception:
            logging.getLogger(__name__).debug('_onde_usada: %s.%s indisponível', tabela, coluna, exc_info=True)
    return saida


_ORDEM_TIPOS = ['ATIVO', 'PASSIVO', 'RECEITAS', 'CUSTOS', 'DESPESAS', 'OUTROS']


def _cards(contas, titulos, em_uso):
    """Agrupa as contas em cards pelo título de 4º nível da classificação
    (1-1-01-02 = Banco Conta Movimento); o de 3º nível vai em cima, menor.
    Conta sem classificação cai num card "Outras contas" do seu tipo."""
    cards = {}
    for c in contas:
        c['em_uso'] = c['id'] in em_uso
        cls = (c.get('classificacao') or '').split('-')
        tipo = c.get('tipo_grupo') or 'OUTROS'
        if len(cls) >= 5:
            chave = '-'.join(cls[:4])
            card = cards.setdefault(chave, {
                'chave': chave, 'tipo': tipo,
                'titulo': titulos.get(chave) or chave,
                'acima': titulos.get('-'.join(cls[:3]), ''),
                'contas': []})
        else:
            card = cards.setdefault('~' + tipo, {
                'chave': '~' + tipo, 'tipo': tipo, 'titulo': 'Outras contas',
                'acima': 'Sem classificação', 'contas': []})
        card['contas'].append(c)
    for card in cards.values():
        card['contas'].sort(key=lambda c: (c.get('classificacao') or '', c['codigo']))
    return sorted(cards.values(), key=lambda k: (_ORDEM_TIPOS.index(k['tipo']) if k['tipo'] in _ORDEM_TIPOS else 99,
                                                 k['chave']))


@bp.route('/<int:id>/contas')
@login_required
@admin_required
def detalhe(id):
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
        grupo = cursor.fetchone()
        if not grupo:
            flash('Grupo não encontrado.', 'danger')
            return redirect(url_for('plano_contas.lista'))
        cursor.execute("SELECT * FROM plano_contas_contas WHERE grupo_id = %s ORDER BY codigo", (id,))
        contas = cursor.fetchall()
        cursor.execute("SELECT classificacao, nome FROM plano_contas_titulos WHERE grupo_id = %s", (id,))
        titulos = {r['classificacao']: r['nome'] for r in cursor.fetchall()}
        em_uso = _ids_em_uso(cursor)
        cursor.execute("SELECT id, codigo, nome FROM plano_contas_grupos WHERE ativo = 1 ORDER BY codigo")
        grupos = cursor.fetchall()
        cursor.execute("""SELECT COALESCE(nome_fantasia, razao_social) AS nome FROM clientes
                           WHERE grupo_contabil_id = %s ORDER BY id""", (id,))
        empresas = [r['nome'] for r in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()

    cards = _cards(contas, titulos, em_uso)
    por_tipo = {t: 0 for t in _ORDEM_TIPOS}
    for c in contas:
        por_tipo[c.get('tipo_grupo') or 'OUTROS'] = por_tipo.get(c.get('tipo_grupo') or 'OUTROS', 0) + 1
    # "Fica dentro de": os títulos de 4º nível, para a gaveta de nova conta/editar
    pais = sorted(((k, v, titulos.get('-'.join(k.split('-')[:3]), '')) for k, v in titulos.items()
                   if k.count('-') == 3), key=lambda x: x[0])
    return render_template('plano_contas/detalhe.html',
                           grupo=grupo, grupos=grupos, empresas=empresas, contas=contas,
                           cards=cards, por_tipo=por_tipo, ordem_tipos=_ORDEM_TIPOS, pais=pais,
                           n_em_uso=sum(1 for c in contas if c['em_uso']))


@bp.route('/contas/<int:conta_id>/uso')
@login_required
@admin_required
def uso_conta(conta_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        return jsonify(ok=True, usos=_onde_usada(cursor, conta_id))
    finally:
        cursor.close()
        conn.close()


@bp.route('/<int:grupo_id>/contas/salvar', methods=['POST'])
@login_required
@admin_required
def salvar_conta(grupo_id):
    """Nova conta ou edição, pela gaveta da tela (JSON). Mesmas regras de
    nova_conta/editar_conta: código só dígitos e ponto, único no grupo."""
    d = request.get_json(silent=True) or {}
    conta_id = d.get('id') or None
    codigo = (d.get('codigo') or '').strip()
    nome = (d.get('nome') or '').strip()
    descricao = (d.get('descricao') or '').strip() or None
    tipo_grupo = (d.get('tipo_grupo') or 'OUTROS').strip().upper()
    pai = (d.get('pai') or '').strip()
    ativo = 0 if d.get('ativo') is False else 1
    if not codigo or not nome:
        return jsonify(ok=False, erro='Código e nome são obrigatórios.'), 400
    if not _validar_codigo_conta(codigo):
        return jsonify(ok=False, erro='Código inválido — use só dígitos e ponto (ex.: 11220).'), 400
    if tipo_grupo not in _ORDEM_TIPOS:
        return jsonify(ok=False, erro='Tipo inválido.'), 400
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if conta_id:
            cursor.execute("SELECT * FROM plano_contas_contas WHERE id = %s AND grupo_id = %s", (conta_id, grupo_id))
            atual = cursor.fetchone()
            if not atual:
                return jsonify(ok=False, erro='Conta não encontrada.'), 404
        if _codigo_conta_duplicado(cursor, grupo_id, codigo, excluir_id=conta_id):
            return jsonify(ok=False, erro=f'Já existe uma conta com o código {codigo} neste plano.'), 400
        # Classificação: mudou o "fica dentro de" (ou é nova) -> próximo número sob o título
        classificacao = atual['classificacao'] if conta_id else None
        if pai and (not classificacao or not classificacao.startswith(pai + '-')):
            cursor.execute("SELECT classificacao FROM plano_contas_contas WHERE grupo_id = %s AND classificacao LIKE %s",
                           (grupo_id, pai + '-%'))
            seq = [int(r['classificacao'].rsplit('-', 1)[1]) for r in cursor.fetchall()
                   if r['classificacao'].rsplit('-', 1)[1].isdigit()]
            classificacao = f"{pai}-{(max(seq) + 1 if seq else 1):02d}"
        if conta_id:
            cursor.execute("""UPDATE plano_contas_contas
                                 SET codigo=%s, nome=%s, descricao=%s, tipo_grupo=%s, ativo=%s, classificacao=%s
                               WHERE id=%s""",
                           (codigo, nome, descricao, tipo_grupo, ativo, classificacao, conta_id))
        else:
            cursor.execute("""INSERT INTO plano_contas_contas (grupo_id, codigo, nome, descricao, tipo_grupo, classificacao)
                              VALUES (%s, %s, %s, %s, %s, %s)""",
                           (grupo_id, codigo, nome, descricao, tipo_grupo, classificacao))
            conta_id = cursor.lastrowid
        conn.commit()
        return jsonify(ok=True, id=conta_id)
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).exception('salvar_conta')
        return jsonify(ok=False, erro=f'Erro ao salvar: {e}'), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/<int:grupo_id>/contas/excluir-lote', methods=['POST'])
@login_required
@admin_required
def excluir_lote(grupo_id):
    """Exclui (de verdade) as contas marcadas que NÃO estão em uso. A trava
    é conferida aqui de novo — a tela só ajuda."""
    ids = [int(i) for i in (request.get_json(silent=True) or {}).get('ids', []) if str(i).isdigit()]
    if not ids:
        return jsonify(ok=False, erro='Nenhuma conta marcada.'), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        em_uso = _ids_em_uso(cursor)
        livres = [i for i in ids if i not in em_uso]
        n = 0
        if livres:
            ph = ','.join(['%s'] * len(livres))
            cursor.execute(f"DELETE FROM plano_contas_contas WHERE grupo_id = %s AND id IN ({ph})",
                           [grupo_id] + livres)
            n = cursor.rowcount
            conn.commit()
        return jsonify(ok=True, excluidas=n, bloqueadas=len(ids) - len(livres))
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).exception('excluir_lote')
        return jsonify(ok=False, erro=f'Erro ao excluir: {e}'), 500
    finally:
        cursor.close()
        conn.close()


# ─── Conta: nova / editar / excluir ─────────────────────────────────────────

@bp.route('/<int:grupo_id>/contas/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_conta(grupo_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (grupo_id,))
    grupo = cursor.fetchone()
    cursor.close()
    conn.close()

    if not grupo:
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    if request.method == 'POST':
        codigo     = request.form.get('codigo', '').strip()
        nome       = request.form.get('nome', '').strip()
        descricao  = request.form.get('descricao', '').strip() or None
        tipo_grupo = request.form.get('tipo_grupo', 'OUTROS').strip() or 'OUTROS'
        acao       = request.form.get('acao', 'salvar')

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)

        if not _validar_codigo_conta(codigo):
            flash('Código inválido — use apenas dígitos e ponto (ex.: 1121 ou 1122.1).', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if _codigo_conta_duplicado(cursor, grupo_id, codigo):
                flash(f'Já existe uma conta com o código {codigo!r} neste grupo.', 'danger')
                return render_template('plano_contas/conta_form.html',
                                       grupo=grupo, conta=None, form=request.form)

            cursor.execute(
                "INSERT INTO plano_contas_contas (grupo_id, codigo, nome, descricao, tipo_grupo) VALUES (%s, %s, %s, %s, %s)",
                (grupo_id, codigo, nome, descricao, tipo_grupo),
            )
            conn.commit()
            flash('Conta criada com sucesso!', 'success')
            if acao == 'proxima':
                return redirect(url_for('plano_contas.nova_conta', grupo_id=grupo_id))
            return redirect(url_for('plano_contas.detalhe', id=grupo_id))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar conta: {e}', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=None, form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/conta_form.html',
                           grupo=grupo, conta=None, form={})


@bp.route('/contas/<int:conta_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_conta(conta_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT c.*, g.nome AS grupo_nome, g.codigo AS grupo_codigo
           FROM plano_contas_contas c
           JOIN plano_contas_grupos g ON g.id = c.grupo_id
           WHERE c.id = %s""",
        (conta_id,),
    )
    conta = cursor.fetchone()
    cursor.close()
    conn.close()

    if not conta:
        flash('Conta não encontrada.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    grupo = {'id': conta['grupo_id'], 'nome': conta['grupo_nome'],
             'codigo': conta['grupo_codigo']}

    if request.method == 'POST':
        codigo     = request.form.get('codigo', '').strip()
        nome       = request.form.get('nome', '').strip()
        descricao  = request.form.get('descricao', '').strip() or None
        ativo      = 1 if request.form.get('ativo') else 0
        tipo_grupo = request.form.get('tipo_grupo', 'OUTROS').strip() or 'OUTROS'

        if not codigo or not nome:
            flash('Código e Nome são obrigatórios.', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=conta, form=request.form)

        if not _validar_codigo_conta(codigo):
            flash('Código inválido — use apenas dígitos e ponto (ex.: 1121 ou 1122.1).', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=conta, form=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if _codigo_conta_duplicado(cursor, conta['grupo_id'], codigo, excluir_id=conta_id):
                flash(f'Já existe outra conta com o código {codigo!r} neste grupo.', 'danger')
                return render_template('plano_contas/conta_form.html',
                                       grupo=grupo, conta=conta, form=request.form)

            cursor.execute(
                """UPDATE plano_contas_contas
                   SET codigo=%s, nome=%s, descricao=%s, ativo=%s, tipo_grupo=%s
                   WHERE id=%s""",
                (codigo, nome, descricao, ativo, tipo_grupo, conta_id),
            )
            conn.commit()
            flash('Conta atualizada com sucesso!', 'success')
            return redirect(url_for('plano_contas.detalhe', id=conta['grupo_id']))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar conta: {e}', 'danger')
            return render_template('plano_contas/conta_form.html',
                                   grupo=grupo, conta=conta, form=request.form)
        finally:
            cursor.close()
            conn.close()

    return render_template('plano_contas/conta_form.html',
                           grupo=grupo, conta=conta, form=conta)


@bp.route('/contas/<int:conta_id>/excluir', methods=['POST'])
@login_required
@admin_required
def excluir_conta(conta_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT grupo_id FROM plano_contas_contas WHERE id = %s", (conta_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        flash('Conta não encontrada.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    grupo_id = row['grupo_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if conta_id in _ids_em_uso(cursor):
            flash('Esta conta está em uso (categoria, fornecedor, banco...) e não pode ser excluída.', 'warning')
            return redirect(url_for('plano_contas.detalhe', id=grupo_id))
        cursor.execute("DELETE FROM plano_contas_contas WHERE id = %s", (conta_id,))
        conn.commit()
        flash('Conta excluída com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir conta: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('plano_contas.detalhe', id=grupo_id))


# ─── Grupo: vincular clientes / empresas ─────────────────────────────────────

@bp.route('/clientes/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def vincular_clientes(id):
    """Tela para vincular/desvincular clientes a um grupo contábil."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM plano_contas_grupos WHERE id = %s", (id,))
    grupo = cursor.fetchone()
    if not grupo:
        cursor.close()
        conn.close()
        flash('Grupo não encontrado.', 'danger')
        return redirect(url_for('plano_contas.lista'))

    if request.method == 'POST':
        # ids de clientes que devem pertencer ao grupo (checkbox multi)
        ids_selecionados = set(request.form.getlist('cliente_ids'))

        # Busca todos os clientes
        cursor.execute("SELECT id FROM clientes")
        todos = cursor.fetchall()

        cur2 = conn.cursor()
        for c in todos:
            cid = str(c['id'])
            if cid in ids_selecionados:
                cur2.execute(
                    "UPDATE clientes SET grupo_contabil_id = %s WHERE id = %s",
                    (id, c['id']),
                )
            else:
                # Só remove se o cliente pertencia a ESTE grupo
                cur2.execute(
                    "UPDATE clientes SET grupo_contabil_id = NULL WHERE id = %s AND grupo_contabil_id = %s",
                    (c['id'], id),
                )
        conn.commit()
        cur2.close()
        cursor.close()
        conn.close()
        flash('Empresas vinculadas com sucesso!', 'success')
        return redirect(url_for('plano_contas.lista'))

    # GET: lista todos os clientes marcando os já vinculados
    cursor.execute(
        """SELECT id, razao_social, nome_fantasia, grupo_contabil_id
           FROM clientes ORDER BY razao_social""",
    )
    clientes = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('plano_contas/vincular_clientes.html',
                           grupo=grupo, clientes=clientes)

