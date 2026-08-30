# Contrato de integração — congelado em T+7

> ## ⚠️ Atualização: a API existe e mudou em dois pontos
>
> Tudo abaixo continua válido, com **duas mudanças que quebram chamadas escritas contra
> a versão anterior** — ambas por segurança, ambas com teste:
>
> 1. **`PATCH /mandates/{id}/limit` agora exige `authorization_jws`** — JWS ES256 do
>    titular sobre `{mandate_id, limit_minor_units, currency, scale, policy_version}`.
>    `policy_version` é a versão substituída, e gasta o token. Sem ele:
>    `403 limit_change_unsigned`. Antes, qualquer um que soubesse o `mandate_id`
>    aumentava a autoridade de gasto sem prova nenhuma, enquanto **revogar** já exigia
>    assinatura — a operação mais perigosa era a desprotegida.
> 2. **`POST /agents`, `POST /admin/psp` e `POST /reconcile` exigem o cabeçalho
>    `X-Aval-Operator`.** Sem ele: `401 operator_token_missing`. `POST /agents` aceitava
>    `trusted: true` de qualquer chamador — ou seja, um atacante se registrava como
>    agente confiável e passava por toda a defesa contra impostor.
>
> **Endpoints novos, não previstos aqui:** `GET /mandates/{id}` (estado vivo com
> orçamento), `GET /escalations`, `GET /escalations/{id}`, `GET /ledger/verify`,
> `POST /agent/purchase` (agente por texto livre), `GET /agent/profile`,
> `GET /merchant/.well-known/jwks.json`, `GET /.well-known/jwks.json`, `POST /disputes`,
> `GET /disputes`, `POST /disputes/{id}/resolution`, `POST /reconcile`, `GET/POST /admin/psp`.
>
> **Reason codes novos** em `awaiting_human`: `category_not_allowed`. Em `rejected`:
> `mandate_ceiling`. A resposta de `/authorize` e `/capture` ganhou `escalation_id`, e a
> de `/capture` ganhou `authorization_proof`.
>
> `GET /docs` na instância rodando é a referência viva. Ver também
> [modelo de segurança](../security-model.md).

Documento único que as quatro lanes leem. Quem mudar este contrato avisa as outras três **antes** de mudar o código.

> **Regra do contrato:** a partir de agora, ninguém espera outra lane ficar pronta. Cada lane constrói contra este documento. Se algo aqui estiver errado, corrija o documento primeiro.

---

## 1. Como o contrato mapeia no núcleo

Tudo aqui já existe como método Python em `src/aval/application/authorization_core.py`. A camada HTTP é uma casca fina — **não reimplemente regra de decisão na borda**.

| Endpoint | Método do núcleo | Estado |
|---|---|---|
| `POST /mandates` | `register_mandate(mandate)` | ✅ pronto |
| `PATCH /mandates/{id}/limit` | `replace_live_limit(mandate_id, limit)` | ✅ pronto |
| `POST /mandates/{id}/revocation` | `submit_signed_revocation(token)` | ✅ pronto |
| `POST /authorize` | `evaluate(AuthorizationCommand)` | ✅ pronto |
| `POST /capture` | `capture(CaptureCommand)` | ✅ pronto |
| `POST /escalations/{id}/decision` | — | ⚠️ **não existe, precisa ser escrito** |
| `GET /ledger` | `AuditLedger.timeline_for()` | ⚠️ porta definida, **sem repositório SQLite** |
| `GET /merchant/offers` | — | ⚠️ merchant não existe |

---

## 2. Tipo `Money` — use exatamente assim

O núcleo **não aceita float**. `src/aval/domain/money.py` valida moeda ISO de 3 letras maiúsculas e escala de 0 a 18.

```json
{ "minor_units": 13000, "currency": "USD", "scale": 2 }
```

`13000` com `scale: 2` é **$130.00**. Converter no front/bot, nunca no núcleo.

`evaluate()` rejeita com `money_unit_mismatch` se moeda ou escala divergirem do mandato. Não é bug — é invariante.

---

## 3. Endpoints

### `POST /mandates`
Cria o mandato. Chamado pelo **bot do Telegram**.

```json
{
  "principal":  { "id": "usr_marta", "display_name": "Marta Silva" },
  "allowed_merchant_ids": ["vuelaya"],
  "limit":      { "minor_units": 20000, "currency": "USD", "scale": 2 },
  "expires_at": "2026-09-30T23:59:59Z",
  "authorities": [
    { "id": "auth_holder", "kid": "usr_marta_k1", "role": "holder",
      "public_jwk": { "kty": "EC", "crv": "P-256", "x": "...", "y": "..." },
      "allowed_scopes": ["mandate"] }
  ]
}
```

