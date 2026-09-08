# -*- coding: utf-8 -*-
"""NH-ROBO — o robo que traz o arquivo do colaborador para o Dropbox.

Cinco pessoas largam OFX e planilha numa pasta da maquina delas; o agente
entrega aqui; este servidor grava em /BANCOS/OFX/NOVO, que e a pasta que o
importador de extrato ja varre. Antes disso elas mandavam por mensagem e
alguem copiava na mao.

Duas metades:

  /api/nhrobo/*   o agente. Sem sessao, sem CSRF, autenticado por Bearer.
  /nh-robo/*      a tela do administrador: gerar e revogar chave, mudar a
                  data de corte, e ver o que chegou.

O NH-Robo e IRMAO do Q-Colabore do Qualicontax, nunca substituto: sao dois
robos, dois servidores, duas chaves. Numa maquina que tenha os dois, tudo o que
poderia colidir precisa de nome proprio -- pasta, chave do registro, porta da
trava de instancia unica e icone da bandeja.

O agente e o mesmo binario do Qualicontax (0.4.0) e NAO foi recompilado: ele
aceita o endereco do servidor pelo proprio config.json. Por isso os codigos de
HTTP abaixo sao contrato, nao escolha — ele decide pelo codigo, e trocar um
deles muda o comportamento nas cinco maquinas sem ninguem tocar nelas.
"""
import logging
import os
import re
from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user, login_required

from extensions import csrf
from utils import nhrobo
from utils.decorators import admin_required

bp = Blueprint('nhrobo', __name__)
_log = logging.getLogger(__name__)


def _token_do_header():
    auth = request.headers.get('Authorization') or ''
    return auth[7:].strip() if auth.lower().startswith('bearer ') else ''


def _quem():
    """(config, None) quando a chave existe; (None, resposta 401) quando nao."""
    cfg = nhrobo.config_por_token(_token_do_header())
    if not cfg:
        return None, (jsonify(status='nao_autorizado'), 401)
    return cfg, None


def _ip():
    # Atras do proxy da Railway o IP real vem no X-Forwarded-For.
    encaminhado = request.headers.get('X-Forwarded-For') or ''
    return (encaminhado.split(',')[0].strip() or request.remote_addr or '')


# ── o agente ──────────────────────────────────────────────────────────────────

# A segunda rota e PONTE DE TESTE, nao endereco oficial: o binario do
# Qualicontax tem "/api/colabore/..." literal dentro dele, e aceita trocar so o
# servidor pelo config.json. Com ela da para provar este servidor hoje, com o
# agente pronto, antes de compilar o nosso. Sai quando o NH-Robo existir.
@bp.route('/api/nhrobo/config', methods=['GET'])
@bp.route('/api/colabore/config', methods=['GET'])
@csrf.exempt
def api_config():
    """Onde o agente descobre ate onde voltar no tempo.

    A data de corte vive AQUI e nao na maquina: mudar de ideia sobre o periodo
    nao pode exigir visita a cinco computadores.
    """
    cfg, erro = _quem()
    if erro:
        return erro
    nhrobo.marcar_contato(cfg['usuario_id'])
    di = cfg.get('data_inicio_captura')
    return jsonify(funcionario=cfg.get('usuario_nome'),
                   ativo=bool(cfg['ativo']),
                   data_inicio_captura=di.isoformat() if di else None)


