"""Para onde voltar depois de uma ação feita a partir de uma lista.

Vive aqui, e não dentro de um blueprint, porque o problema é o mesmo em todas
as telas de lista: o filtro é o estado da tela, e voltar para a URL limpa
obriga o usuário a refazer empresa, conta, período e busca a cada linha
tratada.
"""

from urllib.parse import urlparse

from flask import request


def _interno(caminho):
    """Só caminho da própria aplicação: nada de `//host`, esquema ou host de
    fora — senão o POST vira redirecionamento aberto para um site qualquer."""
    if not caminho or not caminho.startswith('/') or caminho.startswith('//'):
        return None
    if '\\' in caminho or '\n' in caminho or '\r' in caminho:
        return None
    return caminho


def destino_pos_acao():
    """Devolve o caminho de volta preservando o filtro, ou None.

    Ordem: o campo `next` que a própria tela manda (explícito, imune a
    Referrer-Policy), depois o referrer do navegador. Quando nenhum dos dois
    serve, devolve None e quem chamou decide o destino padrão.
    """
    destino = _interno((request.form.get('next') or '').strip())
    if destino:
        return destino

    ref = (request.referrer or '').strip()
    if ref:
        try:
            partes = urlparse(ref)
        except Exception:
            return None
        # Mesmo host: o referrer de outro site não manda no nosso redirect.
        if partes.netloc and partes.netloc != request.host:
            return None
        caminho = partes.path + (('?' + partes.query) if partes.query else '')
        return _interno(caminho)
    return None
