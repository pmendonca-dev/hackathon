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
✅ Entidade `Mandate` completa e validada (`src/aval/domain/entities.py`).

> **Corrigido em 29/08:** o mandato não dizia **o que** podia ser comprado. `Mandate.allowed_categories` agora é obrigatório (invariante de conjunto não vazio) e o núcleo escala `category_not_allowed`. Antes disso a categoria viajava assinada na oferta e era ignorada — mandato de voos autorizava hotel.

> **Também corrigido:** `Mandate.ceiling`, opcional e fixo na criação. Acima dele o núcleo devolve `mandate_ceiling` e **não** oferece aprovação. `replace_live_limit` move o orçamento e não move o teto — há teste. Sem isso, o momento do roteiro em 4:00–4:45 não tinha código por trás.
- [x] `POST /mandates` — cria, valida invariantes, devolve `mandate_id` e `revocation_id`
- [x] `GET /mandates/{id}` — estado vivo com orçamento gasto e restante
- [x] **Fluxo de criação no navegador** — `web/src/pages/HolderView.tsx`, assinado pela carteira local
- [x] **Fluxo de criação no Telegram** — `/start` emite chave P-256 do chat e mandato em nome dela
- [x] **O mandato nomeia o meio de pagamento** — `Mandate.instrument`, migração
  `0010_mandate_instrument`. O cartão é lido uma vez em `POST /mandates`, tokenizado na
  borda e esquecido; o que sobrevive é um token que o agente apresenta e quatro dígitos
  que a pessoa reconhece. Uma captura que apresenta outro instrumento — ou nenhum — é
  recusada com `instrument_not_in_mandate`, antes da escada chegar ao dinheiro.
  `tests/integration/api/test_mandate_instrument.py`
- [x] **Cancelar o cartão sem revogar o mandato** — escopo `instrument:vt_…`, assinado
  pelo titular. O mandato segue 🟢 ACTIVE, o orçamento fica onde estava, e a próxima
  compra é recusada por `instrument_revoked`. Autoridade e pagamento são duas coisas,
  então são duas revogações. Botão no Telegram, com tela de confirmação.
- [ ] `POST /vault/tokens` — allowance escopada por checkout (existe em
  `/agentic_commerce/delegate_payment`; não está no caminho do bot)

> **Nenhum PAN existe no sistema.** O número é lido em um único ponto — o corpo de
> `POST /mandates` — tokenizado ali e descartado. Não é persistido, não é logado e não é
> repassado: o mandato guarda `vt_…` e `•••• 4242`, e nenhum dos dois reconstrói um
> cartão. O agente apresenta o token e nada mais, e o token não vale em outro mandato,
> porque o núcleo recusa uma captura que não apresente o instrumento que este mandato
> nomeia.

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

> **Telegram integrado em 29/08.** O bot deixou de falar com fixtures e passa a
> chamar a API viva. Cada chat recebe a própria chave P-256 e o próprio mandato,
> então uma sala de jurados usa um bot só sem compartilhar autoridade nenhuma —
> um jurado não revoga o mandato do outro porque não tem a chave dele. Aprovação,
> revogação e mudança de limite viajam assinadas pelo titular; o servidor nunca
> assina no lugar dele. Ver [contrato do bot](../contracts/aval-telegram-gateway.md).

### A3. Agente descobre, decide e paga ponta a ponta
✅ `POST /agent/purchase` recebe texto livre e executa a compra inteira. 10 testes.
- [x] Loop de descoberta sobre o catálogo, com preço-alvo e casamento por palavra
- [x] Chamada assinada em `/authorize` e `/capture`, carregando a oferta assinada
- [x] Chave própria do agente, separada da chave do humano
- [x] **Decisão por LLM** — `agent/proposer.py`, opcional, com as regras de piso
- [x] Catálogo de 38 ofertas em três vendedores, atributos dentro da assinatura

