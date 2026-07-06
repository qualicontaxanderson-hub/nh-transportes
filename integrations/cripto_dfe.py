"""
Cifra/decifra a senha do certificado A1 (PFX) do serviço de captura de DFe.

Usa cryptography.fernet (AES-128 em modo CBC + HMAC, autenticado). A chave-mestra
NUNCA é hardcoded: vem exclusivamente de os.environ['DFE_CRYPTO_KEY'].

Fluxo:
  - No banco (dfe_certificados.senha_cifrada VARBINARY) guarda-se o token Fernet
    (bytes) retornado por cifrar_senha().
  - Na hora de assinar/consultar a SEFAZ, decifra_senha() devolve o texto puro
    apenas em memória.

Para gerar a chave-mestra (uma única vez) e configurá-la no Railway:
    python -c "from integrations.cripto_dfe import gerar_chave; gerar_chave()"
    -> copie a linha impressa e crie a variável DFE_CRYPTO_KEY no Railway.
"""
import os

from cryptography.fernet import Fernet, InvalidToken

_ENV_VAR = 'DFE_CRYPTO_KEY'


def _get_fernet() -> Fernet:
    """
    Constrói o Fernet a partir de DFE_CRYPTO_KEY. Levanta RuntimeError claro
    se a variável não estiver configurada ou for inválida.
    """
    chave = os.environ.get(_ENV_VAR, '').strip()
    if not chave:
        raise RuntimeError(
            f"A variável de ambiente {_ENV_VAR} não está configurada. "
            f"Gere uma chave com: "
            f'python -c "from integrations.cripto_dfe import gerar_chave; gerar_chave()" '
            f"e configure-a como {_ENV_VAR} no Railway (serviço do app NH) antes de "
            f"usar certificados de DFe."
        )
    try:
        # Fernet aceita a chave como bytes (urlsafe base64, 32 bytes decodificados).
        return Fernet(chave.encode('utf-8') if isinstance(chave, str) else chave)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"{_ENV_VAR} inválida (não é uma chave Fernet urlsafe-base64 de 32 bytes). "
            f"Gere uma nova com gerar_chave(). Detalhe: {exc}"
        ) from exc


def cifrar_senha(texto: str) -> bytes:
    """
    Cifra a senha do certificado. Recebe texto (str) e devolve o token Fernet (bytes)
    pronto para gravar em dfe_certificados.senha_cifrada.
    """
    if texto is None:
        raise ValueError("cifrar_senha: texto é None")
    f = _get_fernet()
    return f.encrypt(texto.encode('utf-8'))


def decifrar_senha(dados: bytes) -> str:
    """
    Decifra o token Fernet (bytes lidos do banco) e devolve a senha em texto (str).
    Levanta RuntimeError se o token for inválido (chave errada/corrompido).
    """
    if not dados:
        raise ValueError("decifrar_senha: dados vazios")
    f = _get_fernet()
    if isinstance(dados, str):
        dados = dados.encode('utf-8')
    try:
        return f.decrypt(dados).decode('utf-8')
    except InvalidToken as exc:
        raise RuntimeError(
            "Não foi possível decifrar a senha do certificado: token inválido. "
            f"A {_ENV_VAR} atual pode ser diferente da que cifrou o dado."
        ) from exc


def gerar_chave() -> bytes:
    """
    Gera e imprime uma chave-mestra Fernet nova para configurar em DFE_CRYPTO_KEY.
    Uso manual (uma vez): o valor impresso deve ir para o Railway, não para o código.
    Retorna a chave (bytes) também, para uso programático se necessário.
    """
    chave = Fernet.generate_key()
    print(f"{_ENV_VAR}={chave.decode('utf-8')}")
    return chave
