<#
.SYNOPSIS
    Carrega `.env.production` no processo atual.

.DESCRIPTION
    A aplicação lê `os.environ` no import (`aval.main` constrói o app no nível do
    módulo), então as variáveis precisam existir *antes* do uvicorn importar
    qualquer coisa. Por isso um dot-source e não um processo filho.

        . .\scripts\production\Load-AvalEnv.ps1

    Linhas em branco e comentários são ignorados. O valor é tudo depois do
    primeiro `=`, sem trim à direita além de espaços — um segredo pode conter
    `=`, e cortar no último quebraria justamente as chaves.
#>
param([string]$Path = ".env.production")

if (-not (Test-Path $Path)) {
    throw "Arquivo de ambiente não encontrado: $Path. Copie .env.example e preencha."
}

$loaded = 0
foreach ($line in Get-Content $Path -Encoding UTF8) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
    $split = $trimmed.IndexOf("=")
    if ($split -lt 1) { continue }
    $name  = $trimmed.Substring(0, $split).Trim()
    $value = $trimmed.Substring($split + 1).Trim()
    # Uma variável vazia é "desligado" em todo lugar neste sistema, e o código
    # trata ausente e vazio igual. Definir como "" mantém essa equivalência.
    Set-Item -Path "Env:$name" -Value $value
    $loaded++
}
Write-Host "Ambiente carregado de $Path ($loaded variáveis)." -ForegroundColor Green
