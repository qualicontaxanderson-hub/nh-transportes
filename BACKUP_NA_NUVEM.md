# Backup do banco na nuvem — receita vinda do Qualicontax

> Escrito em 02/09/2026 a partir da implantação real feita no `app.qualicontax.com.br`,
> incluindo as três rodadas que falharam antes de acertar. Página equivalente:
> https://claude.ai/code/artifact/34b299ed-d6b5-42cd-b6dc-932f26a80e5b

**Objetivo:** o backup do banco deste app deve rodar sozinho num serviço de cron da
Railway, verificar o próprio trabalho, enviar o arquivo ao Dropbox e **mostrar numa
tela** se deu certo — sem depender de computador ligado.

---

## 1. Por que existe

No Qualicontax o backup era uma tarefa agendada no PC do Anderson. Em 29/08/2026 o
dump saiu com **52 bytes** (a máquina perdeu a rede no meio) e de 30/08 a 01/09 a
tarefa nem disparou, porque os computadores estavam desligados. **Quatro dias sem
backup, e ninguém soube** — a única testemunha da falha era um arquivo de log.

Daí as duas exigências que definem todo o resto:

1. o backup **não pode depender de máquina ligada**;
2. a falha **precisa ter testemunha** — alguém tem que ver, sem procurar.

---

## 2. Premissas — já conferidas neste repositório

Inspecionado em 02/09/2026. A pilha é irmã da do Qualicontax:

| Premissa | Situação |
|---|---|
| Flask + MySQL + Python 3.12 | **Confere** — Flask 3.0.0, `mysql-connector-python` 9.5, `pymysql`, `python-3.12` |
| Nomes das variáveis do banco | **Idênticos** — `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| SDK do Dropbox | **Já instalado** — `dropbox==12.0.2` |
| Credenciais do Dropbox | **Já em uso** — `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`, lidas por `integrations/dropbox_dfe.py` e `integrations/dropbox_ofx.py` |
| Tabela chave/valor para o status | **Não existe** `app_config`. Há algo chamado `parametros` — confirmar se serve; senão, criar uma tabela pequena |
| Arranque do site | `Procfile: web: bash start.sh` — não interfere, o cron usa Start Command próprio |

### Ainda depende de decisão (perguntar ao Anderson)

- **O alcance do token do Dropbox** — não dá para saber pelo código se é *Full Dropbox*
  ou *app folder*. **Teste listando a pasta de destino antes de escrever a etapa de
  envio.** Se for app folder, o backup tem que ficar dentro da pasta do aplicativo.
- **A pasta de destino** do `.sql.gz`.
- **A tela que recebe o card** e quem pode vê-la.
- **O horário do cron** — escolher um que não colida com as outras rotinas deste app.

---

## 3. O que construir

### 3.1 O módulo do backup (`utils/backup_bd.py` na origem)

Um arquivo só, com a lógica inteira. **Nunca levanta exceção**: qualquer falha vira um
status com `etapa` e `erro`, gravado no banco.

**O dump** — `subprocess` chamando o `mysqldump`, comprimindo direto para `.sql.gz`
(sem passar pelo disco descomprimido):

```
--defaults-extra-file=<arquivo temporário 0600>
--databases <DB_NAME>
--single-transaction
--quick
--max-allowed-packet=1G
--routines --triggers
--add-drop-database --add-drop-table
--default-character-set=utf8mb4
```

> **LEI:** a senha vai por `--defaults-extra-file`, arquivo temporário criado com
> permissão `0600` e apagado no `finally`. **Nunca em `argv`** — senha em argumento
> aparece na lista de processos para quem abrir um shell no container.

**A verificação — o portão de verdade.** É a parte que ninguém pensa em construir e que
teria evitado o incidente inteiro. Num pipe, o código de saída pode ser o do
*compressor*, não o do mysqldump: se o dump morre no meio, o `.gz` sai **íntegro porém
truncado**, com cara de sucesso. Foi assim que nasceu o arquivo de 52 bytes.

Três testes, e o arquivo só sobe passando nos três:

1. código de saída do `mysqldump` (o do processo, não o do pipe);
2. CRC do gzip — leia o arquivo **de volta do disco**, não confie no que escreveu;
3. marcador `Dump completed on` na última linha não vazia.

Some um piso de tamanho (1 MB) e um **aviso** — não reprovação — quando o arquivo
encolhe abaixo de 70% do anterior.

**O envio.** O `files_upload` simples do Dropbox **para em 150 MB** e carrega tudo na
memória. Um backup de 215 MB precisa de **sessão**: `upload_session_start` →
`append_v2` em blocos de 8 MB → `upload_session_finish`. Corte em 140 MB para não
namorar a borda.

**O status.** Grave um JSON numa linha da tabela chave/valor com `ok`, `etapa`, `erro`,
`arquivo`, `destino`, `bytes_gz`, `duracao_s` e `quando`. Para a idade use **o relógio
do banco** (`TIMESTAMPDIFF(SECOND, updated_at, NOW())`), nunca o `datetime.now()` do
Python, que diverge entre workers e fusos.

### 3.2 O entrypoint do cron (`cron_backup.py` na origem)

Arquivo fino, no molde dos crons que este app já tiver:

- sai sem fazer nada se `BACKUP_ATIVO != "1"` — **nasce desligado**, o que permite subir
  o código antes de o serviço existir;
- chama o módulo;
- devolve `exit 1` na falha — é por esse código que a Railway marca a rodada como falha.

### 3.3 O card na tela

Cartão lendo o status. A cor não fala só do último resultado, fala da **proteção**:

- **EM DIA** (verde) — deu certo e tem menos de 48 h; mostra hora, tamanho e duração.
- **ATRASADO** (amarelo) — deu certo, mas passou de 48 h: alguma rodada **não
  aconteceu**. Rodada que não acontece não deixa registro de erro, some calada — é esse
  silêncio que o amarelo denuncia, e era exatamente o buraco de 30/08 a 01/09.
- **FALHOU** (vermelho) — traz a etapa e o motivo escritos, para agir sem abrir log.

Renderize os quatro estados (com o "sem registro") usando status forjado antes de dar
por pronto. Verde aparece sozinho; amarelo e vermelho só no dia ruim, que é justamente
o dia em que ninguém quer descobrir um template quebrado.

---

## 4. Configuração na Railway

1. **Suba o código primeiro.** O serviço lê do GitHub; criar antes do push só produz uma
   rodada falhando por arquivo inexistente.
2. **New Service → GitHub Repo**, mesmo repositório. Em *Settings → Source*, confirme
   que a **branch** é a que a produção usa (se vier `main` por padrão e o app viver
   noutra, troque — é o erro mais fácil de cometer).
3. **Settings → Build → Builder: `Nixpacks`.** Ver a armadilha nº 1 abaixo — não pule.
4. **Deploy:**
   - Custom Start Command: `python cron_backup.py`
   - Cron Schedule: `0 6 * * *` — o campo é **UTC**; isso é **03:00 em Brasília**.
5. **Variables** (Raw Editor), por referência ao serviço web em vez de copiar valores —
   assim, trocar uma senha lá atualiza aqui sozinho:

```
DB_HOST="${{<servico-web>.DB_HOST}}"
DB_PORT="${{<servico-web>.DB_PORT}}"
DB_NAME="${{<servico-web>.DB_NAME}}"
DB_USER="${{<servico-web>.DB_USER}}"
DB_PASSWORD="${{<servico-web>.DB_PASSWORD}}"
DROPBOX_APP_KEY="${{<servico-web>.DROPBOX_APP_KEY}}"
DROPBOX_APP_SECRET="${{<servico-web>.DROPBOX_APP_SECRET}}"
DROPBOX_REFRESH_TOKEN="${{<servico-web>.DROPBOX_REFRESH_TOKEN}}"
BACKUP_ATIVO=1
NIXPACKS_PKGS=mysql80
```

6. **Prove antes de confiar.** Não espere as 3 h da manhã: ponha `*/15 * * * *`, veja
   uma rodada acontecer de verdade e **volte para `0 6 * * *` assim que passar** — a
   cada 15 minutos são ~215 MB, uns 20 GB por dia.

---

## 5. As três armadilhas (custaram uma manhã)

### 5.1 A Railway não constrói com Nixpacks

Três rodadas falharam com `mysqldump não existe`, com a variável certa e escrita certa.
Os serviços novos são construídos com **Railpack**, que ignora qualquer variável
`NIXPACKS_*` **em silêncio**: o build passa, o serviço fica *Ready*, e o binário nunca
entra na imagem.

Dá para saber qual construtor rodou **sem acesso ao container**, pelo `PATH`:

```
/app/.venv/bin:/mise/shims:/usr/local/sbin:...   → RAILPACK  (tem /mise/shims)
...caminhos com /nix/store...                    → NIXPACKS
```

| Quero | Railpack | Nixpacks |
|---|---|---|
| pacote de sistema no runtime | `RAILPACK_DEPLOY_APT_PACKAGES` | `NIXPACKS_PKGS` |

Trocar o Builder para **Nixpacks** (aparece marcado como *Deprecated*, mas ainda
constrói) resolveu de uma vez, e traz o `mysqldump` **genuíno da Oracle**. Pelo
Railpack o caminho seria `RAILPACK_DEPLOY_APT_PACKAGES=default-mysql-client`, que no
Debian instala o cliente do **MariaDB** — e o `mariadb-dump` recente escreve uma linha
de *sandbox mode* no topo do arquivo que o cliente do MySQL recusa ao restaurar.
**Backup que não restaura não é backup.**

### 5.2 A rodada que dispara durante o build usa a imagem velha

Depois de trocar o builder, a rodada seguinte falhou igual — e parecia que a troca não
tinha pegado. Não era: o build ainda corria e o cron disparou sobre a imagem anterior.
**Confira o `PATH` do erro antes de concluir qualquer coisa**, e espere o deployment
ficar *ACTIVE*.

### 5.3 Erro de ambiente tem que acusar o ambiente

A primeira falha só dizia "não existe", e cada palpite de variável custava dez minutos
de espera. Passar a mensagem a carregar o `PATH` do container e a lista do que existia
na imagem revelou a causa **em uma única rodada**, sem console e sem acesso à máquina.
Construa isso *antes* de precisar.

No mesmo espírito, procure o binário em quatro lugares antes de desistir: a variável
explícita, o `PATH`, os caminhos usuais de pacote apt e por fim `/nix/store/*/bin/mysqldump`.
Procurar é barato; uma rodada perdida por `PATH` custa um dia de backup.

---

## 6. As leis

- **NUNCA `PURGE BINARY LOGS`.** Derruba a janela de recuperação ponto-no-tempo e é
  irreversível. Se a rotina antiga do PC fizer isso, o cron da nuvem **não** deve fazer.
- **NUNCA apagar backup antigo automaticamente.** Retenção é decisão humana; deixe a
  pasta crescer e trate num segundo momento, com o dono olhando.
- **Restaurar apaga o banco.** O `.sql.gz` começa com `DROP DATABASE` (por causa do
  `--add-drop-database`). Nunca rodar de improviso.

---

## 7. Como provar que ficou pronto

| Prova | Como |
|---|---|
| Envio por sessão | arquivo pequeno com o limite baixado à força, conferindo o tamanho no destino byte a byte |
| Backup ponta a ponta | rodar o entrypoint de verdade, uma vez, e ver o arquivo no Dropbox |
| Os estados do card | renderizar os quatro com status forjado, todos HTTP 200 |
| Nenhuma tela quebrada | abrir todas as rotas GET antes e depois, comparando a lista |
| A rodada real, sozinha | a única que prova o container: cron disparando sem ninguém por perto |

Sinal barato durante o teste: **se o `Running` passar de um minuto, o binário foi
encontrado.** A falha do `mysqldump` acontece em segundos; o dump leva minutos.

---

## 8. Números de referência (do Qualicontax)

| | |
|---|---|
| Banco | 1,5 GB descomprimido |
| Arquivo final | 215 MB (`.sql.gz`, ~6,7x de compressão) |
| Rodada completa | **111 s** dentro da Railway (contra 514 s quando o dump saía pela internet até o PC) |
| Horário | `0 6 * * *` = 03:00 em Brasília |

No app do posto os números serão outros, mas as proporções e as armadilhas são as mesmas.