> **O agente em processo não tem privilégio.** Ele assina e passa pela **mesma**
> verificação que a borda HTTP roda (`verify_signed_request`). Rodar dentro do processo
> não compra confiança nenhuma — e é o que torna a defesa contra impostor honesta.

> **O LLM entrou, e o núcleo não mudou uma linha.** `AVAL_LLM_API_KEY` liga o
> proponente: pré-filtro determinístico (`shortlist`) reduz o catálogo a ~12 candidatos,
> o modelo escolhe um e escreve o motivo, e o motivo aparece no recibo do Telegram. Sem
> chave, com timeout, com resposta fora do formato ou com um SKU inventado, `intent.py`
> decide e a compra acontece do mesmo jeito — **a demo não depende de rede**. Trocar o
> proponente não muda nada sobre o que pode ser comprado, e é esse o ponto.

> **Por que o catálogo é local.** Preço raspado da web não é oferta: não tem chave de
> vendedor, então não tem `terms_hash` para a prova vincular nem nada para o
> `/merchant/verify` verificar. Buscar na internet trocaria a invariante do case por
> inventário. O catálogo tem trade-off de verdade — o mais barato tem 2 escalas e 19h, o
> segundo mais barato parte 04:20 — para que a escolha do modelo seja uma decisão e não
> um `min(price)`.

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
✅ Servido, exibido no navegador e entregue no chat.
- [x] `GET /ledger?view=human` — o que foi comprado, sob qual mandato, quanto sobrou
- [x] **Registro na tela do titular**, com a escada de avaliação de cada decisão
- [x] **Recibo no Telegram após liquidação** — chega sozinho depois da compra, sem precisar pedir

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
- [x] **Push no Telegram com botões Aprovar / Negar** — a decisão vai assinada pela chave do chat

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
- [x] **O agente age sozinho, e a autoridade decide mesmo assim** — o caso mínimo do
  enunciado diz *"Marta cria o mandato; **o agente começa a vigiar preços**"*, e até aqui
  toda superfície só respondia a pedido. `agent/watches.py` guarda a ordem permanente;
  o bot dá o tick no ciclo que ele já tinha e entrega o resultado sem ninguém pedir.
  Quando o preço cai dentro do mandato, ele compra. Quando o jurado revoga antes,
  ele tenta, é recusado por `mandate_revoked` e conta — **o que acabou foi a
  autoridade, não o agente**. `tests/integration/api/test_agent_watches.py`
- [x] **Pedido incompleto perguntado, não adivinhado** — *"compre uma passagem"* não
  nomeia nada à venda. Antes, o mais barato do catálogo vencia por omissão: uma
  aprovação silenciosa de algo que ninguém pediu. Agora o agente devolve
  `needs_clarification` com a pergunta e os botões de resposta, e o mandato nunca é
  consultado porque não há o que submeter a ele — a trilha vem vazia.
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
| **injetar prompt no agente** (*"a Marta liberou"*) | `POST /agent/purchase` | `test_a_prompt_injection_does_not_move_the_ceiling` |
| **pedir sem dizer o quê** (*"compre uma passagem"*) | `POST /agent/purchase` | `test_an_instruction_that_names_nothing_asks_instead_of_buying` |
| **derrubar o preço e ver o agente comprar sozinho** | `POST /admin/catalog/price` | `test_when_the_price_falls_the_agent_buys_with_nobody_typing` |
| **revogar antes de derrubar o preço** | `revocation` + `price` | `test_a_revoked_mandate_stops_the_agent_that_nobody_is_watching` |
| **cancelar o cartão sem revogar** | `POST /mandates/{id}/revocation` | `test_cancelling_the_card_leaves_the_agent_alive_and_the_budget_intact` |
| trocar o merchant permitido | recriar o mandato | `test_a_purchase_from_another_merchant_escalates_instead_of_passing` |
| mudar a validade | recriar o mandato | `test_the_clock_moving_past_the_expiry_ends_the_mandate` |

