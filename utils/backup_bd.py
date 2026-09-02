# -*- coding: utf-8 -*-
"""Backup do banco para o Dropbox, feito para rodar num cron da nuvem.

Existe porque o backup vivia numa tarefa agendada no PC: em 29/08/2026 o dump
saiu truncado (a maquina perdeu a rede no meio) e de 30/08 a 01/09 a tarefa nem
disparou, porque os computadores estavam desligados. Quatro dias sem backup, e
a unica testemunha da falha era um arquivo de log que ninguem abre.

Dai as duas exigencias que moldam este modulo:

  1. nao pode depender de maquina ligada  -> roda num servico de cron da Railway
  2. a falha precisa de testemunha        -> todo resultado vira uma linha no
     banco, que o card do dashboard le

Por isso `executar()` NUNCA levanta excecao: qualquer falha vira um status com
`etapa` e `erro` gravado em `app_config`. Um erro que so aparece no log e um
erro que ninguem ve.

Modulo PURO de proposito: nao importa Flask nem `config.py`. O servico de cron
roda `python cron_backup.py` sem subir a aplicacao, e `config.Config` levanta
RuntimeError quando falta SECRET_KEY. As credenciais vem de
`utils.db_credentials`, a mesma fonte do app web e dos scripts de captura.
"""
import glob
import gzip
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime

from utils import db_credentials

# -- Constantes de politica ---------------------------------------------------

CHAVE_STATUS = 'backup_bd_status'

#: Abaixo disto o arquivo nao e backup, e sintoma. O incidente que originou
#: este modulo produziu um dump de 52 bytes.
PISO_BYTES = 1 * 1024 * 1024

#: Encolher nao reprova (o banco pode ter sido podado de proposito), mas avisa.
FRACAO_AVISO = 0.70

#: `files_upload` para em 150 MB e carrega tudo na memoria. Acima deste corte
#: vai por sessao. O corte fica abaixo do limite real para nao namorar a borda.
LIMITE_SESSAO = 140 * 1024 * 1024

#: Blocos do upload por sessao.
BLOCO_SESSAO = 8 * 1024 * 1024

#: Pasta de destino no Dropbox: a MESMA em que a rotina do PC grava, para o
#: backup do posto ficar todo num lugar so.
#:
#: Conviver com a faxina do `bakup_railway.bat` e seguro, e isso foi TESTADO,
#: nao suposto: aquele script apaga com `forfiles /M *.sql /D -11`, e a mascara
#: `*.sql` do Windows NAO casa com `.sql.gz` (conferido em 02/09/2026 num
#: diretorio de teste com os dois arquivos envelhecidos em 40 dias -- so o
#: `.sql` foi listado). Ou seja, os arquivos da nuvem se acumulam, que e a lei:
#: backup antigo nunca some sozinho.
#:
#: Se algum dia alguem afrouxar aquela mascara para `*`, ela passa a comer estes
#: arquivos. Mexeu no `.bat`, confira isto aqui.
DESTINO_PADRAO = '/BANCOS/OFX/BACKUP/NH'


# -- Localizar o mysqldump ----------------------------------------------------

def _construtor_provavel(caminho_path):
    """Qual construtor da Railway montou esta imagem, deduzido pelo PATH.

    Serve para o erro acusar o AMBIENTE, e nao so dizer "nao existe". Railpack
    ignora `NIXPACKS_PKGS` EM SILENCIO: o build passa, o servico fica Ready, e o
    binario nunca entra na imagem.
    """
    if '/mise/shims' in caminho_path:
        return 'RAILPACK (ignora NIXPACKS_PKGS em silencio -- use Nixpacks)'
    if '/nix/store' in caminho_path:
        return 'NIXPACKS'
    return 'desconhecido'


def _diagnostico_ambiente():
    """Texto que permite achar a causa em UMA rodada, sem console no container."""
    caminho_path = os.environ.get('PATH', '')
    linhas = [
        'PATH=%s' % caminho_path,
        'construtor provavel: %s' % _construtor_provavel(caminho_path),
        'MYSQLDUMP_BIN=%s' % (os.environ.get('MYSQLDUMP_BIN') or '(nao definido)'),
    ]
    achados = []
    for pasta in caminho_path.split(os.pathsep):
        if not pasta:
            continue
        try:
            nomes = sorted(n for n in os.listdir(pasta)
                           if 'mysql' in n or 'maria' in n)
        except OSError:
            continue
        if nomes:
            achados.append('  %s -> %s' % (pasta, ', '.join(nomes)))
    linhas.append('binarios mysql/maria vistos no PATH:')
    linhas.extend(achados or ['  (nenhum)'])
    return '\n'.join(linhas)


