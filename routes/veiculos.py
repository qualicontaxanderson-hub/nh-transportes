import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('veiculos', __name__, url_prefix='/veiculos')

_tables_ready = False

TIPOS_VEICULO = [
    'Caminhão',
    'Truck',
    'Bitruck',
    'Cavalo Mecânico',
    'Carreta',
    'Semirreboque LS',
    'Bitrem',
]

# Tipos que possuem duas placas (cavalo + carreta)
TIPOS_DUPLA_PLACA = {'Carreta', 'Semirreboque LS', 'Bitrem'}


def _ensure_tables():
    """Garante que as tabelas e colunas extras de veículos existem. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return
    log = logging.getLogger(__name__)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Colunas adicionais na tabela veiculos
        for col_sql in [
            "ALTER TABLE veiculos ADD COLUMN tipo_veiculo VARCHAR(30) NULL AFTER modelo",
            "ALTER TABLE veiculos ADD COLUMN placa_carreta VARCHAR(10) NULL AFTER placa",
        ]:
            try:
                cursor.execute(col_sql)
                conn.commit()
            except Exception:
                conn.rollback()

        # Tabela de compartimentos de carregamento
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS veiculo_compartimentos (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                veiculo_id      INT NOT NULL,
                numero_ordem    INT NOT NULL DEFAULT 1,
                capacidade_l    INT NOT NULL,
                descricao       VARCHAR(100) NULL,
                parte           ENUM('unico','cavalo','carreta') NOT NULL DEFAULT 'unico',
                CONSTRAINT fk_vc_veiculo FOREIGN KEY (veiculo_id)
                    REFERENCES veiculos(id) ON DELETE CASCADE
            )
        """)

        # Tabela de licenças / documentos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS veiculo_licencas (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                veiculo_id      INT NOT NULL,
                tipo_documento  VARCHAR(60) NOT NULL,
                numero_doc      VARCHAR(60) NULL,
                data_validade   DATE NULL,
                observacoes     VARCHAR(255) NULL,
                parte           ENUM('unico','cavalo','carreta') NOT NULL DEFAULT 'unico',
                CONSTRAINT fk_vl_veiculo FOREIGN KEY (veiculo_id)
                    REFERENCES veiculos(id) ON DELETE CASCADE
            )
        """)

        # Tabela de conjuntos (cavalo + carreta ativos)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conjuntos_veiculos (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                cavalo_id   INT NOT NULL,
                carreta_id  INT NOT NULL,
                ativo       TINYINT(1) NOT NULL DEFAULT 1,
                UNIQUE KEY uq_cv_cavalo (cavalo_id),
                UNIQUE KEY uq_cv_carreta (carreta_id),
                CONSTRAINT fk_cj_cavalo  FOREIGN KEY (cavalo_id)
                    REFERENCES veiculos(id) ON DELETE CASCADE,
                CONSTRAINT fk_cj_carreta FOREIGN KEY (carreta_id)
                    REFERENCES veiculos(id) ON DELETE CASCADE
            )
        """)

        conn.commit()
        _tables_ready = True
    except Exception:
        log.exception('_ensure_tables veiculos: falha ao inicializar tabelas')
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cursor.close()
        conn.close()