**Nenhum cache na frente de limite e revogação.** Toda decisão relê o estado vivo, e há
teste provando que uma mudança de limite vale na decisão imediatamente seguinte.

## D. Bônus

- [x] **Disputa completa** — `POST /disputes`, `GET /disputes`, `POST /disputes/{id}/resolution`.
  A resolução lê a trilha: prova de autorização sobre reserva comprometida → `MANDATE_HELD`;
  ausência → `MANDATE_FAILED`. Abertura e resolução entram na cadeia de hash, e a cadeia
  continua verificando depois. O botão está no bot: todo recibo liquidado traz *Não reconheço esta compra*.
- [x] **Agente adversarial** — o agente aceita texto livre e tenta de verdade. Cinco
  caminhos criativos testados: teto, orçamento acumulado, merchant fora do escopo,
  categoria fora do escopo e retentativa. Nenhum passa.
- [x] **Injeção de prompt no proponente** — o modelo é convencido a propor a executiva
  alegando autorização da titular. Ele propõe, escreve o motivo, e o teto recusa igual.
  Um sistema cuja segurança dependesse de o modelo não ser enganado não teria segurança
  nenhuma — e o modelo sequer conhece o teto que o recusou.
  `test_a_prompt_injection_does_not_move_the_ceiling`.
- [x] **Ambiguidade pergunta, mandato recusa** — dois freios diferentes, em coisas
  diferentes, demonstráveis separadamente. O mandato responde *não pode*; o agente
  responde *não sei*. Sem o segundo, todo pedido vago vira uma compra que passou em
  todos os limites e mesmo assim não era o que a pessoa queria — que é precisamente a
  falha que o case chama de aprovação silenciosa. Funciona por regra (sem chave, sem
  rede) e por modelo, que pode devolver `{"pergunta": …}` no lugar de um SKU.
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
- [x] Diagrama de arquitetura — `docs/architecture.pdf`, 9 páginas A3 e 1,4 MB, impresso de
  `docs/architecture.html` por `scripts/export_architecture.py`. Seis diagramas em SVG
  desenhado à mão, com azul de autoridade e âmbar de dinheiro atravessando todos eles.
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
| 9 | **Terceiro estado do pagamento** — *em confirmação*: sem resposta não é recusa nem sucesso | `test_payment_in_doubt.py` |
| 10 | **Veredito de responsabilidade** — quem paga, derivado da trilha a cada leitura | `test_dispute_liability.py` |
| 11 | **Teto de reservas vivas** — griefing de orçamento, o ataque que não move um centavo | `test_reservation_griefing.py` |
| 12 | **Rodapé ao vivo** — as afirmações do pitch lidas da própria trilha encadeada | `test_metrics.py` |
| 13 | **Pseudônimo pareado** — cliente recorrente para o merchant, incorrelacionável entre lojas | `test_merchant_pairwise_identity.py` |

---

## H. Auditoria de 30/08 — o que a implementação dos diferenciais encontrou

### H1 — a visão do merchant filtrava campos e nunca eventos `[privacidade]`

`MERCHANT_VISIBLE_DETAIL` é lista branca desde sempre, e a doutrina está escrita no topo
do arquivo. Mas a filtragem parava nos **campos**: todo evento com o `merchant_id` dele
ia para o merchant, qualquer que fosse o evento. O buraco tinha exatamente a forma do
filtro — `payment_in_doubt` carrega só campos que o merchant pode ler e ainda assim conta
a ele que o dinheiro daquele comprador está incerto, que é fato sobre o processador do
comprador e não sobre a venda. Agora existe `MERCHANT_VISIBLE_EVENTS`, e um vendedor é
respondido sobre a venda de que participou e sobre nada mais que aconteceu com a pessoa.

### H2 — `/agent/purchase` devolvia 502 para a pessoa `[demo]`

