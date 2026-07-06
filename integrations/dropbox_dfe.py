"""
Upload/exclusão de XML de DFe (NF-e / CT-e) no Dropbox.

Reaproveita a autenticação do módulo OFX existente (integrations/dropbox_ofx.py):
NÃO duplica lógica de credencial — importa `_criar_dbx()` e `_normalizar_caminho()`
de lá. Assim NF-e/CT-e e OFX usam a MESMA credencial OAuth2.

Escopo Dropbox: Full Dropbox (mesmo do OFX). Precisa de files.content.write e
files.content.read (já habilitados no app do Dropbox).

Padrão de caminho dos XML:
    /FISCAL/DFe/{cnpj}/{ano}/{mes}/{chave}.xml

Erros: qualquer falha do Dropbox levanta RuntimeError com mensagem clara —
nunca é engolida (a captura de DFe precisa saber se o XML foi mesmo gravado).
"""
import os

# Reaproveita a autenticação e a normalização de caminho do módulo OFX.
# Import no topo para falhar cedo caso o módulo/base mude.
from integrations.dropbox_ofx import _criar_dbx, _normalizar_caminho

# WriteMode vem do pacote oficial dropbox. Import protegido: se o pacote não
# estiver instalado, só quebra quando o upload for realmente chamado.
try:
    from dropbox.files import WriteMode
    from dropbox.exceptions import ApiError
    _DROPBOX_AVAILABLE = True
except ImportError:
    WriteMode = None
    ApiError = Exception
    _DROPBOX_AVAILABLE = False


def montar_caminho(cnpj: str, ano, mes, chave: str) -> str:
    """
    Monta o caminho Dropbox padrão de um XML de DFe:
        /FISCAL/DFe/{cnpj}/{ano}/{mes}/{chave}.xml

    - cnpj: só dígitos (14). Espaços/pontuação são removidos.
    - ano: ex. 2026 (int ou str).
    - mes: ex. 7 ou '07' — normalizado para 2 dígitos.
    - chave: chave de acesso de 44 dígitos.

    Retorna o path normalizado (barra inicial, barras Linux).
    """
    cnpj_digitos = ''.join(ch for ch in str(cnpj) if ch.isdigit())
    if not cnpj_digitos:
        raise ValueError("montar_caminho: cnpj sem dígitos")
    if not chave:
        raise ValueError("montar_caminho: chave vazia")

    mes_norm = str(mes).zfill(2)
    raw = f"/FISCAL/DFe/{cnpj_digitos}/{ano}/{mes_norm}/{chave}.xml"
    return _normalizar_caminho(raw)


def upload_arquivo(caminho_dropbox: str, conteudo_bytes: bytes) -> dict:
    """
    Envia bytes para um caminho no Dropbox, sobrescrevendo se já existir.
    Genérico — serve para XML, PFX ou qualquer arquivo.

    Args:
        caminho_dropbox: path Dropbox (ex.: saída de montar_caminho()).
        conteudo_bytes:  bytes do arquivo (str é aceito e vira utf-8).

    Retorna dict com {path, tamanho} em caso de sucesso.
    Levanta RuntimeError com mensagem clara em qualquer falha.
    """
    if not _DROPBOX_AVAILABLE:
        raise RuntimeError('Pacote "dropbox" não instalado. Execute: pip install dropbox==12.0.2')
    if not caminho_dropbox:
        raise RuntimeError("upload_arquivo: caminho_dropbox vazio")
    if conteudo_bytes is None:
        raise RuntimeError("upload_arquivo: conteudo_bytes é None")
    if isinstance(conteudo_bytes, str):
        conteudo_bytes = conteudo_bytes.encode('utf-8')

    caminho = _normalizar_caminho(caminho_dropbox)

    try:
        dbx = _criar_dbx()
        meta = dbx.files_upload(conteudo_bytes, caminho, mode=WriteMode('overwrite'))
    except ApiError as exc:
        raise RuntimeError(f'Falha ao enviar arquivo para o Dropbox em "{caminho}": {exc}') from exc
    except Exception as exc:
        raise RuntimeError(f'Erro inesperado ao enviar arquivo para o Dropbox em "{caminho}": {exc}') from exc

    return {"path": getattr(meta, "path_lower", caminho), "tamanho": len(conteudo_bytes)}


def upload_xml(caminho_dropbox: str, conteudo_bytes: bytes) -> dict:
    """
    Envia o conteúdo de um XML para o Dropbox, sobrescrevendo se já existir.
    Fina camada semântica sobre upload_arquivo() (comportamento idêntico).
    """
    return upload_arquivo(caminho_dropbox, conteudo_bytes)


def apagar_xml(caminho_dropbox: str) -> bool:
    """
    Apaga um XML do Dropbox (usado na limpeza de retenção dos 3 meses).

    Retorna True se apagou. Se o arquivo já não existir, retorna False
    (não é erro — o objetivo, "não existir mais", já está atendido).
    Qualquer outra falha do Dropbox levanta RuntimeError.
    """
    if not _DROPBOX_AVAILABLE:
        raise RuntimeError('Pacote "dropbox" não instalado. Execute: pip install dropbox==12.0.2')
    if not caminho_dropbox:
        raise RuntimeError("apagar_xml: caminho_dropbox vazio")

    caminho = _normalizar_caminho(caminho_dropbox)

    try:
        dbx = _criar_dbx()
        dbx.files_delete_v2(caminho)
        return True
    except ApiError as exc:
        # 'not_found' → o arquivo já não existe; tratamos como sucesso silencioso.
        if 'not_found' in str(exc).lower():
            return False
        raise RuntimeError(f'Falha ao apagar XML no Dropbox em "{caminho}": {exc}') from exc
    except Exception as exc:
        raise RuntimeError(f'Erro inesperado ao apagar XML no Dropbox em "{caminho}": {exc}') from exc
