<#
.SYNOPSIS
    Sorteia os segredos de produção e escreve `.env.production`.

.DESCRIPTION
    Preenche apenas o que precisa ser forte e secreto; o resto vem do
    `.env.example`. Não sobrescreve um arquivo existente sem `-Force`, porque
    trocar AVAL_CUSTODY_SEED invalida toda identidade já registrada no banco.
#>
param([switch]$Force)

# Uma falha aqui tem de parar o script. Sem isto, um gerador que nao funciona
# neste PowerShell devolve buffers zerados, o arquivo e escrito assim mesmo, e a
# instancia sobe com segredos previsiveis - a pior forma de falhar que existe.
$ErrorActionPreference = 'Stop'

$target = ".env.production"
if ((Test-Path $target) -and (-not $Force)) {
    throw "$target já existe. Use -Force para sortear segredos NOVOS — isso invalida as chaves atuais e o banco terá de ser recriado."
}

# RNGCryptoServiceProvider e nao RandomNumberGenerator::Fill: Fill so existe no
# .NET Core, e o Windows PowerShell 5.1 roda sobre o .NET Framework.
$script:Rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider

function New-Secret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    $script:Rng.GetBytes($buffer)
    if (($buffer | Where-Object { $_ -ne 0 }).Count -eq 0) {
        throw "O gerador devolveu bytes zerados. Nenhum segredo sera escrito."
    }
    [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+','-').Replace('/','_')
}

$secrets = [ordered]@{
    AVAL_CUSTODY_SEED            = New-Secret 48
    AVAL_OPERATOR_AUTHORITY_SEED = New-Secret 48
    AVAL_PAIRWISE_SECRET         = New-Secret 48
    AVAL_OPERATOR_TOKEN          = New-Secret 24
    AVAL_UI_HOLDER_CREDENTIAL    = New-Secret 9
    AVAL_UI_MERCHANT_CREDENTIAL  = New-Secret 9
    AVAL_UI_AUDITOR_CREDENTIAL   = New-Secret 9
    AVAL_UI_OPERATOR_CREDENTIAL  = New-Secret 9
}

$lines = foreach ($line in Get-Content ".env.example" -Encoding UTF8) {
    $name = if ($line -match '^([A-Z0-9_]+)=') { $Matches[1] } else { $null }
    if ($name -and $secrets.Contains($name)) { "$name=$($secrets[$name])" } else { $line }
}
Set-Content -Path $target -Value $lines -Encoding UTF8

Write-Host "$target escrito com segredos novos." -ForegroundColor Green
Write-Host "Credenciais de login do navegador:" -ForegroundColor Cyan
foreach ($role in 'HOLDER','MERCHANT','AUDITOR','OPERATOR') {
    "  {0,-9} {1}" -f $role.ToLower(), $secrets["AVAL_UI_${role}_CREDENTIAL"]
}
"  {0,-9} {1}" -f 'operador', $secrets.AVAL_OPERATOR_TOKEN
