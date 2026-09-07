# ATENCAO: este arquivo e ASCII PURO, de proposito. O PowerShell 5.1 le .ps1
# como ANSI quando nao ha BOM, e um travessao em UTF-8 vira tres bytes, um
# deles a aspa tipografica de fechamento -- que o PowerShell aceita como
# delimitador de string. Um travessao dentro de um texto entre aspas fecha a
# string no meio e o script inteiro para de compilar, com o erro apontando
# quinze linhas abaixo do problema. Nao use acento nem travessao aqui.
# Build do agente NH-Robo com Nuitka (Windows) - modo PASTA + ZIP.
#
# Por que PASTA (--standalone) e NAO --onefile: o onefile (e o PyInstaller) se
# descompactam numa pasta temporaria a CADA execucao - justamente o padrao que o
# Windows Defender marca como suspeito. Foi por isso que o Q-Robo abandonou o
# onefile. Em modo pasta o .exe roda direto, com as pecas ao lado, sem extrair
# nada em runtime.
#
# A saida vira um .zip com a mesma convencao do Q-Colabore: a RAIZ
# do zip ja e o conteudo do programa (o .exe + DLLs + tcl/tk), sem uma subpasta
# extra. O funcionario extrai e roda o .exe; o proprio programa cria C:\nhrobo
# (a casa dos dados) sozinho na 1a execucao.
#
# A --file-version e derivada do __version__ do fonte (nao hardcoded).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\build_nhrobo.ps1
#
# Pre-requisitos (uma vez):
#   pip install nuitka requests pystray pillow
#   Um compilador C: o Nuitka baixa o ziglang sozinho na 1a vez
#   (--assume-yes-for-downloads ja responde 'sim').

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$fonte = Join-Path $raiz "nhrobo_agente.py"
$saida = Join-Path $raiz "build"

# --- versao derivada do __version__ do fonte (nao hardcoded) ---
$verLinha = Select-String -Path $fonte -Pattern '^__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $verLinha) { throw "Nao achei __version__ em $fonte" }
$versao = $verLinha.Matches[0].Groups[1].Value
$fileVersion = ($versao.Split('.') + @('0','0','0','0'))[0..3] -join '.'
Write-Host "NH-Robo agente - versao $versao (file-version $fileVersion)" -ForegroundColor Cyan

$icone = Join-Path $raiz "nhrobo.ico"
$logoPng = Join-Path $raiz "nhrobo_logo.png"
$iconPng = Join-Path $raiz "nhrobo_icon.png"
# ---------------------------------------------------------------------------
# Limpa o cache do compilador C (zig) antes de compilar.
#
# Por que: o Nuitka poe as constantes num blob e gera um __constants_data.c de
# 312 bytes que so faz #embed do blob. O texto desse .c e IDENTICO entre um
# build e outro, e o cache do zig nao trata o arquivo embutido como
# dependencia. Resultado: ele devolve o objeto ANTIGO, com as constantes
# ANTIGAS dentro.
#
# Em 07/09/2026 isso produziu um nhrobo.exe com o servidor do Qualicontax,
# C:\qcolabore e a porta 52736. O Nuitka disse "Successfully created", o zip
# saiu do tamanho certo, e nada no log denunciou. So se descobre olhando dentro
# do binario.
#
# O preco de limpar e alguns minutos a mais por build, que acontece raramente.
# O preco de nao limpar e mandar o agente errado para cinco maquinas.
# ---------------------------------------------------------------------------
$zigCache = Join-Path $env:LOCALAPPDATA "Nuitka\\Nuitka\\Cache\\zig"
foreach ($sub in @("global", "local")) {
    $alvoCache = Join-Path $zigCache $sub
    if (Test-Path $alvoCache) {
        Write-Host ("Limpando cache do zig: {0}" -f $alvoCache) -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $alvoCache -ErrorAction SilentlyContinue
    }
}