→ `201 { "mandate_id": "mandate_...", "policy_version": 1, "revocation_id": "rev_..." }`

**Nenhum dado de cartão entra aqui.** O meio de pagamento é emitido por checkout, não por mandato — ver §8.2.

`Mandate.__post_init__` exige pelo menos um merchant permitido, pelo menos uma autoridade de revogação e `revocation_metadata.revocation_id`. Um POST sem isso devolve `422`.

---

### `PATCH /mandates/{id}/limit` `[JURADO]`
Troca o limite ao vivo. **Efeito na próxima decisão, sem restart.**

```json
{ "limit": { "minor_units": 10000, "currency": "USD", "scale": 2 } }
```

→ `200 { "policy_version": 2, "epoch": 1 }`

`replace_live_limit()` já incrementa `policy_version` **e** `epoch`, o que invalida provas de autorização em voo. Esse é o critério nº 1 do júri — não coloque cache na frente.

---

### `POST /mandates/{id}/revocation` `[JURADO]`
Revogação assinada. Irreversível.

```json
{ "token": "<compact JWS ES256>" }
```

Payload do JWS: `{ "mandate_id": "...", "scope": "mandate", "reason": "...", "epoch": 1 }`
Header: `{ "alg": "ES256", "kid": "usr_marta_k1" }`

→ `200 { "revoked": true, "epoch": 1 }` · `400 malformed revocation JWS` · `400 unknown revocation authority`

O núcleo valida assinatura, casamento de `mandate_id`, escopo permitido e completude do payload. **Não afrouxe isso para facilitar a demo** — é o que impede um jurado de revogar mandato alheio, e é o teste que já passa em `test_revocation_commit_race.py`.

---

### `POST /authorize`
Decisão. Requisição **assinada pelo agente** (ver §4).

```json
{
  "mandate_id": "mandate_...",
  "checkout_id": "chk_...",
  "merchant_id": "vuelaya",
  "total": { "minor_units": 13000, "currency": "USD", "scale": 2 }
}
```

→ `200`:
```json
{ "decision": "authorized", "reason_code": "authorized", "human_summary": "Compra autorizada." }
```

**Os três resultados e seus reason codes reais** (extraídos de `_evaluate_with`, não invente outros):

| `decision` | `reason_code` | Quando |
|---|---|---|
| `rejected` | `mandate_not_found` | mandato inexistente |
| `rejected` | `mandate_revoked` | revogado |
| `rejected` | `mandate_expired` | fora da validade |
| `rejected` | `money_unit_mismatch` | moeda/escala divergente |
| `rejected` | `invalid_amount` | valor ≤ 0 |
| `awaiting_human` | `merchant_out_of_scope` | merchant fora do escopo |
| `awaiting_human` | `budget_exceeded` | excede orçamento vivo |
| `authorized` | `authorized` | dentro do mandato |

`awaiting_human` **não é falha**. É o gatilho da escalação — dispare o push no Telegram aqui.

---

### `POST /capture`
Commit + liquidação. Idempotente e transacional.

```json
{
  "mandate_id": "...", "checkout_id": "...", "merchant_id": "vuelaya",
  "total": { "minor_units": 13000, "currency": "USD", "scale": 2 },
  "idempotency_key": "cap_<uuid>"
}
```

→ `200 { "approved": true, "reason_code": "...", "settlement_reference": "..." }`

Reason codes de retry já implementados: `idempotency_key_reused` (mesma chave, corpo diferente), `idempotency_in_flight` (chamada concorrente). **Reenviar a mesma chave com o mesmo corpo devolve o resultado original, não cobra de novo.**

O núcleo relê revogação *dentro* da transação de commit. Uma revogação que chega no meio da captura ganha ou perde por serialização, nunca por corrida.

---

### `POST /escalations/{id}/decision` ⚠️ **A ESCREVER**
Fecha o Buraco 1. Sem isto, `awaiting_human` é um beco sem saída e o requisito *"escalated to human approval"* fica pela metade.

```json
{ "decision": "approve", "approval_jws": "<compact JWS ES256>" }
```

Payload do JWS, assinado pela chave do principal quando ele toca o botão no Telegram:
```json
{ "decision_handle": "dh_...", "mandate_id": "...", "amount_minor_units": 30000, "decided_at": "..." }
```

→ `200 { "resumed": true, "capture": { ... } }` · `403 approval_signature_invalid` · `409 escalation_expired`

**Por que assinar o toque:** a aprovação vira evidência não-repudiável. Quando o humano depois disser *"eu nunca autorizei isso"*, o ledger tem a assinatura dele sobre aquele decision handle exato. É a resposta direta à pergunta central do case sobre disputa. Reaproveita `security/jws.py` e `security/key_custody.py`.