@bp.route('/api/nhrobo/enviar', methods=['POST'])
@bp.route('/api/colabore/enviar', methods=['POST'])   # ponte de teste (ver acima)
@csrf.exempt
def api_enviar():
    """Recebe UM arquivo (multipart, campo "arquivo") e grava no Dropbox."""
    cfg, erro = _quem()
    if erro:
        return erro

    # O carimbo vem antes da checagem de revogada: um agente com chave morta
    # continua dando sinal de vida, e e assim que se sabe que a maquina esta
    # ligada e o problema e a chave.
    nhrobo.marcar_contato(cfg['usuario_id'])
    if not cfg['ativo']:
        return jsonify(status='revogada'), 403

    arq = request.files.get('arquivo')
    if arq is None or not arq.filename:
        return jsonify(status='arquivo_ausente'), 422

    nome = nhrobo.sanitizar_nome(arq.filename)
    ext = nhrobo.extensao(nome)
    if ext not in nhrobo.EXTENSOES_PERMITIDAS:
        return jsonify(status='ext_negada',
                       extensoes=list(nhrobo.EXTENSOES_PERMITIDAS)), 415

    conteudo = arq.read()
    tamanho = len(conteudo)
    if tamanho > nhrobo.TAMANHO_MAX_BYTES:
        return jsonify(status='muito_grande',
                       limite_bytes=nhrobo.TAMANHO_MAX_BYTES), 413
    if not tamanho:
        # Arquivo vazio nao e erro de rede: mandar de novo daria vazio outra
        # vez. 415 encerra o assunto em vez de girar para sempre.
        return jsonify(status='arquivo_vazio'), 415

    try:
        if nhrobo.ja_esta_la(nome, tamanho):
            return jsonify(status='ja_existe', nome=nome), 409
        nome_final = nhrobo.guardar(nome, conteudo)
    except Exception as exc:
        # 5xx de proposito: o agente guarda o arquivo e tenta de novo. Um 4xx
        # aqui faria ele desistir de um arquivo bom por causa de uma queda do
        # Dropbox.
        _log.exception('[nhrobo] falha guardando %s de %s', nome,
                       cfg.get('usuario_login'))
        return jsonify(status='indisponivel', erro=str(exc)[:200]), 503

    try:
        nhrobo.registrar_recebido(cfg['usuario_id'], arq.filename, nome_final,
                                    ext, tamanho, _ip())
    except Exception:
        # O arquivo JA esta no Dropbox. Falhar aqui e perder a linha da tela,
        # nao o arquivo — e devolver erro faria o agente reenviar e duplicar.
        _log.exception('[nhrobo] arquivo gravado mas nao registrado: %s', nome_final)

    return jsonify(status='recebido', nome=nome_final), 200


# ── a tela ────────────────────────────────────────────────────────────────────

# A chave em claro atravessa o redirect por AQUI, e nao por flash: o base.html
# imprime todo flash automaticamente, entao o segredo saia cru no topo da pagina
# antes da caixa que era para mostra-lo. A sessao e por usuario, some na leitura
# (pop) e nao entra em log nem em historico do navegador.
_SESSAO_CHAVE = 'nhrobo_chave_nova'


