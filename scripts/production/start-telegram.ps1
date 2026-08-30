<#
.SYNOPSIS
    Sobe o bot do Telegram contra a API que ja esta de pe neste device.

.DESCRIPTION
    Processo separado da API: o bot faz long polling e nunca poderia viver dentro
    do mesmo servidor ASGI. Ele fala com a API por localhost e nao pelo tunel -
    um salto a menos, e nada de bot dependendo da URL publica ainda existir.
#>
param([string]$EnvFile = ".env.production")

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

. "$PSScriptRoot\Load-AvalEnv.ps1" -Path $EnvFile

if (-not $env:TELEGRAM_BOT_TOKEN) {
    throw "TELEGRAM_BOT_TOKEN nao esta definida em $EnvFile."
}

$avalHost = if ($env:AVAL_HOST) { $env:AVAL_HOST } else { "127.0.0.1" }
$port     = if ($env:AVAL_PORT) { $env:AVAL_PORT } else { "8099" }
$env:AVAL_API_BASE_URL = "http://${avalHost}:$port"

# A API precisa estar respondendo antes: um bot que sobe primeiro entrega o
# primeiro /start a um servidor que nao existe, e o usuario ve um erro cru.
if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
    throw "A API nao esta escutando em $($env:AVAL_API_BASE_URL). Rode start-aval.ps1 primeiro."
}

Write-Host "Bot contra $($env:AVAL_API_BASE_URL). Ctrl+C encerra." -ForegroundColor Cyan
& (Join-Path $root ".venv\Scripts\python.exe") -m aval.interfaces.telegram
