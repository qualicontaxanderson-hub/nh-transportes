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
import re

# Importação lazy para não quebrar o app se o pacote não estiver instalado
try:
    import dropbox
    from dropbox.exceptions import ApiError, AuthError
    from dropbox.files import WriteMode
    _DROPBOX_AVAILABLE = True
except ImportError:
    _DROPBOX_AVAILABLE = False


def _normalizar_caminho(caminho: str) -> str:
    """
    Normaliza um caminho para o formato Dropbox API (barra inicial, barras Linux).

    Suporta:
    - Caminhos Dropbox relativos: "BANCOS/OFX/NOVO" → "/BANCOS/OFX/NOVO"
    - Caminhos Windows completos: "C:\\Users\\user\\Dropbox\\BANCOS\\OFX\\NOVO"
      → extrai a parte após "Dropbox\\" → "/BANCOS/OFX/NOVO"
    """
    if not caminho:
        return caminho
    # Normaliza separadores Windows para Linux
    caminho = caminho.replace('\\', '/')
    # Se for caminho Windows completo contendo "/Dropbox/", extrai a parte relativa
    idx = caminho.lower().find('/dropbox/')
    if idx != -1:
        caminho = caminho[idx + len('/dropbox'):]
    # Remove barra final e garante barra inicial
    caminho = caminho.rstrip('/')
    if caminho and not caminho.startswith('/'):
        caminho = '/' + caminho
    return caminho


def _get_config():
    """Retorna (token, inbox_path, processed_path) a partir das variáveis de ambiente."""
    token = os.environ.get('DROPBOX_TOKEN', '').strip()
    inbox = _normalizar_caminho(
        (os.environ.get('DROPBOX_OFX_INBOX', '/BANCOS/OFX/NOVO') or '').strip()
    )
    processed = _normalizar_caminho(
        (os.environ.get('DROPBOX_OFX_PROCESSED', '/BANCOS/OFX/IMPORTADOS') or '').strip()
    )
    return token, inbox, processed


def _criar_dbx():
    """
    Cria e retorna um objeto Dropbox autenticado.

    Prioridade:
    1. OAuth2 com refresh token (DROPBOX_APP_KEY + DROPBOX_APP_SECRET + DROPBOX_REFRESH_TOKEN)
       → token renovado automaticamente, nunca expira.
    2. Token de acesso direto (DROPBOX_TOKEN)
       → expira em ~4 horas, precisa ser renovado manualmente.

    Lança RuntimeError se nenhuma credencial estiver configurada.
    """
    if not _DROPBOX_AVAILABLE:
        raise RuntimeError('Pacote "dropbox" não instalado. Execute: pip install dropbox')

    app_key     = os.environ.get('DROPBOX_APP_KEY', '').strip()
    app_secret  = os.environ.get('DROPBOX_APP_SECRET', '').strip()
    refresh_tok = os.environ.get('DROPBOX_REFRESH_TOKEN', '').strip()

    if app_key and app_secret and refresh_tok:
        # OAuth2 offline — token renovado automaticamente
        return dropbox.Dropbox(
            oauth2_refresh_token=refresh_tok,
            app_key=app_key,
            app_secret=app_secret,
        )

    token, _, _ = _get_config()
    if token:
        # Token de curta duração — expira em ~4 horas
        return dropbox.Dropbox(token)

    raise RuntimeError(
        'Dropbox não configurado. Configure DROPBOX_APP_KEY + DROPBOX_APP_SECRET + '
        'DROPBOX_REFRESH_TOKEN (recomendado) ou DROPBOX_TOKEN no Render.'
    )


def usa_oauth2() -> bool:
    """Retorna True quando está usando OAuth2 com refresh token (método permanente)."""
    return bool(
        os.environ.get('DROPBOX_APP_KEY', '').strip() and
        os.environ.get('DROPBOX_APP_SECRET', '').strip() and
        os.environ.get('DROPBOX_REFRESH_TOKEN', '').strip()
    )


def is_configured() -> bool:
    """Retorna True se alguma credencial Dropbox estiver definida e o pacote instalado."""
    if not _DROPBOX_AVAILABLE:
        return False
    if usa_oauth2():
        return True
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

    _, inbox, _ = _get_config()

    try:
        dbx = _criar_dbx()
    except RuntimeError:
        raise

    try:
        result = dbx.files_list_folder(inbox)
    except AuthError:
        if usa_oauth2():
            raise RuntimeError(
                'Erro de autenticação Dropbox (OAuth2). Verifique se DROPBOX_APP_KEY, '
                'DROPBOX_APP_SECRET e DROPBOX_REFRESH_TOKEN estão corretos no Render.'
            )
        raise RuntimeError(
            'Token Dropbox inválido ou expirado. '
            'Configure OAuth2 com refresh token para não precisar renovar manualmente: '
            'adicione DROPBOX_APP_KEY, DROPBOX_APP_SECRET e DROPBOX_REFRESH_TOKEN no Render.'
        )
    except ApiError as exc:
        erro_str = str(exc).lower()
        if 'not_found' in erro_str or 'path' in erro_str:
            raise RuntimeError(
                f'Pasta não encontrada no Dropbox: "{inbox}". '
                f'Verifique se a pasta existe no seu Dropbox e se o valor de '
                f'DROPBOX_OFX_INBOX está correto (use apenas o caminho relativo, '
                f'ex: /BANCOS/OFX/NOVO — sem "C:\\\\Users\\\\..." na frente).'
            )
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
    """
    if not _DROPBOX_AVAILABLE:
        raise RuntimeError('Pacote "dropbox" não instalado.')

    nome_arquivo = os.path.basename(nome_arquivo)
    if not nome_arquivo.lower().endswith('.ofx'):
        raise RuntimeError('Apenas arquivos .ofx são aceitos.')

    _, inbox, _ = _get_config()
    dbx = _criar_dbx()
    caminho = f'{inbox}/{nome_arquivo}'

    try:
        _, response = dbx.files_download(caminho)
    except ApiError as exc:
        raise RuntimeError(f'Arquivo não encontrado no Dropbox: {caminho} — {exc}')

    return response.content.decode('latin-1', errors='replace')


def extrair_acctid_ofx(nome_arquivo: str) -> str | None:
    """
    Baixa o arquivo OFX e retorna apenas os dígitos do ACCTID (número da conta)
    encontrado no cabeçalho OFX, ou None em caso de falha.

    Usado para verificar se um arquivo Dropbox realmente pertence à conta selecionada
    quando o nome do arquivo não contém o número da conta.
    """
    try:
        content = baixar_arquivo(nome_arquivo)
        # Busca a tag ACCTID sem precisar do parser completo — mais rápido
        m = re.search(r'<ACCTID>\s*([^\s<]+)', content, re.IGNORECASE)
        if m:
            return re.sub(r'\D', '', m.group(1))
    except Exception:
        pass
    return None


def mover_para_processados(nome_arquivo: str) -> None:
    """
    Move um arquivo OFX de DROPBOX_OFX_INBOX para DROPBOX_OFX_PROCESSED.
    Erros são ignorados (não críticos — o arquivo já foi importado).
    """
    if not _DROPBOX_AVAILABLE:
        return

    nome_arquivo = os.path.basename(nome_arquivo)
    _, inbox, processed = _get_config()

    try:
        dbx = _criar_dbx()
        origem = f'{inbox}/{nome_arquivo}'
        destino = f'{processed}/{nome_arquivo}'
        dbx.files_move_v2(origem, destino, autorename=True)
    except Exception:
        pass  # Não crítico – o arquivo foi importado com sucesso
