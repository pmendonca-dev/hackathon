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
- [x] `POST /mandates` — cria, valida invariantes, devolve `mandate_id` e `revocation_id`
- [x] `GET /mandates/{id}` — estado vivo com orçamento gasto e restante
- [x] **Fluxo de criação no navegador** — `web/src/pages/HolderView.tsx`, assinado pela carteira local
- [ ] Fluxo de criação no Telegram *(outra lane)*
- [ ] `POST /vault/tokens` — token escopado por checkout

> **Nenhum PAN existe no sistema.** O mandato nunca recebe dado de cartão e o agente
> nunca vê um. O token escopado por checkout continua pendente, mas a propriedade que o
> case pede — *sem entregar o cartão bruto* — já é verdadeira por construção.

> **Decidido:** `vault_tokens` não é cofre de cartão. O schema é `mandate_id + checkout_intent_id + merchant_id + max_amount + expires_at` — um credencial que só serve neste merchant, neste checkout, até este valor, até este horário. Não é que o cartão esteja guardado com segurança: **ele nunca existe no sistema**. Resposta mais forte ao case do que um cofre seria.

### A2. Merchant verifica antes de aceitar
✅ VuelaYa existe, assina suas ofertas e verifica compras. 14 testes.

> **Pré-requisito destravado em 29/08:** a prova de autorização agora vincula `checkout_id`, `merchant_id`, valor, moeda e `terms_hash`, e **omite** `mandate_id` e `principal_id`. Antes, o merchant recebia um JWS que só falava de `reservation_id` — e o `transaction_hash` só era recomputável com o `mandate_id`, que a visão merchant esconde de propósito. O merchant não tinha como verificar nada sozinho.
- [x] `GET /merchant/offers` — catálogo com 5 itens, cada oferta assinada e com nonce próprio
- [x] Oferta assinada em JWS ES256 pela chave do merchant (`merchant_authorization`)
- [x] `terms_hash` = SHA-256 sobre JCS do payload, verificado por teste independente
- [x] Oferta canônica gravada em `checkout_intents.canonical_payload` — placeholder removido
- [x] `POST /merchant/verify` — os cinco checks, com `accepted` agregado
- [x] `GET /merchant/.well-known/jwks.json` e `GET /.well-known/jwks.json` — verificação offline
- [x] **Tela do merchant** — `web/src/pages/MerchantDeskView.tsx`, contra a API real, com o
  diff de privacidade lado a lado e a lista de campos retidos vinda do servidor

> **Chaves separadas de propósito.** O merchant assina a oferta, o AVAL assina a
> autorização, e nenhum dos dois consegue produzir o outro lado da troca.

> **Privacidade testada, não prometida.** `test_the_merchant_verification_never_returns_the_mandate_or_the_buyer`
> falha se `mandate_id` ou `principal_id` aparecerem em qualquer lugar da resposta.

### A3. Agente descobre, decide e paga ponta a ponta
✅ `POST /agent/purchase` recebe texto livre e executa a compra inteira. 10 testes.
- [x] Loop de descoberta sobre o catálogo, com preço-alvo e casamento por palavra
- [x] Chamada assinada em `/authorize` e `/capture`, carregando a oferta assinada
- [x] Chave própria do agente, separada da chave do humano
- [x] **Decisão por LLM** — `agent/llm_intent.py`, opcional, com as regras de piso

> **O agente em processo não tem privilégio.** Ele assina e passa pela **mesma**
> verificação que a borda HTTP roda (`verify_signed_request`). Rodar dentro do processo
> não compra confiança nenhuma — e é o que torna a defesa contra impostor honesta.

> **Sobre o LLM:** `agent/intent.py` é a metade que *propõe*. Trocá-lo por um modelo não
> muda nada sobre o que pode ser comprado, e é exatamente esse o ponto da arquitetura.
> A demo funciona sem chave de API e sem risco de timeout no palco.

### A6. Liquidação com falha demonstrável
✅ Completo, incluindo o reconciliador.
- [x] `DemoPspAdapter` com modos `online` / `offline` / `decline`, lidos a cada chamada
- [x] `POST /admin/psp` `[J]` e `GET /admin/psp`
- [x] `POST /reconcile` — varre `capture_attempts` pendentes e conclui pelo mesmo caminho
- [x] `502 settlement_unreachable` — timeout não é recusa, e o orçamento continua retido

