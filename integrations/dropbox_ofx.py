"""
Integração com a API do Dropbox para leitura automática de arquivos OFX.

Fluxo:
  1. O usuário coloca o arquivo OFX na pasta Dropbox local
     (ex: C:\\Users\\ander\\Dropbox\\BANCOS\\OFX\\NOVO).
  2. O Dropbox sincroniza automaticamente para a nuvem.
  3. O servidor Render/Railway usa este módulo para:
     a. Listar arquivos .ofx em DROPBOX_OFX_INBOX
     b. Baixar o conteúdo de um arquivo específico
     c. Mover o arquivo para DROPBOX_OFX_PROCESSED após importação

Configuração necessária (variáveis de ambiente):
  DROPBOX_TOKEN          – token de acesso longo (gerado no Dropbox App Console)
  DROPBOX_OFX_INBOX      – caminho Dropbox ex: /BANCOS/OFX/NOVO  (padrão: /BANCOS/OFX/NOVO)
  DROPBOX_OFX_PROCESSED  – caminho Dropbox ex: /BANCOS/OFX/IMPORTADOS (padrão: /BANCOS/OFX/IMPORTADOS)

Como gerar o DROPBOX_TOKEN:
  1. Acesse https://www.dropbox.com/developers/apps
  2. Clique em "Create app" -> Scoped access -> Full Dropbox
  3. Em "Permissions", habilite: files.content.read, files.content.write, files.metadata.read
  4. Na aba "Settings", em "OAuth 2" -> "Generated access token", clique em "Generate"
  5. Copie o token e configure como variável de ambiente DROPBOX_TOKEN no Render/Railway
"""

import os

# Importação lazy para não quebrar o app se o pacote não estiver instalado
try:
    import dropbox
    from dropbox.exceptions import ApiError, AuthError
    from dropbox.files import WriteMode
    _DROPBOX_AVAILABLE = True
except ImportError:
    _DROPBOX_AVAILABLE = False


def _get_config():
    """Retorna (token, inbox_path, processed_path) a partir das variáveis de ambiente."""
    token = os.environ.get('DROPBOX_TOKEN', '').strip()
    inbox = (os.environ.get('DROPBOX_OFX_INBOX', '/BANCOS/OFX/NOVO') or '').rstrip('/')
    processed = (os.environ.get('DROPBOX_OFX_PROCESSED', '/BANCOS/OFX/IMPORTADOS') or '').rstrip('/')
    # Garante barra inicial (padrão Dropbox API)
    if inbox and not inbox.startswith('/'):
        inbox = '/' + inbox
    if processed and not processed.startswith('/'):
        processed = '/' + processed
    return token, inbox, processed


def is_configured() -> bool:
    """Retorna True se DROPBOX_TOKEN estiver definido e o pacote dropbox instalado."""
    if not _DROPBOX_AVAILABLE:
        return False
    token, _, _ = _get_config()
    return bool(token)


def get_inbox_paths() -> tuple:
    """Retorna (inbox_path, processed_path) configurados."""
    _, inbox, processed = _get_config()
    return inbox, processed


def listar_arquivos_ofx() -> list:
    """
    Lista arquivos .ofx na pasta DROPBOX_OFX_INBOX.

    Retorna lista de dicts com chaves: nome, tamanho, modificado (str dd/mm/YYYY HH:MM), path_lower.
    Lança RuntimeError em caso de falha.
    """
    if not _DROPBOX_AVAILABLE:
        raise RuntimeError('Pacote "dropbox" não instalado. Execute: pip install dropbox==12.0.2')

    token, inbox, _ = _get_config()
    if not token:
        raise RuntimeError('DROPBOX_TOKEN não configurado.')

    dbx = dropbox.Dropbox(token)

    try:
        result = dbx.files_list_folder(inbox)
    except AuthError:
        raise RuntimeError('Token Dropbox inválido ou expirado. Gere um novo token no Dropbox App Console.')
    except ApiError as exc:
        raise RuntimeError(f'Erro ao acessar pasta Dropbox "{inbox}": {exc}')

    arquivos = []
    entradas = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entradas.extend(result.entries)

    for entry in entradas:
        # Ignora subpastas e arquivos que não sejam .ofx
        if not hasattr(entry, 'size'):
            continue
        if not entry.name.lower().endswith('.ofx'):
            continue
        mod = entry.client_modified or entry.server_modified
        arquivos.append({
            'nome': entry.name,
            'tamanho': entry.size,
            'modificado': mod.strftime('%d/%m/%Y %H:%M') if mod else '',
            'path_lower': entry.path_lower,
        })

    arquivos.sort(key=lambda x: x['nome'])
    return arquivos


def baixar_arquivo(nome_arquivo: str) -> str:
    """
    Baixa o conteúdo de um arquivo OFX do Dropbox e retorna como string (latin-1).

    Parâmetros:
        nome_arquivo – nome simples do arquivo (sem caminho), ex: "extrato_jan.ofx"

    Lança RuntimeError em caso de falha ou arquivo não encontrado.
    """
    if not _DROPBOX_AVAILABLE:
        raise RuntimeError('Pacote "dropbox" não instalado.')

    # Segurança: apenas nomes simples
    nome_arquivo = os.path.basename(nome_arquivo)
    if not nome_arquivo.lower().endswith('.ofx'):
        raise RuntimeError('Apenas arquivos .ofx são aceitos.')

    token, inbox, _ = _get_config()
    if not token:
        raise RuntimeError('DROPBOX_TOKEN não configurado.')

    dbx = dropbox.Dropbox(token)
    caminho = f'{inbox}/{nome_arquivo}'

    try:
        _, response = dbx.files_download(caminho)
    except ApiError as exc:
        raise RuntimeError(f'Arquivo não encontrado no Dropbox: {caminho} — {exc}')

    return response.content.decode('latin-1', errors='replace')


def mover_para_processados(nome_arquivo: str) -> None:
    """
    Move um arquivo OFX de DROPBOX_OFX_INBOX para DROPBOX_OFX_PROCESSED.

    Adiciona prefixo de timestamp caso o arquivo já exista no destino.
    Erros de movimentação são ignorados (não críticos — o arquivo já foi importado).
    """
    if not _DROPBOX_AVAILABLE:
        return

    nome_arquivo = os.path.basename(nome_arquivo)
    token, inbox, processed = _get_config()
    if not token:
        return

    dbx = dropbox.Dropbox(token)
    origem = f'{inbox}/{nome_arquivo}'
    destino = f'{processed}/{nome_arquivo}'

    try:
        dbx.files_move_v2(origem, destino, autorename=True)
    except Exception:
        pass  # Não crítico – o arquivo foi importado com sucesso