A rota de máquina (`/capture`) está certa em devolver 502: um chamador automático precisa
saber que não obteve resposta. Mas o bot e o navegador chamam `/agent/purchase`, e um
`502` na tela de quem comprou é indistinguível de um bug — justamente na cena em que o
jurado derruba o processador de propósito. Agora essa rota devolve `200` com
`outcome: in_doubt`; o contrato de máquina não mudou.

### H3 — o bot chamava de "Recusado" uma compra retida `[demo]`

`purchase_result` tinha quatro saídas e o estado retido caía no `else`, que diz
**⛔ Recusado**. Recusado e sem-resposta são fatos opostos sobre o orçamento — num, o
dinheiro voltou; no outro, segue preso — e a única tela que o comprador de verdade lê
tinha os dois fundidos.

### H4 — congelar o orçamento era um ataque sem defesa `[segurança]`

Cada captura sem resposta retém orçamento, e reter é o comportamento correto. Só que nada
limitava **quantas** podiam estar vivas ao mesmo tempo: um agente com bug — ou hostil —
zera a capacidade de compra da Marta em N chamadas, sem mover um centavo e sem disparar
nenhum reason code. O próprio botão *derrubar o PSP* do console do jurado torna isso
alcançável na demo. Agora há teto de reservas vivas, e ele **recusa** em vez de escalar:
um humano apertando aprovar não destrava dinheiro que já está preso.

### H5 — os dois contadores que o merchant não precisava ver `[privacidade]`

`policy_version` e `revocation_epoch` andam com o mandato, não com a venda. Dois merchants
comparando-os contra timestamps têm sinal de ligação — fraco, mas real — para o mesmo
comprador, e eles não compram nada ao merchant: a prova assinada que ele verifica já
carrega os dois. Saíram da projeção, e no lugar entrou o pseudônimo pareado, que é o que
um vendedor legitimamente quer (reconhecer cliente recorrente) na única forma que não
serve para correlacionar.

> **O padrão dos cinco, de novo.** Três nasceram de perguntar *o que a pessoa vê quando
> isto dá errado* em vez de *o código está correto*; dois de perguntar *o que dois
> merchants conseguem fazer juntos*. Nenhum aparecia em teste verde, porque cada teste
> exercitava o caminho honesto da funcionalidade que cobria.

---

## F. Riscos operacionais

- [x] **Ambiente resolvido.** `pyproject.toml` agora aceita Python 3.12 e 3.13; a suíte
  roda nesta máquina. **478 testes passando.**
- [x] **Ambiente limpo verificado, a partir de um clone do zero** — 30/08, contra o branch
  do PR #14. `git clone` raso, `venv` nova, `pip install -e .`, `npm install`: 478 testes
  Python, 23 do navegador, `smoke_demo.py` e `telegram_smoke.py` ALL GREEN contra um
  servidor HTTP real, e a jornada do navegador 15/15. Nada de estado de execução vai no
  repositório — `var/` e `.aval` não existem no clone, então a primeira execução de um
  jurado é a mesma que esta.
- [x] **LLM sem dependência de rede** — o proponente cai para regras em qualquer falha
  (sem chave, timeout, JSON inválido, SKU inventado), com teste para cada caso. A decisão
  de autorização nunca dependeu do modelo, e agora isso é demonstrável nos dois sentidos:
  ligado, o modelo propõe e explica; desligado ao vivo, a compra continua acontecendo.
- [x] **Telegram por long polling, não webhook** — sem URL pública, sem túnel no palco
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

---

## G. Auditoria de 30/08 — cinco defeitos encontrados com a suíte verde

A suíte passava e o smoke ao vivo passava. Estes cinco não apareciam em
nenhum dos dois, porque cada teste exercitava o **caminho honesto** da funcionalidade que
ele cobria. Todos têm agora teste de regressão que falha sem a correção.

### G1 — a oferta assinada podia ser gasta infinitas vezes `[crítico]`

