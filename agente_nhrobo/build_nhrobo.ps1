# Build do agente NH-Robo com Nuitka (Windows) — modo PASTA + ZIP.
#
# Por que PASTA (--standalone) e NAO --onefile: o onefile (e o PyInstaller) se
# descompactam numa pasta temporaria a CADA execucao — justamente o padrao que o
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
$argsNuitka = @(
    "-m", "nuitka",
    "--standalone",                      # PASTA, sem --onefile
    "--assume-yes-for-downloads",
    "--enable-plugin=tk-inter",
    "--include-package=pystray",         # backend do tray e importado por plataforma
    # imagens embutidas (logo do cabecalho + "Q" verde da janela/bandeja) — ficam
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
