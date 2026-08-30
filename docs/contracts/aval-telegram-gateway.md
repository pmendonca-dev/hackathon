# Telegram bot — interface humana do AVAL

O bot é a **superfície humana principal**: o agente compra, o humano aprova,
recusa e revoga por aqui. Ele não é autoridade — não guarda política, saldo nem
revogação, e nunca toca banco, ledger ou `AuthorizationCore`. Tudo passa pelo
port `AvalGateway` (`src/aval/interfaces/telegram/gateway.py`).

## Estado atual

Roda hoje, com fixtures, enquanto o backend está em construção.

| `AVAL_API_BASE_URL` | Gateway em uso | Para que serve |
| --- | --- | --- |
| ausente | `MockGateway` | ensaiar a demo, o roteiro e os textos sem backend |
| definida | `HttpGateway` | fala com a API real; nenhum handler muda |

Não existe terceiro caminho: `build_gateway()` escolhe pela variável, e é a
única linha que decide isso.

## Como rodar

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."          # BotFather
export TELEGRAM_ALLOWED_CHAT_IDS="4242,7788"       # quem pode decidir
uv run python -m aval.interfaces.telegram
```

Descobrir o próprio chat id: mande `/meuid` ao bot. Sem estar na allowlist,
`/start` e `/meuid` respondem; todo o resto é recusado.

### Modo demo aberta (para os juízes)

Numa apresentação você não vai reiniciar o bot a cada jurado. Com
`TELEGRAM_DEMO_MODE=1` qualquer pessoa pode falar com o bot e decidir —
**cada chat recebe seu próprio conjunto de mandatos**, isolado dos demais. Um
jurado revoga e vê 🔴; o do lado, no mesmo segundo, continua vendo 🟢.

```powershell
$env:TELEGRAM_DEMO_MODE = "1"     # dispensa TELEGRAM_ALLOWED_CHAT_IDS
```

Isso vale **apenas com fixtures**. Combinar `TELEGRAM_DEMO_MODE` com
`AVAL_API_BASE_URL` é recusado na partida: contra um backend real não existe
sandbox por pessoa, e abrir seria dar a qualquer estranho autoridade sobre o
mandato de alguém. Para a apresentação com backend, volte à allowlist.

### Variáveis

| Variável | Obrigatória | Padrão | Efeito |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | sim | — | token do BotFather |
| `TELEGRAM_ALLOWED_CHAT_IDS` | sim na prática | vazio | **vazio autoriza ninguém** (fail-closed) |
| `TELEGRAM_DEMO_MODE` | não | desligado | `1` abre para qualquer pessoa, com sandbox por chat; incompatível com `AVAL_API_BASE_URL` |
| `AVAL_API_BASE_URL` | não | — | definir liga o `HttpGateway` |
| `AVAL_API_TOKEN` | não | — | vira `Authorization: Bearer` |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` | não | 30 | long poll do `getUpdates` |
| `AVAL_ESCALATION_POLL_SECONDS` | não | 10 | intervalo de busca por escalações novas |
| `AVAL_REQUEST_TIMEOUT_SECONDS` | não | 10 | timeout HTTP |

## Comandos

| Comando | O que faz |
| --- | --- |
| `/start`, `/ajuda` | apresentação e lista de comandos |
| `/meuid` | mostra o chat id, para entrar na allowlist |
| `/mandatos` | mandatos com status, teto e gasto |
| `/mandato <id>` | detalhe, com botão de revogação |
| `/aprovacoes` | escalações pendentes, com Aprovar/Recusar |
| `/atividade [id]` | últimos eventos auditáveis |
| `/revogar <id>` | menu de revogação (mandato inteiro ou orçamento) |
| `/status` | saúde do backend e modo atual |

Além dos comandos, o bot **empurra** cada escalação nova para todos os chats da
allowlist, uma vez por escalação.

## Contrato HTTP esperado

O `HttpGateway` chama os caminhos abaixo; eles vivem no dicionário `ENDPOINTS`,
no topo de `gateway.py`. Quando o backend fechar o contrato, ajuste ali — não
nos handlers.

