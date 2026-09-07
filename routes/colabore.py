# -*- coding: utf-8 -*-
"""Q-COLABORE — o robo que traz o arquivo do colaborador para o Dropbox.

Cinco pessoas largam OFX e planilha numa pasta da maquina delas; o agente
entrega aqui; este servidor grava em /BANCOS/OFX/NOVO, que e a pasta que o
importador de extrato ja varre. Antes disso elas mandavam por mensagem e
alguem copiava na mao.

Duas metades:

  /api/colabore/*   o agente. Sem sessao, sem CSRF, autenticado por Bearer.
  /colabore/*       a tela do administrador: gerar e revogar chave, mudar a
                    data de corte, e ver o que chegou.

O agente e o mesmo binario do Qualicontax (0.4.0) e NAO foi recompilado: ele
aceita o endereco do servidor pelo proprio config.json. Por isso os codigos de
HTTP abaixo sao contrato, nao escolha — ele decide pelo codigo, e trocar um
deles muda o comportamento nas cinco maquinas sem ninguem tocar nelas.
"""
import logging
from datetime import datetime

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required

from extensions import csrf
from utils import colabore
from utils.decorators import admin_required

bp = Blueprint('colabore', __name__)
_log = logging.getLogger(__name__)


def _token_do_header():
    auth = request.headers.get('Authorization') or ''
    return auth[7:].strip() if auth.lower().startswith('bearer ') else ''


def _quem():
    """(config, None) quando a chave existe; (None, resposta 401) quando nao."""
    cfg = colabore.config_por_token(_token_do_header())
    if not cfg:
        return None, (jsonify(status='nao_autorizado'), 401)
    return cfg, None


def _ip():
    # Atras do proxy da Railway o IP real vem no X-Forwarded-For.
    encaminhado = request.headers.get('X-Forwarded-For') or ''
    return (encaminhado.split(',')[0].strip() or request.remote_addr or '')


# ── o agente ──────────────────────────────────────────────────────────────────

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
    colabore.marcar_contato(cfg['usuario_id'])
    di = cfg.get('data_inicio_captura')
    return jsonify(funcionario=cfg.get('usuario_nome'),
                   ativo=bool(cfg['ativo']),
                   data_inicio_captura=di.isoformat() if di else None)


@bp.route('/api/colabore/enviar', methods=['POST'])
@csrf.exempt
def api_enviar():
    """Recebe UM arquivo (multipart, campo "arquivo") e grava no Dropbox."""
    cfg, erro = _quem()
    if erro:
        return erro

    # O carimbo vem antes da checagem de revogada: um agente com chave morta
    # continua dando sinal de vida, e e assim que se sabe que a maquina esta
    # ligada e o problema e a chave.
    colabore.marcar_contato(cfg['usuario_id'])
    if not cfg['ativo']:
        return jsonify(status='revogada'), 403

    arq = request.files.get('arquivo')
    if arq is None or not arq.filename:
        return jsonify(status='arquivo_ausente'), 422

    nome = colabore.sanitizar_nome(arq.filename)
    ext = colabore.extensao(nome)
    if ext not in colabore.EXTENSOES_PERMITIDAS:
        return jsonify(status='ext_negada',
                       extensoes=list(colabore.EXTENSOES_PERMITIDAS)), 415

    conteudo = arq.read()
    tamanho = len(conteudo)
    if tamanho > colabore.TAMANHO_MAX_BYTES:
        return jsonify(status='muito_grande',
                       limite_bytes=colabore.TAMANHO_MAX_BYTES), 413
    if not tamanho:
        # Arquivo vazio nao e erro de rede: mandar de novo daria vazio outra
        # vez. 415 encerra o assunto em vez de girar para sempre.
        return jsonify(status='arquivo_vazio'), 415

    try:
        if colabore.ja_esta_la(nome, tamanho):
            return jsonify(status='ja_existe', nome=nome), 409
        nome_final = colabore.guardar(nome, conteudo)
    except Exception as exc:
        # 5xx de proposito: o agente guarda o arquivo e tenta de novo. Um 4xx
        # aqui faria ele desistir de um arquivo bom por causa de uma queda do
        # Dropbox.
        _log.exception('[colabore] falha guardando %s de %s', nome,
                       cfg.get('usuario_login'))
        return jsonify(status='indisponivel', erro=str(exc)[:200]), 503

    try:
        colabore.registrar_recebido(cfg['usuario_id'], arq.filename, nome_final,
                                    ext, tamanho, _ip())
    except Exception:
        # O arquivo JA esta no Dropbox. Falhar aqui e perder a linha da tela,
        # nao o arquivo — e devolver erro faria o agente reenviar e duplicar.
        _log.exception('[colabore] arquivo gravado mas nao registrado: %s', nome_final)

    return jsonify(status='recebido', nome=nome_final), 200


# ── a tela ────────────────────────────────────────────────────────────────────

@bp.route('/colabore/', methods=['GET'])
@login_required
@admin_required
def painel():
    return render_template('colabore/painel.html',
                           pessoas=colabore.painel(),
                           recebidos=colabore.recebidos(),
                           destino=colabore.PASTA_DESTINO,
                           extensoes=colabore.EXTENSOES_PERMITIDAS,
                           limite_mb=colabore.TAMANHO_MAX_BYTES // (1024 * 1024))


def _data_do_form(campo='data_inicio'):
    bruto = (request.form.get(campo) or '').strip()
    if not bruto:
        return None
    try:
        return datetime.strptime(bruto, '%Y-%m-%d').date()
    except ValueError:
        return None


@bp.route('/colabore/chave/<int:uid>/gerar', methods=['POST'])
@login_required
@admin_required
def gerar(uid):
    regerar = request.form.get('regerar') == '1'
    token, erro = colabore.gerar_chave(uid, getattr(current_user, 'id', None),
                                       regerar=regerar,
                                       data_inicio=_data_do_form())
    if erro == 'ja_existe':
        flash('Essa pessoa já tem chave. Use "Regerar" — a antiga para de '
              'funcionar na hora.', 'warning')
    elif token:
        # Aparece UMA vez. Depois daqui só existe o hash, e nem o administrador
        # consegue ver de novo.
        flash('CHAVE|%d|%s' % (uid, token), 'chave')
    return redirect(url_for('colabore.painel'))


@bp.route('/colabore/chave/<int:uid>/revogar', methods=['POST'])
@login_required
@admin_required
def revogar(uid):
    if colabore.revogar_chave(uid):
        flash('Chave revogada. O agente daquela máquina para de enviar no '
              'próximo ciclo e mostra o aviso.', 'success')
    else:
        flash('Essa pessoa não tem chave para revogar.', 'warning')
    return redirect(url_for('colabore.painel'))


@bp.route('/colabore/chave/<int:uid>/corte', methods=['POST'])
@login_required
@admin_required
def corte(uid):
    data = _data_do_form()
    ok, erro = colabore.definir_corte(uid, data)
    if erro == 'futura':
        flash('Data no futuro faria o agente ficar parado sem ninguém entender '
              'por quê. Escolha hoje ou uma data passada.', 'danger')
    elif ok:
        flash('Data de corte atualizada. O agente pega sozinho no próximo '
              'ciclo — não precisa mexer na máquina.', 'success')
    else:
        flash('Essa pessoa ainda não tem chave.', 'warning')
    return redirect(url_for('colabore.painel'))
