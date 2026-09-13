# -*- coding: utf-8 -*-
"""Ponto com foto — o registro de quem chegou, a que horas e onde.

O problema nao e anotar horario: o papel ja fazia isso. E o Joao pegar o
cartao do Marcelo e bater por ele. Tudo aqui gira em torno disso:

  * a FOTO e obrigatoria e tirada na hora, pela camera da frente. Sem foto a
    batida e recusada -- uma linha sem foto nao prova nada.
  * a HORA e a do servidor, nunca a do aparelho. Relogio de celular se muda
    no ajuste de data e hora.
  * a LOCALIZACAO vai junto quando o aparelho deixa. Quando nao deixa, a
    batida acontece do mesmo jeito e fica marcada como "sem localizacao" --
    trancar a porta por causa de uma permissao negada resolveria menos.
  * o registro e so INSERT. Nao ha rota que altere o horario de uma batida.

A empresa nao tem obrigacao legal de ponto (poucos funcionarios), entao isto
e controle interno, sem as exigencias da Portaria 671/2021.

Duas telas: /ponto, que roda no aparelho do posto e e onde se bate; e
/ponto/espelho, do gestor, que mostra as batidas do periodo com as fotos lado
a lado -- e e olhando as fotos em sequencia que "um batendo pelo outro"
aparece sozinho.

POR ENQUANTO TUDO E SO PARA ADMIN, por decisao do Anderson enquanto o ponto
esta em teste. Isso vale para as QUATRO rotas, inclusive a da foto: esconder
o item do menu nao protege nada, quem souber a URL entra. Quando abrir para a
pista, o que muda e o decorador de /ponto e /ponto/bater -- o espelho e a
foto seguem sendo do gestor, porque sao a foto dos outros.
"""
import base64
import binascii
import logging
from datetime import datetime, timedelta

import pytz
from flask import (Blueprint, Response, jsonify, render_template, request)
from flask_login import current_user, login_required

from routes.auth import admin_required
from utils.db import get_db_connection

ponto_bp = Blueprint('ponto', __name__, url_prefix='/ponto')

_BRASILIA = pytz.timezone('America/Sao_Paulo')
_LOG = logging.getLogger(__name__)

# O navegador ja reduz a foto para 480px antes de enviar, o que da uns 30 KB.
# O teto aqui e folgado de proposito: serve contra aparelho que ignore o
# redimensionamento, nao para brigar por alguns quilobytes.
FOTO_MAX_BYTES = 600 * 1024
TIPOS = ('ENTRADA', 'SAIDA')


def _agora_br():
    """Agora em Brasilia. O container roda UTC; a tela e o Brasil."""
    return datetime.now(_BRASILIA)


def _hoje_br():
    return _agora_br().date()


def _para_br(dt):
    """DATETIME do banco (UTC, sem fuso) -> horario de Brasilia."""
    if dt is None:
        return None
    return pytz.utc.localize(dt).astimezone(_BRASILIA)


def _admin():
    nivel = (getattr(current_user, 'nivel', '') or '').strip().upper()
    return nivel == 'ADMIN'


# ==========================================================================
#  A tela de bater
# ==========================================================================

def _funcionarios_do_dia(cur, dia):
    """Quem pode bater hoje, e o que cada um vai registrar se tocar no nome.

    Desligado nao aparece: se a Brena saiu em julho, o nome dela na tela de
    agosto so serve para alguem bater por engano. A regra e a mesma do resto
    do sistema (data_saida >= o dia).
    """
    cur.execute("""
        SELECT f.id, f.nome, f.cargo
          FROM funcionarios f
         WHERE f.ativo = 1
           AND (f.data_saida IS NULL OR f.data_saida >= %s)
           AND (f.data_admissao IS NULL OR f.data_admissao <= %s)
         ORDER BY f.nome
    """, (dia, dia))
    gente = cur.fetchall()
    if not gente:
        return []

    ids = [g['id'] for g in gente]
    marcas = ','.join(['%s'] * len(ids))
    # A ultima batida de HOJE diz o que vem agora. Em Brasilia: o dia do
    # posto vira a meia-noite daqui, nao a do servidor.
    ini_utc = _BRASILIA.localize(datetime.combine(dia, datetime.min.time())) \
        .astimezone(pytz.utc).replace(tzinfo=None)
    cur.execute("""
        SELECT b.funcionario_id, b.tipo, b.momento
          FROM ponto_batidas b
          JOIN (SELECT funcionario_id, MAX(momento) AS m
                  FROM ponto_batidas
                 WHERE momento >= %s AND funcionario_id IN (""" + marcas + """)
                 GROUP BY funcionario_id) u
            ON u.funcionario_id = b.funcionario_id AND u.m = b.momento
    """, [ini_utc] + ids)
    ultima = {r['funcionario_id']: r for r in cur.fetchall()}

    fora = []
    for g in gente:
        u = ultima.get(g['id'])
        hora = _para_br(u['momento']).strftime('%H:%M') if u else None
        fora.append({
            'id': g['id'], 'nome': g['nome'], 'cargo': g['cargo'] or '',
            # alterna sozinho: quem entrou, sai; quem saiu (ou nao bateu
            # ainda), entra. Numa tela compartilhada, escolher o tipo a mao e
            # so mais uma chance de errar.
            'proxima': 'SAIDA' if (u and u['tipo'] == 'ENTRADA') else 'ENTRADA',
            'ultima_tipo': u['tipo'] if u else None,
            'ultima_hora': hora,
        })
    return fora


