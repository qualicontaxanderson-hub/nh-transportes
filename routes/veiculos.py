import json
import logging
import os
import re
import uuid

from flask import (Blueprint, abort, current_app, render_template, request,
                   redirect, send_file, url_for, flash, jsonify)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

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


def _ensure_upload_dir():
    """Creates and returns the upload directory for license PDFs."""
    path = os.path.join(current_app.static_folder, 'uploads', 'licencas')
    os.makedirs(path, exist_ok=True)
    return path


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

        # Colunas adicionais na tabela veiculo_licencas
        for col_sql in [
            "ALTER TABLE veiculo_licencas ADD COLUMN tipo_doc_id INT NULL AFTER tipo_documento",
            "ALTER TABLE veiculo_licencas ADD COLUMN arquivo_pdf VARCHAR(255) NULL AFTER observacoes",
        ]:
            try:
                cursor.execute(col_sql)
                conn.commit()
            except Exception:
                conn.rollback()

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

        # Catálogo de tipos de documento / licença
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tipos_documento_veiculo (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                nome            VARCHAR(80) NOT NULL,
                obrigatorio     TINYINT(1) NOT NULL DEFAULT 0,
                tipos_veiculo   TEXT NULL COMMENT 'JSON array dos tipos de veículo aplicáveis',
                ativo           TINYINT(1) NOT NULL DEFAULT 1,
                UNIQUE KEY uq_tdv_nome (nome)
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


def _get_docs_catalog(cursor, tipo_veiculo=None):
    """Retorna tipos de documento ativos, opcionalmente filtrados pelo tipo do veículo."""
    cursor.execute("SELECT * FROM tipos_documento_veiculo WHERE ativo=1 ORDER BY nome")
    docs = cursor.fetchall()
    if tipo_veiculo is None:
        return docs
    result = []
    for d in docs:
        tv = d.get('tipos_veiculo')
        if not tv:
            result.append(d)
            continue
        try:
            tipos = json.loads(tv)
        except Exception:
            tipos = [t.strip() for t in tv.split(',')]
        if tipo_veiculo in tipos:
            result.append(d)
    return result


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
                   vc_cavalo.placa          AS conjunto_cavalo_placa,
                   (SELECT COUNT(*) FROM tipos_documento_veiculo tdv
                    WHERE tdv.ativo=1 AND tdv.obrigatorio=1
                      AND (tdv.tipos_veiculo IS NULL
                           OR JSON_CONTAINS(tdv.tipos_veiculo, JSON_QUOTE(v.tipo_veiculo)))
                      AND tdv.id NOT IN (
                          SELECT vl.tipo_doc_id FROM veiculo_licencas vl
                          WHERE vl.veiculo_id=v.id AND vl.tipo_doc_id IS NOT NULL
                      )
                      AND tdv.nome NOT IN (
                          SELECT vl.tipo_documento FROM veiculo_licencas vl
                          WHERE vl.veiculo_id=v.id
                      )
                   ) AS docs_obrigatorios_pendentes
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
        cursor = conn.cursor(dictionary=True)

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

            # Salvar licenças (com possíveis uploads de PDF)
            upload_dir = _ensure_upload_dir()
            _salvar_licencas(cursor, veiculo_id, request.form, upload_dir=upload_dir)

            conn.commit()
            flash('Veículo cadastrado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))

        catalog_docs = _get_docs_catalog(cursor)
        return render_template('veiculos/novo.html', tipos=TIPOS_VEICULO,
                               tipos_dupla_placa=list(TIPOS_DUPLA_PLACA),
                               catalog_docs=catalog_docs)
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
            upload_dir = _ensure_upload_dir()
            _salvar_licencas(cursor, id, request.form, upload_dir=upload_dir)

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

        # Catálogo completo para datalist e docs obrigatórios faltantes
        all_catalog_docs = _get_docs_catalog(cursor)
        catalog_for_type = _get_docs_catalog(cursor, veiculo.get('tipo_veiculo'))

        filled_doc_ids = {l['tipo_doc_id'] for l in licencas if l.get('tipo_doc_id')}
        filled_doc_names = {(l['tipo_documento'] or '').lower() for l in licencas}
        docs_faltantes = [
            d for d in catalog_for_type
            if d['obrigatorio'] and (
                d['id'] not in filled_doc_ids and
                (d['nome'] or '').lower() not in filled_doc_names
            )
        ]

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
                               tipos_dupla_placa=list(TIPOS_DUPLA_PLACA),
                               catalog_docs=all_catalog_docs,
                               docs_faltantes=docs_faltantes)
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
# Catálogo de tipos de documento / licença
# ---------------------------------------------------------------------------

@bp.route('/config-documentos', methods=['GET', 'POST'])
@login_required
@admin_required
def config_documentos():
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            acao = request.form.get('acao', 'salvar')

            if acao == 'excluir':
                doc_id = request.form.get('doc_id', type=int)
                if doc_id:
                    cursor.execute("DELETE FROM tipos_documento_veiculo WHERE id=%s", (doc_id,))
                    conn.commit()
                    flash('Tipo de documento excluído.', 'success')

            elif acao == 'salvar':
                doc_id = request.form.get('doc_id', type=int)
                nome = (request.form.get('nome') or '').strip()
                obrigatorio = 1 if request.form.get('obrigatorio') else 0
                tipos_sel = request.form.getlist('tipos_veiculo')
                tipos_json = json.dumps(tipos_sel) if tipos_sel else None
                ativo = 1 if request.form.get('ativo', '1') != '0' else 0

                if not nome:
                    flash('Nome do documento é obrigatório.', 'danger')
                elif doc_id:
                    cursor.execute("""
                        UPDATE tipos_documento_veiculo
                        SET nome=%s, obrigatorio=%s, tipos_veiculo=%s, ativo=%s
                        WHERE id=%s
                    """, (nome, obrigatorio, tipos_json, ativo, doc_id))
                    conn.commit()
                    flash('Tipo de documento atualizado.', 'success')
                else:
                    try:
                        cursor.execute("""
                            INSERT INTO tipos_documento_veiculo (nome, obrigatorio, tipos_veiculo, ativo)
                            VALUES (%s, %s, %s, 1)
                        """, (nome, obrigatorio, tipos_json))
                        conn.commit()
                        flash('Tipo de documento cadastrado.', 'success')
                    except Exception:
                        conn.rollback()
                        flash('Já existe um tipo com este nome.', 'danger')

            return redirect(url_for('veiculos.config_documentos'))

        cursor.execute("SELECT * FROM tipos_documento_veiculo ORDER BY nome")
        tipos_doc = cursor.fetchall()
        for td in tipos_doc:
            tv = td.get('tipos_veiculo')
            if tv:
                try:
                    td['tipos_veiculo_list'] = json.loads(tv)
                except Exception:
                    td['tipos_veiculo_list'] = []
            else:
                td['tipos_veiculo_list'] = []

        return render_template('veiculos/config_documentos.html',
                               tipos_doc=tipos_doc, tipos_veiculo=TIPOS_VEICULO)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro: {str(e)}', 'danger')
        return redirect(url_for('veiculos.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/licenca/pdf/<path:filename>')
@login_required
def licenca_pdf(filename):
    """Serve o PDF de uma licença de veículo."""
    if not re.match(r'^\d+_[0-9a-f]{32}\.pdf$', filename):
        abort(404)
    upload_dir = os.path.realpath(
        os.path.join(current_app.static_folder, 'uploads', 'licencas')
    )
    # Use basename to strip any residual path separators before joining
    file_path = os.path.realpath(os.path.join(upload_dir, os.path.basename(filename)))
    if not file_path.startswith(upload_dir + os.sep):
        abort(404)
    if not os.path.isfile(file_path):
        abort(404)
    return send_file(file_path, mimetype='application/pdf')


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
        try:
            ordem = int(ordens[i].strip()) if i < len(ordens) else (i + 1)
        except (ValueError, TypeError):
            ordem = i + 1
        desc = descricoes[i] if i < len(descricoes) else ''
        cursor.execute("""
            INSERT INTO veiculo_compartimentos (veiculo_id, numero_ordem, capacidade_l, descricao, parte)
            VALUES (%s, %s, %s, %s, %s)
        """, (veiculo_id, ordem, cap_int, desc or None, parte))


def _salvar_licencas(cursor, veiculo_id, form, upload_dir=None):
    """Lê as licenças do formulário e insere na tabela (com suporte a upload de PDF)."""
    partes_lic = form.getlist('lic_parte')
    tipos = form.getlist('lic_tipo')
    tipo_doc_ids = form.getlist('lic_tipo_doc_id')
    numeros = form.getlist('lic_numero')
    validades = form.getlist('lic_validade')
    observacoes = form.getlist('lic_observacoes')
    arquivos_existentes = form.getlist('lic_arquivo_existente')
    lic_arquivos = request.files.getlist('lic_arquivo') if upload_dir else []

    for i, tipo in enumerate(tipos):
        if not tipo:
            continue
        parte = partes_lic[i] if i < len(partes_lic) else 'unico'
        if parte not in ('unico', 'cavalo', 'carreta'):
            parte = 'unico'
        tdid_raw = tipo_doc_ids[i] if i < len(tipo_doc_ids) else ''
        tipo_doc_id = int(tdid_raw) if tdid_raw and str(tdid_raw).strip().isdigit() else None
        numero = numeros[i] if i < len(numeros) else ''
        validade = validades[i] if i < len(validades) else ''
        obs = observacoes[i] if i < len(observacoes) else ''
        validade = validade if validade else None

        # Arquivo PDF: novo upload ou manter existente
        arquivo_pdf = None
        if upload_dir and i < len(lic_arquivos):
            f = lic_arquivos[i]
            if f and f.filename:
                ext = os.path.splitext(secure_filename(f.filename))[1].lower()
                if ext == '.pdf':
                    # Filename is entirely our own — no user data in the path
                    fname = f"{int(veiculo_id)}_{uuid.uuid4().hex}.pdf"
                    save_path = os.path.realpath(os.path.join(upload_dir, fname))
                    real_upload = os.path.realpath(upload_dir)
                    if save_path.startswith(real_upload + os.sep):
                        f.save(save_path)
                        arquivo_pdf = fname
        if arquivo_pdf is None and i < len(arquivos_existentes):
            arquivo_pdf = arquivos_existentes[i] or None

        cursor.execute("""
            INSERT INTO veiculo_licencas
                (veiculo_id, tipo_documento, tipo_doc_id, numero_doc, data_validade, observacoes, parte, arquivo_pdf)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (veiculo_id, tipo, tipo_doc_id, numero or None, validade, obs or None, parte, arquivo_pdf))
