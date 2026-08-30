# Lado da oferta — design

**Data:** 2026-08-29
**Escopo:** o merchant, a oferta assinada, a verificação, e o ingresso multi-protocolo do AVAL.
**Contrato de referência:** `docs/plans/2026-08-29-integration-contract.md` §8.1 e §8.2. Onde este documento e o contrato divergirem, o contrato vence e este documento é corrigido.

---

## 0. Decisão de direção

O AVAL expõe **ingresso multi-protocolo na própria borda**: um núcleo de domínio único, com cada protocolo como adaptador de encoder/decoder. O agente **não** roteia protocolo; a borda do AVAL é que fala vários dialetos.

Isso não é escolha nova — é o que `docs/aval-integration-architecture.md` §0.2 já estabeleceu (*"não implementar quatro integrações (...) todo protocolo é representação; o núcleo é autoridade"*), e é o que três artefatos já construídos pressupõem:

| Artefato | Por que só faz sentido com ingresso multi-protocolo |
|---|---|
| `src/aval/domain/checkout_status.py` | `to_ucp_status()` / `to_acp_status()` projetam **uma** verdade interna em **dois** dialetos. Definido, nunca chamado. |
| `application/ports.py:55` — `get_or_claim(surface, key, …)` | idempotência com namespace **por superfície de ingresso**. O parâmetro só se paga com mais de uma superfície. |
| `infrastructure/sqlite/seed.py:18` — `profile_url=".../.well-known/ucp"` | perfil de descoberta UCP já semeado. |

**Abordagem escolhida:** uma loja embutida, uma borda de ingresso, protocolo como projeção de resposta — com caminho de upgrade aditivo para uma segunda loja como serviço separado. O upgrade só é executado depois dos itens 1–7 do contrato §7 estarem verdes.