def encontrar_mysqldump():
    """Procura o mysqldump em quatro lugares antes de desistir.

    Procurar e barato; uma rodada perdida por PATH custa um dia de backup.
    """
    explicito = (os.environ.get('MYSQLDUMP_BIN') or '').strip()
    if explicito and os.path.isfile(explicito):
        return explicito

    no_path = shutil.which('mysqldump')
    if no_path:
        return no_path

    for candidato in ('/usr/bin/mysqldump', '/usr/local/bin/mysqldump',
                      '/usr/local/mysql/bin/mysqldump', '/opt/mysql/bin/mysqldump'):
        if os.path.isfile(candidato):
            return candidato

    for candidato in sorted(glob.glob('/nix/store/*/bin/mysqldump')):
        if os.path.isfile(candidato):
            return candidato

    raise RuntimeError(
        'mysqldump nao encontrado na imagem.\n' + _diagnostico_ambiente()
    )


# -- O dump -------------------------------------------------------------------

def _escrever_arquivo_de_senha():
    """Arquivo 0600 com as credenciais, para o `--defaults-extra-file`.

    LEI: a senha NUNCA vai em argv. Argumento de processo aparece na lista de
    processos para quem abrir um shell no container.
    """
    senha = db_credentials.exigir_senha()
    descritor, caminho = tempfile.mkstemp(prefix='.mydump', suffix='.cnf')
    os.close(descritor)
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass  # Windows nao tem modo POSIX; no container Linux tem.
    # No formato de option file do MySQL a barra invertida escapa, entao ela e
    # as aspas precisam ser escapadas dentro do valor entre aspas.
    seguro = senha.replace('\\', '\\\\').replace('"', '\\"')
    with open(caminho, 'w', encoding='utf-8') as arquivo:
        arquivo.write(
            '[client]\n'
            'host=%s\n'
            'port=%d\n'
            'user=%s\n'
            'password="%s"\n' % (
                db_credentials.DB_HOST,
                db_credentials.DB_PORT,
                db_credentials.DB_USER,
                seguro,
            )
        )
    return caminho


def gerar_dump_gz(destino_local, binario=None):
    """Roda o mysqldump comprimindo direto para `.sql.gz`, sem passar pelo disco
    descomprimido, e devolve (codigo_de_saida_DO_MYSQLDUMP, texto_do_stderr).

    A compressao acontece dentro deste processo, em vez de num pipe de shell,
    justamente para que `returncode` seja o do mysqldump. Num pipe o codigo de
    saida e o do COMPRESSOR: se o dump morre no meio, o `.gz` sai integro porem
    truncado, com cara de sucesso. Foi assim que nasceu o arquivo de 52 bytes.
    """
    binario = binario or encontrar_mysqldump()
    arquivo_senha = _escrever_arquivo_de_senha()
    # stderr vai para arquivo, nao para PIPE: com PIPE, um mysqldump falante
    # encheria o buffer do canal e travaria o processo enquanto ninguem le.
    descritor_erro, caminho_erro = tempfile.mkstemp(prefix='.mydump', suffix='.err')
    os.close(descritor_erro)
    try:
        comando = [
            binario,
            '--defaults-extra-file=%s' % arquivo_senha,
            '--databases', db_credentials.DB_NAME,
            '--single-transaction',
            '--quick',
            '--max-allowed-packet=1G',
            '--routines', '--triggers',
            '--add-drop-database', '--add-drop-table',
            '--default-character-set=utf8mb4',
        ]
        with open(caminho_erro, 'wb') as saida_erro:
            processo = subprocess.Popen(comando, stdout=subprocess.PIPE,
                                        stderr=saida_erro)
            try:
                with gzip.open(destino_local, 'wb', compresslevel=6) as comprimido:
                    shutil.copyfileobj(processo.stdout, comprimido, 1024 * 1024)
            finally:
                processo.stdout.close()
                codigo = processo.wait()
        with open(caminho_erro, 'rb') as leitura:
            erro = leitura.read().decode('utf-8', 'replace').strip()
        return codigo, erro
    finally:
        for descartavel in (arquivo_senha, caminho_erro):
            try:
                os.unlink(descartavel)
            except OSError:
                pass


# -- A verificacao: o portao de verdade ---------------------------------------

MARCADOR_FIM = 'Dump completed on'


