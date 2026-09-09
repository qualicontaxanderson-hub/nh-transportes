# -*- coding: utf-8 -*-
"""Prova do robô que lê o comprovante de PIX enviado no e-mail do banco.

O caso: o frentista pega o cheque e pede o troco, a gente faz o PIX pela conta
do posto e a Cora manda o aviso na hora. A conciliação com o extrato só vem no
dia seguinte, com o OFX — e até lá a tela dizia "falta conciliar" tanto para o
troco já pago quanto para o que ninguém mandou.

Aqui prova-se, sem tocar na caixa de e-mail: o parser em cima do texto REAL dos
avisos, o casamento contra as solicitações que estão no banco agora, e o selo
na tela. A parte que escreve (um comprovante de mentira, para ver o selo) é
desfeita no fim, e a última prova confere que não sobrou nada.

    python prova_pix_email.py
"""
import email as emaillib
import io
import os
import re
import secrets
import sys
from datetime import datetime

if not os.environ.get('DB_PASSWORD') and os.path.exists('bakup_railway.bat'):
    _m = re.search(r'set DBPASS=(.+)',
                   io.open('bakup_railway.bat', encoding='latin-1').read(), re.I)
    if _m:
        os.environ['DB_PASSWORD'] = _m.group(1).strip()
os.environ.setdefault('SECRET_KEY', secrets.token_hex(32))
os.environ.setdefault('WTF_CSRF_ENABLED', 'False')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import app                                    # noqa: E402
from utils.db import get_db_connection                 # noqa: E402
from integrations import pix_email                     # noqa: E402

falhas = []


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