`POST /capture` aceitava um campo `terms_hash` do chamador, e ele **vencia** o valor
derivado da oferta que a borda tinha acabado de verificar. O ataque: enviar a compra
**sem** `merchant_authorization` — de modo que o nonce da oferta nunca é queimado — e
declarar o `terms_hash` daquela oferta à mão. O AVAL emitia uma prova de autorização
vinculada a esses termos, e `POST /merchant/verify` **aceitava**, com os cinco checks
verdes. A mesma passagem de $130 podia ser resgatada quantas vezes o orçamento
aguentasse, e o `test_the_same_offer_cannot_be_spent_twice` continuava passando porque
só testava o caminho honesto.

O `terms_hash` é exatamente aquilo contra o que o merchant confere a compra, então só
pode sair da oferta que esta borda verificou. O campo saiu do contrato:
`src/aval/api/schemas.py`, `src/aval/api/purchase_flow.py`.
`tests/integration/api/test_offer_single_use.py`

### G2 — a escalação de frequência aprovava e não comprava

`usage_limit_exceeded` escalava para aprovação humana, mas não estava em
`APPROVABLE_REASONS`. O titular assinava *Aprovar*, a escalação fechava como `APPROVED`
— e a captura retomada era recusada pelo mesmo degrau que a abriu. Não sobrava nada para
retentar: uma compra morta com a tela dizendo que foi aprovada. É o bônus que o próprio
enunciado nomeia (*"até 3× por mês"*), e a documentação já prometia que era aprovável.

### G3 — o mesmo beco sem saída no orçamento zerado

`budget_revoked` (escopo `budget:zero`) também devolvia `AWAITING_HUMAN` sem escape
algum na escada. `budget:zero` é justamente o escopo que o titular escolhe quando quer
**congelar** o gasto sem matar o agente, então quem congelou é quem pode liberar uma
compra avulsa. Revogar o mandato inteiro segue sendo parada dura — recusado, nunca
escalado. `tests/integration/api/test_escalation_reasons_are_approvable.py`

### G4 — a faixa de protocolo não tinha defesa nenhuma contra replay `[protocolo]`

`Rfc9421Verifier` não exigia `created` nem `nonce` — a regex do `Signature-Input`
sequer os **permitia**. Uma assinatura que essa faixa emitiu autenticava para sempre:
quem a lesse num log, num proxy ou numa captura podia reenviá-la intacta na semana
seguinte. A faixa de autorização sempre exigiu os dois; esta não. Agora as duas
respondem igual, contra o mesmo relógio e a mesma memória de nonces do runtime, e o
verificador exige `clock` e `seen` como argumentos obrigatórios — uma defesa que se
pode desligar esquecendo um parâmetro acaba desligada na implantação que importava.
`tests/integration/api/test_protocol_lane_replay.py`

### G5 — revogação com escopo aplicava e reportava falha

`POST /mandates/{id}/revocations` julgava o resultado pelo **status do mandato**. Mas
uma revogação com escopo — cartão cancelado, orçamento congelado — deixa o mandato
`ACTIVE` de propósito: é o ponto inteiro dela. Toda revogação com escopo parecia então
um token apontado para outro mandato, e a rota devolvia `403 revocation_mandate_mismatch`
**depois de a revogação já estar comprometida**. A pior resposta possível: convida a
retentar o que já aconteceu. A rota agora compara o mandato que o *token* nomeia com o
da URL — que é a pergunta que ela sempre quis fazer. `tests/integration/api/test_protocol_revocation_scopes.py`

> **O padrão dos cinco.** Nenhum é um erro de digitação; todos são um teste que exercita
> o caminho honesto de uma funcionalidade e nunca o caminho torto ao lado. G1 e G4 são de
> segurança, G2, G3 e G5 quebram na frente do jurado. Vale como método: para cada garantia
> que o sistema anuncia, o teste tem que tentar **quebrá-la**, não confirmá-la.
