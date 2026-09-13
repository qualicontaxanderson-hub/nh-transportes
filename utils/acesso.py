# -*- coding: utf-8 -*-
"""Quem entra onde — a regra do Anderson: "o certo é só ter acesso ao que
consegue ver".

O menu de cada nivel ja dizia o que a pessoa deveria usar. O que faltava era
alguem BARRAR o resto: ate aqui o menu escondia e a rota deixava passar, entao
o GERENTE, o SUPERVISOR e o PISTA abriam as mesmas 16 de 24 telas testadas --
financeiro e folha inclusive -- bastando digitar o endereco.

A tabela abaixo e a lista do que cada nivel ALCANCA, e nasceu do proprio menu
dele. Quem nao esta na tabela (hoje, so o ADMIN) continua alcancando tudo.

Por que aqui e nao um decorador em cada rota: sao 428 rotas. Espalhar a regra
por elas garante que uma nova rota nasca sem trava e ninguem perceba -- foi
exatamente assim que se chegou ao estado de hoje. Aqui a regra e uma so, se le
de cima a baixo, e o padrao e NEGAR: rota nova ja nasce fechada para quem nao
e admin, e so abre quando alguem escrever aqui que deve abrir.

As regras sao prefixos de caminho. '/troco_pix/pista' NAO libera
'/troco_pix/' inteiro; libera o que comeca com ele. E por isso que o PISTA
tem varias linhas em vez de uma: a tela dele conversa com quatro outras, e
'/troco_pix' de uma vez entregaria o modulo todo, que nao e o pedido.
"""
from flask import (current_app, flash, jsonify, redirect, request, url_for)
from flask_login import current_user

# ---------------------------------------------------------------------------
# O que todo mundo que esta logado alcanca, em qualquer nivel: sair, trocar a
# propria senha, e os arquivos da pagina. Sem isso a trava prenderia a pessoa
# dentro do sistema sem conseguir nem deslogar.
# ---------------------------------------------------------------------------
COMUM = (
    '/static',
    '/auth/logout',
    '/auth/perfil',
    '/auth/alterar-senha',
    '/auth/login',
    '/health',
    '/favicon.ico',
)

# ---------------------------------------------------------------------------
# Cada nivel, o que ele ve no menu -- e agora tambem o que ele alcanca.
# 'casa' e para onde ele vai quando cai na raiz ou tenta o que nao pode.
# ---------------------------------------------------------------------------
NIVEIS = {
    'PISTA': {
        'casa': '/troco_pix/pista',
        'rotas': (
            '/troco_pix/pista',
            # A tela da pista conversa com estas quatro. Sem elas o frentista
            # abre a tela e nao consegue fazer nada: nao lanca, nao corrige,
            # nao ve o que lancou, e nao acha o cliente.
            '/troco_pix/novo',
            '/troco_pix/editar',
            '/troco_pix/visualizar',
            '/troco_pix/clientes',
            '/troco_pix/cliente',
        ),
    },
    'SUPERVISOR': {
        'casa': '/lancamentos_caixa/',
        'rotas': (
            '/cartoes',
            '/caixa',
            '/tipos_receita_caixa',
            '/lubrificantes',
            '/descargas',
            '/quilometragem',
            '/arla',
            '/posto',
            '/lancamentos_caixa',
            '/troco_pix',
        ),
    },
    'GERENTE': {
        'casa': '/descargas/',
        'rotas': (
            '/descargas',
            '/troco_pix',
        ),
    },
}


def _nivel_de(usuario):
    return (getattr(usuario, 'nivel', '') or '').strip().upper()


def pode(nivel, caminho):
    """Esse nivel alcanca esse caminho?

    ADMIN (e qualquer nivel que nao esteja na tabela) alcanca tudo: a trava
    so existe para quem tem uma lista escrita. Assim, mexer nisto nunca
    derruba o administrador de dentro do proprio sistema.
    """
    regra = NIVEIS.get(nivel)
    if regra is None:
        return True
    if caminho.startswith(COMUM):
        return True
    return caminho.startswith(tuple(regra['rotas']))


def casa_de(nivel):
    regra = NIVEIS.get(nivel)
    return regra['casa'] if regra else '/'


def registrar(app):
    """Liga a trava no app. Roda antes de cada requisicao."""

    @app.before_request
    def _porteiro():
        # quem nao esta logado e problema do flask-login, nao deste porteiro
        if not getattr(current_user, 'is_authenticated', False):
            return None
        nivel = _nivel_de(current_user)
        if nivel not in NIVEIS:
            return None

        caminho = request.path
        if caminho == '/':
            # a raiz manda todo mundo para fretes, que estes niveis nao veem
            return redirect(casa_de(nivel))
        if pode(nivel, caminho):
            return None

        current_app.logger.info('[acesso] %s (%s) barrado em %s',
                                getattr(current_user, 'username', '?'),
                                nivel, caminho)
        # Tela pede HTML; javascript pede JSON. Devolver uma pagina inteira
        # para um fetch faria a tela quebrar calada em vez de dizer o que
        # houve.
        if (request.is_json
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or 'application/json' in (request.headers.get('Accept') or '')):
            return jsonify(ok=False,
                           erro='Seu acesso não inclui esta tela.'), 403
        flash('Seu acesso não inclui essa tela.', 'warning')
        return redirect(casa_de(nivel))

    app.logger.info('[acesso] porteiro ligado para %s',
                    ', '.join(sorted(NIVEIS)))