def consulta(sql, args=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def executa(sql, args=()):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        conn.commit()
        return cur.lastrowid, cur.rowcount
    finally:
        cur.close()
        conn.close()


# ── o e-mail de verdade, como a Cora manda ─────────────────────────────────
# Texto copiado dos avisos de 09/09/2026 (os tres trocos do dia).
def aviso(valor, favorecido):
    return (
        '<html><body><table><tr><td>'
        '<h1>Transferência Pix enviada!</h1>'
        '<p>A transferência Pix feita de <b>NH GTBA - 33.503.987/0001-16</b> '
        '<b>no valor de R$ %s</b> para <b>%s</b> foi efetuada com sucesso :)</p>'
        '<p>Abraços,<br><b>Equipe Cora</b></p>'
        '</td></tr></table></body></html>' % (valor, favorecido)
    )


def mensagem(valor, favorecido, quando='Wed, 9 Sep 2026 11:29:03 -0300',
             assunto='Sua transferência Pix foi realizada com sucesso!'):
    msg = emaillib.message.EmailMessage()
    msg['Subject'] = assunto
    msg['From'] = 'noreply@cora.com.br'
    msg['To'] = 'pix.goiatuba@postonovohorizonte.com.br'
    msg['Date'] = quando
    msg['Message-ID'] = '<prova-%s-%s@cora.com.br>' % (valor.replace(',', ''),
                                                       secrets.token_hex(4))
    msg.add_alternative(aviso(valor, favorecido), subtype='html')
    return msg


# ── 1. o parser em cima do texto real ──────────────────────────────────────
casos = [('1000,08', 'LUCILENE SILVA OLIVEIRA ALVES', 1000.08),
         ('1232,10', 'JOSE GOMES VIEIRA JUNIOR', 1232.10),
         ('585,81', 'RODRIGO CARDOSO DE OLIVEIRA', 585.81)]
for txt_valor, nome, esperado in casos:
    msg = mensagem(txt_valor, nome)
    texto = pix_email._texto_msg(msg)
    d = pix_email.parse_envio(texto)
    prova('lê o aviso de R$ %s para %s' % (txt_valor, nome.split()[0].title()),
          d is not None and abs(d['valor'] - esperado) < 0.005
          and d['favorecido'] == nome,
          'extraiu: %r' % d)

prova('o valor com ponto de milhar também é lido',
      (pix_email.parse_envio(
          pix_email._texto_msg(mensagem('12.345,67', 'FULANO DE TAL')))
       or {}).get('valor') == 12345.67,
      'os trocos do dia sao de mil e poucos, mas 10 mil chega qualquer dia')
prova('guarda de que conta saiu',
      'NH GTBA' in ((pix_email.parse_envio(
          pix_email._texto_msg(mensagem('100,00', 'FULANO'))) or {}).get('pagador') or ''))

# Outro aviso do banco nao pode virar comprovante de troco.
for outro in ('Você recebeu um Pix de R$ 500,00 de FULANO DE TAL',
              'Seu boleto foi pago! Valor de R$ 300,00',
              'A transferência Pix feita de NH GTBA no valor de R$ 10,00 '
              'para FULANO foi cancelada'):
    prova('ignora aviso que não é PIX enviado (%s…)' % outro[:22],
          pix_email.parse_envio(outro) is None,
          'entendeu como envio: %r' % pix_email.parse_envio(outro))

# ── 2. o nome, comparado sem tropeçar em acento ────────────────────────────
prova('compara nome sem se perder em acento e pontuação',
      pix_email._chave('José  Gomes Vieira Júnior') == pix_email._chave('JOSE GOMES VIEIRA JUNIOR'))
prova('nomes diferentes continuam diferentes',
      pix_email._chave('JOSE GOMES') != pix_email._chave('JOSE GOMES VIEIRA'))

# ── 3. a tabela nasce sozinha ──────────────────────────────────────────────
pix_email.ensure_tables()
cols = consulta("""SELECT COLUMN_NAME c FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'troco_pix_comprovantes'""")
nomes = {r['c'] for r in cols}
prova('a tabela dos comprovantes existe, com o que a tela precisa',
      {'message_id', 'enviado_em', 'valor', 'favorecido', 'troco_pix_id'} <= nomes,
      'colunas: %r' % sorted(nomes))
uq = consulta("""SELECT INDEX_NAME i FROM information_schema.STATISTICS
                  WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = 'troco_pix_comprovantes'
                    AND NON_UNIQUE = 0 AND COLUMN_NAME = 'message_id'""")
prova('o mesmo e-mail não pode entrar duas vezes (message_id único)', bool(uq))

# ── 4. o casamento com as solicitações que estão no banco ──────────────────
alvos = consulta("""SELECT tp.id, tp.data, tp.troco_pix, tpc.nome_completo
                      FROM troco_pix tp
                      LEFT JOIN troco_pix_clientes tpc ON tpc.id = tp.troco_pix_cliente_id
                     WHERE COALESCE(tp.troco_pix,0) > 0
                       AND tp.data >= DATE_SUB(CURDATE(), INTERVAL 2 DAY)
                     ORDER BY tp.data DESC, tp.id DESC LIMIT 3""")
prova('há solicitações recentes com troco para casar', bool(alvos),
      'sem troco lançado nos últimos dias')

# O robô já rodou em produção, então essas solicitações provavelmente já têm
# comprovante. A prova não pode depender disso: ela SOLTA o vínculo, prova o
# casamento e devolve cada um para onde estava.
vinculos = {}
for a in alvos:
    ligados = consulta("SELECT id FROM troco_pix_comprovantes WHERE troco_pix_id=%s",
                       (a['id'],))
    vinculos[a['id']] = [r['id'] for r in ligados]

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
try:
    for a in alvos:
        quando = datetime.combine(a['data'], datetime.min.time()).replace(hour=11)
        # já com comprovante, a mesma solicitação não pode ser oferecida de
        # novo — senão um segundo aviso igual roubaria o dono do primeiro
        if vinculos[a['id']]:
            prova('solicitação que já tem comprovante não casa de novo (%s)' % a['id'],
                  pix_email.casar(cur, float(a['troco_pix']), a['nome_completo'],
                                  quando) != a['id'])
        for cid in vinculos[a['id']]:
            executa("UPDATE troco_pix_comprovantes SET troco_pix_id=NULL WHERE id=%s",
                    (cid,))
        # O UPDATE foi por outra conexão. Esta aqui abriu a transação antes e,
        # em REPEATABLE READ, continuaria lendo o vínculo velho — a prova
        # falharia acusando o código de não casar. Um commit renova o
        # instantâneo.
        conn.commit()
        achou = pix_email.casar(cur, float(a['troco_pix']), a['nome_completo'],
                                quando)
        prova('o aviso de R$ %s para %s acha a solicitação %s'
              % (a['troco_pix'], (a['nome_completo'] or '?').split()[0].title(), a['id']),
              achou == a['id'], 'casou com %r' % achou)
        if a is alvos[0]:
            prova('valor certo com nome de outra pessoa NÃO casa',
                  pix_email.casar(cur, float(a['troco_pix']),
                                  'ZEZINHO DA SILVA SAURO', quando) is None,
                  'casou com quem não devia')
            prova('nome certo com valor de outro NÃO casa',
                  pix_email.casar(cur, float(a['troco_pix']) + 7.77,
                                  a['nome_completo'], quando) is None,
                  'casou com quem não devia')
        for cid in vinculos[a['id']]:
            executa("UPDATE troco_pix_comprovantes SET troco_pix_id=%s WHERE id=%s",
                    (a['id'], cid))
        conn.commit()   # o proximo alvo tem de enxergar o vinculo devolvido
finally:
    cur.close()
    conn.close()

for a in alvos:
    agora = {r['id'] for r in consulta(
        "SELECT id FROM troco_pix_comprovantes WHERE troco_pix_id=%s", (a['id'],))}
    prova('o vínculo da solicitação %s voltou como estava' % a['id'],
          agora == set(vinculos[a['id']]),
          'antes %r, agora %r' % (vinculos[a['id']], agora))

# ── 5. o selo na tela ──────────────────────────────────────────────────────
admin = (consulta("""SELECT id FROM usuarios WHERE ativo = 1
                      AND UPPER(nivel) = 'ADMIN' LIMIT 1""") or [None])[0]
# O POST de "ler agora" e protegido por CSRF: no navegador o token vai
# sozinho (o base.html injeta em todo fetch), mas o test_client nao passa por
# ele e levaria 400 vazio.
app.config['WTF_CSRF_ENABLED'] = False
cli = app.test_client()
if admin:
    with cli.session_transaction() as s:
        s['_user_id'] = str(admin['id'])
        s['_fresh'] = True

# Um troco a conciliar, para montar os dois estados do envelope: sem aviso
# (vermelho) e com aviso (azul).
alvo_tela = (consulta("""SELECT tp.id, tp.data, tp.troco_pix, tpc.nome_completo
                           FROM troco_pix tp
                           LEFT JOIN troco_pix_clientes tpc
                                  ON tpc.id = tp.troco_pix_cliente_id
                          WHERE COALESCE(tp.troco_pix,0) > 0
                            AND tp.bank_transaction_id IS NULL
                            AND tp.data >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
                          ORDER BY tp.data DESC LIMIT 1""") or [None])[0]
prova('há um troco a conciliar para provar o envelope', bool(alvo_tela))

comp_id = None
soltos = []
try:
    if alvo_tela and admin:
        a = alvo_tela
        soltos = [r['id'] for r in consulta(
            "SELECT id FROM troco_pix_comprovantes WHERE troco_pix_id=%s", (a['id'],))]
        for cid in soltos:
            executa("UPDATE troco_pix_comprovantes SET troco_pix_id=NULL WHERE id=%s",
                    (cid,))

        antes = cli.get('/troco_pix/').get_data(as_text=True)
        prova('sem o aviso, o troco a conciliar leva envelope VERMELHO',
              'env env--nao' in antes,
              'nenhum envelope vermelho na tela')

        comp_id, _ = executa("""INSERT INTO troco_pix_comprovantes
                                  (message_id, enviado_em, valor, favorecido,
                                   pagador, assunto, troco_pix_id)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                             ('<prova-tela-%s@cora.com.br>' % secrets.token_hex(4),
                              datetime.combine(a['data'], datetime.min.time())
                              .replace(hour=11, minute=29),
                              a['troco_pix'], a['nome_completo'],
                              'NH GTBA - 33.503.987/0001-16',
                              'Sua transferência Pix foi realizada com sucesso!',
                              a['id']))
        depois = cli.get('/troco_pix/').get_data(as_text=True)
        prova('a tela abre inteira com o comprovante',
              'Erro ao carregar transações' not in depois and 'id="tpx"' in depois)
        prova('o card ganha o envelope AZUL',
              depois.count('env env--ok') == antes.count('env env--ok') + 1,
              'azuis antes: %s, depois: %s'
              % (antes.count('env env--ok'), depois.count('env env--ok')))
        prova('o envelope é só o ícone, sem texto empurrando a linha',
              'PIX enviado</button>' not in depois
              and 'bi-envelope-fill"></i></button>' in depois)
        prova('o envelope azul diz a hora no toque longo (title)',
              re.search(r'title="PIX enviado em \d{2}/\d{2}/\d{4} às 11:29"', depois)
              is not None, 'não achei o title com a hora')
        prova('e guarda a hora escondida, para o clique mostrar',
              re.search(r'selo--hora" hidden>\s*11:29', depois) is not None,
              'não achei a hora escondida ao lado do envelope')
        prova('esse card perdeu o envelope vermelho (o aviso chegou)',
              depois.count('env env--nao') == antes.count('env env--nao') - 1,
              'vermelhos antes: %s, depois: %s'
              % (antes.count('env env--nao'), depois.count('env env--nao')))
        prova('o card aberto mostra o comprovante do banco',
              'Comprovante do banco' in depois
              and '11:29' in depois)
        prova('a tela deixa claro que isso NÃO é a conciliação',
              'não a conciliação' in depois)
        prova('o selo de falta conciliar continua lá (o OFX ainda não veio)',
              'falta conciliar' in depois)
finally:
    if comp_id:
        executa("DELETE FROM troco_pix_comprovantes WHERE id=%s", (comp_id,))
    for cid in soltos:
        executa("UPDATE troco_pix_comprovantes SET troco_pix_id=%s WHERE id=%s",
                (alvo_tela['id'], cid))

# ── 6. a caixa é a mesma do ELS: nada a configurar no Railway ─────────────
# Os avisos da Cora chegam junto com os do sistema de medição. Repetir a senha
# em PIX_MAIL_PASSWORD seria um segundo lugar para ela ficar velha.
_guarda = {k: os.environ.get(k) for k in
           ('PIX_MAIL_USER', 'PIX_MAIL_PASSWORD', 'PIX_MAIL_IMAP_HOST',
            'PIX_MAIL_REMETENTE', 'ELS_MAIL_USER', 'ELS_MAIL_PASSWORD',
            'ELS_MAIL_IMAP_HOST')}
try:
    for k in _guarda:
        os.environ.pop(k, None)
    prova('sem nenhuma variável, não há caixa (e o robô nem liga)',
          not pix_email.caixa_configurada())

    os.environ['ELS_MAIL_USER'] = 'goiatuba@postonovohorizonte.com.br'
    os.environ['ELS_MAIL_PASSWORD'] = 'senha-do-els'
    os.environ['ELS_MAIL_IMAP_HOST'] = 'imap.titan.email'
    prova('só com as do ELS, o PIX já tem caixa para ler',
          pix_email.caixa_configurada())
    prova('herda usuário, senha e servidor do ELS',
          pix_email._cfg('PIX_MAIL_USER') == 'goiatuba@postonovohorizonte.com.br'
          and pix_email._cfg('PIX_MAIL_PASSWORD') == 'senha-do-els'
          and pix_email._cfg('PIX_MAIL_IMAP_HOST') == 'imap.titan.email')
    # O remetente NAO pode ser herdado: o do ELS e o sistema de medicao, e
    # com ele a busca nao acharia um aviso da Cora sequer.
    os.environ['ELS_REMETENTE'] = 'notificacao@sistemaels.com.br'
    prova('mas NÃO herda o remetente (o do ELS é outro sistema)',
          pix_email._cfg('PIX_MAIL_REMETENTE', pix_email.REMETENTE_PADRAO)
          == 'cora.com.br')

    os.environ['PIX_MAIL_USER'] = 'pix.goiatuba@postonovohorizonte.com.br'
    prova('quando a do PIX existe, é ela que vale',
          pix_email._cfg('PIX_MAIL_USER') == 'pix.goiatuba@postonovohorizonte.com.br')
finally:
    for k, v in _guarda.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    os.environ.pop('ELS_REMETENTE', None)

# ── 7. o botão "Ler e-mails" ──────────────────────────────────────────────
if admin:
    tela = cli.get('/troco_pix/').get_data(as_text=True)
    prova('a tela tem o botão de ler os e-mails agora',
          'tpxLerEmails(this)' in tela and 'Ler e-mails' in tela)
    r = cli.post('/troco_pix/comprovantes/ler')
    corpo = r.get_json() or {}
    # Nesta maquina nao ha caixa configurada: a resposta tem de explicar isso,
    # e nao estourar.
    prova('sem caixa configurada, a rota recusa por escrito',
          r.status_code == 400 and 'caixa de e-mail' in (corpo.get('erro') or ''),
          'codigo %s, corpo %r' % (r.status_code, corpo))

    _g2 = {k: os.environ.get(k) for k in ('PIX_MAIL_USER', 'PIX_MAIL_PASSWORD',
                                          'PIX_MAIL_IMAP_HOST')}
    try:
        os.environ['PIX_MAIL_USER'] = 'ninguem@exemplo.invalido'
        os.environ['PIX_MAIL_PASSWORD'] = 'nao-existe'
        os.environ['PIX_MAIL_IMAP_HOST'] = 'imap.exemplo.invalido'
        r = cli.post('/troco_pix/comprovantes/ler')
        corpo = r.get_json() or {}
        prova('servidor que não responde vira mensagem, não tela de erro',
              r.status_code == 500 and 'Falha ao ler' in (corpo.get('erro') or ''),
              'codigo %s, corpo %r' % (r.status_code, corpo))
    finally:
        for k, v in _g2.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

sobrou = consulta("""SELECT COUNT(*) n FROM troco_pix_comprovantes
                      WHERE message_id LIKE '<prova-%'""")
prova('a prova não deixou comprovante de mentira no banco',
      int(sobrou[0]['n']) == 0, 'sobraram %s' % sobrou[0]['n'])

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