@ponto_bp.route('/', methods=['GET'])
@admin_required
def index():
    """O aparelho do posto: toca no nome, tira a foto, bate."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        hoje = _hoje_br()
        gente = _funcionarios_do_dia(cur, hoje)
    finally:
        cur.close()
        conn.close()
    return render_template('ponto/bater.html', gente=gente,
                           hoje=hoje, agora=_agora_br(), admin=_admin())


@ponto_bp.route('/bater', methods=['POST'])
@admin_required
def bater():
    """Grava a batida. Sem foto, nao grava.

    A hora nao vem do aparelho e o tipo nao vem da tela: os dois sao
    decididos aqui. Se viessem de fora, bastaria abrir o inspetor do
    navegador para registrar a hora que se quisesse.
    """
    dados = request.get_json(silent=True) or {}
    try:
        func_id = int(dados.get('funcionario_id') or 0)
    except (TypeError, ValueError):
        func_id = 0
    if not func_id:
        return jsonify(ok=False, erro='Escolha quem está batendo o ponto.'), 400

    foto_b64 = (dados.get('foto') or '').strip()
    if ',' in foto_b64[:64]:                  # "data:image/jpeg;base64,...."
        foto_b64 = foto_b64.split(',', 1)[1]
    if not foto_b64:
        return jsonify(ok=False,
                       erro='A foto é obrigatória — sem ela o ponto não vale.'), 400
    try:
        foto = base64.b64decode(foto_b64, validate=True)
    except (binascii.Error, ValueError):
        return jsonify(ok=False, erro='A foto chegou corrompida. Tente de novo.'), 400
    if len(foto) < 2000:
        return jsonify(ok=False,
                       erro='A foto ficou vazia. Verifique a câmera e tente de novo.'), 400
    if len(foto) > FOTO_MAX_BYTES:
        return jsonify(ok=False, erro='A foto ficou grande demais.'), 400

    def _num(chave, conv):
        v = dados.get(chave)
        try:
            return conv(v) if v is not None and v != '' else None
        except (TypeError, ValueError):
            return None

    lat, lng = _num('lat', float), _num('lng', float)
    precisao = _num('precisao', lambda x: int(round(float(x))))
    geo_negada = 1 if (lat is None or lng is None) else 0

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        hoje = _hoje_br()
        podem = {g['id']: g for g in _funcionarios_do_dia(cur, hoje)}
        quem = podem.get(func_id)
        if not quem:
            return jsonify(ok=False,
                           erro='Esse funcionário não está ativo hoje.'), 400

        tipo = quem['proxima']            # o servidor decide, nao a tela
        agora_utc = datetime.now(pytz.utc).replace(tzinfo=None)
        cur.execute("""
            INSERT INTO ponto_batidas
                   (funcionario_id, cliente_id, tipo, momento, foto, foto_mime,
                    foto_bytes, lat, lng, precisao_m, geo_negada, dispositivo,
                    usuario_id, ip)
            VALUES (%s, %s, %s, %s, %s, 'image/jpeg', %s, %s, %s, %s, %s, %s,
                    %s, %s)
        """, (func_id, getattr(current_user, 'cliente_id', None), tipo,
              agora_utc, foto, len(foto), lat, lng, precisao, geo_negada,
              (request.headers.get('User-Agent') or '')[:255],
              getattr(current_user, 'id', None),
              (request.headers.get('X-Forwarded-For')
               or request.remote_addr or '')[:45]))
        conn.commit()
        return jsonify(ok=True, tipo=tipo, nome=quem['nome'],
                       hora=_agora_br().strftime('%H:%M:%S'),
                       sem_local=bool(geo_negada))
    except Exception as e:
        conn.rollback()
        _LOG.exception('[ponto] falha ao gravar batida')
        return jsonify(ok=False, erro='Não deu para gravar: %s' % e), 500
    finally:
        cur.close()
        conn.close()


# ==========================================================================
#  A tela do gestor
# ==========================================================================

@ponto_bp.route('/foto/<int:batida_id>', methods=['GET'])
@admin_required
def foto(batida_id):
    """A foto de uma batida. Sem login nao sai daqui."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT foto, foto_mime FROM ponto_batidas
                        WHERE id = %s""", (batida_id,))
        r = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not r or not r['foto']:
        return '', 404
    return Response(r['foto'], mimetype=r['foto_mime'] or 'image/jpeg',
                    headers={'Cache-Control': 'private, max-age=3600'})


def _horas(batidas):
    """Soma as horas de um dia pareando ENTRADA com SAIDA, na ordem.

    Par sem fechamento (entrou e nao saiu) nao vira hora nenhuma e fica
    marcado como aberto — inventar uma saida seria inventar hora trabalhada.
    """
    total = timedelta()
    aberta = None
    for b in batidas:
        if b['tipo'] == 'ENTRADA':
            aberta = b['momento']
        elif aberta is not None:
            total += b['momento'] - aberta
            aberta = None
    return total, aberta is not None


@ponto_bp.route('/espelho', methods=['GET'])
@admin_required
def espelho():
    """As batidas do periodo, com as fotos — e e nas fotos que se confere."""
    def _data(nome, padrao):
        try:
            return datetime.strptime(request.args.get(nome, ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return padrao

    hoje = _hoje_br()
    ini = _data('data_inicio', hoje - timedelta(days=6))
    fim = _data('data_fim', hoje)
    if fim < ini:
        fim = ini
    try:
        func_id = int(request.args.get('funcionario_id') or 0)
    except (TypeError, ValueError):
        func_id = 0

    ini_utc = _BRASILIA.localize(datetime.combine(ini, datetime.min.time())) \
        .astimezone(pytz.utc).replace(tzinfo=None)
    fim_utc = _BRASILIA.localize(
        datetime.combine(fim + timedelta(days=1), datetime.min.time())) \
        .astimezone(pytz.utc).replace(tzinfo=None)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, nome FROM funcionarios
                        WHERE ativo = 1 ORDER BY nome""")
        funcionarios = cur.fetchall()

        sql = """
            SELECT b.id, b.funcionario_id, f.nome, b.tipo, b.momento,
                   b.lat, b.lng, b.precisao_m, b.geo_negada, b.foto_bytes
              FROM ponto_batidas b
              JOIN funcionarios f ON f.id = b.funcionario_id
             WHERE b.momento >= %s AND b.momento < %s
        """
        args = [ini_utc, fim_utc]
        if func_id:
            sql += ' AND b.funcionario_id = %s'
            args.append(func_id)
        sql += ' ORDER BY b.momento'
        cur.execute(sql, args)
        linhas = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    # agrupa por dia (de Brasilia) e, dentro do dia, por pessoa
    dias = {}
    for r in linhas:
        br = _para_br(r['momento'])
        r['momento'] = br
        r['hora'] = br.strftime('%H:%M')
        d = br.date()
        dias.setdefault(d, {}).setdefault(r['funcionario_id'], {
            'nome': r['nome'], 'batidas': []})['batidas'].append(r)

    fora, tot_geral, sem_local = [], timedelta(), 0
    for d in sorted(dias, reverse=True):
        pessoas = []
        for fid, p in sorted(dias[d].items(), key=lambda kv: kv[1]['nome']):
            horas, aberto = _horas(p['batidas'])
            tot_geral += horas
            sem_local += sum(1 for b in p['batidas'] if b['geo_negada'])
            pessoas.append({
                'id': fid, 'nome': p['nome'], 'batidas': p['batidas'],
                'horas': horas, 'aberto': aberto,
                'horas_txt': '%d:%02d' % (horas.seconds // 3600 + horas.days * 24,
                                          (horas.seconds % 3600) // 60),
            })
        fora.append({'data': d, 'pessoas': pessoas})

    return render_template(
        'ponto/espelho.html', dias=fora, funcionarios=funcionarios,
        data_inicio=ini, data_fim=fim, funcionario_id=func_id,
        total_batidas=len(linhas), sem_local=sem_local,
        total_txt='%d:%02d' % (tot_geral.days * 24 + tot_geral.seconds // 3600,
                               (tot_geral.seconds % 3600) // 60),
    )
