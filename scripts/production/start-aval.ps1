<#
.SYNOPSIS
    Sobe a AVAL em producao neste device: migrations, build do navegador, API e tunel.

.DESCRIPTION
    Um processo de API e so um. Cada custodia deriva suas chaves da mesma
    AVAL_CUSTODY_SEED, entao um segundo processo ja nao invalida o primeiro - mas
    o SQLite continua tendo um escritor so, e dois uvicorn na mesma porta
    continuam sendo um erro. O script recusa subir se a porta ja estiver ocupada.

    -SkipTunnel sobe so em 127.0.0.1, para conferir antes de publicar.
    -SkipBuild pula o `npm run build` quando o bundle ja esta atual.

.EXAMPLE
    .\scripts\production\start-aval.ps1
    .\scripts\production\start-aval.ps1 -SkipTunnel
#>
param(
    [string]$EnvFile = ".env.production",
    [switch]$SkipTunnel,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

. "$PSScriptRoot\Load-AvalEnv.ps1" -Path $EnvFile

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Interpretador nao encontrado em $python" }

$avalHost = if ($env:AVAL_HOST) { $env:AVAL_HOST } else { "127.0.0.1" }
$port     = if ($env:AVAL_PORT) { $env:AVAL_PORT } else { "8099" }

# --- Um processo so -------------------------------------------------------
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    throw "A porta $port ja esta escutando (PID $($busy.OwningProcess)). Pare o processo antes de subir outro."
}

# --- Fail-closed conferido antes de abrir a porta -------------------------
# Estas quatro nao tem default seguro: sem elas a instancia sobe, parece viva e
# recusa todo mundo. Descobrir isso na frente de um jurado e o pior momento.
foreach ($required in 'AVAL_CUSTODY_SEED','AVAL_OPERATOR_TOKEN','AVAL_UI_HOLDER_CREDENTIAL','AVAL_PAIRWISE_SECRET') {
    if (-not (Get-Item "Env:$required" -ErrorAction SilentlyContinue).Value) {
        throw "$required nao esta definida em $EnvFile. A instancia subiria fechada."
    }
}

# --- Schema ---------------------------------------------------------------
# Migrations sao donas do banco. `metadata.create_all` no boot so cria tabelas
# que faltam e nunca faz ALTER, entao um banco que nunca passou por aqui fica
# com colunas de menos e so quebra em producao.
Write-Host "`n[1/4] Migrations..." -ForegroundColor Cyan
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head falhou." }

# --- Navegador ------------------------------------------------------------
# Servido same-origin pelo proprio FastAPI, entao nao ha VITE_AVAL_API_BASE_URL
# a definir: o bundle chama a origem de onde a pagina veio.
if (-not $SkipBuild) {
    Write-Host "`n[2/4] Build do navegador..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "web")
    try {
        Remove-Item Env:VITE_AVAL_API_BASE_URL -ErrorAction SilentlyContinue
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build falhou." }
    } finally { Pop-Location }
} else {
    Write-Host "`n[2/4] Build pulado (-SkipBuild)." -ForegroundColor DarkGray
}

# --- Tunel ----------------------------------------------------------------
# Ele sobe antes da API porque a URL publica precisa entrar em
# AVAL_ALLOWED_ORIGINS, e a API le esse valor no import.
$tunnel = $null
if (-not $SkipTunnel) {
    Write-Host "`n[3/4] Tunel HTTPS..." -ForegroundColor Cyan
    # A URL sai no stderr, nao num --logfile: a flag existe e nao produziu arquivo
    # nenhum nesta versao, entao a espera abaixo ficava esperando para sempre.
    $log    = Join-Path $root "var\cloudflared.log"
    $logOut = Join-Path $root "var\cloudflared.out.log"
    Remove-Item $log, $logOut -ErrorAction SilentlyContinue
    $tunnel = Start-Process cloudflared `
        -ArgumentList "tunnel","--no-autoupdate","--url","http://${avalHost}:$port" `
        -PassThru -NoNewWindow -RedirectStandardError $log -RedirectStandardOutput $logOut

    $public = $null
    foreach ($attempt in 1..60) {
        Start-Sleep -Milliseconds 500
        if ($tunnel.HasExited) {
            throw "cloudflared saiu com codigo $($tunnel.ExitCode). Veja $log."
        }
        foreach ($candidate in @($log, $logOut)) {
            if (-not (Test-Path $candidate)) { continue }
            $match = Select-String -Path $candidate -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue |
                     Select-Object -First 1
            if ($match) { $public = $match.Matches[0].Value; break }
        }
        if ($public) { break }
    }
    if (-not $public) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
        throw "O tunel nao publicou uma URL em 30s. Veja $log."
    }
    # Nomear origens EXCLUI os defaults de dev - e por isso que a URL publica
    # precisa entrar aqui, e por isso que localhost:5173 deixa de ser confiavel.
    $env:AVAL_ALLOWED_ORIGINS = $public
    Write-Host "  URL publica: $public" -ForegroundColor Green
} else {
    Write-Host "`n[3/4] Tunel pulado (-SkipTunnel)." -ForegroundColor DarkGray
    # Sem HTTPS o cookie de sessao `Secure` nunca chega de volta, e nenhum papel
    # consegue logar. Este e o unico caso em que afrouxa-lo e correto.
    $env:AVAL_UI_LOCAL_HTTP = "true"
    Write-Host "  HTTP local: AVAL_UI_LOCAL_HTTP=true (cookie sem Secure)." -ForegroundColor DarkGray
}

Write-Host "`n[4/4] API em http://${avalHost}:$port" -ForegroundColor Cyan
Write-Host "  Ctrl+C encerra a API e o tunel.`n" -ForegroundColor DarkGray

try {
    & $python -m uvicorn aval.main:app --host $avalHost --port $port
} finally {
    if ($tunnel) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
        Write-Host "Tunel encerrado." -ForegroundColor DarkGray
    }
}