def conferir_dump_gz(caminho):
    """Le o arquivo DE VOLTA DO DISCO e devolve (bytes_sql, ultima_linha).

    Nao confia no que acabou de escrever. Percorrer o gzip inteiro forca a
    conferencia do CRC (o modulo gzip levanta ao chegar no fim se nao bater), e
    de quebra guarda a ultima linha nao vazia, onde o mysqldump escreve
    "Dump completed on ..." -- linha que so existe quando ele terminou.
    """
    bytes_sql = 0
    cauda = b''
    with gzip.open(caminho, 'rb') as comprimido:
        while True:
            bloco = comprimido.read(4 * 1024 * 1024)
            if not bloco:
                break
            bytes_sql += len(bloco)
            cauda = (cauda + bloco)[-4096:]
    linhas = [l.strip() for l in cauda.decode('utf-8', 'replace').splitlines()]
    nao_vazias = [l for l in linhas if l]
    return bytes_sql, (nao_vazias[-1] if nao_vazias else '')


# -- O envio ------------------------------------------------------------------

def _cliente_dropbox():
    """Cliente autenticado, reaproveitando as credenciais que o app ja usa.

    `integrations.dropbox_ofx` monta o cliente com OAuth2 + refresh token
    (DROPBOX_APP_KEY / _APP_SECRET / _REFRESH_TOKEN). Reaproveitar em vez de
    duplicar: assim uma troca de credencial vale para os dois caminhos.
    """
    from integrations.dropbox_ofx import _criar_dbx
    return _criar_dbx()


def enviar_para_dropbox(caminho_local, destino_remoto, limite_sessao=LIMITE_SESSAO,
                        cliente=None):
    """Sobe o arquivo e devolve o tamanho que o Dropbox diz ter recebido.

    Acima de `limite_sessao` vai por sessao em blocos: o `files_upload` simples
    para em 150 MB e carrega o arquivo inteiro na memoria.
    """
    from dropbox.files import CommitInfo, UploadSessionCursor, WriteMode

    dbx = cliente or _cliente_dropbox()
    tamanho = os.path.getsize(caminho_local)
    modo = WriteMode.overwrite

    with open(caminho_local, 'rb') as arquivo:
        if tamanho <= limite_sessao:
            dbx.files_upload(arquivo.read(), destino_remoto, mode=modo)
        else:
            sessao = dbx.files_upload_session_start(arquivo.read(BLOCO_SESSAO))
            cursor = UploadSessionCursor(session_id=sessao.session_id,
                                         offset=arquivo.tell())
            comprovante = CommitInfo(path=destino_remoto, mode=modo)
            while tamanho - arquivo.tell() > BLOCO_SESSAO:
                dbx.files_upload_session_append_v2(arquivo.read(BLOCO_SESSAO), cursor)
                cursor.offset = arquivo.tell()
            dbx.files_upload_session_finish(arquivo.read(BLOCO_SESSAO), cursor,
                                            comprovante)

    return dbx.files_get_metadata(destino_remoto).size


# -- O status no banco --------------------------------------------------------