---

### `GET /ledger?mandate_id=...&view=human|merchant|auditor`
Três visões de **uma** verdade. Requisito obrigatório do case.

| `view` | Vê | Não vê |
|---|---|---|
| `human` | o que foi comprado, sob qual mandato, orçamento restante | chaves, hashes internos |
| `merchant` | decisão, valor, categoria, decision handle, assinatura | **orçamento, gasto acumulado, `principal_id`, `mandate_id`** |
| `auditor` | cadeia completa com hashes, atores e epochs | — |

A visão `merchant` é seletiva **de propósito**. `web/src/pages/MerchantView.tsx` já mostra os campos ocultados com o motivo, em vez de simplesmente omiti-los.

⚠️ Falta o `SqliteAuditLedger`. A tabela `audit_events` já existe em `models.py`; falta o repositório que implementa a porta `AuditLedger` de `ports.py`.

---

### `GET /merchant/offers` e `POST /merchant/verify` ⚠️ **A ESCREVER**
Ver §8.1. Catálogo estático de voos, oferta assinada pelo merchant, e verificação com os cinco checks.

---

## 4. Invariante de assinatura — fecha o Buraco 2

**Toda requisição de agente carrega assinatura.** Sem isso, "agente impostor" — item obrigatório e nomeado do case — fica sem implementação.

```
Signature-Input: sig1=("@method" "@path" "content-digest");keyid="agent_travel_k1";created=...
Signature: sig1=:<base64>:
Content-Digest: sha-256=:<base64>:
```

Falha → `401 { "reason_code": "signature_invalid" }` · chave desconhecida → `401 key_not_found` · perfil não confiável → `403 profile_not_trusted`.

**Já existe quase tudo:** `security/ecdsa.py`, `security/jws.py`, `security/content_digest.py`, `security/key_custody.py`, a entidade `AgentIdentity` (com `public_jwk` e `trusted`) e a tabela `agent_profiles`. `AgentIdentity` está **definida e nunca usada** — é só ligar. Estimativa realista: ~1h.

Demonstração do impostor: reenviar o mesmo corpo com a assinatura de outra chave → `401`. Um comando de curl no pitch.

---

## 5. Duas regras não negociáveis

1. **Nenhum cache na frente de limite e revogação.** O júri vai mudar o limite e tentar comprar em seguida. Qualquer cache transforma o critério nº 1 em falha.
2. **A borda não decide.** HTTP valida forma e assinatura; quem decide é o `AuthorizationCore`. Se a regra existir em dois lugares, ela vai divergir sob pressão — e a defesa técnica cai junto.

---

## 6. Convenção de erro

```json
{ "reason_code": "mandate_revoked", "human_summary": "Mandato revogado." }
```

`reason_code` é estável e legível por máquina; `human_summary` é a frase que vai para a tela e para o Telegram. **Os dois campos já vêm prontos do núcleo** em `AuthorizationResult` — repasse, não reescreva.

---

## 7. Ordem de implementação sugerida

| # | Item | Destrava |
|---|---|---|
| 1 | `POST /authorize` + `POST /capture` | agente e front saem do papel |
| 2 | Merchant + oferta assinada (§8.1) | a metade "compra" do case |
| 3 | Verificação de assinatura na borda | Buraco 2, item obrigatório |
| 4 | `PATCH /limit` + `POST /revocation` | trial by fire, critério nº 1 |
| 5 | `POST /escalations/{id}/decision` | Buraco 1, item obrigatório |
| 6 | Token escopado (§8.2) | *"sem entregar o cartão bruto"* |
| 7 | `SqliteAuditLedger` + `GET /ledger` | três visões, item obrigatório |
| 8 | PSP controlável + reconciliação (§8.3) | fluxo de falha, trial by fire |
| 9 | Disputa | bônus |

Itens 1 a 7 são **obrigatórios pelo case**. O 8 é o que dá história de falha ao trial by fire. O 9 só entra com o resto de pé.

---

## 8. A metade "compra"

O núcleo autoriza **um valor contra um mandato**. Ele recebe `checkout_id` como string opaca e **nunca pergunta o que foi comprado**. Isso é uma boa propriedade — o núcleo é agnóstico ao produto — mas significa que produto, oferta, entrega e liquidação estão fora dele e precisam ser construídos.

### 8.1 Oferta assinada pelo merchant

O merchant publica o catálogo e assina cada oferta. Sem isso, `POST /merchant/verify` não teria o que verificar.

**Payload da oferta:**
```json
{
  "offer_id":    "off_9e21",
  "merchant_id": "vuelaya",
  "item":        { "sku": "FL-SAO-BUE-0917", "title": "São Paulo → Buenos Aires", "category": "travel" },
  "total":       { "minor_units": 13000, "currency": "USD", "scale": 2 },
  "not_after":   "2026-08-29T20:10:00Z",
  "nonce":       "ofn_7c31"
}
```

