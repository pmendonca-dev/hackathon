# Subindo a AVAL em produção

Este device é o centralizador: as chaves vivem aqui, em `.env.production`, que o git
ignora. Nada precisa ser configurado em nenhum outro lugar.

## Uma vez

```powershell
.\scripts\production\new-secrets.ps1
```

Sorteia `.env.production` a partir do `.env.example` e imprime as credenciais de login
de cada papel. **Guarde o que ele imprime** — os valores não são recuperáveis de outro
jeito, e sortear de novo (`-Force`) invalida toda identidade já registrada no banco.

## Toda vez

```powershell
.\scripts\production\start-aval.ps1
```

Quatro passos, nessa ordem, e o script para no primeiro que falhar:

1. **Migrations.** As migrations são donas do schema. O boot chama
   `metadata.create_all`, que cria tabelas que faltam e nunca faz `ALTER TABLE` — um
   banco que nunca passou pelo alembic fica com colunas de menos e só quebra em uso.
2. **Build do navegador.** Sem `VITE_AVAL_API_BASE_URL`: o FastAPI serve o bundle, então
   a página chama a origem de onde veio. Um endereço embutido mandaria o navegador de
   cada jurado para o *próprio* laptop dele.
3. **Túnel HTTPS.** `cloudflared` publica uma URL `*.trycloudflare.com`, e ela entra em
   `AVAL_ALLOWED_ORIGINS` antes da API subir, porque a API lê essa variável no import.
   HTTPS não é enfeite: o cookie de sessão é `Secure`, e sem TLS nenhum papel loga.
4. **API.** `Ctrl+C` encerra a API e o túnel juntos.

Bandeiras úteis: `-SkipTunnel` sobe só em `127.0.0.1` (e afrouxa o cookie, o único caso
em que isso é correto); `-SkipBuild` pula o `npm run build`.

## Verificação

Com a instância no ar, contra a URL pública:

```powershell
. .\scripts\production\Load-AvalEnv.ps1
.venv\Scripts\python.exe scripts\smoke_demo.py https://SUA-URL.trycloudflare.com

Set-Location web
node --experimental-strip-types tests\live-browser-journey.mjs https://SUA-URL.trycloudflare.com
```

O smoke percorre 20 passos do case; a jornada percorre 29 usando a **mesma** classe de
gateway e a **mesma** carteira WebCrypto que a página. Se ela passa, o jurado consegue
fazer tudo no navegador.

## O bot do Telegram

Processo separado, no mesmo device, depois da API estar de pé:

```powershell
. .\scripts\production\Load-AvalEnv.ps1
$env:AVAL_API_BASE_URL = "http://127.0.0.1:8099"
.venv\Scripts\python.exe -m aval.interfaces.telegram
```

Precisa de `TELEGRAM_BOT_TOKEN` em `.env.production`. Ele fala com a API por localhost,
não pelo túnel — um salto a menos e nada de bot dependendo da URL pública.

## O que quebra, e por quê

**`signature_invalid` em toda compra depois de um restart.** `AVAL_CUSTODY_SEED` está
vazia ou mudou. O banco guarda a metade pública das chaves; sem a semente cada boot
sorteia metades privadas novas, e nada mais bate. Se a semente mudou de propósito, o
banco precisa ser recriado.

**Ninguém consegue logar.** As credenciais de papel são fail-closed: uma variável
`AVAL_UI_*_CREDENTIAL` vazia desliga aquele papel. Em HTTP puro sem `-SkipTunnel`, o
cookie `Secure` também nunca volta.

**Superfícies de operador recusando.** `AVAL_OPERATOR_TOKEN` vazio fecha `/agents`,
`/admin/psp`, `/reconcile`, o relógio e as demos destrutivas. Não há token sorteado.

**As demos destrutivas dão 404.** `AVAL_DEMO_TAMPER` e `AVAL_DEMO_ROGUE` não são
checagens de permissão: sem a variável o router nem é montado, então o caminho some
até do OpenAPI. Ligadas, ainda exigem o token de operador.

**A porta 8099 já está escutando.** O script recusa subir um segundo processo. O SQLite
tem um escritor só.
