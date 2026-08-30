# Telegram — a superfície humana do AVAL

O bot é onde o jurado põe a mão. Criar o mandato, comprar em texto livre,
aprovar, revogar, contestar: tudo acontece no celular, e é o roteiro da demo
(`docs/plans/2026-08-29-demo-script.md`) do minuto 0:45 ao fim.

Ele **não é autoridade**. Não guarda política, saldo nem revogação, e não toca
banco, ledger ou `AuthorizationCore`. Toda regra vive no núcleo; o bot mostra o
que o núcleo respondeu e carrega de volta o que a pessoa decidiu.

## A ideia central: cada chat é um titular

Quando alguém manda `/start`, o bot **gera uma chave P-256 para aquele chat** e
emite um mandato em nome dela, com essa chave como `holder`. A partir daí:

- o mandato é dela, e só ela pode revogá-lo — porque só ela tem a chave;
- um jurado nunca mexe no mandato de outro, e isso é regra do domínio, não
  truque de interface;
- a sala inteira usa o mesmo bot ao mesmo tempo, sem reiniciar nada.

É o que torna o *trial by fire* possível com uma mesa de jurados.

## Por que o bot assina

Três escritas exigem JWS ES256 do titular: **aprovar/negar escalação**,
**revogar** e **mudar o limite**. O servidor não assina no lugar da pessoa — se
assinasse, a frase central do roteiro seria falsa:

> *"Quando alguém disser depois 'eu nunca autorizei isso', a assinatura dela
> sobre esse decision handle exato está no ledger."*

O bot é o dispositivo do titular. As chaves ficam em
`var/telegram-identities.json` (fora do git), gravadas com write-then-rename e
recarregadas na subida: um bot que esquecesse as chaves deixaria cada jurado com
um mandato que ninguém pode revogar — e revogação é o momento mais forte da
demo.

> `ponytail:` chave privada em arquivo simples. Aceitável para chaves de teste
> que autorizam dinheiro de teste; o lugar honesto é o secure element do
> celular, que é onde a assinatura moraria de verdade.

## Rodar

