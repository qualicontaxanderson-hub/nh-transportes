"""
Cadastro do certificado A1 (PFX) por empresa — serviço de captura de DFe.

Tela de usuário logado (NÃO máquina-a-máquina): usa @login_required e o CSRF
normal do app. Grava apenas na tabela nova `dfe_certificados`; não toca em
nenhuma tabela existente.

Modelo de armazenamento (decidido com o usuário):
  - o arquivo .pfx vai para o DROPBOX (não entra nos backups do banco);
  - no banco fica só o CAMINHO do pfx (dfe_certificados.pfx_caminho);
  - a senha do PFX fica CIFRADA no banco (dfe_certificados.senha_cifrada);
  - a coluna antiga pfx_conteudo fica NULL (deprecada).

Fluxo do POST: valida o PFX com a senha ANTES de salvar; extrai CNPJ e validade
do próprio certificado; sobe o PFX pro Dropbox; cifra a senha; grava com
INSERT ... ON DUPLICATE KEY UPDATE (UNIQUE = cliente_id) para permitir renovar.
"""
import os
import re
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from utils.db import get_db_connection
from integrations.cripto_dfe import cifrar_senha
from integrations.dropbox_dfe import upload_arquivo

# Validação/leitura do PFX
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
from cryptography.x509.oid import NameOID

dfe_certificado_bp = Blueprint('dfe_certificado', __name__, url_prefix='/dfe/certificado')

# OID ICP-Brasil que carrega o CNPJ (14 dígitos) da pessoa jurídica no SAN.
_OID_CNPJ_ICP = '2.16.76.1.3.3'

# Pasta base no Dropbox onde os certificados são gravados.
# ATENÇÃO: é uma App Folder do Qualicontax; a integração do NH é Full Dropbox.
# O upload pode falhar por permissão — o erro é tratado com mensagem clara.
_BASE_DROPBOX_CERT = 'Aplicativos/QUALICONTAX/Certificados'


def _extrair_cnpj(cert) -> str | None:
    """
    Extrai o CNPJ (14 dígitos) do certificado. Prioriza o SAN otherName
    OID 2.16.76.1.3.3 (padrão ICP-Brasil e-CNPJ); cai para o CN (formato
    'RAZAO SOCIAL:CNPJ') como fallback. Retorna só dígitos, ou None.
    """
    # 1) SAN otherName OID 2.16.76.1.3.3
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for gn in san:
            if isinstance(gn, x509.OtherName) and gn.type_id.dotted_string == _OID_CNPJ_ICP:
                texto = gn.value.decode('latin-1', errors='ignore')
                m = re.search(r'\d{14}', texto)
                if m:
                    return m.group(0)
    except Exception:
        pass

    # 2) Fallback: Common Name no formato "NOME:CNPJ"
    try:
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        if ':' in cn:
            digitos = re.sub(r'\D', '', cn.split(':')[-1])
            if len(digitos) >= 14:
                return digitos[:14]
    except Exception:
        pass

    return None


def _extrair_validade(cert) -> date | None:
    """Data de expiração (not_valid_after) do certificado, como date."""
    try:
        na = getattr(cert, 'not_valid_after_utc', None) or cert.not_valid_after
        return na.date()
    except Exception:
        return None


def _carregar_clientes():
    """Empresas (clientes) para o dropdown."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT id, COALESCE(nome_fantasia, razao_social) AS nome, cnpj
                 FROM clientes
                ORDER BY nome"""
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def _carregar_certificados():
    """Certificados já cadastrados (SEM a senha) para a listagem."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT dc.cliente_id, dc.cnpj, dc.nome_arquivo, dc.pfx_caminho,
                      dc.validade_ate, dc.modo_automatico, dc.ativo, dc.atualizado_em,
                      COALESCE(c.nome_fantasia, c.razao_social) AS empresa_nome
                 FROM dfe_certificados dc
                 LEFT JOIN clientes c ON c.id = dc.cliente_id
                ORDER BY empresa_nome"""
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