> **Bug encontrado e corrigido ao ligar isso:** uma compra recusada pelo processador
> ficava **permanentemente bloqueada** para nova tentativa. A reserva liberada mantinha
> seu `transaction_hash`, e o índice único `(mandate_id, transaction_hash)` recusava a
> segunda tentativa com `transaction_already_captured`. Um cartão recusado nunca poderia
> retentar o mesmo carrinho. Agora `RELEASED` devolve o slot; há teste dos dois lados —
> o que libera e o que continua bloqueando cobrança dupla de uma compra liquidada.

> Se o adapter levanta exceção em `capture()`, `finish()` não roda: reserva fica `COMMITTED` (orçamento retido), attempt fica pendente, idempotência bloqueia retry. É o *fail-closed* certo — timeout não é recusa. **Não envolver em `try/except` liberando a reserva:** soltar o orçamento no timeout é exatamente o bug que o desenho evita.

### A4. Humano recebe registro do que foi comprado e sob qual mandato
🟡 Servido e exibido no navegador; falta a entrega no chat.
- [x] `GET /ledger?view=human` — o que foi comprado, sob qual mandato, quanto sobrou
- [x] **Registro na tela do titular**, com a escada de avaliação de cada decisão
- [ ] Recibo no Telegram após liquidação *(outra lane; consome este endpoint)*

### A5. Humano, merchant e auditor leem a trilha
✅ Completo, e a trilha se verifica sozinha. 17 testes.
- [x] `SqliteAuditLedger` — **cadeia de hash**, um elo por mandato
- [x] `GET /ledger?view=human|merchant|auditor`
- [x] `GET /ledger/verify` — aponta a posição exata onde a cadeia quebrou
- [x] As três visões demonstráveis lado a lado

> **Mais forte do que o pedido.** O case pede uma trilha legível; esta é *verificável*.
> Cada evento canonicaliza a si mesmo (RFC 8785) e encadeia o digest do anterior, então
> editar qualquer linha quebra o próprio digest e todos os elos seguintes. Há teste que
> adultera uma linha no banco e confirma que `/ledger/verify` acusa a posição 1.

> **A visão do merchant é construída por lista branca**, nunca apagando campos do
> registro completo. Uma lista negra esquece; uma lista branca não pode vazar um campo
> que ninguém lembrou de esconder.

---

## B. Obrigatório — os casos feios

| # | Caso | Estado | Onde |
|---|---|---|---|
| B1 | Compra fora do mandato | ✅ escala **com caminho de volta** | `test_escalation_api.py` |
| B2 | Mandato expirado | ✅ exposto via HTTP; validade lida como instante real | `test_authorization_api.py` |
| B3 | Revogação ao vivo | ✅ exposto via HTTP; corrida testada; funciona com mandatos irmãos | `test_revocation_commit_race.py` |
| B4 | Agente impostor | ✅ 6 ataques, todos recusados na borda | `test_agent_identity_api.py` |
| B5 | Disputa posterior | ✅ exposto via HTTP, resolvido pela trilha | `test_settlement_and_disputes_api.py` |

### B1 — a escalação agora tem retorno

`POST /escalations/{id}/decision` fecha o buraco. O núcleo abre uma escalação com handle
`dh_...`, o titular assina a decisão e a compra retoma — ou morre.

- [x] `POST /escalations/{id}/decision`, `GET /escalations`, `GET /escalations/{id}`
- [x] Aprovação assinada (ES256) guardada inteira no ledger como evidência
- [x] Retomada da captura após aprovação, com idempotência derivada do handle
- [x] **Aprovar / Recusar no navegador**, com o JWS assinado na carteira local
- [ ] Push no Telegram com botões Aprovar / Negar *(outra lane; consome estes endpoints)*

> **A aprovação vincula a compra, não o motivo.** O JWS nomeia `decision_handle`,
> `mandate_id`, `decision` e `amount_minor_units`, e os quatro são conferidos contra a
> escalação congelada. Sem isso, uma aprovação poderia ser levantada de uma compra e
> aplicada a outra maior.

> **Descoberto rodando o smoke contra um servidor real, não pelos testes:** aprovar
> liberava só a condição escalada, então uma compra barrada por categoria *e* orçamento
> pedia uma segunda aprovação da **mesma** compra congelada. Como a assinatura já vincula
> valor, merchant e handle exatos, a segunda pergunta era atrito sem segurança. Hoje uma
> aprovação cobre a compra inteira — e os motivos que nunca são aprováveis (teto,
> revogação, expiração, valor inválido) continuam de pé. Há teste para os dois lados.

> **A aprovação não ressuscita nada.** Tudo é reavaliado no momento da retomada: uma
> revogação que chegou enquanto a pessoa decidia ainda recusa a compra. Testado.

### B4 — impostor implementado