@bp.route('/nh-robo/', methods=['GET'])
@login_required
@admin_required
def painel():
    # pop: a chave aparece na primeira tela depois de gerada e em nenhuma outra.
    # Um F5 nao a traz de volta — e nem deveria.
    return render_template('nhrobo/painel.html',
                           chave_nova=session.pop(_SESSAO_CHAVE, None),
                           pessoas=nhrobo.painel(),
                           recebidos=nhrobo.recebidos(),
                           destino=nhrobo.PASTA_DESTINO,
                           extensoes=nhrobo.EXTENSOES_PERMITIDAS,
                           limite_mb=nhrobo.TAMANHO_MAX_BYTES // (1024 * 1024))


def _data_do_form(campo='data_inicio'):
    bruto = (request.form.get(campo) or '').strip()
    if not bruto:
        return None
    try:
        return datetime.strptime(bruto, '%Y-%m-%d').date()
    except ValueError:
        return None


@bp.route('/nh-robo/chave/<int:uid>/gerar', methods=['POST'])
@login_required
@admin_required
def gerar(uid):
    regerar = request.form.get('regerar') == '1'
    token, erro = nhrobo.gerar_chave(uid, getattr(current_user, 'id', None),
                                       regerar=regerar,
                                       data_inicio=_data_do_form())
    if erro == 'ja_existe':
        flash('Essa pessoa já tem chave. Use "Regerar" — a antiga para de '
              'funcionar na hora.', 'warning')
    elif token:
        # Aparece UMA vez. Depois daqui só existe o hash, e nem o administrador
        # consegue ver de novo. Só o par (uid, token) viaja: o nome da pessoa e a
        # data de corte a tela já tem em mãos, e o que não viaja não vaza.
        session[_SESSAO_CHAVE] = {'uid': uid, 'token': token}
    return redirect(url_for('nhrobo.painel'))


@bp.route('/nh-robo/chave/<int:uid>/revogar', methods=['POST'])
@login_required
@admin_required
def revogar(uid):
    if nhrobo.revogar_chave(uid):
        flash('Chave revogada. O agente daquela máquina para de enviar no '
              'próximo ciclo e mostra o aviso.', 'success')
    else:
        flash('Essa pessoa não tem chave para revogar.', 'warning')
    return redirect(url_for('nhrobo.painel'))


@bp.route('/nh-robo/chave/<int:uid>/corte', methods=['POST'])
@login_required
@admin_required
def corte(uid):
    data = _data_do_form()
    ok, erro = nhrobo.definir_corte(uid, data)
    if erro == 'futura':
        flash('Data no futuro faria o agente ficar parado sem ninguém entender '
              'por quê. Escolha hoje ou uma data passada.', 'danger')
    elif ok:
        flash('Data de corte atualizada. O agente pega sozinho no próximo '
              'ciclo — não precisa mexer na máquina.', 'success')
    else:
        flash('Essa pessoa ainda não tem chave.', 'warning')
    return redirect(url_for('nhrobo.painel'))


# ── o instalador, para os cinco ───────────────────────────────────────────────
# Estas tres rotas sao para o COLABORADOR, nao para o administrador: login
# basta, nao precisa ser admin. E por elas que a pessoa instala o robo sem
# nunca encostar no Dropbox — se ela precisasse de um link de la, o robo
# perderia o proprio sentido.

@bp.route('/nh-robo/instalar', methods=['GET'])
@login_required
def instalar():
    """A pagina que o colaborador abre: baixar, e o manual ao lado."""
    return render_template('nhrobo/instalar.html',
                           destino=nhrobo.PASTA_DESTINO,
                           extensoes=nhrobo.EXTENSOES_PERMITIDAS,
                           limite_mb=nhrobo.TAMANHO_MAX_BYTES // (1024 * 1024))


@bp.route('/nh-robo/meus-envios', methods=['GET'])
@login_required
def meus_envios():
    """A prova, para o proprio colaborador. Login basta -- nao e tela de admin.

    O robo ja deixa um recibo na pasta da pessoa, mas aquilo e a palavra DELE.
    Esta tela le a tabela do servidor: e o que de fato chegou. Quando os dois
    discordarem, esta ganha -- e e ela que encerra a discussao sem o tecnico
    precisar abrir o Dropbox para conferir na mao.
    """
    uid = getattr(current_user, 'id', None)
    return render_template('nhrobo/meus_envios.html',
                           envios=nhrobo.meus_envios(uid),
                           estado=nhrobo.meu_estado(uid),
                           destino=nhrobo.PASTA_DESTINO,
                           extensoes=nhrobo.EXTENSOES_PERMITIDAS,
                           limite_mb=nhrobo.TAMANHO_MAX_BYTES // (1024 * 1024))


@bp.route('/nh-robo/instalador', methods=['GET'])
@login_required
def instalador():
    """Entrega o .zip do agente. O servidor busca no Dropbox e repassa."""
    from flask import Response
    from urllib.parse import quote
    try:
        nome, conteudo = nhrobo.instalador()
    except Exception:
        _log.exception('[nhrobo] falha buscando o instalador')
        nome, conteudo = None, None
    if not conteudo:
        flash('O instalador ainda não foi publicado. Ele precisa ser gerado '
              '(build_nhrobo.ps1) e colocado em %s no Dropbox.'
              % nhrobo.PASTA_INSTALADOR, 'warning')
        return redirect(url_for('nhrobo.instalar'))
    return Response(conteudo, mimetype='application/zip', headers={
        'Content-Disposition': "attachment; filename=\"%s\"; filename*=UTF-8''%s"
                               % (re.sub(r'[^A-Za-z0-9._-]', '_', nome), quote(nome)),
        'Content-Length': str(len(conteudo)),
    })


@bp.route('/nh-robo/manual', methods=['GET'])
@login_required
def manual():
    """O passo a passo da instalacao, entregue pelo proprio app."""
    from flask import current_app, send_from_directory
    return send_from_directory(
        os.path.join(current_app.root_path, 'agente_nhrobo'),
        'LEIA-ME-instalacao.html')