@dfe_certificado_bp.route('', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        cliente_id = (request.form.get('cliente_id') or '').strip()
        senha = request.form.get('senha') or ''
        modo_automatico = 1 if request.form.get('modo_automatico') else 0
        pfx_file = request.files.get('pfx_arquivo')

        # --- validações de entrada ---
        if not cliente_id:
            flash('Selecione a empresa.', 'danger')
            return redirect(url_for('dfe_certificado.index'))
        if not pfx_file or not pfx_file.filename:
            flash('Anexe o arquivo .pfx do certificado.', 'danger')
            return redirect(url_for('dfe_certificado.index'))
        if not senha:
            flash('Informe a senha do certificado.', 'danger')
            return redirect(url_for('dfe_certificado.index'))

        nome_arquivo = os.path.basename(pfx_file.filename)
        pfx_bytes = pfx_file.read()
        if not pfx_bytes:
            flash('O arquivo .pfx está vazio.', 'danger')
            return redirect(url_for('dfe_certificado.index'))

        # --- 2) VALIDA o PFX com a senha ANTES de salvar ---
        try:
            _, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode('utf-8'))
        except Exception:
            flash('Senha incorreta ou arquivo .pfx inválido. Nada foi salvo.', 'danger')
            return redirect(url_for('dfe_certificado.index'))
        if cert is None:
            flash('O arquivo .pfx não contém um certificado válido. Nada foi salvo.', 'danger')
            return redirect(url_for('dfe_certificado.index'))

        # --- 3) extrai CNPJ e validade do certificado ---
        cnpj = _extrair_cnpj(cert)
        if not cnpj:
            flash('Não consegui extrair o CNPJ do certificado. Confirme que é um e-CNPJ (A1). Nada foi salvo.', 'danger')
            return redirect(url_for('dfe_certificado.index'))
        validade_ate = _extrair_validade(cert)

        # --- 4) sobe o PFX pro Dropbox ---
        caminho_dropbox = f'{_BASE_DROPBOX_CERT}/{cnpj}/certificado.pfx'
        try:
            res = upload_arquivo(caminho_dropbox, pfx_bytes)
            pfx_caminho = res['path']
        except Exception as e:
            # Teste de permissão da App Folder do Qualicontax: mensagem clara.
            flash(f'Não consegui gravar na pasta "{caminho_dropbox}" do Dropbox: {e}. Nada foi salvo.', 'danger')
            return redirect(url_for('dfe_certificado.index'))

        # --- 5) cifra a senha ---
        try:
            senha_cifrada = cifrar_senha(senha)
        except Exception as e:
            flash(f'Erro ao cifrar a senha (verifique DFE_CRYPTO_KEY no Railway): {e}. Nada foi salvo.', 'danger')
            return redirect(url_for('dfe_certificado.index'))

        # --- 6) grava/atualiza (UNIQUE = cliente_id). pfx_conteudo fica NULL ---
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO dfe_certificados
                       (cliente_id, cnpj, nome_arquivo, pfx_caminho, senha_cifrada,
                        validade_ate, modo_automatico, ativo)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE
                       cnpj            = VALUES(cnpj),
                       nome_arquivo    = VALUES(nome_arquivo),
                       pfx_caminho     = VALUES(pfx_caminho),
                       senha_cifrada   = VALUES(senha_cifrada),
                       validade_ate    = VALUES(validade_ate),
                       modo_automatico = VALUES(modo_automatico),
                       ativo           = 1""",
                (int(cliente_id), cnpj, nome_arquivo, pfx_caminho, senha_cifrada,
                 validade_ate, modo_automatico)
            )
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao salvar o certificado no banco: {e}', 'danger')
            return redirect(url_for('dfe_certificado.index'))
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        val_str = validade_ate.strftime('%d/%m/%Y') if validade_ate else 'sem data'
        flash(f'Certificado do CNPJ {cnpj} salvo com sucesso (validade {val_str}).', 'success')
        return redirect(url_for('dfe_certificado.index'))

    # GET
    clientes = _carregar_clientes()
    certificados = _carregar_certificados()
    return render_template('dfe/certificado.html', clientes=clientes, certificados=certificados)