Assinatura RFC 9421 (ES256) sobre `@method`, `@path` e `content-digest`, exigida em
`/authorize` e `/capture`.

- [x] Verificação de assinatura na borda, antes de o corpo ser lido
- [x] `401 signature_missing` · `401 key_not_found` · `401 signature_invalid`
- [x] `401 content_digest_mismatch` · `401 signature_replayed` · `401 signature_stale`
- [x] `403 profile_not_trusted` — perfil conhecido e ainda assim recusado
- [x] `401 signature_components_insufficient` — assinatura que não cobre o corpo
- [x] `POST /agents` e `GET /agents/{kid}` — registro e consulta de perfil

> **Os componentes cobertos são fixos.** Deixar o chamador escolher o que a própria
> assinatura cobre é exatamente como corpos assinados são trocados: a assinatura segue
> válida sobre as partes que ninguém checou. Há teste que tenta isso.

> **O nonce é queimado por último**, depois de a assinatura verificar. Caso contrário um
> atacante gastaria nonces alheios com lixo assinado por ninguém.

## C. Obrigatório — a demo deve comprovar

- [x] Criação de mandato e compra ponta a ponta autorizada
- [x] Tentativa fora do mandato recusada **ou escalada** — nunca aprovada em silêncio
- [x] Revogação ao vivo: revogado → próxima tentativa falha
- [x] Visão do humano, verificação do merchant, trilha do auditor
- [x] **Trial by fire sem o time tocar em nada** `[J]`

> `scripts/smoke_demo.py` percorre os cinco pontos contra um servidor de verdade e falha
> alto no primeiro que não se comportar. Rodar isso antes do pitch é o ensaio.

### Trial by fire — o que o jurado consegue fazer sozinho `[J]`

| ação | endpoint | verificado por |
|---|---|---|
| mudar o limite | `PATCH /mandates/{id}/limit` | `test_a_live_limit_change_binds_the_very_next_decision` |
| revogar | `POST /mandates/{id}/revocation` | `test_a_signed_revocation_blocks_the_next_purchase` |
| aprovar / negar | `POST /escalations/{id}/decision` | `test_an_approved_escalation_completes_the_purchase` |
| derrubar o PSP | `POST /admin/psp` | `test_an_unreachable_processor_is_not_a_refusal` |
| reconciliar | `POST /reconcile` | `test_reconciling_after_the_processor_returns_settles_what_was_held` |
| comprar fora do escopo **em texto livre** | `POST /agent/purchase` | `test_agent_purchase_api.py` |
| trocar o merchant permitido | recriar o mandato | `test_a_purchase_from_another_merchant_escalates_instead_of_passing` |
| mudar a validade | recriar o mandato | `test_the_clock_moving_past_the_expiry_ends_the_mandate` |

**Nenhum cache na frente de limite e revogação.** Toda decisão relê o estado vivo, e há
teste provando que uma mudança de limite vale na decisão imediatamente seguinte.

## D. Bônus

- [x] **Disputa completa** — `POST /disputes`, `GET /disputes`, `POST /disputes/{id}/resolution`.
  A resolução lê a trilha: prova de autorização sobre reserva comprometida → `MANDATE_HELD`;
  ausência → `MANDATE_FAILED`. Abertura e resolução entram na cadeia de hash, e a cadeia
  continua verificando depois. **Falta** apenas o botão no bot *(outra lane)*.
- [x] **Agente adversarial** — o agente aceita texto livre e tenta de verdade. Cinco
  caminhos criativos testados: teto, orçamento acumulado, merchant fora do escopo,
  categoria fora do escopo e retentativa. Nenhum passa.
- [x] **Mandatos com condições ricas** — as duas condições que o case nomeia funcionam.
  O preço-alvo (*"if it drops below $150"*) é preferência do comprador, aplicada pelo
  agente. A frequência (*"até 3× por mês"*) é **autoridade**, aplicada pelo núcleo:
  `usage_limit: {max_uses, window_seconds}`, janela deslizante, na escada entre o teto
  e o orçamento — e aprovável, porque um humano pode dizer sim a uma quarta compra.
  Um uso é queimado por dinheiro efetivamente retido, então um cartão que o processador
  recusou não come uma das compras permitidas. `test_usage_frequency.py`.

> **Onde o preço-alvo vive, e por quê.** Ele é preferência do comprador, aplicada pelo
> agente; os limites do mandato são autoridade, aplicada pelo núcleo. Misturar as duas
> coisas colocaria uma regra de compra dentro do caminho de confiança — e o núcleo passaria
> a depender do que o agente diz querer.

## E. Entregáveis do Mission Control

