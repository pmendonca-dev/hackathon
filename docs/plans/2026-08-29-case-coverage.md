# Cobertura do case — checklist até o code freeze

Rastreamento único do desafio 01 contra o que existe no repositório. Atualize marcando a caixa; não apague linhas.

Fontes: `ideias/case.txt` (enunciado) e `docs/hackathon-rules.md` (regras e avaliação).

**Code freeze: domingo 30/08, 12:30.**

---

## Legenda

`✅` funciona e tem teste · `🟡` parcial · `⛔` não existe · `[J]` superfície que o jurado toca

---

## A. Obrigatório — o sistema deve permitir

### A1. Humano cria mandato verificável, sem expor o cartão
🟡 Entidade `Mandate` completa e validada (`src/aval/domain/entities.py`).

> **Corrigido em 29/08:** o mandato não dizia **o que** podia ser comprado. `Mandate.allowed_categories` agora é obrigatório (invariante de conjunto não vazio) e o núcleo escala `category_not_allowed`. Antes disso a categoria viajava assinada na oferta e era ignorada — mandato de voos autorizava hotel.

> **Também corrigido:** `Mandate.ceiling`, opcional e fixo na criação. Acima dele o núcleo devolve `mandate_ceiling` e **não** oferece aprovação. `replace_live_limit` move o orçamento e não move o teto — há teste. Sem isso, o momento do roteiro em 4:00–4:45 não tinha código por trás.
- [ ] `POST /mandates`
- [ ] Fluxo de criação no Telegram
- [ ] `POST /vault/tokens` — token escopado por checkout

> **Decidido:** `vault_tokens` não é cofre de cartão. O schema é `mandate_id + checkout_intent_id + merchant_id + max_amount + expires_at` — um credencial que só serve neste merchant, neste checkout, até este valor, até este horário. Não é que o cartão esteja guardado com segurança: **ele nunca existe no sistema**. Resposta mais forte ao case do que um cofre seria.

### A2. Merchant verifica antes de aceitar
⛔ Merchant não existe. Design em `docs/superpowers/specs/2026-08-29-supply-side-design.md`.

> **Pré-requisito destravado em 29/08:** a prova de autorização agora vincula `checkout_id`, `merchant_id`, valor, moeda e `terms_hash`, e **omite** `mandate_id` e `principal_id`. Antes, o merchant recebia um JWS que só falava de `reservation_id` — e o `transaction_hash` só era recomputável com o `mandate_id`, que a visão merchant esconde de propósito. O merchant não tinha como verificar nada sozinho.
- [ ] `GET /merchant/offers` — catálogo estático de voos
- [ ] Oferta assinada em JWS ES256 pela chave do merchant (`merchant_authorization`)
- [ ] `terms_hash` = SHA-256 sobre JCS do payload (`security/jcs.py`, `rfc8785` já é dependência)
- [ ] Gravar a oferta canônica em `checkout_intents.canonical_payload` — hoje é placeholder `{"id": ...}` em `ledger_repository.py:33`
- [ ] `POST /merchant/verify` — os cinco checks
- [ ] Tela do merchant (`web/src/pages/MerchantView.tsx` já é a especificação visual)

### A3. Agente descobre, decide e paga ponta a ponta
⛔ Agente não existe.
- [ ] Loop de descoberta sobre o catálogo
- [ ] Decisão por LLM
- [ ] Chamada assinada em `/authorize` e `/capture`, carregando a oferta assinada

### A6. Liquidação com falha demonstrável
🟡 Estado IN_DOUBT **já emerge corretamente**; falta quem o resolva.
- [ ] `DemoPspAdapter` com modos `online` / `offline` / `decline`
- [ ] `POST /admin/psp` `[J]`
- [ ] `POST /reconcile` — varre `capture_attempts` pendentes

> Se o adapter levanta exceção em `capture()`, `finish()` não roda: reserva fica `COMMITTED` (orçamento retido), attempt fica pendente, idempotência bloqueia retry. É o *fail-closed* certo — timeout não é recusa. **Não envolver em `try/except` liberando a reserva:** soltar o orçamento no timeout é exatamente o bug que o desenho evita.

### A4. Humano recebe registro do que foi comprado e sob qual mandato
⛔
- [ ] Recibo no Telegram após liquidação, citando o mandato

### A5. Humano, merchant e auditor leem a trilha
🟡 Porta `AuditLedger` definida em `ports.py`, tabela `audit_events` existe em `models.py`. **Falta o repositório.**
- [ ] `SqliteAuditLedger` implementando a porta
- [ ] `GET /ledger?view=human|merchant|auditor`
- [ ] As três visões demonstráveis lado a lado

---

## B. Obrigatório — os casos feios