`GET /health` → `{"status": "ok"}`

`GET /v1/mandates` → `{"mandates": [Mandate]}`

`GET /v1/mandates/{mandate_id}` → `Mandate` (404 vira "não encontrado")

`GET /v1/escalations?status=pending` → `{"escalations": [Escalation]}`

`POST /v1/escalations/{approval_id}/decision`
· headers `Idempotency-Key`, `Authorization`
· body `{"decision": "approve"|"deny", "actor": "telegram:@marta"}`
· resposta `{"ok": bool, "human_summary": str}`

`POST /v1/mandates/{mandate_id}/revocations`
· headers `Idempotency-Key`, `Authorization`
· body `{"scope": "mandate"|"budget:zero"|"merchant:<id>"|"instrument:<id>", "reason": str, "actor": str}`
· resposta `{"ok": bool, "human_summary": str}`

`GET /v1/audit-events?mandate_id=&limit=` → `{"events": [AuditEvent]}`

### Formas

```jsonc
// Money — minor_units inteiro, jamais float
{ "minor_units": 250000, "currency": "BRL", "scale": 2 }

// Mandate
{ "id": "mnd_...", "principal": "Marta Ribeiro", "agent": "agent://...",
  "status": "ACTIVE|REVOKED|EXPIRED", "limit": Money, "spent": Money,
  "allowed_merchant_ids": ["mrc_..."], "expires_at": "2026-09-30T12:00:00Z",
  "policy_version": 3, "revocation_epoch": 1 }

// Escalation — uma decisão AWAITING_HUMAN esperando o humano
{ "id": "esc_...", "mandate_id": "mnd_...", "merchant_id": "mrc_...",
  "item": "Monitor 27\"", "amount": Money,
  "reason_code": "merchant_out_of_scope", "human_summary": "...",
  "created_at": "2026-08-29T18:00:00Z" }

// AuditEvent
{ "id": "aud_...", "mandate_id": "mnd_...", "event_type": "capture.committed",
  "human_summary": "...", "occurred_at": "2026-08-29T18:00:00Z" }
```

## O que o backend precisa entregar

1. **Revogação é escrita assinada.** O bot não assina nada. O endpoint de
   revogação recebe a intenção e é o servidor que assina como autoridade
   `operator` e chama `AuthorizationCore.submit_signed_revocation`, registrando
   no `AuditLedger`. O bot é o mesmo caminho do console de operador, não um
   bypass.
2. **`Idempotency-Key` respeitado** nos dois POSTs, com a semântica já usada na
   captura: replay devolve a mesma resposta, corpo divergente é recusado.
3. **Escalações listáveis.** Toda decisão `AWAITING_HUMAN` precisa virar uma
   linha consultável, com `human_summary` já em português — o bot exibe o texto
   do núcleo, não reescreve razão nenhuma.

## Invariantes que o bot respeita

- Dinheiro só entra e sai como `minor_units` inteiro; a formatação é aritmética
  inteira (`views.format_money`). Nenhum float em lugar nenhum.
- Allowlist fail-closed: chat fora da lista não lê nem decide.
- Modo demo abre a porta sem abrir o estado: cada chat decide só no próprio
  sandbox, e ele é recusado se houver backend real configurado.
- `callback_data` é entrada não confiável — validada em `views.parse_callback`
  antes de virar ação.
- Chave de idempotência determinística por (ação, alvo, chat): toque duplo não
  decide duas vezes.
- Backend fora do ar vira "nenhuma ação foi executada", nunca um falso sucesso.

## Limites conhecidos

- `ponytail:` o loop é sequencial — uma chamada lenta ao gateway segura os
  próximos updates. Um chat, um humano, uma demo: suficiente. Se precisar de
  concorrência, uma fila por chat resolve.
- `ponytail:` as escalações já notificadas vivem em memória; reiniciar o bot
  re-notifica as pendentes. Persistir isso só vale se o bot passar a reiniciar
  durante a demo.
- Push é por polling, não webhook. Latência ≤ `AVAL_ESCALATION_POLL_SECONDS`.
  Webhook só quando o segundo importar.