Precisa da API de pé (`uvicorn aval.main:app --port 8099`).

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
$env:TELEGRAM_BOT_TOKEN = "<token do BotFather>"
$env:TELEGRAM_OPEN_MODE = "1"          # sala de jurados
python -m aval.interfaces.telegram
```

Sem `TELEGRAM_OPEN_MODE`, só os ids em `TELEGRAM_ALLOWED_CHAT_IDS` agem — que é
o modo certo quando o bot não está sob os olhos do time. `/meuid` responde
sempre, para descobrir o próprio id.

### Variáveis

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | obrigatório |
| `AVAL_API_BASE_URL` | `http://127.0.0.1:8099` | onde o núcleo responde |
| `TELEGRAM_OPEN_MODE` | desligado | `1` abre para qualquer pessoa, um mandato por chat |
| `TELEGRAM_ALLOWED_CHAT_IDS` | vazio | quem pode agir quando o modo aberto está desligado |
| `TELEGRAM_IDENTITY_PATH` | `var/telegram-identities.json` | onde as chaves ficam |
| `AVAL_MANDATE_LIMIT_MINOR_UNITS` | `20000` | orçamento vivo do mandato novo (US$ 200,00) |
| `AVAL_MANDATE_CEILING_MINOR_UNITS` | `50000` | teto por compra; `none` remove |
| `AVAL_MANDATE_MERCHANTS` · `AVAL_MANDATE_CATEGORIES` | `vuelaya` · `travel` | escopo do mandato novo |
| `AVAL_MANDATE_CURRENCY` · `AVAL_MANDATE_SCALE` · `AVAL_MANDATE_VALID_DAYS` | `USD` · `2` · `30` | unidade e validade |
| `AVAL_ESCALATION_POLL_SECONDS` | `8` | de quanto em quanto tempo busca escalação nova |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` · `AVAL_REQUEST_TIMEOUT_SECONDS` | `30` · `15` | long poll e timeout HTTP |

## Comandos

| Comando | O que faz | Item do case |
| --- | --- | --- |
| `/start` | emite a chave e o mandato da pessoa | A1 |
| `/comprar <pedido>` | o agente tenta comprar em texto livre | A3, bônus adversarial |
| `/mandato` | orçamento vivo, teto, escopo, epoch | A1 |
| `/extrato` | recibo e trilha auditável | A4, A5 |
| `/aprovacoes` | escalações abertas, com Aprovar/Recusar | B1 |
| `/limite <valor>` | muda o orçamento, assinado | trial by fire |
| `/revogar` | encerra a autoridade, assinado | B3 |
| `/catalogo` · `/status` · `/ajuda` · `/meuid` | apoio | — |

Além disso, o bot **empurra** cada escalação nova para o dono do mandato, uma
vez por escalação.

## O que o bot chama

Caminhos no dict `ENDPOINTS`, no topo de `gateway.py`. `GET /docs` na instância
é a referência viva.

| Ação | Chamada |
| --- | --- |
| criar mandato | `POST /mandates` com a JWK pública do chat como `holder` |
| estado vivo | `GET /mandates/{id}` |
| comprar | `POST /agent/purchase` `{mandate_id, instruction}` |
| escalações | `GET /escalations?mandate_id=` · `GET /escalations/{id}` |
| decidir | `POST /escalations/{id}/decision` `{decision, approval_jws}` |
| revogar | `POST /mandates/{id}/revocation` `{token}` |
| mudar limite | `PATCH /mandates/{id}/limit` `{limit, authorization_jws}` |
| recibo | `GET /ledger?mandate_id=&view=human` |
| contestar | `POST /disputes` `{reservation_id, reason}` |
| catálogo | `GET /merchant/offers` |

### O que o bot assina

```jsonc
// aprovar/negar — POST /escalations/{id}/decision
{ "decision_handle": "dh_...", "mandate_id": "mandate_...",
  "amount_minor_units": 30000, "decision": "approve", "decided_at": "..." }

// revogar — POST /mandates/{id}/revocation
{ "mandate_id": "mandate_...", "scope": "mandate", "reason": "...", "epoch": 2 }

// mudar limite — PATCH /mandates/{id}/limit
{ "mandate_id": "mandate_...", "limit_minor_units": 5000,
  "currency": "USD", "scale": 2 }
```

O núcleo confere que a assinatura é do `holder` **e** que ela fala desta compra:
handle, mandato, valor e decisão. Uma aprovação não pode ser levantada de uma
compra e aplicada a outra maior.

## Invariantes

- Dinheiro só em `minor_units` inteiro — inclusive ao ler o que a pessoa digitou
  (`views.parse_money`) e ao imprimir (`views.format_money`). Nenhum float.
- `callback_data` é entrada não confiável: validada, e o alvo conferido contra o
  mandato de quem tocou.
- Núcleo fora do ar vira "nenhuma ação foi executada", com o `reason_code` do
  próprio núcleo. Nunca um falso sucesso.
- O bot repete o `human_summary` do núcleo; não reescreve razão nenhuma.
- Teto (`mandate_ceiling`) aparece **sem botão de aprovar** — o humano também não
  atravessa o teto.

## Limites conhecidos

- `ponytail:` o loop trata um update por vez; uma chamada lenta segura a próxima.
  Um humano por chat, uma demo. Fila por chat é o caminho de upgrade.
- `ponytail:` escalações já notificadas vivem em memória; reiniciar re-notifica
  as abertas. Inofensivo — o card é idempotente e o núcleo decide uma vez só.
- Push por long polling, não webhook. Latência ≤ `AVAL_ESCALATION_POLL_SECONDS`.

## Testes

`tests/unit/interfaces/test_telegram_bot.py` — 47 testes. O servidor falso
**verifica as assinaturas de verdade**, com o mesmo `verify_compact_jws` do
núcleo: uma aprovação que não bata com a chave publicada do chat falha ali.
