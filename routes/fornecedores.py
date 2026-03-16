import re
import urllib.request
import urllib.error
import json as _json

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('fornecedores', __name__, url_prefix='/fornecedores')

_tables_ready = False


def _ensure_tables():
    """Garante que a tabela fornecedor_empresas existe e que a coluna cep existe. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fornecedor_empresas (
                fornecedor_id     INT NOT NULL,
                cliente_id        INT NOT NULL,
                conta_contabil_id INT NULL,
                PRIMARY KEY (fornecedor_id, cliente_id),
                CONSTRAINT fk_fe_fornecedor FOREIGN KEY (fornecedor_id)
                    REFERENCES fornecedores(id) ON DELETE CASCADE,
                CONSTRAINT fk_fe_cliente FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # Add cep column to fornecedores if it doesn't exist yet
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'fornecedores'
              AND COLUMN_NAME = 'cep'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE fornecedores ADD COLUMN cep VARCHAR(10) NULL AFTER bairro"
            )
        conn.commit()
        cursor.close()
        _tables_ready = True
    finally:
        conn.close()


def _load_form_data(conn):
    """Carrega todas as empresas e o mapeamento grupo→contas contábeis."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome,
                  c.grupo_contabil_id
             FROM clientes c
            ORDER BY nome"""
    )
    empresas = cursor.fetchall()
    cursor.execute(
        """SELECT c.id, c.grupo_id, c.codigo, c.nome AS conta_nome
             FROM plano_contas_contas c
             JOIN plano_contas_grupos g ON g.id = c.grupo_id
            WHERE c.ativo = 1
            ORDER BY g.codigo, c.codigo"""
    )
    contas_raw = cursor.fetchall()
    cursor.close()
    contas_por_grupo = {}
    for c in contas_raw:
        gid = c['grupo_id']
        if gid not in contas_por_grupo:
            contas_por_grupo[gid] = []
        contas_por_grupo[gid].append({
            'id': c['id'],
            'label': f"{c['codigo']} {c['conta_nome']}",
        })
    return empresas, contas_por_grupo


@bp.route('/api/cnpj/<cnpj>')
@login_required
def api_cnpj_lookup(cnpj):
    """Consulta dados de CNPJ na BrasilAPI e retorna JSON com dados da empresa."""
    cnpj_digits = re.sub(r'\D', '', cnpj)
    if len(cnpj_digits) != 14:
        return jsonify({'erro': 'CNPJ inválido'}), 400
    try:
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_digits}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        if not isinstance(data, dict):
            return jsonify({'erro': 'Resposta inválida da Receita Federal'}), 502
        result = {
            'razao_social': str(data.get('razao_social') or ''),
            'nome_fantasia': str(data.get('nome_fantasia') or ''),
            'telefone': str(data.get('ddd_telefone_1') or ''),
            'email': str(data.get('email') or ''),
            'cep': str(data.get('cep') or ''),
            'endereco': str(data.get('logradouro') or ''),
            'numero': str(data.get('numero') or ''),
            'complemento': str(data.get('complemento') or ''),
            'bairro': str(data.get('bairro') or ''),
            'municipio': str(data.get('municipio') or ''),
            'uf': str(data.get('uf') or ''),
        }
        return jsonify(result)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return jsonify({'erro': 'CNPJ não encontrado'}), 404
        return jsonify({'erro': 'Erro ao consultar Receita Federal'}), 502
    except Exception:
        return jsonify({'erro': 'Erro ao consultar Receita Federal'}), 502


@bp.route('/')
@login_required
def lista():
    _ensure_tables()
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM fornecedores ORDER BY razao_social")
        fornecedores = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('fornecedores/lista.html', fornecedores=fornecedores)
    except Exception as e:
        flash(f'Erro ao carregar fornecedores: {str(e)}', 'danger')
        return render_template('fornecedores/lista.html', fornecedores=[])


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
            razao_social = request.form.get('razao_social')
            nome_fantasia = request.form.get('nome_fantasia')
            cnpj = request.form.get('cnpj')
            ie = request.form.get('ie')
            endereco = request.form.get('endereco')
            numero = request.form.get('numero')
            complemento = request.form.get('complemento')
            bairro = request.form.get('bairro')
            municipio = request.form.get('municipio')
            uf = request.form.get('uf')
            cep = request.form.get('cep') or None
            nome_vendedor = request.form.get('nome_vendedor')
            telefone = request.form.get('telefone')
            email = request.form.get('email')
            tipo_pagamento_padrao = request.form.get('tipo_pagamento_padrao') or None
            chave_pix = request.form.get('chave_pix') or None
            dados_bancarios = request.form.get('dados_bancarios') or None

            cursor.execute("""
                INSERT INTO fornecedores (
                    razao_social, nome_fantasia, cnpj, ie,
                    endereco, numero, complemento, bairro,
                    municipio, uf, cep, nome_vendedor, telefone, email,
                    tipo_pagamento_padrao, chave_pix, dados_bancarios
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                razao_social, nome_fantasia, cnpj, ie,
                endereco, numero, complemento, bairro,
                municipio, uf, cep, nome_vendedor, telefone, email,
                tipo_pagamento_padrao, chave_pix, dados_bancarios
            ))
            conn.commit()
            novo_id = cursor.lastrowid

            # Salvar vínculos empresa + conta contábil
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_contabil_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO fornecedor_empresas
                               (fornecedor_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (novo_id, int(eid), conta_contabil_id)
                    )
            conn.commit()

            flash('Fornecedor cadastrado com sucesso!', 'success')
            return redirect(url_for('fornecedores.lista'))

        empresas, contas_por_grupo = _load_form_data(conn)
        return render_template('fornecedores/novo.html',
                               empresas=empresas,
                               contas_por_grupo=contas_por_grupo,
                               vinculos=[])
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar fornecedor: {str(e)}', 'danger')
        return redirect(url_for('fornecedores.lista'))
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
            razao_social = request.form.get('razao_social')
            nome_fantasia = request.form.get('nome_fantasia')
            cnpj = request.form.get('cnpj')
            ie = request.form.get('ie')
            endereco = request.form.get('endereco')
            numero = request.form.get('numero')
            complemento = request.form.get('complemento')
            bairro = request.form.get('bairro')
            municipio = request.form.get('municipio')
            uf = request.form.get('uf')
            cep = request.form.get('cep') or None
            nome_vendedor = request.form.get('nome_vendedor')
            telefone = request.form.get('telefone')
            email = request.form.get('email')
            tipo_pagamento_padrao = request.form.get('tipo_pagamento_padrao') or None
            chave_pix = request.form.get('chave_pix') or None
            dados_bancarios = request.form.get('dados_bancarios') or None

            cursor.execute("""
                UPDATE fornecedores 
                SET razao_social = %s,
                    nome_fantasia = %s,
                    cnpj = %s,
                    ie = %s,
                    endereco = %s,
                    numero = %s,
                    complemento = %s,
                    bairro = %s,
                    municipio = %s,
                    uf = %s,
                    cep = %s,
                    nome_vendedor = %s,
                    telefone = %s,
                    email = %s,
                    tipo_pagamento_padrao = %s,
                    chave_pix = %s,
                    dados_bancarios = %s
                WHERE id = %s
            """, (
                razao_social, nome_fantasia, cnpj, ie,
                endereco, numero, complemento, bairro,
                municipio, uf, cep, nome_vendedor, telefone, email,
                tipo_pagamento_padrao, chave_pix, dados_bancarios,
                id
            ))
            conn.commit()

            # Atualizar vínculos empresa + conta contábil
            cursor.execute("DELETE FROM fornecedor_empresas WHERE fornecedor_id = %s", (id,))
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_contabil_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO fornecedor_empresas
                               (fornecedor_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (id, int(eid), conta_contabil_id)
                    )
            conn.commit()

            flash('Fornecedor atualizado com sucesso!', 'success')
            return redirect(url_for('fornecedores.lista'))

        cursor.execute("SELECT * FROM fornecedores WHERE id = %s", (id,))
        fornecedor = cursor.fetchone()
        cursor.execute(
            """SELECT fe.cliente_id, fe.conta_contabil_id, c.grupo_contabil_id
                 FROM fornecedor_empresas fe
                 JOIN clientes c ON c.id = fe.cliente_id
                WHERE fe.fornecedor_id = %s""",
            (id,)
        )
        vinculos = cursor.fetchall()
        empresas, contas_por_grupo = _load_form_data(conn)
        return render_template('fornecedores/editar.html', fornecedor=fornecedor,
                               empresas=empresas, contas_por_grupo=contas_por_grupo,
                               vinculos=vinculos)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar fornecedor: {str(e)}', 'danger')
        return redirect(url_for('fornecedores.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fornecedores WHERE id = %s", (id,))
        conn.commit()
        flash('Fornecedor excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir fornecedor: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('fornecedores.lista'))