$argsNuitka = @(
    "-m", "nuitka",
    "--standalone",                      # PASTA, sem --onefile (Defender)
    # SEM cache do compilador C. Nao e frescura: `__constants_data.c` tem
    # 312 bytes e so faz `#embed "blobs\__constant.bin"` - o texto do .c e
    # IDENTICO entre builds, entao o cache devolve o .o antigo com o blob
    # ANTIGO embutido. Em 07/09/2026 isso gerou um nhrobo.exe com as
    # strings do Qualicontax dentro: servidor deles, C:\qcolabore, porta
    # 52736. Teria ido para as cinco maquinas sem ninguem notar, porque o
    # build "deu certo". O cache nao enxerga o que foi embutido.
    "--disable-ccache",
    "--assume-yes-for-downloads",
    "--enable-plugin=tk-inter",
    "--include-package=pystray",         # backend do tray e importado por plataforma
    # imagens embutidas (logo do cabecalho + "Q" verde da janela/bandeja) - ficam
    # ao lado do .exe; o codigo as acha via _recurso(). Ver gerar_assets.py.
    "--include-data-file=$logoPng=nhrobo_logo.png",
    "--include-data-file=$iconPng=nhrobo_icon.png",
    "--windows-console-mode=disable",    # app de janela, sem console preto
    "--company-name=Grupo NH",
    "--product-name=NH-Robo Agente",
    "--file-version=$fileVersion",
    "--product-version=$fileVersion",
    "--file-description=Agente NH-Robo (envio de arquivos)",
    "--output-dir=$saida",
    "--output-filename=nhrobo.exe"
)
if (Test-Path $icone) { $argsNuitka += "--windows-icon-from-ico=$icone" }
$argsNuitka += $fonte

python @argsNuitka
if ($LASTEXITCODE -ne 0) { throw "Nuitka falhou (exit $LASTEXITCODE)." }

# Nuitka standalone gera <script>.dist com o .exe + pecas dentro.
$dist = Join-Path $saida "nhrobo_agente.dist"
if (-not (Test-Path (Join-Path $dist "nhrobo.exe"))) {
    throw "Pasta standalone nao encontrada em $dist"
}

# ---------------------------------------------------------------------------
# PROVA de que o .exe e o NOSSO. Em 07/09/2026 um build "bem-sucedido" produziu
# um nhrobo.exe com as strings do Qualicontax dentro (servidor deles,
# C:\qcolabore, porta 52736), por causa do cache do compilador C. Nada no log
# denunciou: o Nuitka disse "Successfully created" e o zip saiu do tamanho
# certo. So se descobre olhando dentro do binario -- entao o build olha.
#
# Sem isto, o erro chega nas maquinas dos colaboradores.
# ---------------------------------------------------------------------------
$exeBytes = [System.IO.File]::ReadAllBytes((Join-Path $dist "nhrobo.exe"))
$exeTexto = [System.Text.Encoding]::GetEncoding(28591).GetString($exeBytes)
$exeBytes = $null

if ($exeTexto -notmatch "postonovohorizonte") {
    throw "O .exe NAO contem o servidor do Grupo NH. Provavelmente o cache do compilador devolveu um objeto velho. Apague a pasta build e compile de novo."
}
foreach ($proibido in @("qcolabore", "QColabore", "app.qualicontax")) {
    if ($exeTexto -match [regex]::Escape($proibido)) {
        throw "O .exe contem '$proibido' - e o agente do Qualicontax, nao o nosso. NAO distribua. Apague a pasta build e compile de novo."
    }
}
$exeTexto = $null
Write-Host "Conferido: o .exe aponta para o Grupo NH e nao tem marca do Qualicontax." -ForegroundColor Green

# Compacta o CONTEUDO da pasta na RAIZ do zip (flat), como o do Q-Colabore.
$zip = Join-Path $saida ("nhrobo-{0}.zip" -f $versao)
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $dist "*") -DestinationPath $zip -CompressionLevel Optimal

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 2)
$nArq = (Get-ChildItem $dist -Recurse -File).Count
Write-Host "`nOK." -ForegroundColor Green
Write-Host ("  Pasta standalone: {0} ({1} arquivos)" -f $dist, $nArq)
Write-Host ("  ZIP para distribuir: {0} ({1} MB)" -f $zip, $mb) -ForegroundColor Green
Write-Host "Publique o ZIP onde os cinco colaboradores vao baixar." -ForegroundColor Yellow
Write-Host "Lembrete: se o Defender reclamar, veja 'Excecao no Defender' no README." -ForegroundColor Yellow