**Rejeitado:** duas lojas como serviços separados agora (consome o orçamento dos itens obrigatórios #3, #5 e #7 antes do code freeze); ofertas como fixtures pré-assinadas sem serviço (não satisfaz A2 — *"o merchant verifica antes de aceitar"* — porque uma fixture não verifica nada).

---

## 1. Arquitetura e direção de dependência

```
merchant (loja)  ──assina oferta──▶  borda HTTP  ──comando canônico──▶  AuthorizationCore
                                          │
                                          └──resultado canônico──▶  encoder por protocolo
```

A loja não conhece o núcleo. A borda verifica **autenticidade** e traduz; o núcleo decide **autoridade** e não sabe que protocolo existe.

Invariante não negociável, herdada do contrato §5.2: **a borda não decide.** Se uma regra de decisão aparecer em `src/aval/merchant/` ou em `src/aval/api/`, ela está no lugar errado.

---

## 2. Componentes

| Arquivo | Responsabilidade | Estado |
|---|---|---|
| `src/aval/merchant/catalog.py` | Catálogo estático de voos: `sku`, `title`, `category`, `total` | novo |
| `src/aval/merchant/offer.py` | Monta o payload da oferta, assina (detached JWS), calcula `terms_hash` | novo |
| `src/aval/merchant/verify.py` | Os cinco checks de `POST /merchant/verify` | novo |
| `src/aval/security/jws.py` | Ganha `sign_detached_jws()` e `verify_detached_jws()` | alterado, aditivo |
| `src/aval/api/protocol/ucp.py` | Encoder UCP | novo |
| `src/aval/api/protocol/acp.py` | Encoder ACP | novo |
| `src/aval/api/routes/merchant.py` | `GET /merchant/offers`, `POST /merchant/verify` | novo |
| `merchant_profiles` (tabela) | `id`, `display_name`, `protocol`, `public_jwk`, `trusted` | migração Alembic |
| `infrastructure/sqlite/ledger_repository.py` | `save()` aceita `canonical_payload` | alterado |
| `infrastructure/sqlite/seed.py` | Semeia o perfil da VuelaYa | alterado |
| `domain/checkout_status.py` | Passa a ser chamado pelos encoders | inalterado |

Nenhuma porta nova em `application/ports.py`. O docstring do arquivo é explícito — *"infrastructure implements persistence, never adapters"* — e os adaptadores de protocolo moram na borda, não atrás de uma porta.

---

## 3. A oferta

### 3.1 Payload

Exatamente a forma fixada no contrato §8.1:

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

As ofertas são **cunhadas no request**, nunca pré-assinadas: `nonce` e `not_after` exigem isso. `not_after` = `now + 10 minutos`, lido do `Clock` injetado, nunca de `datetime.now()` direto.

O `item.category` **é decidido pelo núcleo**, não pela borda. A borda copia a categoria da oferta para `AuthorizationCommand.category`; `Mandate.allowed_categories` é que diz se ela pode. Uma categoria fora do escopo devolve `category_not_allowed` e escala. Ver §11.

### 3.2 `terms_hash`

`base64url(SHA-256(canonicalize(payload)))`, com `canonicalize` de `src/aval/security/jcs.py` (RFC 8785).

Os **bytes JCS**, não um resumo deles, são gravados em `checkout_intents.canonical_payload`. Hoje aquela coluna recebe o placeholder `json.dumps({"id": reservation.checkout_intent_id})` em `ledger_repository.py:33`.

### 3.3 `merchant_authorization` — detached JWS

**Decisão:** forma **detached**, `<protected>..<signature>`, sobre a serialização JCS do payload.

**Alternativa rejeitada:** reaproveitar `sign_compact_jws` (attached), que custaria zero. Rejeitada porque `docs/protocol-validation.md` já registrou publicamente que o `merchant_authorization` do AP2 é detached sobre JCS. Documento e código dizendo coisas diferentes é uma falha de defesa técnica mais cara que as ~25 linhas.

Construção:

- entrada de assinatura: `b64url(header) + "." + b64url(canonicalize(payload))`
- header: `{"alg":"ES256","kid":"<kid do merchant>"}`
- token emitido: `b64url(header) + ".." + b64url(assinatura)`
- verificação: reconstrói a entrada de assinatura a partir do payload da oferta recebida; assinatura sobre payload adulterado não verifica

Reaproveita `sign_es256_raw` / `verify_es256_raw` de `security/ecdsa.py`, que já garantem ES256 em 64 bytes crus, não DER.

**Não confundir com o JWS attached existente.** `sign_compact_jws` codifica o payload com `json.dumps(separators=(",",":"))`, não com JCS, e está correto assim: aquele JWS protege os próprios bytes base64url dele. O `terms_hash` é um digest JCS **separado**. Ninguém deve unificar os dois.

### 3.4 Chaves do merchant

A chave da VuelaYa é gerada no boot pelo `KeyCustodyService` e sua JWK pública é semeada em `merchant_profiles`.

**Limitação conhecida e aceita:** `KeyCustodyService` é in-memory (`key_custody.py:35`). Um restart gera chave nova, e ofertas assinadas antes do restart deixam de verificar. Aceitável na demo, porque ofertas expiram em 10 minutos de qualquer forma. **Consequência operacional:** não reiniciar o processo entre o ensaio e o pitch com uma oferta em voo.

---

## 4. Roteamento de protocolo

O protocolo **não é query param**. É a coluna `merchant_profiles.protocol`.

A borda faz lookup do `merchant_id`, lê o protocolo do perfil e escolhe o encoder. Consequências:

- responde ao jurado cético: não é um `if` na URL, é roteamento por perfil do merchant;
- torna o upgrade para duas lojas **aditivo** — uma linha na tabela e um serviço, sem refatoração;
- mantém o núcleo intocado: `AuthorizationResult` e `AvalCheckoutStatus` são os mesmos nos dois caminhos.

Encoders:

| | UCP | ACP |
|---|---|---|
| Estado | `to_ucp_status()` | `to_acp_status()` |
| Evidência anexa | `ap2.merchant_authorization` | token delegado opaco `vlt_` (depende do item #6) |

O encoder ACP degrada com elegância enquanto o item #6 do contrato §7 não existir: ele emite o estado ACP correto sem o token delegado. O roteamento é demonstrável antes do cofre escopado ficar pronto.

Demonstração: a mesma compra em dois merchants produz **o mesmo `reason_code` e a mesma linha de ledger**, com `ready_for_complete` de um lado e `ready_for_payment` do outro.

---

## 5. Endpoints

### `GET /merchant/offers?category=travel`

→ `200 { "offers": [ { …payload…, "merchant_authorization": "<detached JWS>", "terms_hash": "…" } ] }`

### `POST /merchant/verify`

Recebe o recibo e reexecuta os cinco checks que `web/src/pages/MerchantView.tsx` já desenha:

1. **assinatura da oferta** — JWS detached verifica com a chave do próprio merchant
2. **oferta ainda válida** — `not_after` não venceu
3. **prova do AVAL** — a prova de autorização verifica com a JWK pública do AVAL, e o `merchant_id`, o valor e a moeda que ela vincula batem com a oferta
4. **`terms_hash`** — o da prova é igual ao hash JCS do `canonical_payload` gravado
5. **revogação** — releitura viva do estado do mandato

O check 3 é o que torna a verificação **independente**: o merchant não pergunta ao AVAL se a compra vale, ele verifica uma assinatura. E consegue fazer isso sem nunca receber `mandate_id` nem `principal_id` — a prova omite os dois de propósito.

O check 5 é uma **releitura viva**, nunca cache. Um mandato revogado depois da compra faz este check reportar revogado, e isso é o comportamento correto: a verificação responde *"isto ainda vale agora?"*.

### Verificações na borda de `POST /authorize` e `POST /capture`

Nesta ordem, antes de `evaluate()`. A primeira linha é o item #3 do contrato §7 e **não é parte deste design** — aparece aqui porque a ordem importa:

| Check | Falha |
|---|---|
| assinatura do agente (RFC 9421) — *pré-requisito, item #3* | `401 signature_invalid` |
| assinatura do merchant (detached JWS) | `401 offer_signature_invalid` |
| `not_after` vencido | `409 offer_expired` |
| `total` ou `merchant_id` divergente da oferta | `409 offer_mismatch` |
| nonce já gasto | `409 offer_replayed` |

**Cofre de nonce:** `IdempotencyStore.get_or_claim("merchant_offer", nonce, request_hash)`. O schema já tem `UniqueConstraint("scope","idempotency_key")` e o caminho já é testado. Nenhuma tabela nova, e o parâmetro `surface` finalmente é usado para o que foi desenhado.

Formato de erro conforme contrato §6: `{ "reason_code": …, "human_summary": … }`. Quando o erro vier do núcleo, os dois campos são **repassados** de `AuthorizationResult`, nunca reescritos.

---

## 6. Fluxo ponta a ponta

1. Agente pede o catálogo; recebe ofertas assinadas com `merchant_authorization` e `terms_hash`.
2. Agente escolhe uma, assina a requisição (RFC 9421) e chama `POST /authorize` carregando a oferta.
3. Borda roda os cinco checks da §5.
4. Borda monta `AuthorizationCommand(mandate_id, checkout_id, merchant_id, total)` e chama `evaluate()`.
5. Resultado canônico → encoder do protocolo do perfil do merchant → resposta.
6. `POST /capture` segue o mesmo caminho, e `canonical_payload` recebe os bytes JCS da oferta.
7. `POST /merchant/verify` reexecuta os cinco checks sobre o recibo.

---

## 7. Migração

Uma migração Alembic, uma tabela:

```
merchant_profiles(
  id            String  primary key,
  display_name  String  not null,
  protocol      String  not null,      -- ucp | acp
  public_jwk    Text    not null,
  trusted       Integer not null default 0
)
```

**Rejeitado:** reaproveitar `agent_profiles` para guardar o merchant. Economizaria a migração e cobraria na defesa técnica — *"por que o merchant está em `agent_profiles`?"* é uma pergunta sem boa resposta no palco. O Alembic já está montado.

`ledger_repository.save()` ganha `canonical_payload: bytes | None = None`. O default preserva as chamadas e os testes existentes.

---

## 8. Testes

**Unidade**

- `terms_hash` é estável sob reordenação das chaves do payload — é o ponto inteiro do JCS
- detached JWS verifica com o payload correto e **falha** com payload adulterado
- `to_ucp_status` / `to_acp_status` cobrem todos os membros de `AvalCheckoutStatus`

**Integração**

- oferta válida → `authorized`
- `not_after` vencido → `409 offer_expired`
- total adulterado na requisição → `409 offer_mismatch`
- nonce reenviado → `409 offer_replayed`
- assinatura de merchant desconhecido → `401 offer_signature_invalid`
- **mesma compra em merchant UCP e merchant ACP → mesmo `reason_code`, status diferente**

O último é o teste que prova a tese do roteamento, e é o que se cita na defesa técnica.

---

## 9. Fora de escopo

Carrinho e múltiplos itens; estoque; frete; cancelamento pelo merchant; x402; checkout ACP completo (redundante com UCP, conforme `aval-integration-architecture.md` §0.4); segunda loja como serviço separado.

A segunda loja é o upgrade B e só é executada depois dos itens 1–7 do contrato §7 estarem verdes.

---

## 10. Riscos

| Risco | Mitigação |
|---|---|
| A casca HTTP (item #1 do contrato) não existe; nada disto encosta em lugar nenhum sem ela | Este design pressupõe `POST /authorize` e `POST /capture` como pré-requisito, não como parte |
| Chaves in-memory somem no restart | Ofertas expiram em 10 min; não reiniciar entre ensaio e pitch |
| O detached JWS é código cripto novo escrito sob pressão | Os testes de payload adulterado são obrigatórios, não opcionais |
| `transaction_hash` tem `mandate_id` no preimage e vai para o merchant | Os demais campos do preimage são conhecidos do merchant, mas `mandate_<uuid4>` tem 128 bits de entropia; é um compromisso, não uma divulgação |

---

## 11. Mudanças no núcleo que este design exigiu

A auditoria do lado da oferta contra o enunciado encontrou dois requisitos nomeados que o núcleo não atendia. Ambos foram corrigidos antes da borda existir, porque nenhum deles pode viver na borda.

| Correção | O que era | O que é |
|---|---|---|
| **Escopo de compra** | `Mandate` só tinha merchant, limite e validade. A categoria viajava na oferta assinada e era ignorada. | `Mandate.allowed_categories` (não vazio, invariante), `AuthorizationCommand.category`, `category_not_allowed` → escala |
| **Teto do mandato** | Todo valor acima do orçamento escalava; não existia valor que a aprovação humana não destravasse | `Mandate.ceiling` opcional, fixo na criação. Acima dele: `mandate_ceiling`, rejeição sem botão. `replace_live_limit` move o orçamento e **não** move o teto |
| **Prova de autorização** | Payload vinculava só `reservation_id` e `transaction_hash`; o merchant não conseguia verificar que a prova era da oferta dele | Payload vincula `checkout_id`, `merchant_id`, valor, moeda e `terms_hash`; **omite** `mandate_id` e `principal_id` |
| **Disputa** | Não existia | Entidade `Dispute`, tabela `disputes`, `open_dispute()` e `resolve_dispute()`. A resolução lê a trilha: prova sobre reserva comprometida → `MANDATE_HELD`; ausência → `MANDATE_FAILED` |

Migração `0002_mandate_scope_and_disputes`, escrita idempotente porque `0001` constrói o schema a partir do metadata vivo.

**Ainda em aberto, e é defesa de palco, não código:** o enunciado diz que o mandato define *"o meio de pagamento"*. O AVAL emite a credencial por checkout, não por mandato (ver *Payment credential scope* no decision log). É uma divergência deliberada e mais forte — mas alguém vai perguntar, e a resposta precisa estar ensaiada.