- [ ] Slides (URL)
- [ ] Demo (URL de vídeo ou experiência ao vivo)
- [x] Repositório público com README legível por quem não participou
- [x] Diagrama de arquitetura — `docs/architecture.md` (exportar para PDF/PNG antes do envio)
- [x] Decision log exportado em `.md` — `docs/decision-log.md`

## E2. Diferenciais construídos além do pedido

| # | O quê | Onde |
|---|---|---|
| 1 | **Escada de avaliação publicada** — a ordem do núcleo vira imagem, com os degraus nunca consultados visíveis | `test_evaluation_trace.py` · `EvaluationLadder.tsx` |
| 2 | **Relógio de demonstração, só para frente** — o jurado vê o mandato expirar | `test_demo_clock.py` |
| 3 | **Adulteração da trilha ao vivo** — a cadeia se defende na frente de quem duvida | `test_ledger_tamper_demo.py` |
| 4 | **Frequência no mandato** — o bônus nomeado no enunciado | `test_usage_frequency.py` |
| 5 | **Kill switch do titular** — uma assinatura encerra tudo aquela chave sustenta | `test_principal_kill_switch.py` |
| 6 | **Carteira no navegador** — chave P-256 não-extraível, o servidor nunca vê a metade privada | `holder-wallet.test.mjs` |
| 7 | **Diff de privacidade** — as duas projeções do mesmo evento, lado a lado | `MerchantDeskView.tsx` |
| 8 | **LLM real no agente** — alucinação demonstrável, recusada pelo núcleo | `test_llm_intent.py` |

---

## F. Riscos operacionais

- [x] **Ambiente resolvido.** `pyproject.toml` agora aceita Python 3.12 e 3.13; a suíte
  roda nesta máquina. **161 testes passando.**
- [x] **Ambiente limpo verificado** — `scripts/smoke_demo.py` roda o case inteiro contra
  um servidor HTTP real e passa. Rodar de novo a partir de um clone do zero antes do freeze.
- [x] **Agente sem dependência de LLM** — nenhuma chave de API, nenhum timeout possível
  no palco. A decisão de autorização nunca dependeu do modelo, e agora isso é visível.
- [ ] **Telegram por long polling, não webhook** *(outra lane)*
- [ ] **Ensaio em 7 minutos**, com 3 sobrando para os jurados
- [ ] **Confirmar qual máquina apresenta** e rodar o smoke nela

---

## Estado da suíte

| área | arquivos | testes |
|---|---|---:|
| domínio, cripto e documentos | `tests/unit/{domain,security}` + bootstrap | 20 |
| núcleo de autorização e persistência | `test_authorization_core`, `test_dispute_resolution`, `tests/integration/{application,test_database_bootstrap}` | 27 |
| API de autorização, mandato e revogação | `test_authorization_api` | 21 |
| trilha de auditoria e três visões | `test_audit_ledger_api` | 16 |
| escalação e aprovação assinada | `test_escalation_api` | 17 |
| merchant, oferta assinada e verificação | `test_merchant_api` | 14 |
| identidade de agente e impostor | `test_agent_identity_api` | 12 |
| liquidação, reconciliação e disputas | `test_settlement_and_disputes_api` | 13 |
| agente comprador ponta a ponta | `test_agent_purchase_api` | 10 |
| segurança de operador e autoridade assinada | `test_operator_authorization.py` | 11 |
| **total** | | **161** |

Uma revisão de segurança dedicada encontrou e corrigiu quatro falhas de autorização —
registro anônimo de agente confiável, mudança de limite sem assinatura, CORS curinga e
superfícies de operador abertas. Ver [modelo de segurança](../security-model.md).

**Bug crítico encontrado sondando o sistema ao vivo, depois da suíte estar verde:** quando
duas pessoas — ou a mesma pessoa renovando o mandato — registravam a **mesma chave de
titular**, só o primeiro mandato varrido podia ser revogado; os demais devolviam
`revocation_mandate_mismatch` e continuavam gastando. A varredura por `kid` tratava um
mandato irmão como fraude em vez de simplesmente pular para o próximo candidato. Isso
quebraria o momento nº 1 da demo assim que um jurado criasse um segundo mandato. Há dois
testes de núcleo e um de API cobrindo o caso.

Quatro bugs de correção foram encontrados e corrigidos durante esta implementação — a primeira
mudança de limite não avançava a versão de política, uma compra recusada pelo processador
ficava bloqueada para sempre, e a aprovação de escalação pedia uma segunda confirmação da
mesma compra. Os dois primeiros vieram de testes; o terceiro só apareceu contra um
servidor de verdade.