| # | Caso | Estado | Falta |
|---|---|---|---|
| B1 | Compra fora do mandato | ✅ `budget_exceeded` e `merchant_out_of_scope` → `awaiting_human` | **caminho de volta** ⚠️ |
| B2 | Mandato expirado | ✅ `mandate_expired`, testado | expor via HTTP |
| B3 | Revogação ao vivo | ✅ testado com corrida (`test_revocation_commit_race.py`) | expor via HTTP |
| B4 | Agente impostor | ⛔ cripto pronta, verificação ausente | ligar na borda ⚠️ |
| B5 | Disputa posterior | 🟡 modelada e resolvida pela trilha | expor via HTTP e no bot |

### ⚠️ B1 — a escalação não tem retorno

O núcleo devolve `awaiting_human` e para. Não existe *"o humano aprovou, prossiga"*.

O case diz: *"rejected **or escalated to human approval** — never silently approved"*. Sem o retorno, metade do requisito não está entregue.

- [ ] `POST /escalations/{id}/decision`
- [ ] Push no Telegram com botões Aprovar / Negar
- [ ] Aprovação assinada (ES256) vira evidência no ledger
- [ ] Retomada da captura após aprovação

### ⚠️ B4 — impostor não implementado

Item **nomeado** no case (*"someone impersonates it"*). Existem `security/{jws,ecdsa,content_digest,key_custody}.py`, a entidade `AgentIdentity` e a tabela `agent_profiles`. `AgentIdentity` está definida e **nunca usada**.

- [ ] Verificação de assinatura na borda (RFC 9421)
- [ ] `401 signature_invalid` · `401 key_not_found` · `403 profile_not_trusted`
- [ ] Demonstração: mesmo corpo, chave errada → 401

---

## C. Obrigatório — a demo deve comprovar

- [ ] Criação de mandato e compra ponta a ponta autorizada
- [ ] Tentativa fora do mandato recusada **ou escalada** — nunca aprovada em silêncio
- [ ] Revogação ao vivo: revogado → próxima tentativa falha
- [ ] Visão do humano, verificação do merchant, trilha do auditor
- [ ] **Trial by fire sem o time tocar em nada** `[J]`

### Trial by fire — o que o jurado precisa conseguir fazer sozinho `[J]`

- [ ] Mudar o limite → próxima decisão respeita, sem restart
- [ ] Revogar → próxima tentativa falha
- [ ] Trocar o merchant permitido → compra fora do escopo escala
- [ ] Mudar a validade → mandato expira
- [ ] Mandar o agente comprar fora do escopo **em texto livre**

> A regra é explícita: *"os jurados alterarão entradas ou regras sem ensaio; o sistema deve reagir sem intervenção manual do time"*. Qualquer regra constante em código, ou qualquer cache na frente de limite e revogação, reprova aqui.

---

## D. Bônus

- [x] **Disputa completa (núcleo)** — `Dispute`, tabela `disputes`, `open_dispute()` e `resolve_dispute()`. A resolução lê a trilha: prova de autorização sobre reserva comprometida → `MANDATE_HELD`; ausência → `MANDATE_FAILED`. **Falta** a superfície HTTP e o botão no bot.
- [ ] **Mandatos com condições ricas** — *"se cair abaixo de $150"*, *"até 3× por mês"*
- [ ] **Agente adversarial** — defesa contra caminhos criativos

> **Sobre condições ricas:** o preço-alvo (*"if it drops below $150"*) é o exemplo-título do próprio case. Um jurado que leu o enunciado vai procurar. Hoje `Mandate` só tem `limit` e `expires_at` — não há condição de preço nem contagem de frequência. Se der para fazer um, faça o preço-alvo.

> **Sobre agente adversarial:** é o único bônus que vocês ganham praticamente de graça, porque decidiram usar LLM de verdade. Ver o roteiro da demo.

---

## E. Entregáveis do Mission Control

- [ ] Slides (URL)
- [ ] Demo (URL de vídeo ou experiência ao vivo)
- [ ] Repositório público com README legível por quem não participou
- [ ] Diagrama de arquitetura em PDF/PNG, < 25 MB
- [ ] Decision log exportado em `.md`

---

## F. Riscos operacionais

- [ ] **Uma máquina roda a pilha inteira.** Verificado nesta: Python 3.12, sem `uv`, sem `pytest`; `pyproject.toml` exige `>=3.13,<3.14`. **Nenhum teste do backend roda aqui.** Confirme hoje qual máquina apresenta.
- [ ] **Telegram por long polling, não webhook.** Sem túnel, sem ngrok caindo no pitch. Só internet de saída.
- [ ] **Agente LLM tem timeout e fallback.** Se o modelo demorar ou falhar no pitch, a demo não pode travar — a decisão de autorização não depende dele, e isso precisa estar visível.
- [ ] **Ensaio em 7 minutos**, com 3 sobrando para os jurados.
- [ ] **Ambiente limpo**: clonar o repo do zero e rodar, uma vez, antes do freeze.
