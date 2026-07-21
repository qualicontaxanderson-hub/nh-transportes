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

# OIDs ICP-Brasil no SAN otherName:
#   2.16.76.1.3.3 = e-CNPJ (14 digitos da pessoa juridica)
#   2.16.76.1.3.1 = e-CPF  (nascimento[8] + CPF[11] + NIS[11] + RG[...])
_OID_CNPJ_ICP = '2.16.76.1.3.3'
_OID_CPF_ICP  = '2.16.76.1.3.1'

# Pasta base no Dropbox onde os certificados são gravados.
# ATENÇÃO: é uma App Folder do Qualicontax; a integração do NH é Full Dropbox.
# O upload pode falhar por permissão — o erro é tratado com mensagem clara.
_BASE_DROPBOX_CERT = 'Aplicativos/QUALICONTAX/Certificados'


def _san_otherName_digitos(cert, oid) -> str | None:
    """Dígitos do SAN otherName do OID dado (ICP-Brasil), PULANDO o tag+length
    DER do valor. Isso importa no e-CPF: se a length (2º byte) calhar de ser um
    ASCII '0'-'9', ela injetaria um dígito e deslocaria as posições do CPF."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except Exception:
        return None
    for gn in san:
        if isinstance(gn, x509.OtherName) and gn.type_id.dotted_string == oid:
            raw = gn.value  # DER do valor (bytes): [tag][length][conteudo]
            if isinstance(raw, (bytes, bytearray)) and len(raw) >= 2 and raw[1] < 0x80:
                conteudo = raw[2:]          # pula tag+length (forma curta)
            else:
                conteudo = raw
            texto = conteudo.decode('latin-1', errors='ignore')
            return re.sub(r'\D', '', texto)
    return None


def _extrair_documento(cert):
    """Extrai (documento, tipo_doc) do certificado ICP-Brasil:
      - e-CNPJ (OID 2.16.76.1.3.3): 14 dígitos           -> ('<14>', 'CNPJ')
      - e-CPF  (OID 2.16.76.1.3.1): nascimento[8]+CPF[11] -> ('<11>', 'CPF')
        (o CPF são os 11 dígitos APÓS os 8 da data de nascimento -> posições 8:19)
    Fallback: CN 'RAZÃO:CNPJ'. Retorna (None, None) se não achar."""
    # 1) e-CNPJ
    d = _san_otherName_digitos(cert, _OID_CNPJ_ICP)
    if d and len(d) >= 14:
        return d[:14], 'CNPJ'
    # 2) e-CPF (CPF = 11 dígitos após os 8 da data de nascimento)
    d = _san_otherName_digitos(cert, _OID_CPF_ICP)
    if d and len(d) >= 19:
        return d[8:19], 'CPF'
    # 3) Fallback: Common Name "NOME:CNPJ"
    try:
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        if ':' in cn:
            digitos = re.sub(r'\D', '', cn.split(':')[-1])
            if len(digitos) >= 14:
                return digitos[:14], 'CNPJ'
    except Exception:
        pass
    return None, None


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

        # --- 3) extrai documento (CNPJ/CPF), tipo e validade do certificado ---
        documento, tipo_doc = _extrair_documento(cert)
        if not documento:
            flash('Não consegui extrair o CNPJ/CPF do certificado. Confirme que é um e-CNPJ ou e-CPF (A1). Nada foi salvo.', 'danger')
            return redirect(url_for('dfe_certificado.index'))
        validade_ate = _extrair_validade(cert)

        # nome do arquivo PADRONIZADO: {documento}.pfx (sem empresa nem senha no nome)
        nome_arquivo = f'{documento}.pfx'

        # --- 4) sobe o PFX pro Dropbox: /{documento}/{documento}.pfx ---
        caminho_dropbox = f'{_BASE_DROPBOX_CERT}/{documento}/{documento}.pfx'
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
                       (cliente_id, cnpj, tipo_doc, nome_arquivo, pfx_caminho, senha_cifrada,
                        validade_ate, modo_automatico, ativo)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE
                       cnpj            = VALUES(cnpj),
                       tipo_doc        = VALUES(tipo_doc),
                       nome_arquivo    = VALUES(nome_arquivo),
                       pfx_caminho     = VALUES(pfx_caminho),
                       senha_cifrada   = VALUES(senha_cifrada),
                       validade_ate    = VALUES(validade_ate),
                       modo_automatico = VALUES(modo_automatico),
                       ativo           = 1""",
                (int(cliente_id), documento, tipo_doc, nome_arquivo, pfx_caminho, senha_cifrada,
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
        flash(f'Certificado do {tipo_doc} {documento} salvo com sucesso (validade {val_str}).', 'success')
        return redirect(url_for('dfe_certificado.index'))

    # GET
    clientes = _carregar_clientes()
    certificados = _carregar_certificados()
    return render_template('dfe/certificado.html', clientes=clientes, certificados=certificados)