@bp.route('/')
@login_required
def lista():
    _ensure_tables()
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT v.*,
                   m.nome AS motorista_nome,
                   m.id   AS motorista_id,
                   cj_as_cavalo.carreta_id  AS conjunto_carreta_id,
                   vc_carreta.placa         AS conjunto_carreta_placa,
                   cj_as_carreta.cavalo_id  AS conjunto_cavalo_id,
                   vc_cavalo.placa          AS conjunto_cavalo_placa
            FROM veiculos v
            LEFT JOIN motoristas m ON m.veiculo_id = v.id
            LEFT JOIN conjuntos_veiculos cj_as_cavalo
                   ON cj_as_cavalo.cavalo_id = v.id AND cj_as_cavalo.ativo = 1
            LEFT JOIN veiculos vc_carreta ON vc_carreta.id = cj_as_cavalo.carreta_id
            LEFT JOIN conjuntos_veiculos cj_as_carreta
                   ON cj_as_carreta.carreta_id = v.id AND cj_as_carreta.ativo = 1
            LEFT JOIN veiculos vc_cavalo ON vc_cavalo.id = cj_as_carreta.cavalo_id
            ORDER BY v.placa
        """)
        veiculos = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('veiculos/lista.html', veiculos=veiculos)
    except Exception as e:
        flash(f'Erro ao carregar veículos: {str(e)}', 'danger')
        return render_template('veiculos/lista.html', veiculos=[])


@bp.route('/listar', methods=['GET'])
@login_required
def listar():
    """API endpoint para listar veículos em JSON"""
    _ensure_tables()
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(veiculos), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'POST':
            tipo = request.form.get('tipo_veiculo') or None
            placa_carreta = request.form.get('placa_carreta') or None
            cursor.execute("""
                INSERT INTO veiculos (caminhao, placa, placa_carreta, modelo, tipo_veiculo)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                request.form.get('caminhao'),
                request.form.get('placa'),
                placa_carreta,
                request.form.get('modelo') or None,
                tipo,
            ))
            veiculo_id = cursor.lastrowid

            # Salvar compartimentos
            _salvar_compartimentos(cursor, veiculo_id, request.form)

            # Salvar licenças
            _salvar_licencas(cursor, veiculo_id, request.form)

            conn.commit()
            flash('Veículo cadastrado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))

        return render_template('veiculos/novo.html', tipos=TIPOS_VEICULO,
                               tipos_dupla_placa=list(TIPOS_DUPLA_PLACA))
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar veículo: {str(e)}', 'danger')
        return redirect(url_for('veiculos.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            tipo = request.form.get('tipo_veiculo') or None
            placa_carreta = request.form.get('placa_carreta') or None
            cursor.execute("""
                UPDATE veiculos
                SET caminhao=%s, placa=%s, placa_carreta=%s, modelo=%s, tipo_veiculo=%s
                WHERE id=%s
            """, (
                request.form.get('caminhao'),
                request.form.get('placa'),
                placa_carreta,
                request.form.get('modelo') or None,
                tipo,
                id,
            ))

            # Substituir compartimentos e licenças
            cursor.execute("DELETE FROM veiculo_compartimentos WHERE veiculo_id=%s", (id,))
            _salvar_compartimentos(cursor, id, request.form)

            cursor.execute("DELETE FROM veiculo_licencas WHERE veiculo_id=%s", (id,))
            _salvar_licencas(cursor, id, request.form)

            conn.commit()
            flash('Veículo atualizado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))

        cursor.execute("SELECT * FROM veiculos WHERE id = %s", (id,))
        veiculo = cursor.fetchone()
        if not veiculo:
            flash('Veículo não encontrado.', 'warning')
            return redirect(url_for('veiculos.lista'))

        cursor.execute("""
            SELECT * FROM veiculo_compartimentos WHERE veiculo_id=%s ORDER BY parte, numero_ordem
        """, (id,))
        compartimentos = cursor.fetchall()

        cursor.execute("""
            SELECT * FROM veiculo_licencas WHERE veiculo_id=%s ORDER BY parte, data_validade
        """, (id,))
        licencas = cursor.fetchall()

        # Conjunto atual
        cursor.execute("""
            SELECT cj.*, vc.placa AS carreta_placa, vc.caminhao AS carreta_nome,
                   vv.placa AS cavalo_placa, vv.caminhao AS cavalo_nome
            FROM conjuntos_veiculos cj
            LEFT JOIN veiculos vc ON vc.id = cj.carreta_id
            LEFT JOIN veiculos vv ON vv.id = cj.cavalo_id
            WHERE (cj.cavalo_id=%s OR cj.carreta_id=%s) AND cj.ativo=1
            LIMIT 1
        """, (id, id))
        conjunto_atual = cursor.fetchone()

        # Veículos disponíveis para vincular como carreta (não estão em conjunto ativo)
        cursor.execute("""
            SELECT v.id, v.placa, v.caminhao, v.tipo_veiculo
            FROM veiculos v
            WHERE v.id != %s
              AND v.id NOT IN (
                    SELECT carreta_id FROM conjuntos_veiculos WHERE ativo=1
                    UNION
                    SELECT cavalo_id  FROM conjuntos_veiculos WHERE ativo=1
              )
            ORDER BY v.placa
        """, (id,))
        veiculos_disponiveis = cursor.fetchall()

        return render_template('veiculos/editar.html', veiculo=veiculo,
                               compartimentos=compartimentos, licencas=licencas,
                               conjunto_atual=conjunto_atual,
                               veiculos_disponiveis=veiculos_disponiveis,
                               tipos=TIPOS_VEICULO,
                               tipos_dupla_placa=list(TIPOS_DUPLA_PLACA))
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar veículo: {str(e)}', 'danger')
        return redirect(url_for('veiculos.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
        conn.commit()
        flash('Veículo excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir veículo: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('veiculos.lista'))


# ---------------------------------------------------------------------------
# Conjunto (cavalo ↔ carreta)
# ---------------------------------------------------------------------------

@bp.route('/<int:id>/vincular-carreta', methods=['POST'])
@login_required
@admin_required
def vincular_carreta(id):
    _ensure_tables()
    carreta_id = request.form.get('carreta_id', type=int)
    if not carreta_id:
        flash('Selecione uma carreta para vincular.', 'warning')
        return redirect(url_for('veiculos.editar', id=id))
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Desativa quaisquer conjuntos anteriores envolvendo este cavalo ou a carreta
        cursor.execute("""
            UPDATE conjuntos_veiculos SET ativo=0
            WHERE cavalo_id=%s OR carreta_id=%s OR carreta_id=%s
        """, (id, id, carreta_id))
        cursor.execute("""
            INSERT INTO conjuntos_veiculos (cavalo_id, carreta_id, ativo)
            VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE carreta_id=%s, ativo=1
        """, (id, carreta_id, carreta_id))
        conn.commit()
        flash('Conjunto vinculado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao vincular conjunto: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('veiculos.editar', id=id))


@bp.route('/<int:id>/desvincular-conjunto', methods=['POST'])
@login_required
@admin_required
def desvincular_conjunto(id):
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE conjuntos_veiculos SET ativo=0
            WHERE (cavalo_id=%s OR carreta_id=%s) AND ativo=1
        """, (id, id))
        conn.commit()
        flash('Conjunto desvinculado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desvincular conjunto: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('veiculos.editar', id=id))


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _salvar_compartimentos(cursor, veiculo_id, form):
    """Lê os compartimentos do formulário e insere na tabela."""
    partes_comp = form.getlist('comp_parte')
    ordens = form.getlist('comp_ordem')
    capacidades = form.getlist('comp_capacidade')
    descricoes = form.getlist('comp_descricao')
    for i, cap in enumerate(capacidades):
        try:
            cap_int = int(cap)
        except (ValueError, TypeError):
            continue
        if cap_int <= 0:
            continue
        parte = partes_comp[i] if i < len(partes_comp) else 'unico'
        if parte not in ('unico', 'cavalo', 'carreta'):
            parte = 'unico'
        ordem = int(ordens[i]) if i < len(ordens) and ordens[i].isdigit() else (i + 1)
        desc = descricoes[i] if i < len(descricoes) else ''
        cursor.execute("""
            INSERT INTO veiculo_compartimentos (veiculo_id, numero_ordem, capacidade_l, descricao, parte)
            VALUES (%s, %s, %s, %s, %s)
        """, (veiculo_id, ordem, cap_int, desc or None, parte))


def _salvar_licencas(cursor, veiculo_id, form):
    """Lê as licenças do formulário e insere na tabela."""
    partes_lic = form.getlist('lic_parte')
    tipos = form.getlist('lic_tipo')
    numeros = form.getlist('lic_numero')
    validades = form.getlist('lic_validade')
    observacoes = form.getlist('lic_observacoes')
    for i, tipo in enumerate(tipos):
        if not tipo:
            continue
        parte = partes_lic[i] if i < len(partes_lic) else 'unico'
        if parte not in ('unico', 'cavalo', 'carreta'):
            parte = 'unico'
        numero = numeros[i] if i < len(numeros) else ''
        validade = validades[i] if i < len(validades) else ''
        obs = observacoes[i] if i < len(observacoes) else ''
        validade = validade if validade else None
        cursor.execute("""
            INSERT INTO veiculo_licencas (veiculo_id, tipo_documento, numero_doc, data_validade, observacoes, parte)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (veiculo_id, tipo, numero or None, validade, obs or None, parte))