_DDL_APP_CONFIG = """
CREATE TABLE IF NOT EXISTS `app_config` (
    `chave`      VARCHAR(100) NOT NULL,
    `valor`      TEXT         NULL,
    `updated_at` TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`chave`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _conectar():
    import pymysql
    return pymysql.connect(**db_credentials.pymysql_params())


def gravar_status(status):
    """Grava o status como JSON em `app_config`. Cria a tabela se faltar.

    Cria aqui tambem, e nao so na migration, porque o servico de cron nao sobe o
    Flask -- e portanto nunca passa pelo runner de migrations.
    """
    conexao = _conectar()
    try:
        with conexao.cursor() as cursor:
            cursor.execute(_DDL_APP_CONFIG)
            cursor.execute(
                "INSERT INTO app_config (chave, valor) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE valor = VALUES(valor), "
                # explicito: `ON UPDATE CURRENT_TIMESTAMP` so dispara quando o
                # valor MUDA, e a idade nao pode depender disso.
                "updated_at = CURRENT_TIMESTAMP",
                (CHAVE_STATUS, json.dumps(status, ensure_ascii=False)),
            )
        conexao.commit()
    finally:
        conexao.close()


def ler_status():
    """Status do ultimo backup + `idade_s` pelo RELOGIO DO BANCO.

    A idade sai de TIMESTAMPDIFF(SECOND, updated_at, NOW()) de proposito: o
    `datetime.now()` do Python diverge entre o worker web e o container do cron,
    e e a idade que denuncia a rodada que NAO aconteceu.

    Devolve None quando nao ha registro (ou quando o banco nao responde) -- quem
    chama trata como "sem registro", nunca como sucesso.
    """
    try:
        conexao = _conectar()
    except Exception:
        return None
    try:
        with conexao.cursor() as cursor:
            cursor.execute(
                "SELECT valor, TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS idade_s "
                "FROM app_config WHERE chave = %s", (CHAVE_STATUS,))
            linha = cursor.fetchone()
        if not linha or not linha.get('valor'):
            return None
        status = json.loads(linha['valor'])
        status['idade_s'] = int(linha['idade_s'] or 0)
        return status
    except Exception:
        return None
    finally:
        try:
            conexao.close()
        except Exception:
            pass


# -- A rodada -----------------------------------------------------------------

def _agora_brasilia():
    try:
        from utils.fuso import BRASILIA
        return datetime.now(BRASILIA)
    except Exception:
        return datetime.utcnow()


def _falha(etapa, erro, inicio, extra=None):
    status = {
        'ok': False,
        'etapa': etapa,
        'erro': str(erro)[:4000],
        'duracao_s': round(time.time() - inicio, 1),
        'quando': _agora_brasilia().strftime('%d/%m/%Y %H:%M'),
    }
    if extra:
        status.update(extra)
    return status


def _guardar(status):
    """Grava o status e devolve. Se nem gravar der, marca no proprio retorno --
    o cron ainda imprime, e o `exit 1` continua acusando a falha."""
    try:
        gravar_status(status)
    except Exception as erro:
        status = dict(status)
        status['status_nao_gravado'] = str(erro)[:500]
    return status


def executar(destino_pasta=None, limite_sessao=LIMITE_SESSAO, cliente_dropbox=None):
    """Faz o backup inteiro e devolve o status. NUNCA levanta excecao.

    Etapas, na ordem: localizar -> dump -> conferencia -> envio.
    O arquivo so sobe se passar nos TRES testes da conferencia.
    """
    inicio = time.time()
    destino_pasta = (destino_pasta
                     or os.environ.get('BACKUP_DROPBOX_PASTA')
                     or DESTINO_PADRAO).rstrip('/')
    anterior = ler_status() or {}
    nome = 'railway_%s.sql.gz' % _agora_brasilia().strftime('%Y-%m-%d_%H%M')
    destino_remoto = '%s/%s' % (destino_pasta, nome)
    caminho_local = os.path.join(
        os.environ.get('BACKUP_TMPDIR') or tempfile.gettempdir(), nome)

    # Tamanho do ultimo backup que DEU CERTO, para o aviso de encolhimento.
    # Vem de uma chave propria e e carregado adiante tambem nas falhas: se
    # olhasse so o `bytes_gz` do status anterior, uma unica rodada com erro
    # apagaria a referencia e o aviso morreria calado justamente depois de um
    # dia ruim -- que e quando ele mais serve.
    referencia_ok = int(anterior.get('ultimo_ok_bytes_gz')
                        or (anterior.get('bytes_gz') if anterior.get('ok') else 0)
                        or 0)

    def falhar(etapa, erro, extra=None):
        dados = {'ultimo_ok_bytes_gz': referencia_ok} if referencia_ok else {}
        dados.update(extra or {})
        return _guardar(_falha(etapa, erro, inicio, dados))

    try:
        # 1. localizar
        try:
            binario = encontrar_mysqldump()
        except Exception as erro:
            return falhar('localizar_mysqldump', erro)

        # 2. dump
        try:
            codigo, erro_texto = gerar_dump_gz(caminho_local, binario)
        except Exception as erro:
            return falhar('dump', erro, {'binario': binario})
        if codigo != 0:
            return falhar('dump',
                          'mysqldump saiu com codigo %s. %s' % (codigo, erro_texto),
                          {'binario': binario})

        # 3. conferencia -- o portao. Os tres testes, e so entao o envio.
        try:
            bytes_sql, ultima_linha = conferir_dump_gz(caminho_local)
        except Exception as erro:
            return falhar('verificacao',
                          'o .gz nao le de volta (CRC/truncado): %s' % erro)
        if MARCADOR_FIM not in ultima_linha:
            return falhar(
                'verificacao',
                'falta o marcador "%s" no fim do dump -- ele foi interrompido. '
                'Ultima linha: %r' % (MARCADOR_FIM, ultima_linha[:200]))

        bytes_gz = os.path.getsize(caminho_local)
        if bytes_gz < PISO_BYTES:
            return falhar(
                'verificacao',
                'arquivo com %d bytes, abaixo do piso de %d.' % (bytes_gz, PISO_BYTES))

        aviso = None
        if referencia_ok and bytes_gz < referencia_ok * FRACAO_AVISO:
            aviso = ('encolheu: %s contra %s do ultimo backup que deu certo.'
                     % (formatar_bytes(bytes_gz), formatar_bytes(referencia_ok)))

        # 4. envio
        try:
            bytes_no_destino = enviar_para_dropbox(
                caminho_local, destino_remoto, limite_sessao, cliente_dropbox)
        except Exception as erro:
            return falhar('envio', erro, {'arquivo': nome, 'bytes_gz': bytes_gz})
        if bytes_no_destino != bytes_gz:
            return falhar(
                'envio',
                'o destino ficou com %d bytes e o arquivo tem %d.'
                % (bytes_no_destino, bytes_gz),
                {'arquivo': nome, 'bytes_gz': bytes_gz})

        return _guardar({
            'ok': True,
            'etapa': 'concluido',
            'erro': None,
            'arquivo': nome,
            'destino': destino_remoto,
            'bytes_gz': bytes_gz,
            'ultimo_ok_bytes_gz': bytes_gz,
            'bytes_sql': bytes_sql,
            'duracao_s': round(time.time() - inicio, 1),
            'quando': _agora_brasilia().strftime('%d/%m/%Y %H:%M'),
            'aviso': aviso,
        })
    finally:
        try:
            os.unlink(caminho_local)
        except OSError:
            pass


# -- Apresentacao (usada pelo card) -------------------------------------------

def formatar_bytes(quantidade):
    valor = float(quantidade or 0)
    for unidade in ('B', 'KB', 'MB', 'GB'):
        if valor < 1024 or unidade == 'GB':
            casas = 0 if unidade == 'B' else 1
            return ('%.*f %s' % (casas, valor, unidade)).replace('.', ',')
        valor /= 1024


#: Passou disto sem sucesso, alguma rodada NAO aconteceu.
LIMITE_ATRASO_S = 48 * 3600


def status_para_card(status=None, limite_atraso_s=LIMITE_ATRASO_S):
    """Traduz o status em algo que o template so precisa imprimir.

    A cor nao fala do ultimo resultado, fala da PROTECAO:
      verde    EM DIA     -- deu certo e e recente
      amarelo  ATRASADO   -- deu certo, mas ha tempo demais: uma rodada nao
                            aconteceu, e rodada que nao acontece nao deixa
                            registro de erro. E esse silencio que o amarelo
                            denuncia -- era o buraco de 30/08 a 01/09.
      vermelho FALHOU     -- traz a etapa e o motivo, para agir sem abrir log
      cinza    SEM REGISTRO
    """
    if status is None:
        return {
            'estado': 'sem_registro', 'cor': 'cinza',
            'titulo': 'BACKUP SEM REGISTRO',
            'icone': 'bi-question-circle',
            'detalhe': 'Nenhuma rodada registrada ainda.',
            'aviso': None,
        }

    idade_s = int(status.get('idade_s') or 0)
    quando = status.get('quando') or '?'

    if not status.get('ok'):
        return {
            'estado': 'falhou', 'cor': 'vermelho', 'titulo': 'BACKUP FALHOU',
            'icone': 'bi-x-octagon-fill',
            'detalhe': 'Parou na etapa "%s" em %s. %s' % (
                status.get('etapa') or '?', quando, status.get('erro') or ''),
            'aviso': None,
        }

    resumo = '%s · %s · %ss' % (
        status.get('arquivo') or '?',
        formatar_bytes(status.get('bytes_gz')),
        status.get('duracao_s'))

    if idade_s > limite_atraso_s:
        return {
            'estado': 'atrasado', 'cor': 'amarelo', 'titulo': 'BACKUP ATRASADO',
            'icone': 'bi-exclamation-triangle-fill',
            'detalhe': 'O ultimo deu certo em %s, ha %d h. Alguma rodada nao '
                       'aconteceu. %s' % (quando, idade_s // 3600, resumo),
            'aviso': status.get('aviso'),
        }

    return {
        'estado': 'em_dia', 'cor': 'verde', 'titulo': 'BACKUP EM DIA',
        'icone': 'bi-shield-fill-check',
        'detalhe': '%s · %s' % (quando, resumo),
        'aviso': status.get('aviso'),
    }
