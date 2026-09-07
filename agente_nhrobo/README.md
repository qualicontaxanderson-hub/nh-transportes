# NH-Robô — agente da máquina do funcionário

Programa que roda na máquina do funcionário, vigia as pastas que ele escolher e
manda cada arquivo novo para a nuvem do Grupo NH (a caixa `_ENTRADA`),
autenticado pela **chave dele**. É o irmão do Q-Robô (que faz o mesmo por posto):
a inteligência fica no servidor; o agente é simples.

- **Casa dos dados:** `C:\nhrobo` (config e log). O programa a cria sozinho.
- **Nunca apaga** arquivo do usuário — só **move** para subpastas.
- A **chave** mora só em `C:\nhrobo\config.json`. Nunca em variável de
  ambiente, registro do Windows, ou log.

---

## Como funciona (resumo)

1. Lê `config.json`: a chave e as pastas a vigiar.
2. A cada ~60 s procura arquivo novo nessas pastas.
3. Pergunta ao servidor a **data de corte** (`GET /api/nhrobo/config`) e
   **ignora** arquivo anterior a ela (essa data é sempre do servidor).
4. Envia cada arquivo (`POST /api/nhrobo/enviar`, chave no `Bearer`).
5. Pelo resultado (conferido no codigo em 06/09/2026 — a versao 0.4.0
   parou de MOVER o arquivo do usuario, e `Enviados` sobrou so como
   pasta a ser ignorada na varredura):
   | Resposta | O que o agente faz |
   |----------|--------------------|
   | **200 / 409** | anota no caderninho. **Nada é movido** — o arquivo fica onde a pessoa salvou |
   | **413 / 415** | anota como recusado e deixa uma **cópia** em **`Nao enviados`** + um `.motivo.txt`. O original não sai do lugar |
   | **401 / 403** (chave inválida/revogada) | **para de enviar** e avisa na janela (o programa continua aberto para colar a chave nova) |
   | **5xx / sem rede** | deixa onde está e tenta de novo depois |

### Fica de pé sozinho
- **Nunca morre por erro:** exceção num arquivo é anotada no log e o agente segue
  para o próximo; qualquer erro inesperado no ciclo é capturado e o laço continua.
- **Perda de rede / servidor fora / Dropbox indisponível:** não encerra — espera
  e tenta de novo com **intervalo crescente** (dobra até no máximo 5 min), voltando
  ao normal quando reconecta.
- **Heartbeat:** mesmo sem arquivo novo, a consulta periódica ao servidor atualiza
  o "último contato" — o escritório distingue máquina desligada de máquina parada.

### Início com o Windows
Ao **Salvar** a configuração, se a caixa *"Iniciar junto com o Windows"* estiver
marcada (é o padrão), o agente se registra para subir no logon — no perfil do
**próprio usuário**, **sem exigir administrador** (chave `HKCU\...\Run`,
valor `NHRobo`, guardando só o caminho do `.exe`, nunca a chave). Desmarcar
remove o registro. A janela de status mostra se está ativo.

---

## Instalar (a partir do .zip)

1. Baixe **`nhrobo-0.3.0.zip`** da pasta do Dropbox
   `/Aplicativos/GRUPO NH/NH-Robô/`.
2. **Extraia tudo** para uma pasta fixa — o mais simples é **`C:\nhrobo`**
   (clique direito no `.zip` → *Extrair tudo…*).
3. Rode **`nhrobo.exe`** de dentro dessa pasta.
4. Na janela (uma só, com as etapas numeradas como a do Q-Robô):
   **(1)** cole a chave e clique **Testar conexão** — ela mostra o **nome do
   funcionário** dono da chave, para você confirmar; **(2)** **Adicione** a(s)
   pasta(s) a vigiar; **(3)** deixe *"Iniciar junto com o Windows"* marcada e
   clique **Ativar**.

Pronto — o agente vai para a **bandeja** (ao lado do relógio) e trabalha sozinho.
Clique no ícone para abrir; botão direito tem **Abrir**, **Configurar…** e
**Sair**. Fechar no **X** minimiza para a bandeja (não encerra).

O log fica em `C:\nhrobo\nhrobo.log` (com rotação; **nunca** grava a chave).

---

## Compilar (gerar o .zip para distribuir)

Tecnologia: **Nuitka em modo PASTA** (`--standalone`, **sem** `--onefile`).
O `--onefile` (e o PyInstaller) descompactam numa pasta temporária a cada
execução — o padrão que o **Defender** marca. Em modo pasta o `.exe` roda direto,
com as peças ao lado.

```powershell
pip install nuitka requests pystray pillow
powershell -ExecutionPolicy Bypass -File .\build_nhrobo.ps1
```

O script:
- deriva a `--file-version` do `__version__` do fonte (não hardcoded);
- gera a pasta `build\nhrobo_agente.dist\` (o `.exe` + DLLs + tcl/tk);
- compacta o **conteúdo** dela na raiz de `build\nhrobo-0.3.0.zip` — a **mesma
  convenção do `nhrobo.zip` do Q-Robô** (raiz do zip = o programa, sem
  subpasta extra).

Publique o `.zip` em `/Aplicativos/GRUPO NH/NH-Robô/`, no lugar do `.exe`.
Na primeira vez o Nuitka baixa o compilador **ziglang** — responda **sim**.

---

## Exceção no Windows Defender

Se uma máquina mais rígida barrar o programa, adicione uma exceção para a pasta
onde ele foi extraído:

1. **Segurança do Windows** → **Proteção contra vírus e ameaças**.
2. *Configurações de proteção contra vírus e ameaças* → **Gerenciar configurações**.
3. **Exclusões** → **Adicionar ou remover exclusões** → **Adicionar uma exclusão**
   → **Pasta**.
4. Escolha a pasta onde está o `nhrobo.exe` (ex.: **`C:\nhrobo`**).

A solução definitiva é **assinar** o executável com um certificado de código.

---

## Arquivos deste diretório

| Arquivo | O quê |
|---------|-------|
| `nhrobo_agente.py` | o agente (janela única + loop + bandeja + envio) |
| `build_nhrobo.ps1` | build Nuitka (pasta) + zip, com logo/ícone embutidos |
| `gerar_assets.py` | gera logo/ícone/.ico a partir das imagens do sistema |
| `nhrobo_logo.png` / `nhrobo_icon.png` / `nhrobo.ico` | assets embutidos |
| `requirements.txt` | dependências (`requests`, `pystray`, `Pillow`) |
| `README.md` | este arquivo |

> A variável de ambiente `NHROBO_HOME` troca a casa `C:\nhrobo` por outra
> pasta — usada **só** pela prova automatizada. Em produção não defina.