- **`merchant_authorization`** = compact JWS ES256 sobre esse payload, com a chave do merchant e `kid` no header. Mesmo mecanismo da revogação — reaproveita `security/jws.py`.
- **`terms_hash`** = `base64url(SHA-256(JCS(payload)))`, usando `security/jcs.py`. A canonicalização RFC 8785 é o que faz merchant e núcleo concordarem byte a byte; `rfc8785` já está no `pyproject.toml` exatamente para isso.

**Guarde os bytes canônicos em `checkout_intents.canonical_payload`.** Hoje `SqliteLedgerRepository.save()` grava um placeholder — `json.dumps({"id": reservation.checkout_intent_id})`. Trocar esse placeholder pela oferta canônica é o que torna o recibo do merchant verificável depois, e é uma linha.

**`POST /merchant/verify`** devolve os cinco checks que a tela do merchant já desenha em `web/src/pages/MerchantView.tsx`: assinatura válida, oferta válida, decisão válida, terms hash confere, status de revogação válido.

### Onde cada coisa é verificada

Regra que mantém a §5.2 precisa: **a borda verifica autenticidade, o núcleo decide autoridade.**

| Borda HTTP, antes de `evaluate()` | Núcleo |
|---|---|
| assinatura do agente (RFC 9421) → `401 signature_invalid` | mandato ativo, não revogado, não expirado |
| assinatura do merchant → `401 offer_signature_invalid` | valor dentro do limite vivo |
| `not_after` vencido → `409 offer_expired` | orçamento acumulado |
| `total` ou `merchant_id` divergente da oferta → `409 offer_mismatch` | escopo de merchant |
| nonce já gasto → `409 offer_replayed` | corrida com revogação |

### 8.2 Token escopado por checkout — *"sem entregar o cartão bruto"*

⚠️ **Correção importante:** `vault_tokens` **não é um cofre de cartão.** Olhando o schema em `models.py`, as colunas são `mandate_id`, `checkout_intent_id`, `merchant_id`, `max_amount_minor_units`, `currency`, `expires_at`.

É um **credencial escopado por checkout** — e isso é uma resposta mais forte ao case do que um cofre de cartão seria.

```
POST /vault/tokens
{ "mandate_id": "...", "checkout_intent_id": "...", "merchant_id": "vuelaya",
  "max_amount": { "minor_units": 13000, "currency": "USD", "scale": 2 },
  "expires_at": "2026-08-29T20:10:00Z" }
→ 201 { "token": "vlt_...", "scope": { ... } }
```

O agente recebe `vlt_...` e mais nada. O token só funciona **neste merchant, neste checkout, até este valor, até este horário**. Não há PAN em lugar nenhum do sistema — não é que o cartão esteja guardado com segurança, é que **ele nunca existe aqui**.

> Frase para o pitch: *"O agente nunca segura um cartão. Ele segura um token que só funciona neste merchant, neste checkout, até este valor, até este horário."*

### 8.3 PSP controlável — e o IN_DOUBT que já existe

```python
class DemoPspAdapter:
    def authorize(self, reservation, proof) -> SettlementResult:
        mode = self._mode()                       # lido a cada chamada, nunca cacheado
        if mode == "decline":
            return SettlementResult(approved=False)
        if mode == "offline":
            raise PspUnreachable()
        return SettlementResult(approved=True, reference=f"psp_{uuid4().hex[:8]}")
```

```
POST /admin/psp   [J]   { "mode": "online" | "offline" | "decline" }
POST /reconcile         varre capture_attempts pendentes e conclui
```

**Achado que muda o trabalho:** o estado IN_DOUBT **já emerge sozinho**, e corretamente.

Em `capture()`, se o adapter levantar exceção, `finish()` nunca roda. O resultado:

- a reserva fica `COMMITTED` → **orçamento continua retido** ✅
- o `capture_attempt` fica pendente → **recuperável** ✅
- a idempotência fica reivindicada → retry devolve `idempotency_in_flight` ✅

Isso é exatamente o comportamento *fail-closed* certo: timeout não é recusa, e o orçamento não é liberado. **O que falta é o reconciliador** — nada conclui esses attempts depois. Na restauração do PSP, varra os pendentes, pergunte de novo e conclua pelo mesmo caminho de `finish`.

> ⚠️ **Não "conserte" isso com `try/except` liberando a reserva.** Liberar no timeout é precisamente o bug que o desenho evita: soltaria o orçamento de um pagamento que pode ter liquidado do outro lado. O estado pendente é a resposta certa; só falta quem o resolva.
