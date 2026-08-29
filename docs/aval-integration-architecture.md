# Arquitetura de Integração de Protocolos

## AVAL — Pagamento Agêntico com Mandato Verificável

**Projeto:** NextWave Hackathon 2026 — Desafio 01, *The Buyer Who Isn't Human*
**Repositório:** `pmendonca-dev/hackathon`
**Data:** 29 de agosto de 2026
**Escopo:** UCP, ACP, AP2 e x402 — como compor os quatro em um único sistema sem duplicação de responsabilidade, sem conflito de fonte de verdade e sem módulos isolados.

---

## 0. Sumário executivo

### 0.1 A recomendação em um parágrafo

Os quatro protocolos **não competem entre si dentro do AVAL**; eles ocupam planos distintos de uma mesma transação. A forma de integrá-los com alta coesão e sem conflito é **não implementar quatro integrações**. É implementar **um núcleo de domínio único** — o *Authorization Core* do AVAL — e expor cada protocolo como um **adaptador de borda** (encoder/decoder) sobre esse núcleo. Nenhum protocolo pode carregar estado próprio, política própria, contador próprio ou fonte de verdade própria. Todo protocolo é *representação*; o núcleo é *autoridade*.

### 0.2 O mapa de camadas

| Plano | Pergunta que responde | Protocolo dono | O que o AVAL implementa |
|---|---|---|---|
| Descoberta e identidade | *Quem é este agente e o que este negócio sabe fazer?* | **UCP** (`/.well-known/ucp`, RFC 9421) | Registry de merchants e plataformas; verificação de assinatura |
| Sessão de compra | *Qual é o carrinho, o total, o status?* | **UCP Checkout** (primário) / **ACP Checkout** (secundário) | Um único agregado `CheckoutIntent` canônico |
| Evidência e consentimento | *O humano autorizou exatamente isto?* | **AP2** (mandatos SD-JWT+KB, recibos) | Emissão, verificação e encadeamento; **não** a política viva |
| Instrumento de pagamento | *Como pagar sem expor o cartão ao agente?* | **ACP Delegate Payment** (`Allowance`) | Cofre de credenciais + emissão de token escopado |
| Liquidação | *O dinheiro se moveu?* | **PSP mock** (cartão) / **x402** (máquina-a-máquina) | Serviço de captura único com adaptadores plugáveis |
| **Autoridade viva** | *Isto ainda é permitido, agora?* | **Nenhum protocolo** | **Exclusivo do AVAL**: revogação, orçamento, locks, idempotência, ledger |
| **Commit point** | *Esta transação específica ainda pode ser retirada?* | **Nenhum protocolo** | **Exclusivo do AVAL**: transição atômica da reserva e prova de autorização (Seção 11) |

A última linha é a mais importante do documento. **Nenhum dos quatro protocolos implementa revogação em tempo real, orçamento vivo, prevenção de double-spend ou decisão de captura.** Todos os quatro são protocolos de *atestação estática*: provam que algo foi autorizado em um instante passado. O desafio 01 exige explicitamente revogação ao vivo e recusa de compra fora do mandato — portanto **a parte do sistema que os jurados vão testar no *trial by fire* é justamente a parte que nenhum protocolo entrega**. Esse é o núcleo do produto, e é onde o esforço de engenharia deve ir. A **Seção 11** especifica essa camada em detalhe: máquina de estados, commit point, autenticação da revogação, cache, falha fechada e threat model.

### 0.3 Nota terminológica sobre "RFX402"

A sigla **RFX402 não corresponde a nenhum protocolo de pagamento**. A busca por esse identificador retorna exclusivamente equipamentos de áudio (pedal Rolls RFX402) e placas de veículo. O protocolo pretendido é quase certamente o **x402**, padrão HTTP-nativo criado pela Coinbase que reativa o status `402 Payment Required`. A confusão provavelmente vem da leitura de "RFC x402" — x402 **não é uma RFC do IETF**; a especificação vive na x402 Foundation, formalizada sob a Linux Foundation em 2 de abril de 2026. Este documento trata x402 e dedica a ele a **Seção 8**, separada, conforme solicitado.

### 0.4 Veredito de viabilidade por protocolo, em 24 horas

| Protocolo | Viabilidade no prazo | Recomendação |
|---|---|---|
| **AP2** | Alta — SDK Python existe, já investigado pelo time | **Implementar de verdade.** É a resposta ao requisito "mandato verificável". |
| **UCP** | Alta — REST simples, discovery é um JSON estático | **Implementar como espinha dorsal.** É o único que hospeda AP2 nativamente e define `requires_escalation`. |
| **ACP** | Média-alta — apenas o `delegate_payment` é necessário | **Implementar parcialmente** (só o cofre/token). Checkout completo em ACP é redundante com UCP. |
| **x402** | Média — o risco é chain/facilitator, não o protocolo | **Implementar com facilitator mock**, em trilho isolado. Nunca no caminho do cartão. |

E uma quinta linha que não é protocolo nenhum:

| Componente | Viabilidade no prazo | Recomendação |
|---|---|---|
| **Camada de revogação AVAL** | Alta se local; média se registry externo | **Implementar primeiro e nunca cortar.** É o que o *trial by fire* testa e o que nenhum dos quatro protocolos entrega. Especificação na Seção 11. |

---

## 1. Contexto e restrições

### 1.1 Estado atual do repositório

O repositório contém hoje apenas documentação: `README.md`, regras do hackathon, decision log, o estudo de integração do AP2 e a skill de Flight Log em `.agents/`. **Não existe aplicação, API, banco, modelo de domínio, testes ou UI.** Toda a arquitetura descrita aqui é greenfield.

O documento `docs/ap2-aval-integration-decision.md` já estabeleceu decisões que este documento **respeita e estende**:

- AP2 é camada de protocolo criptográfico, não arquitetura de produto.
- O modelo OpenAI fica restrito à conversa e a solicitações de ferramentas tipadas; nunca recebe chaves nem autoridade.
- Revogação, orçamento, double-spend, captura e ledger são código determinístico do AVAL.
- AP2 é fixado no commit `e1ea56d`; `main` é mutável e removeu o lockfile.
- Nada de Gemini, ADK, A2A, MCP ou Web3 vindo dos samples do AP2.

Este documento **acrescenta** três protocolos ao redor daquele núcleo e resolve as sobreposições resultantes.

### 1.2 Restrições duras do evento

| Restrição | Consequência arquitetural |
|---|---|
| Code freeze em T+24:00 (dom. 30/08, 12:30) | Cada protocolo precisa de uma "linha de corte" definida *antes* de começar. |
| *Trial by fire*: jurados alteram entradas/regras sem ensaio | Toda regra precisa ser **dado configurável em runtime**, nunca constante compilada. |
| Sistema deve reagir sem intervenção manual | Nada de reiniciar serviço para aplicar mudança de limite ou revogação. |
| Critério nº 1 é "Funciona?" | Protocolo pela metade que quebra a demo vale menos que zero. |
| Critério nº 2 é "Profundidade e julgamento" | Saber *por que* x402 fica fora do caminho do cartão pontua mais que implementá-lo mal. |
| "Quantidade de integrações não pontua por si só" | Quatro protocolos mal costurados **perdem** pontos. A costura é a tese. |

### 1.3 Os seis comportamentos obrigatórios do desafio

O sistema deve tratar explicitamente: **(1)** compra fora do mandato, **(2)** mandato expirado, **(3)** revogação em tempo real, **(4)** agente impostor, **(5)** disputa posterior, **(6)** trilha de auditoria legível para humano, merchant e auditor. A Seção 7 mapeia cada um a um mecanismo protocolar concreto.

---

## 2. O que cada protocolo é, de fato

### 2.1 Quadro comparativo

| | **UCP** | **ACP** | **AP2** | **x402** |
|---|---|---|---|---|
| Nome | Universal Commerce Protocol | Agentic Commerce Protocol | Agent Payments Protocol | x402 |
| Origem | Google + Shopify (co-desenvolvido com Etsy, Wayfair, Target, Walmart, Amazon, Microsoft, Meta, Salesforce, Stripe) | OpenAI + Stripe | Google | Coinbase + Cloudflare |
| Governança | Open source, Apache-2.0, comunidade UCP | Processo SEP no repositório ACP | Doado à **FIDO Alliance** em 28/04/2026 | **x402 Foundation** sob Linux Foundation desde 02/04/2026 |
| Versão corrente | `2026-08-25` | `2026-04-17` (estável) | v0.2 | v2 |
| Escopo | Ciclo completo de comércio: catálogo, carrinho, checkout, pedido, pós-venda, identity linking | Checkout agêntico, feed, cart, delegate payment, delegate authentication | Consentimento e evidência de pagamento | Pagamento por requisição HTTP |
| Unidade central | `Checkout Session` + capacidades negociadas | `checkout_session` + `Allowance` | `Mandate` (VDC) + `Receipt` | `PaymentRequired` / `PaymentPayload` |
| Transportes | REST, MCP, A2A, Embedded | REST, MCP | Agnóstico (integra a UCP) | HTTP, MCP, A2A |
| Criptografia | RFC 9421 (HTTP Message Signatures), ES256 | HMAC (`Signature` + `Timestamp`), Bearer | SD-JWT / KB-SD-JWT, JWS destacado, JCS | EIP-712 / EIP-3009, Permit2 |
| Liquidação | Delegada a *payment handlers* | Delegada ao PSP do merchant | Fora de escopo (é evidência) | On-chain, stablecoin |
| Tem revogação? | **Não** | **Não** | **Não** | **Não** (o `nonce` impede reuso, não retira autoridade) |
| Tem orçamento vivo? | Não | `Allowance.max_amount` (estático, one-time) | Constraints estáticas no mandato | `upto` (máximo por autorização) |

### 2.2 UCP — a espinha dorsal

UCP resolve o gargalo N×N: em vez de cada negócio integrar com cada superfície de IA, o negócio publica um manifesto em `/.well-known/ucp` declarando *serviços* e *capacidades*, e qualquer agente que fale o protocolo descobre e negocia dinamicamente.

Três características tornam o UCP a escolha natural para espinha dorsal do AVAL:

**a) Negociação de capacidades.** A capacidade só está ativa se aparecer na *interseção* entre o perfil do negócio e o perfil da plataforma. Isso dá ao AVAL um mecanismo declarativo, verificável e demonstrável para ligar/desligar comportamento sem recompilar — exatamente o que o *trial by fire* exige.

**b) `requires_escalation` é nativo.** O enum de status do checkout UCP inclui `requires_escalation`, e a especificação obriga o campo `continue_url` quando esse status é usado. O desafio 01 exige que "tentativa fora do mandato seja recusada **ou escalada para aprovação humana**, nunca aprovada silenciosamente". O UCP já modela esse caminho no protocolo — não é gambiarra do time, é conformidade.

**c) Assinaturas de mensagem resolvem "agente impostor".** UCP usa RFC 9421 sobre `@method`, `@authority`, `@path`, `ucp-agent`, `idempotency-key`, `content-digest` e `content-type`, com chave pública descoberta via `signing_keys[]` no perfil do assinante. Isso protege contra impersonação, adulteração, replay e confusão de método/endpoint — os quatro vetores que um "agente impostor" usaria.

**Extensão AP2 Mandates.** O UCP define oficialmente a extensão `dev.ucp.common.payment.ap2_mandate`. Quando negociada, a sessão fica *security locked*: nenhuma das partes pode voltar ao fluxo desprotegido. O negócio **deve** embutir `ap2.merchant_authorization` em toda resposta de checkout, e **não pode** aceitar `complete_checkout` sem `ap2.checkout_mandate`. **Este é o ponto de solda entre UCP e AP2, e ele é normativo — não precisamos inventá-lo.**

### 2.3 ACP — o cofre e o token

ACP é o padrão de checkout agêntico mantido por OpenAI e Stripe. Nota de realidade importante para a defesa técnica: o **Instant Checkout do ChatGPT, superfície de lançamento do ACP, foi descontinuado em março de 2026** após poucos merchants integrarem; o protocolo, porém, seguiu evoluindo, com a versão estável `2026-04-17` cobrindo checkout, cart, feed, orders, delegate payment, delegate authentication e binding MCP.

Para o AVAL, a peça verdadeiramente valiosa do ACP é o **Delegate Payment**, e especificamente o objeto `Allowance`:

```json
{
  "reason": "one_time",
  "max_amount": 100000,
  "currency": "usd",
  "checkout_session_id": "csn_01HV3P3XYZ789",
  "merchant_id": "merchant_12345",
  "expires_at": "2026-02-15T18:30:00Z"
}
```

O agente envia a credencial ao cofre (endpoint `POST /agentic_commerce/delegate_payment`) e recebe de volta apenas um identificador de token (`vt_...`). **O agente nunca porta o PAN.** O token nasce amarrado a valor máximo, moeda, sessão de checkout, merchant e prazo. Isso atende diretamente ao requisito do desafio: "definir meio de pagamento sem expor o cartão bruto ao agente".

O ACP também oferece uma disciplina de idempotência mais rica que a do UCP, que vale copiar: `Idempotency-Key` obrigatório em todo POST, header de resposta `Idempotent-Replayed: true` em replays, e três códigos distintos — `400` quando a chave falta, `409` quando há requisição em voo com a mesma chave, `422` quando a mesma chave chega com corpo diferente. Essa tripla é o que impede double-spend por retry.

### 2.4 AP2 — a evidência

AP2 fornece **Verifiable Digital Credentials** que provam consentimento. Na v0.2 os mandatos existem em dois estados:

- **Checkout Mandate** — *aberto*: as restrições que o usuário aceita (merchants permitidos, itens, teto). *Fechado*: autorização de um checkout específico, contendo `checkout_hash`, o hash base64url do `checkout_jwt` assinado pelo merchant.
- **Payment Mandate** — *aberto*: restrições de pagamento (`payment.allowed_payees`, instrumentos permitidos, `payment.execution_date` com `not_before`/`not_after`). *Fechado*: autorização de um valor específico ligado ao checkout finalizado. Os `vct` são `mandate.payment.open.1` e `mandate.payment.1`.

Os dois modos de operação mapeiam perfeitamente o desafio:

- **Human Present:** o usuário aprova diretamente os mandatos fechados. É a "compra ponta a ponta autorizada" da demo.
- **Human Not Present:** o usuário aprova apenas os mandatos **abertos** com constraints; o agente monta e assina os fechados sozinho, dentro daqueles limites. **Este é literalmente o desafio 01.**

E há um detalhe de ouro: um fluxo Human Not Present pode ser convertido em Human Present quando o merchant (ou Credential Provider) devolve o erro **`unresolved_constraint`**, trazendo o usuário de volta ao loop. Combinado com o `requires_escalation` do UCP, isso dá ao AVAL um **caminho de escalonamento humano que é conformidade protocolar em duas camadas**, não invenção.

Ao final, AP2 emite **Checkout Receipt** (assinado pelo merchant) e **Payment Receipt** (assinado pelo processador). Encadeados, formam a trilha não-repudiável que responde à disputa.

### 2.5 x402 — o trilho de máquina

Tratado integralmente na **Seção 8**.

---

## 3. O princípio: por que não há conflito

### 3.1 Regra de ouro

> **Protocolo é representação. O núcleo é autoridade. Nenhum protocolo mantém estado.**

E o corolário que governa a Seção 11:

> **Nenhum componente fora do `AuthorizationCore` decide revogação, e nenhum trilho de liquidação é acionado sem passar pelo commit point.**

Toda vez que um protocolo parece "querer" guardar estado — a sessão de checkout do UCP, o `Allowance` do ACP, as constraints do AP2, o nonce do x402 — esse estado é **projeção** de uma entidade do núcleo, gerada sob demanda e descartável. Se o dado só existe dentro do protocolo, é bug.

### 3.2 O teste de conflito

Antes de escrever qualquer adaptador, aplique esta pergunta:

> *"Se dois protocolos discordarem sobre este valor, quem vence?"*

Se a resposta não for **"o núcleo, sempre"**, o desenho está errado. Se a resposta for "depende", há um conflito latente que vai aparecer no *trial by fire*.

### 3.3 Diagrama de responsabilidade

```
   Humano                                          Auditor
     |                                                |
     v                                                v
 +---------------------------------------------------------------+
 |            UI AVAL  (visão humano / merchant / auditor)        |
 +---------------------------------------------------------------+
     |                                                ^
     v                                                |
 +-----------------+                          +-------------------+
 | Shopping Agent  |   solicitação NÃO        |  Audit Ledger     |
 | (OpenAI)        |-- confiável ----+        |  (append-only)    |
 +-----------------+                 |        +-------------------+
                                     v                 ^
 +---------------------------------------------------------------+
 |          TOOL GATEWAY DETERMINÍSTICO  (fronteira de confiança) |
 |   ler catálogo | montar rascunho | submeter request_id         |
 +---------------------------------------------------------------+
                                     |
                                     v
 +===============================================================+
 |             AVAL AUTHORIZATION CORE   (autoridade)            |
 |  MandateStore · PolicyEngine · RevocationRegistry · Budget-   |
 |  Ledger · ReservationLock · IdempotencyStore · CaptureService |
 +===============================================================+
     |            |               |                     |
     v            v               v                     |
 +---------+ +---------+ +----------------+             |
 | UCP     | | AP2     | | ACP Delegate   |             |
 | Adapter | | Adapter | | Payment (cofre)|             |
 | REST +  | | SD-JWT  | | Allowance ->   |             |
 | RFC9421 | | +KB,JWS | | token vt_...   |             |
 +---------+ +---------+ +----------------+             |
     |            |               |                     |
     v            v               v                     v
   Merchant mock  ·  cofre  ·  agente         +=====================+
                                              |    COMMIT POINT     |
   Revogação do usuário ---------------------->  Reservation:       |
   (chega a qualquer instante)                |  PENDING -> COMMIT  |
                                              |  transacional, único|
                                              +==========+==========+
                                                         |
                                        depois daqui a revogação NÃO
                                        afeta esta transação
                                                         |
                                                         v
                                              +---------------------+
                                              | Settlement Adapters |
                                              |  +-- PSP mock       |
                                              |  +-- x402 (isolado) |
                                              +----------+----------+
                                                         |
                                                         v
                                          PSP mock  ·  x402 facilitator mock
```

O commit point é **um só** e fica na fronteira do `SettlementAdapter`, não "imediatamente antes da Mastercard". A distinção importa: se o commit point fosse definido pela rede de cartões, o trilho x402 da Seção 8 sairia de baixo da revogação e um mandato revogado ainda pagaria micropagamentos. Detalhamento em 11.1.

### 3.4 O que cada adaptador pode e não pode fazer

| Adaptador | **Pode** | **Nunca pode** |
|---|---|---|
| UCP | Serializar `CheckoutIntent`, verificar/gerar assinaturas RFC 9421, publicar discovery | Decidir se a compra é permitida; guardar totais próprios |
| AP2 | Emitir/verificar SD-JWT, computar `checkout_hash`, montar recibos | Ser a única checagem de limite; expirar mandato por conta própria |
| ACP | Tokenizar credencial, emitir `Allowance` derivada, replicar idempotência | Definir `max_amount` a partir de qualquer coisa que não seja o mandato vivo |
| x402 | Formar/verificar `PaymentPayload`, chamar facilitator | Aparecer no caminho do cartão; criar reserva de orçamento própria |
| **Todos** | Ler o status de revogação para exibição | **Consultar revogação por fora do commit point; ser acionado sem uma `Reservation` já em `COMMITTED`** |

---

## 4. Mapa de sobreposições e regras de resolução

Esta é a seção operacional do documento. Cada linha é um conflito **real** que emerge ao combinar os quatro protocolos, com a regra que o elimina.

### C1 — Duas sessões de checkout

**Conflito.** UCP tem `Checkout Session` com `id`, `line_items`, `totals`, `status`. ACP tem `checkout_session` com estrutura análoga mas enum de status diferente. Implementar os dois cria duas fontes de verdade para o mesmo carrinho.

**Resolução.** Um agregado interno `CheckoutIntent` com identificador próprio `chi_*`. UCP e ACP são *projeções somente-de-saída*. Nenhum adaptador escreve direto no banco; ambos chamam o mesmo serviço de aplicação. Se o time ficar sem tempo, **corte o ACP checkout inteiro** — ele é redundante; o `delegate_payment` não é.

**Mapeamento de status (obrigatório, tabela única no código):**

| Interno AVAL | UCP | ACP |
|---|---|---|
| `DRAFT` | `incomplete` | `incomplete` / `not_ready_for_payment` |
| `AWAITING_HUMAN` | `requires_escalation` (+ `continue_url`) | `requires_escalation` / `pending_approval` |
| `AUTHORIZED` | `ready_for_complete` | `ready_for_payment` |
| `CAPTURING` | `complete_in_progress` | `complete_in_progress` |
| `SETTLED` | `completed` | `completed` |
| `REJECTED` | `canceled` | `canceled` |
| `EXPIRED` | `canceled` + mensagem | `expired` |

> **Armadilha:** ACP tem `expired` e `authentication_required`; UCP não tem nenhum dos dois. Nunca faça o mapeamento por string. Use um enum interno e uma função total de conversão que falha ruidosamente em valor não mapeado.

### C2 — Três lugares que "seguram" limite de gasto

**Conflito.** AP2 tem constraints estáticas no mandato aberto. ACP tem `Allowance.max_amount`. O AVAL tem o orçamento vivo. Se os três forem consultados independentemente, uma mudança de limite feita pelo jurado durante a demo será respeitada por um e ignorada pelos outros.

**Resolução.** **Hierarquia estrita, avaliada sempre nesta ordem:**

1. `RevocationList` — revogado? Rejeita. Nada mais é avaliado.
2. `MandateStore` — mandato válido e não expirado *no relógio do servidor*?
3. `PolicyEngine` — política **viva** do AVAL (limites atuais, categorias, recorrência).
4. Constraints AP2 — verificação criptográfica de que o mandato apresentado é coerente.
5. `Allowance` ACP — **derivada**, calculada como `min(saldo_vivo, teto_do_mandato, total_do_checkout)` no instante da tokenização.

O passo 5 nunca lê configuração; ele lê o resultado dos passos 1-3. **`Allowance.max_amount` é uma função, não um campo.**

### C3 — Três esquemas de assinatura

**Conflito.** UCP exige RFC 9421 com ECDSA P-256. ACP usa HMAC no header `Signature` mais `Timestamp`. AP2 usa SD-JWT com key binding e JWS destacado. x402 usa EIP-712. Quatro criptografias, risco de quatro custódias de chave.

**Resolução.** Um único `KeyCustodyService` no servidor com um registro de chaves por papel (`aval-platform`, `merchant-mock`, `psp-mock`, `agent-<id>`). Os adaptadores pedem *operações* ("assine estes bytes com a chave X"), nunca material de chave. Uma `AgentIdentity` no núcleo, quatro codificações na borda.

> **Nota da especificação UCP:** há um debate registrado (AP2 issue #268) sobre o requisito de algoritmo. Sob a leitura por entropia, o Checkout JWT pode ser assinado com qualquer algoritmo, permitindo que **uma única chave sirva tanto para o mandato AP2 quanto para Web Bot Auth**. Para o hackathon, fique com **ES256 em tudo** — é o mínimo obrigatório do UCP e evita a discussão.

### C4 — Duas idempotências e um nonce

**Conflito.** UCP inclui `idempotency-key` nos componentes assinados. ACP exige `Idempotency-Key` em todo POST com semântica 400/409/422. x402 usa `nonce` de 32 bytes na autorização EIP-3009. Três mecanismos de "não execute duas vezes".

**Resolução.** Uma tabela `idempotency` única, chave composta `(surface, key_value)` → `request_id` canônico + resposta serializada. Os adaptadores traduzem para o vocabulário do seu protocolo. O nonce do x402 é registrado na **mesma** tabela como `(x402, nonce)`. Prazo mínimo de retenção: 24h (recomendação UCP), 48h ideal. **Em falha de escrita na tabela, falhe fechado com 503** — nunca deixe passar.

### C5 — "Quem confirma que o dinheiro se moveu"

**Conflito.** ACP entrega um token para o PSP cobrar. AP2 emite Payment Mandate que o processador verifica. x402 devolve `SettleResponse` com hash de transação. Se cada um puder declarar sucesso, o ledger fica inconsistente.

**Resolução.** Um `CaptureService` único, com interface `SettlementAdapter { authorize(reservation) -> SettlementResult }`. O ledger **reserva antes** de chamar qualquer adaptador e concilia depois. Nenhum adaptador escreve no ledger; ele devolve um resultado e o `CaptureService` decide. Adaptadores: `MockCardPSP` e `X402Facilitator`.

### C6 — Três formatos de recibo

**Conflito.** AP2 tem Checkout Receipt e Payment Receipt. UCP tem o objeto `Order` com `fulfillment`, `adjustments`, `totals`. ACP tem webhooks de pedido.

**Resolução.** Um log `AuditEvent` append-only é a verdade. Recibos e objetos `Order` são **renderizações** desse log, geradas sob demanda. O `AuditEvent` carrega o hash do artefato criptográfico correspondente, de modo que a trilha legível e a trilha verificável apontem uma para a outra.

### C7 — Unidades monetárias incompatíveis

**Conflito, e este é sério.**

| Protocolo | Representação |
|---|---|
| UCP | inteiro em menor unidade; `currency` ISO 4217 (exemplos em maiúscula: `USD`) |
| ACP | inteiro em menor unidade; `currency` com padrão **`^[a-z]{3}$`** — *minúscula obrigatória* |
| AP2 | valor no payload do mandato |
| x402 | **string** em unidades atômicas do token; `asset` é endereço de contrato ou código ISO |

Somar `3500` (centavos) com `"10000"` (6 casas do USDC) é um bug de produção esperando acontecer.

**Resolução.** Um value object `Money { amount: int, currency: str, scale: int }` no núcleo. Normalização **na borda**, com conversão explícita e testes de round-trip. O adaptador ACP faz `.lower()`; o UCP faz `.upper()`; o x402 converte escala e serializa como string. **Nunca** use float. **Nunca** deixe uma string de valor entrar no núcleo.

### C8 — Revogação: o buraco comum

**Conflito.** Nenhum dos quatro protocolos define revogação. O desafio exige revogação ao vivo, e é o teste mais provável do *trial by fire*.

**Resolução.** `RevocationRegistry` no AVAL é consultado **em toda decisão**, inclusive na revalidação dentro da transação de captura. O mandato AP2 continua criptograficamente válido depois de revogado — isso é esperado e correto; a assinatura atesta o passado. O AVAL responde com um erro de política, não de criptografia. Para o UCP, o código de erro mais próximo é `mandate_scope_mismatch`; emitimos `aval.mandate_revoked` no corpo e mapeamos para HTTP 403, documentando a extensão.

Como a revogação é o produto e não um detalhe, ela tem **seção própria**: a Seção 11 especifica posição no fluxo, máquina de estados, onde a referência de revogação vive no mandato, quem pode revogar, cache, falha fechada, prova de autorização e threat model. As linhas C11 a C14 abaixo registram apenas os *conflitos* que a camada de revogação cria com os quatro protocolos; a resolução completa está na Seção 11.

> **Ponto de defesa técnica:** quando um jurado perguntar "por que a revogação não está no protocolo?", a resposta é que os quatro protocolos são de **atestação**, não de **autorização contínua**. Um mandato assinado é como um cheque assinado: continua autêntico depois de sustado. O sustamento vive no banco, não no cheque. O AVAL é o banco.

### C9 — Relógios e janelas de validade

**Conflito.** O SDK AP2 usa tolerância padrão de **300 segundos** de desvio de relógio. UCP define TTL padrão de checkout de **6 horas**. ACP tem `Allowance.expires_at`. x402 tem `validAfter`/`validBefore` e `maxTimeoutSeconds`. Quatro janelas independentes.

**Resolução.** Um `ClockService` injetável (permite testar expiração sem esperar). Skew explícito e **reduzido para 5 segundos** na configuração AVAL — 300s é largo demais para uma demo em que o jurado vai expirar um mandato ao vivo. Toda validade é derivada do mandato, não do protocolo. E: **valide expiração na captura, não só na autorização.**

### C10 — Descoberta e confiança de perfil

**Conflito.** UCP resolve a chave do assinante buscando `/.well-known/ucp` do perfil declarado no header `UCP-Agent`. Isso é uma requisição de rede síncrona no caminho crítico e um vetor de SSRF.

**Resolução.** Registry local pré-carregado no AVAL, com fetch remoto **desabilitado** na demo. UCP prevê exatamente esse modo com o erro `profile_not_trusted` (403) para perfis fora do registro de plataformas pré-aprovadas. Isso é conformidade *e* é como se demonstra "agente impostor": um agente com perfil desconhecido leva 403 antes mesmo da verificação de assinatura.

### C11 — Onde fica o commit point

**Conflito.** É tentador posicionar o gate de autorização "imediatamente antes da rede de pagamento" — é o desenho mais intuitivo e o que um processador faria. Mas nesse ponto a sessão de checkout UCP já passou por `complete_in_progress`, e o único desfecho possível é aceitar ou rejeitar. O comportamento obrigatório nº 1 do desafio exige **recusar *ou escalar para aprovação humana***, e o escalonamento (`requires_escalation` + `continue_url` no UCP, `unresolved_constraint` no AP2) só existe enquanto a sessão está viva. Um gate posicionado no fim do fluxo perde metade do requisito.

**Resolução.** **Dois pontos de decisão, um commit point.**

| | Ponto de autorização | Commit point |
|---|---|---|
| Quando | Passo 8, com a sessão de checkout aberta | Passo 11, dentro da transação de captura |
| Desfechos | `AUTHORIZED` · `AWAITING_HUMAN` · `REJECTED` | `COMMITTED` · `REJECTED` |
| Pode escalar? | **Sim** | Não |
| Efeito da revogação | Bloqueia e pode escalar | Bloqueia |
| Onde fica | `AuthorizationCore.evaluate()` | Fronteira do `SettlementAdapter` |

O commit point **não** é definido pela rede de cartões; é definido pela fronteira do `SettlementAdapter`. Assim o trilho x402 recebe exatamente a mesma disciplina que o cartão.

### C12 — Duas máquinas de estado para "consumido"

**Conflito.** Uma leitura natural da revogação modela o mandato como `ACTIVE → COMMITTED | REVOKED`. Isso é incompatível com o `BudgetLedger`: um mandato aberto com teto de R$ 800 pode originar várias compras, e não "se consome" na primeira. Se o código ganhar uma transição `COMMITTED` no mandato *e* um ciclo de vida na reserva, haverá duas máquinas de estado para a mesma pergunta e elas vão divergir sob concorrência.

**Resolução.** A transição atômica pertence à **`Reservation`**, nunca ao `Mandate`.

| Entidade | Estados | Propriedade |
|---|---|---|
| `Mandate` | `ACTIVE → REVOKED` · `ACTIVE → EXPIRED` | Monótono, irreversível, **não** tem `COMMITTED` |
| `Reservation` | `PENDING → COMMITTED → SETTLED` · `PENDING/COMMITTED → RELEASED` | Uma por transação; é aqui que a corrida é decidida |

A corrida "revogação versus compra" é resolvida porque **as duas escritas disputam o mesmo lock de `mandate_id`**, não porque o mandato tenha um estado de commit. Ver 11.2.

### C13 — Onde a referência de revogação vive no mandato

**Conflito.** Colocar `revocation_id`, `revocation_authority` ou `revocation_commitment` dentro do payload tipado do AP2 colide com três decisões já tomadas: extensões AVAL vivem no namespace `aval.*` **fora** dos schemas AP2 (Passo 1); a canonicalização JCS cobre o JSON **completo** e a verificação proíbe remover membros não reconhecidos (Passo 7); e os parsers tipados do AP2 são estritos quanto ao formato da cadeia (Passo 9).

**Resolução.** A referência vai como claim de namespace `aval.revocation` no mandato **aberto**, coberta pela assinatura e nunca removida antes de verificar, com cópia autoritativa no `Mandate` do AVAL e binding por hash. Esquema em 11.3.

### C14 — Fail-closed versus a válvula de escape de assinatura

**Conflito.** A Seção 9.3 prevê um flag `SIGNATURE_ENFORCEMENT=warn` para desbloquear desenvolvimento. Por simetria, alguém vai propor `REVOCATION_ENFORCEMENT=warn` às quatro da manhã.

**Resolução.** **A revogação não tem modo warn, em nenhum ambiente.** Indisponibilidade do armazenamento de revogação resulta em `503 revocation_unavailable`, igual à invariante 5 da Seção 10.1 para idempotência. Detalhamento em 11.7.


---

## 5. Modelo de domínio canônico

### 5.1 Entidades do núcleo

| Entidade | Responsabilidade | Nunca faz |
|---|---|---|
| `Money` | Valor + moeda + escala | Aritmética com float |
| `Principal` | Humano ou empresa que delega | Assinar (quem assina é o KeyCustody) |
| `AgentIdentity` | Identidade do agente, **separada** da humana; chave pública, perfil, status | Ser inferida do conteúdo da requisição |
| `Mandate` | Autoridade delegada: escopo, limites, validade, instrumento, versão de política | Ser mutável (mudanças criam nova versão) |
| `Revocation` | Fato de revogação assinado: `mandate_id`, escopo, autor, motivo, `revoked_at`, `epoch` | Ser reversível; ser aceita sem assinatura verificada |
| `RevocationAuthority` | Quem pode revogar um mandato: chave pública, papel, escopo permitido | Ser inferida da requisição |
| `CheckoutIntent` | Carrinho canônico + total + status + merchant + mandato de referência | Existir sem mandato associado |
| `Reservation` | Consumo *atômico* de orçamento com lock; é ela que transita `PENDING → COMMITTED` | Ser criada fora de transação; ser criada sem releitura de revogação |
| `CaptureAttempt` | Tentativa idempotente de liquidação | Executar duas vezes com a mesma chave |
| `Evidence` | Blob criptográfico (mandato, JWS, recibo) + hash + origem | Ser interpretado como política |
| `AuthorizationProof` | Prova curta, de uso único, emitida **após** a reserva entrar em `COMMITTED` | Ser emitida antes do commit; ser reutilizada |
| `AuditEvent` | Registro append-only, legível, com referência ao `Evidence` | Ser editado ou deletado |

### 5.2 Tabela de projeção — um campo, quatro nomes

Esta tabela vira código (o arquivo de mapeamento) e vira slide (é a prova visual de que a integração é única).

| Campo canônico | UCP | ACP | AP2 | x402 |
|---|---|---|---|---|
| `checkout.id` | `id` | `checkout_session_id` | dentro do `checkout_jwt` | `resource.url` (referência) |
| `checkout.total` | `totals[type=total].amount` | `totals` / `total` | valor no mandato fechado | `accepts[].amount` (string atômica) |
| `checkout.currency` | `currency` (ISO, maiúscula) | `currency` (minúscula) | payload do mandato | `asset` + rede CAIP-2 |
| `checkout.status` | `status` (6 valores) | `status` (10 valores) | — | — |
| `agent.identity` | `UCP-Agent: profile="…"` | Bearer + `User-Agent` | `cnf` / key binding | `payload.authorization.from` |
| `agent.signature` | `Signature` + `Signature-Input` | `Signature` + `Timestamp` (HMAC) | assinatura SD-JWT+KB | `payload.signature` (EIP-712) |
| `mandate.limit` | — | `Allowance.max_amount` | constraint no mandato aberto | `amount` (scheme `upto` = teto) |
| `mandate.expiry` | `expires_at` do checkout | `Allowance.expires_at` | `exp` / `payment.execution_date` | `validBefore` / `deadline` |
| `mandate.merchant_scope` | perfil do negócio | `Allowance.merchant_id` | `payment.allowed_payees` | `payTo` (binding de destinatário) |
| `idempotency` | `Idempotency-Key` (assinado) | `Idempotency-Key` (obrigatório) | — | `nonce` (32 bytes) |
| `mandate.revocation_ref` | `aval.revocation` (extensão documentada) | — | claim `aval.revocation` no mandato aberto | — (herda do mandato) |
| `mandate.revocation_status` | `aval.mandate_revoked` (403) | erro de tokenização | — (fora do escopo do protocolo) | recusa antes de `PAYMENT-SIGNATURE` |
| `merchant_proof` | `ap2.merchant_authorization` | — | `checkout_jwt` + `checkout_hash` | — |
| `settlement_proof` | — | resposta do PSP | Payment Receipt | `transaction` (hash on-chain) |

### 5.3 A regra de escrita

Só o `AuthorizationCore` escreve. Adaptadores leem do núcleo e escrevem **na rede**. Concretamente: nenhum arquivo em `adapters/` importa a sessão do banco.

---

## 6. Fluxo integrado, passo a passo

Cada passo traz: **quem faz**, **artefato**, **validações**, **o que pode dar errado**, **como detectar** e **plano B para a demo**.

### Passo 1 — Criação do mandato pelo humano

**Quem:** UI AVAL → `MandateService`. Sem participação do LLM.
**Artefato:** `Mandate` no banco + **AP2 open Checkout Mandate** e **open Payment Mandate** (SD-JWT), assinados pelo `KeyCustodyService` com a chave da plataforma, contendo o claim `aval.revocation` (ver 11.3) e uma `RevocationAuthority` registrada.
**Validações:** escopo não-vazio; teto > 0; validade futura; instrumento existente no cofre; **pelo menos uma autoridade de revogação registrada e verificável** — mandato sem caminho de revogação não é emitido.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| API privada do `sd-jwt` 0.10.4 quebra | **Alta** | Teste de emissão no primeiro commit | Envolver atrás de `MandateSigner`; fallback: JWS simples com claims equivalentes |
| `mandate.py` do AP2 escreve em `.logs/mandate_operations.log` | Alta | `strace`/inspeção | Já mapeado no doc do time: isolar esse efeito colateral no vendor |
| Constraints AP2 não expressam "categoria" ou "recorrência" | Média | Modelagem | Usar namespace `aval.*` **fora** dos schemas AP2, como já decidido |
| Claim `aval.revocation` quebra parser tipado do AP2 | Média | Teste de round-trip do mandato aberto | Claim em namespace, coberto pela assinatura, nunca removido antes de verificar (C13) |
| Mandato emitido sem autoridade de revogação → não é revogável no *trial by fire* | **Alta** | Validação de emissão | Bloquear emissão; teste que espera erro |

> **Decisão:** emitir mandatos **abertos** com constraints e deixar o AVAL assinar os fechados por delegação. É o modo *Human Not Present* do AP2 e é exatamente o desafio.

---

### Passo 2 — Registro do instrumento no cofre (ACP)

**Quem:** UI AVAL → `VaultService`, formato ACP `delegate_payment`.
**Artefato:** token `vt_*` + `Allowance` derivada.
**Validações:** `Allowance.max_amount = min(saldo_vivo, teto_mandato, total)`; `merchant_id` do escopo; `expires_at ≤ expiração do mandato`.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| Time confunde `Allowance` com a política e passa a lê-la como verdade | **Alta** | Code review; teste C2 | Nomear o campo `derived_allowance`; comentário no schema |
| `reason` só aceita `one_time` na spec — mandatos recorrentes não cabem | Alta (certeza) | Leitura da spec | Recorrência vive no `Mandate` do AVAL; cada compra emite novo token one-time |
| Dados de cartão reais entram no repositório | Média | Scan de segredos | **Só PAN de teste** (`4242…`); nunca PAN real em qualquer ambiente |

---

### Passo 3 — Descoberta UCP

**Quem:** Agente → `GET /.well-known/ucp` do merchant mock.
**Artefato:** manifesto com `services`, `capabilities` (incluindo `dev.ucp.shopping.checkout` e `dev.ucp.common.payment.ap2_mandate`), `payment_handlers` e `signing_keys[]`.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| **Formato do manifesto mudou entre versões UCP** | **Alta** | Comparar exemplo do blog (`2026-01-11`, `capabilities` como *array*, `payment.handlers`) com a spec `2026-08-25` (`capabilities` como *objeto*, `payment_handlers`) | Fixar **uma** versão no `ucp.version` e não misturar exemplos de datas diferentes |
| Fetch remoto de perfil vira SSRF / trava a demo sem rede | Média | Teste offline | Registry local; `profile_not_trusted` para o resto; **desligar fetch remoto** |
| Interseção de capacidades vazia por typo no nome reverso-domínio | Média | Teste de negociação | Constantes centralizadas; teste que falha se a interseção for vazia |

---

### Passo 4 — Verificação de identidade do agente

**Quem:** Merchant mock verifica assinatura RFC 9421 da requisição do agente.
**Validações:** perfil no registry → `key_not_found` / `profile_not_trusted`; `Content-Digest` sobre bytes crus; componentes assinados presentes.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| **Assinatura ECDSA em DER em vez de `r\|\|s` cru** | **Muito alta** | Teste de vetor conhecido | A própria spec avisa: OpenSSL/Java/.NET usam DER por padrão. Converter para 64 bytes (P-256). **Escrever este teste primeiro.** |
| **Framework re-serializa o JSON e quebra o `Content-Digest`** | **Muito alta** | Teste com corpo contendo unicode e chaves fora de ordem | Ler `await request.body()` **cru**; assinar/verificar sobre esses bytes; nunca sobre o modelo Pydantic re-serializado |
| Proxy/ngrok altera o corpo | Média | Teste ponta a ponta pela URL pública | A spec proíbe re-serialização por intermediários. Rodar demo em rede local, ou proxy passthrough |
| Header `UCP-Agent` mal parseado (é RFC 8941 Dictionary, não string simples) | Média | Teste unitário | Parser dedicado; rejeitar não-HTTPS |

> **Este passo é a defesa contra "agente impostor" e é o mais fácil de errar.** Reserve o primeiro bloco de implementação criptográfica para ele.

---

### Passo 5 — Descoberta e rascunho (LLM)

**Quem:** Shopping Agent (OpenAI) via tool gateway determinístico.
**Regra:** o modelo só pode ler catálogo, montar rascunho e submeter um `request_id` **criado pelo servidor**. Preço, merchant, itens e mandatos são recuperados pelo backend, nunca aceitos do modelo.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| Modelo alucina preço ou ID de produto | Alta | Validação no gateway | Backend re-resolve todo ID; divergência = rejeição |
| **Prompt injection via descrição de produto no catálogo** | Média-alta | Teste com item malicioso plantado | Tratar catálogo como dado não confiável; o gateway não executa instruções vindas de conteúdo. *Isto é o bônus de "agente adversarial" — plante o item e demonstre.* |
| Latência do modelo estoura o tempo da demo | Média | Ensaio cronometrado | Caminho de fallback com agente scriptado; a autoridade não depende do LLM |

---

### Passo 6 — Criação da sessão de checkout (UCP)

**Quem:** Agente → merchant mock, `POST /checkout-sessions`.
**Artefato:** `CheckoutIntent` → resposta UCP com `status`, `totals`, `links`, `expires_at`.
**Ativação AP2:** a extensão entra na interseção; a sessão fica *security locked*.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| `links[]` é obrigatório (compliance legal) e é esquecido | Alta | Validação de schema | Preencher com política de privacidade/TOS fake do merchant mock |
| Sessão expira no meio da demo (TTL padrão 6h) | Baixa | — | Definir `expires_at` explicitamente |
| Time implementa ACP checkout em paralelo e diverge | Média | Revisão | **Corte:** ACP checkout não entra. Só `delegate_payment`. |

---

### Passo 7 — Assinatura do merchant (`merchant_authorization`)

**Quem:** Merchant mock.
**Artefato:** JWS com payload destacado (RFC 7515 Apêndice F) no formato `<header>..<signature>`, sobre o checkout **canonicalizado por JCS (RFC 8785)**, com o campo `ap2` **excluído**.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| **Canonicalização JCS incorreta** | **Muito alta** | Teste de round-trip com unicode, ordem de chaves, inteiros grandes | Usar biblioteca dedicada (`rfc8785`); nunca `json.dumps(sort_keys=True)` — não é JCS |
| Esquecer de excluir `ap2` antes de assinar | Alta | Teste de verificação | Função única `canonical_payload(checkout)` usada por assinatura *e* verificação |
| Remover campo "não reconhecido" do checkout antes de verificar | Alta | Teste com campo extra | A spec é explícita: a verificação opera sobre o JSON **completo**; remover qualquer membro coberto invalida a assinatura |
| Assinar só o payload e não o header (ataque de substituição de `alg`) | Média | Teste adversarial | Base = `header_b64 + "." + payload_b64`, como na spec |

---

### Passo 8 — Decisão de autorização (núcleo AVAL)

**Quem:** `AuthorizationCore`. **Sem LLM, sem protocolo.**
**Ordem obrigatória:** revogação → validade do mandato → política viva → constraints AP2 → saldo.

Este é o **ponto de autorização**, não o commit point (C11). Aqui a revogação pode produzir `REJECTED` **ou** `AWAITING_HUMAN`; no Passo 11 ela só pode produzir `REJECTED`.

**Saídas possíveis:** `AUTHORIZED` · `AWAITING_HUMAN` (→ UCP `requires_escalation` + `continue_url`; AP2 `unresolved_constraint`) · `REJECTED`.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| Ordem de avaliação invertida (checa saldo antes de revogação) | Média | Teste de cenário 3 | Uma única função `evaluate()`; ordem como constante testada |
| Política hard-coded → *trial by fire* falha | **Alta** | Ensaio com jurado simulado | Política em tabela, editável por endpoint de admin, efeito imediato |
| Rejeição silenciosa sem motivo legível | Média | Revisão da trilha | Todo `REJECTED` grava `AuditEvent` com razão estruturada + texto em português |

---

### Passo 9 — Consentimento e mandatos fechados

**Quem:** Humano (Human Present) ou AVAL por delegação (Human Not Present).
**Artefato:** `checkout_mandate` SD-JWT+kb contendo o checkout **completo, incluindo `ap2.merchant_authorization`** — a assinatura da plataforma cobre a do merchant. Payment Mandate vai em `payment.instruments[*].credential.token`.

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| **Parsers tipados do AP2 exigem exatamente dois payloads na cadeia** | Alta (já mapeado pelo time) | Teste de cadeia | Limitar o MVP a **uma delegação**; normalizar a cadeia explicitamente |
| Cadeia de checkout decodifica mas não verifica a assinatura do merchant | Alta (já mapeado) | Teste com JWT adulterado | Verificar assinatura/chave do merchant **antes** de aplicar constraints |
| Key binding (`aud`, `nonce`) ausente → replay | Média | Teste de replay | Desafio único `{aud, nonce, transaction_id}` emitido pelo merchant mock |
| Mandato fechado não bate com o aberto na cadeia | Média | Teste de hash | O AP2 avalia isso via hash no *delegate chain*; implementar a checagem |

---

### Passo 10 — Submissão do `complete_checkout`

**Quem:** Agente → merchant mock.
**Merchant deve:** exigir `ap2.checkout_mandate` (senão `mandate_required`); verificar SD-JWT, key binding e expiração; extrair o checkout embutido; **confirmar que `merchant_authorization` embutido é a própria assinatura**; conferir que os termos batem com a sessão atual (id, totais, line items).

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| Merchant aceita `complete` sem mandato porque o *lock* não foi implementado | Alta | Teste negativo | Flag de sessão `ap2_locked`; teste que envia sem mandato e espera `mandate_required` |
| Termos divergem por recálculo de frete/imposto entre criar e completar | **Alta** | Teste de mudança de total | Congelar totais na sessão; qualquer recálculo gera nova assinatura e novo consentimento |
| Códigos de erro AP2 não implementados | Média | Checklist | Implementar os sete: `mandate_required`, `agent_missing_key`, `mandate_invalid_signature`, `mandate_expired`, `mandate_scope_mismatch`, `merchant_authorization_invalid`, `merchant_authorization_missing` |

---

### Passo 11 — Captura (o coração determinístico)

**Quem:** `CaptureService` do AVAL.
**Sequência obrigatória, em uma transação:**

1. Adquire lock por `(mandate_id, transaction_id)`.
2. Consulta idempotência; se replay, devolve resposta cacheada.
3. **Revalida tudo** — revogação, expiração, política, constraints. *Sim, de novo.* A leitura de revogação é **autoritativa e sem cache**, dentro desta transação (11.6).
4. Cria `Reservation` consumindo orçamento atomicamente e a transita para `COMMITTED`. **Este é o commit point.**
5. Emite o `AuthorizationProof` de uso único, ligado a `(reservation_id, transaction_hash)` (11.9).
6. Chama o `SettlementAdapter` — **fora do lock**, com a tentativa já persistida como `PENDING`.
7. Concilia: sucesso → `SETTLED`; falha → libera a reserva (`RELEASED`).
8. Grava `AuditEvent` e emite recibos.

**Regra do commit point:** uma revogação que chega **antes** do passo 4 impede a captura; uma que chega **depois** vale para utilizações futuras do mandato e não desfaz esta transação — o desfazimento é tratado por reversal/refund/dispute, não por revogação (11.8).

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| **Double-spend em capturas concorrentes** | **Alta** | Teste com duas requisições simultâneas | `SELECT … FOR UPDATE` (Postgres) ou SQLite em WAL com escritor único serializado. **Teste obrigatório do desafio.** |
| Limite muda entre autorização e captura | Alta (é cenário de teste) | Teste dedicado | Passo 3 acima existe exatamente para isso |
| Adaptador de liquidação lento trava o lock | Média | Timeout | Timeout curto + liberação de reserva; nunca segurar lock em I/O de rede longa |
| Falha parcial: PSP aprovou, ledger não gravou | Média | Reconciliação | Gravar `CaptureAttempt` em `PENDING` **antes** de chamar; conciliar no retorno |
| Revogação chega durante a chamada externa e o time tenta "cancelar" a transação | **Alta** | Teste 17 | Depois de `COMMITTED` a revogação não desfaz; documentar o commit point na UI do auditor |
| Retry vira nova compra por perder o `transaction_hash` | Média | Teste 19 | Chave de idempotência amarrada a `(mandate_id, transaction_hash)`; retry reusa a mesma `Reservation` |

---

### Passo 12 — Recibos e trilha

**Quem:** AVAL emite Checkout Receipt e Payment Receipt AP2 ligados ao hash do JWT fechado; `AuditEvent` grava a versão legível.
**Três visões:** humano (o que comprei, sob qual mandato), merchant (o que verifiquei), auditor (linha do tempo completa com hashes).

| Risco | Prob. | Detecção | Mitigação / Plano B |
|---|---|---|---|
| `ReceiptClient.verify_receipt` chama callback opcional mesmo quando `None` | Alta (já mapeado) | Teste | Corrigir atrás da interface local |
| Trilha "verificável" mas ilegível → perde no critério 5 | **Alta** | Teste com leitor externo | Cada `AuditEvent` tem `human_summary` em português além do hash |
| Recibo emitido antes da captura confirmada | Média | Teste de ordem | Emissão **pós-captura**, como já decidido pelo time |

---

### Passo 13 — Disputa

**Quem:** Auditor. Reconstrói a cadeia: mandato aberto → constraints → mandato fechado → `checkout_hash` → `merchant_authorization` → recibo de pagamento.
**Veredito:** se todas as assinaturas verificam e as constraints são satisfeitas, a responsabilidade é do humano; se alguma quebra, é do agente ou do merchant.

> O desafio classifica o fluxo completo de disputa como **bônus**, mas a disputa aparece no objetivo obrigatório. A interpretação conservadora do time (modelar e explicar sempre; implementar se sobrar tempo) está correta. A cadeia AP2 já dá a evidência de graça — o custo é só a UI de leitura.

---

### Passo 14 — Trial by fire

O jurado vai fazer algo como: mudar o limite, revogar o mandato, trocar o merchant permitido, alterar a data de validade, ou mandar o agente comprar algo fora do escopo.

**Requisito arquitetural:** toda essa configuração precisa ser **linha de banco editável por endpoint**, com efeito na próxima decisão, sem restart, sem deploy, sem alguém do time tocando no teclado. Se qualquer regra for constante em código, o sistema falha no critério nº 1.

---

## 7. Os seis cenários obrigatórios, mapeados

| Cenário | Mecanismo protocolar | Onde vive a decisão | Resposta ao usuário |
|---|---|---|---|
| **Compra fora do mandato** | AP2 constraint não satisfeita; UCP `requires_escalation` + `continue_url`; AP2 `unresolved_constraint` | `PolicyEngine` | Escala para aprovação humana. **Nunca aprova em silêncio.** |
| **Mandato expirado** | `exp` do SD-JWT; `payment.execution_date.not_after`; `Allowance.expires_at` | `MandateStore` + `ClockService` | `mandate_expired` |
| **Revogação ao vivo** | **Nenhum protocolo cobre** — camada própria, Seção 11 | `RevocationRegistry` (AVAL), lido na autorização *e* dentro da transação de commit, sem cache | `aval.mandate_revoked` (403); mandato segue criptograficamente válido, mas sem autoridade |
| **Agente impostor** | UCP RFC 9421 + `signing_keys[]` + registry de perfis confiáveis | Verificação na borda | `signature_invalid`, `key_not_found` ou `profile_not_trusted` |
| **Disputa posterior** | Cadeia AP2 + recibos + `AuditEvent` | `AuditLedger` | Veredito reconstruído da evidência |
| **Trilha de auditoria** | UCP `Order` + recibos AP2 como renderização do log | `AuditLedger` | Três visões da mesma verdade |

---

## 8. x402 — análise separada

### 8.1 O que é

x402 é um protocolo de pagamento **nativo de HTTP**. O servidor responde `402 Payment Required` com um header `PAYMENT-REQUIRED` contendo um JSON base64 que descreve o preço; o cliente reenvia a requisição com um header `PAYMENT-SIGNATURE` carregando uma autorização assinada; um *facilitator* verifica e liquida. Criado pela Coinbase (whitepaper de maio de 2025), governado pela x402 Foundation, formalizada sob a Linux Foundation em abril de 2026. A versão corrente é a **v2**.

**Estrutura essencial:**

```
Servidor → 402 + PAYMENT-REQUIRED:
{
  "x402Version": 2,
  "resource": { "url": "...", "mimeType": "application/json" },
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:84532",     // CAIP-2
    "amount": "10000",             // string, unidades atômicas
    "asset":  "0x036C…",           // contrato do token
    "payTo":  "0x2096…",
    "maxTimeoutSeconds": 60
  }],
  "extensions": {}
}

Cliente → PAYMENT-SIGNATURE:
{
  "x402Version": 2,
  "accepted": { …PaymentRequirements escolhido… },
  "payload": {
    "signature": "0x2d6a…",                    // EIP-712
    "authorization": {                          // EIP-3009
      "from": "0x857b…", "to": "0x2096…",
      "value": "10000",
      "validAfter": "1740672089",
      "validBefore": "1740672154",
      "nonce": "0xf374…"                        // 32 bytes, anti-replay
    }
  }
}

Facilitator: POST /verify → { isValid, invalidReason?, payer? }
             POST /settle → { success, transaction, network, amount?, errorReason? }
```

**Schemes disponíveis:** `exact` (valor fixo, EIP-3009 em EVM, `TransferChecked` em SVM) e `upto` (valor máximo, com o valor real definido na liquidação).

### 8.2 Por que ele **não** é um concorrente dos outros três

x402 opera em um plano completamente diferente:

| | UCP / ACP / AP2 | x402 |
|---|---|---|
| Objeto da transação | Um **carrinho** de bens ou serviços | Um **recurso HTTP** (chamada de API, dado, computação) |
| Contraparte | Um merchant com identidade legal | Um servidor de recurso |
| Consentimento | Humano, explícito, com evidência | Implícito no orçamento pré-configurado do agente |
| Liquidação | Cartão, wallet, PSP | Stablecoin on-chain |
| Latência típica | Segundos a minutos | ~2 segundos |
| Ticket típico | Dezenas a milhares | Frações de centavo a alguns dólares |
| Reversibilidade | Chargeback existe | Liquidação final |

Colocar x402 no caminho do cartão seria um erro de categoria. **A tese correta é: o mandato do AVAL é agnóstico de trilho, e x402 prova isso.**

### 8.3 O ângulo de integração de alto valor: `upto` como orçamento

Aqui está a conexão intelectual mais forte entre x402 e o resto do sistema. O scheme **`upto`** garante quatro propriedades por especificação:

1. **Uso único** — cada autorização liquida no máximo uma vez.
2. **Limitada no tempo** — `validAfter` e `deadline` obrigatórios.
3. **Vínculo de destinatário** — o facilitator não pode redirecionar fundos.
4. **Teto de valor** — o liquidado é `≤` o autorizado (podendo ser zero).

Essas quatro propriedades são **exatamente as invariantes de um mandato**. Ou seja: `upto` é um mandato AP2 expresso em criptografia de blockchain. Demonstrar que o mesmo `Mandate` do AVAL **gera** tanto o `Allowance` do ACP quanto o `PaymentRequirements` do x402 é a prova visual de que o núcleo é único e os protocolos são projeções. **Este é provavelmente o slide mais forte do pitch.**

### 8.4 Como plugar sem conflito

```
CaptureService
  └── SettlementAdapter (interface)
        ├── MockCardPSP        → resposta determinística approved/declined
        └── X402Settlement     → PAYMENT-REQUIRED / PAYMENT-SIGNATURE / facilitator mock
```

**Cinco regras não negociáveis:**

1. **x402 nunca aparece no caminho do cartão.** Trilho separado, endpoint separado, tela separada.
2. **A reserva de orçamento acontece no ledger AVAL antes** de qualquer coisa x402. O nonce do x402 é registrado na mesma tabela de idempotência.
3. **O `nonce` não substitui a idempotência do AVAL** — ele é registrado *nela*.
4. **Conversão de escala explícita na borda.** `"10000"` em USDC de 6 casas é 0,01 USD, não 10.000. Escreva o teste.
5. **Facilitator é mock.** Sem RPC, sem gas, sem chave privada real, sem rede de teste.
6. **O trilho x402 passa pelo mesmo commit point.** Nenhum `PAYMENT-SIGNATURE` é formado sem uma `Reservation` em `COMMITTED`. Definir o commit point como "antes da rede de cartões" deixaria o micropagamento fora da revogação — mandato revogado continuaria pagando a API de decisão. Esse é um bug demonstrável, e é o teste 18.

### 8.5 Caso de uso concreto para a demo

O cenário que justifica x402 sem forçar a barra: **o agente precisa comprar um dado para tomar a decisão de compra.**

> Marta autoriza o agente a comprar uma passagem até R$ 800. Para decidir, o agente precisa consultar uma API paga de previsão de preço, que cobra R$ 0,02 por consulta via x402. O mandato de Marta inclui uma verba operacional de R$ 5,00 para custos de decisão. O agente paga a API por x402, consome R$ 0,02 do **mesmo** ledger, e o auditor vê as duas linhas — a micropagamento e a compra — sob o **mesmo mandato**.

Isso demonstra: (a) o mandato governa trilhos heterogêneos; (b) o ledger é único; (c) a trilha de auditoria é completa de ponta a ponta. É original, é defensável, e não põe a demo principal em risco.

### 8.6 Riscos específicos do x402

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Tentar usar rede real (Base Sepolia) | Média | **Crítico** — gas, faucet, latência, falha na demo | Facilitator mock. Sem exceção. |
| Confusão de escala de token → valores absurdos na tela | **Alta** | Alto | `Money` com `scale`; teste de conversão |
| `PAYMENT-REQUIRED` é header base64, não corpo — implementado errado | Média | Médio | Seguir a spec de transporte HTTP v2 |
| Dependências Web3 pesadas travando o build | Média | Alto | Verificar EIP-712 offline com `eth_account`; sem cliente RPC |
| Reintroduzir os samples x402 do AP2 (que o time já decidiu excluir) | Média | Médio | Implementação própria, mínima, ~150 linhas |
| Time gasta 6h no x402 e não termina a revogação | **Alta** | **Crítico** | **Linha de corte: x402 só entra depois que os cenários 1-4 passarem.** |

### 8.7 Veredito

**Implementar, com escopo cirúrgico, depois do resto.** Custo estimado: 2 a 3 horas para o caminho descrito. Ganho: o critério de **originalidade** e um argumento de arquitetura que nenhum outro time provavelmente terá. Risco: alto **se** for feito cedo demais ou com rede real.


---

## 9. Análise consolidada de risco

### 9.1 Matriz mestre — os quinze riscos que decidem o resultado

Ordenados por *probabilidade × impacto*.

| # | Risco | Origem | Prob. | Impacto | Sintoma | Mitigação |
|---|---|---|---|---|---|---|
| 1 | Assinatura ECDSA em DER em vez de `r\|\|s` | UCP / RFC 9421 | Muito alta | Crítico | Verificação falha 100% | Conversão explícita; teste de vetor no primeiro commit |
| 2 | Corpo re-serializado quebra `Content-Digest` | UCP | Muito alta | Crítico | `digest_mismatch` intermitente | Assinar/verificar sobre bytes crus |
| 3 | JCS mal implementado | UCP AP2 ext | Muito alta | Crítico | `merchant_authorization_invalid` | Biblioteca RFC 8785; nunca `sort_keys=True` |
| 4 | Política em constante de código | AVAL | Alta | Crítico | Falha no trial by fire | Tudo em tabela; endpoint de admin |
| 5 | Double-spend em captura concorrente | AVAL | Alta | Crítico | Duas capturas aprovadas | Lock transacional; teste obrigatório |
| 6 | Revogação só na autorização, não na captura | AVAL | Alta | Crítico | Revogação ao vivo "não funciona" | Revalidação completa no capture |
| 7 | x402 iniciado cedo demais | Escopo | Alta | Crítico | Núcleo incompleto no freeze | Linha de corte rígida |
| 8 | Formato do manifesto UCP misturando versões | UCP | Alta | Alto | Interseção de capacidades vazia | Fixar `2026-08-25`; um único exemplo de referência |
| 9 | SDK `sd-jwt` com API privada instável | AP2 | Alta | Alto | Import quebra | Interface `MandateSigner`; fallback JWS |
| 10 | Totais recalculados entre criar e completar | UCP | Alta | Alto | `mandate_scope_mismatch` | Congelar totais; re-consentir se mudar |
| 11 | `Allowance` tratada como fonte de política | ACP | Alta | Alto | Limite antigo respeitado | `derived_allowance`; teste C2 |
| 12 | Confusão de escala monetária | Todos | Alta | Alto | Valores absurdos na tela | `Money` com `scale`; testes de borda |
| 13 | Trilha verificável mas ilegível | AVAL | Alta | Médio | Perde critério 5 | `human_summary` em cada evento |
| 14 | Cadeia AP2 limitada a dois payloads | AP2 | Média | Médio | Erro em cadeia longa | MVP com uma delegação |
| 15 | Prompt injection via catálogo | LLM | Média | Médio | Agente desvia do mandato | Gateway; item malicioso plantado como demo |
| 16 | Cache de revogação no caminho de commit | Revogação | Alta | **Crítico** | Jurado revoga e a próxima compra passa | TTL zero no commit; cache só em pré-voo marcado como não autoritativo |
| 17 | Endpoint de revogação sem autenticação | Revogação | Alta | Alto | Qualquer um revoga qualquer mandato | Revogação assinada por `RevocationAuthority`; admin do *trial by fire* com token |
| 18 | Commit point definido pela rede de cartões | Revogação | Média | Alto | x402 escapa da revogação | Commit point na fronteira do `SettlementAdapter` |
| 19 | Duas máquinas de estado (`Mandate.COMMITTED` + `Reservation`) | Revogação | Média | Alto | Divergência sob concorrência | Só `Reservation` transita; `Mandate` é monótono (C12) |
| 20 | `AuthorizationProof` emitido antes do commit | Revogação | Média | Alto | Reintroduz a corrida que a prova deveria eliminar | Emissão pós-`COMMITTED`, uso único (11.9) |

### 9.2 As três armadilhas criptográficas, em detalhe

**(a) `r||s` versus DER.** A especificação UCP é explícita: assinaturas ECDSA devem usar codificação crua de largura fixa `r||s` — 64 bytes em P-256, 96 em P-384 — e **não** ASN.1/DER. OpenSSL, Java e .NET produzem DER por padrão. Em Python com `cryptography`, `sign()` devolve DER; é preciso usar `decode_dss_signature` e reencodar com `int.to_bytes(32, "big")` em cada metade. Esta é uma linha de código e três horas de depuração se esquecida.

**(b) Bytes crus versus objeto.** `Content-Digest` é SHA-256 sobre os **bytes do corpo**, sem canonicalização. Se o servidor faz `json.dumps(pydantic_model.dict())` para recalcular o digest, qualquer diferença de espaçamento, ordem ou escape unicode quebra a verificação. Em FastAPI: capture `await request.body()` no middleware antes do parse e carregue esses bytes pelo request context.

**(c) JCS não é `sort_keys`.** RFC 8785 define ordenação por **code points UTF-16** das chaves, serialização numérica no formato ECMAScript e escape específico. `json.dumps(obj, sort_keys=True, separators=(",", ":"))` acerta em casos simples e erra com acentuação — o que, num projeto em português com nomes de produto acentuados, é garantia de bug. Use `rfc8785` ou equivalente e escreva um teste com "Café", "R$" e emoji.

### 9.3 O que fazer se algo quebrar durante a demo

| Falha | Degradação aceitável |
|---|---|
| Verificação de assinatura instável | Flag `SIGNATURE_ENFORCEMENT=warn` que loga e segue — **mas nunca ligada durante a demo**; existe só para desbloquear desenvolvimento |
| Armazenamento de revogação indisponível | **Nenhuma degradação.** `503 revocation_unavailable`. Não existe `REVOCATION_ENFORCEMENT=warn` em ambiente nenhum (C14) |
| x402 não sobe | Trilho oculto na UI; o resto é independente por construção |
| LLM lento ou fora do ar | Agente scriptado com as mesmas chamadas de ferramenta |
| Banco corrompido | Seed determinístico e reset em um comando |

---

## 10. Concorrência, idempotência e double-spend

Este é o núcleo que nenhum protocolo entrega e que o desafio testa diretamente.

### 10.1 Invariantes

1. Um mandato nunca é consumido além do seu saldo, sob nenhuma ordem de requisições.
2. Duas capturas concorrentes com o mesmo `transaction_id` resultam em **exatamente uma** liquidação.
3. Uma requisição repetida com a mesma `Idempotency-Key` devolve a resposta original, sem novo efeito.
4. Uma revogação que chega entre autorização e captura **impede** a captura.
5. Uma falha de escrita no armazenamento de idempotência resulta em rejeição (`503`), nunca em execução.
6. Uma revogação e um commit da mesma reserva nunca vencem os dois: as duas escritas disputam o mesmo lock de `mandate_id`.
7. Depois de `Reservation = COMMITTED`, nenhuma revogação altera aquela transação; ela permanece válida para utilizações futuras do mandato.
8. Nenhum `SettlementAdapter` — inclusive x402 — é acionado sem uma `Reservation` em `COMMITTED`.
9. Uma leitura de revogação usada para decidir nunca vem de cache.

### 10.2 Implementação mínima defensável

```python
# Pseudocódigo — a ordem é o produto.
def capture(mandate_id, transaction_id, idem_key, amount):
    with db.transaction():                      # 1. transação única
        lock = acquire_lock(mandate_id)         # 2. SELECT ... FOR UPDATE

        if cached := idem.get(("ucp", idem_key)):
            return cached                       # 3. replay

        if revocations.is_revoked(mandate_id,   # 4. REVOGAÇÃO PRIMEIRO
                                  fresh=True):  #    leitura sem cache
            return reject("mandate_revoked")

        m = mandates.get(mandate_id)
        if clock.now() > m.expires_at:
            return reject("mandate_expired")

        if not policy.evaluate(m, amount):      # 5. política VIVA
            return escalate_or_reject()

        if not ap2.verify_chain(...):           # 6. evidência
            return reject("mandate_invalid_signature")

        res = ledger.reserve(m, amount)         # 7. consumo ATÔMICO
        res.to_committed(transaction_hash)      # 8. COMMIT POINT
        proof = proofs.issue(res, ttl=60)       # 9. prova pós-commit
        attempt = attempts.create(PENDING, ...) # 10. antes da rede

    result = settlement.authorize(res, proof)   # 11. FORA do lock

    with db.transaction():                      # 12. concilia
        if result.approved:
            ledger.settle(res); attempts.settle(attempt)
        else:
            ledger.release(res); attempts.fail(attempt)
        idem.put(("ucp", idem_key), response)
        audit.append(...)
    return response
```

Quatro detalhes que importam: a revogação é checada **antes** de tudo, com leitura fresca; a reserva acontece **antes** da chamada de rede; o commit da reserva é a linha 8 e nada além dela é o commit point; e a chamada de rede acontece **fora** do lock, com a tentativa já persistida como `PENDING` para permitir conciliação em caso de queda.

Note o que **não** está no pseudocódigo: não há transição de estado no `Mandate`. Ele permanece `ACTIVE`; quem transita é a `Reservation` (C12).

### 10.3 Escolha de banco

SQLite em modo WAL é suficiente para uma demo e reduz risco operacional, **desde que** haja um único processo escritor e as transações usem `BEGIN IMMEDIATE`. Essa escolha tem uma consequência que a Seção 11.10 explora: com escritor único, não existe suporte a múltiplos verificadores concorrentes consumindo o mesmo mandato a partir de processos distintos. Postgres é mais seguro para concorrência real mas adiciona uma dependência de infra na madrugada. Recomendação: **SQLite + WAL + escritor serializado**, com a camada de repositório isolada para permitir troca se sobrar tempo.

---

## 11. Camada de revogação — a autoridade viva

Esta seção é a especificação do único componente que nenhum dos quatro protocolos entrega e que o *trial by fire* testa diretamente. Tudo aqui é código determinístico do AVAL. Nada aqui depende do LLM.

**Propriedade de segurança que a camada garante:**

> Um usuário pode retirar a autoridade de um agente até o instante em que uma transação específica é irrevogavelmente aceita para submissão ao trilho de liquidação, e nenhum agente pode utilizar uma autorização revogada nem reutilizar uma autorização já consumida.

### 11.1 Posição no fluxo e definição do commit point

O modelo mental "gate imediatamente antes da rede de pagamento" está **quase** certo e erra em duas coisas: perde o caminho de escalonamento humano (C11) e deixa trilhos não-cartão fora da revogação (8.4, regra 6). A correção é definir o commit point pela **fronteira do `SettlementAdapter`**, e reconhecer que existem dois momentos de decisão, não um.

```
Humano ──emite──► Mandate (aberto, com aval.revocation)
                        │
                        ▼
  Agente ──► UCP checkout ──► [PONTO DE AUTORIZAÇÃO]  Passo 8
                                    │  AUTHORIZED / AWAITING_HUMAN / REJECTED
                                    │  ← revogação aqui pode ESCALAR
                                    ▼
                            complete_checkout (AP2 lock)
                                    │
                                    ▼
                        ┌───────────────────────────┐
   revogação ──────────►│      COMMIT POINT         │  Passo 11, dentro
   (a qualquer instante)│  Reservation: → COMMITTED │  de UMA transação
                        └─────────────┬─────────────┘
                                      │  AuthorizationProof (uso único, TTL 60s)
             ─────────────────────────┼─────────────────────────
              antes: revogável        │        depois: NÃO revogável
                                      ▼
                            SettlementAdapter
                          (PSP mock  |  x402)
                                      │
                                      ▼
                            reversal / refund / dispute
```

**Regras da fronteira:**

1. Antes do commit point, a autorização é revogável.
2. Depois do commit point, a revogação do mandato **não afeta aquela tentativa**; continua valendo para todas as futuras.
3. Depois do commit point, o desfazimento é problema dos mecanismos normais de pagamento — reversal, cancelamento, refund, disputa — e a UI do auditor precisa dizer isso com essas palavras.
4. Nenhum adaptador de liquidação é acionado sem uma `Reservation` em `COMMITTED`.

### 11.2 Máquina de estados

Duas máquinas separadas, e nunca uma terceira (C12).

```
Mandate            ACTIVE ──► REVOKED        (monótono, irreversível)
                      └────► EXPIRED

Reservation        PENDING ──► COMMITTED ──► SETTLED
                      │             └──────► RELEASED   (liquidação falhou)
                      └────────────────────► RELEASED   (rejeitado no commit)
```

O `Mandate` **não tem** estado `COMMITTED`: um mandato aberto com teto financia N compras. Quem é consumido é a `Reservation`.

A corrida entre revogação e compra é resolvida por serialização, não por state machine:

| Ordem real | Efeito |
|---|---|
| Revogação escreve primeiro | Commit lê `REVOKED` dentro da mesma transação → `REJECTED` |
| Commit escreve primeiro | Revogação encontra a reserva já `COMMITTED` → aquela transação segue; mandato passa a `REVOKED` para as próximas |

As duas escritas adquirem o **mesmo lock de `mandate_id`** (`SELECT … FOR UPDATE`, ou `BEGIN IMMEDIATE` no SQLite). Não existe janela entre "ler status" e "gravar commit", porque as duas coisas acontecem na mesma transação. Essa é a resposta ao `authorize_and_commit()` conceitual: ele não é uma primitiva nova, é a transação da Seção 10.2.

### 11.3 Onde a referência de revogação vive

No mandato **aberto**, como claim de namespace, fora dos schemas tipados do AP2 (C13):

```json
"aval": {
  "revocation": {
    "v": 1,
    "revocation_id": "rev_01JAV…",
    "registry": "https://aval.local/.well-known/aval-revocation",
    "authorities": [
      { "role": "holder",   "kid": "usr_01JAV…", "alg": "ES256" },
      { "role": "guardian", "kid": "gdn_01JAV…", "alg": "ES256" }
    ],
    "commitment": "b64u(SHA-256(R))",
    "epoch": 0
  }
}
```

**Regras:**

- O bloco é coberto pela assinatura do mandato e **nunca** é removido antes de verificar — a verificação opera sobre o JSON completo (Passo 7).
- `revocation_id` é opaco e não deriva de dados do usuário (11.11).
- A cópia autoritativa vive na tabela `mandates` do AVAL; o claim é a *projeção* verificável, coerente com 3.1.
- `commitment` é **opcional** e não é o mecanismo primário — ver 11.4.
- `epoch` incrementa a cada mudança de política e entra no `AuthorizationProof`, permitindo invalidar provas em voo.

### 11.4 Commit-reveal versus revocation key assinada

A proposta de `C = SHA256(R)`, com revogação por publicação de `R`, foi avaliada contra a alternativa de uma **revocation key** que assina uma chamada de revogação.

| Propriedade | Commit-reveal | Revocation key assinada |
|---|---|---|
| Não-forjabilidade da revogação | Sim | Sim |
| Autoria identificável | Não | **Sim** |
| Múltiplos revogadores (titular, guardião, emissor) | Não sem múltiplos segredos | **Sim, por papel** |
| Revogação de escopo parcial | Não | **Sim** |
| Delegação / rotação | Não | **Sim** |
| Revogação sem o usuário presente | **Não** | Sim (guardião/operador) |
| Perda do segredo | **Mandato torna-se irrevogável** | Rotação de chave |
| Vazamento do segredo | **DoS: revogação forçada** | Mesmo risco, mas mitigável por rotação |
| Privacidade antes do reveal | **Sim** (entrada opaca) | Depende do identificador usado |
| Impede o registry de censurar/equivocar | Não | Não |

**Decisão: a revocation key assinada é o mecanismo primário; o commitment é acessório de privacidade em produção.**

Três razões:

1. **O commitment não resolve a falha real do registry.** O risco de um registry não é forjar uma revogação — é *ocultá-la* ou responder coisas diferentes para partes diferentes. SHA-256 não trata censura nem equivocação; log append-only e auditoria externa tratam (11.13).
2. **Commit-reveal quebra o *trial by fire*.** O jurado revoga por um endpoint de operador. Se revogar exige posse de `R`, ou o jurado não consegue revogar, ou o AVAL guarda `R` pelo usuário — e nesse caso o commitment não oferece nada sobre uma linha de banco, porque quem verifica e quem revoga estão no mesmo domínio de confiança.
3. **Commit-reveal é binário.** Não expressa "revogue só este merchant" nem "zere o teto e mantenha o resto", que são casos que o desafio provavelmente vai testar.

O que o commitment **de fato** entrega e vale manter no roadmap: uma entrada de registry que não identifica o mandato até o reveal, útil quando o registry é operado por terceiro. Para isso, porém, uma *status list* agregada é melhor (11.11 e 11.13).

### 11.5 Quem pode revogar

Revogação é uma escrita privilegiada e **assinada**. Nunca um `POST` aberto.

| Papel | Autenticação | Escopo permitido |
|---|---|---|
| `holder` (usuário) | JWS ES256 com a chave em `aval.revocation.authorities` | Qualquer escopo do próprio mandato |
| `guardian` | JWS ES256, chave co-registrada na emissão | Mandato inteiro |
| `issuer` (AVAL, por risco) | Chave de plataforma via `KeyCustodyService` | Mandato inteiro, com motivo obrigatório |
| `operator` (*trial by fire*) | Token de operador + registro de auditoria | Qualquer escopo, sempre logado como `operator` |

O papel `operator` existe porque o jurado precisa revogar sem a chave da Marta. Ele é uma autoridade de primeira classe, autenticada e auditada — **não** um bypass. O endpoint de admin da Seção 12 é o mesmo endpoint, com o mesmo registro no `AuditLedger`.

**Escopos de revogação:**

| Escopo | Efeito |
|---|---|
| `mandate` | Mandato inteiro para `REVOKED` |
| `merchant:<id>` | Remove um merchant do escopo permitido |
| `instrument:<vt_…>` | Invalida um token do cofre |
| `budget:zero` | Zera o saldo vivo mantendo o mandato ativo |

Toda revogação grava `Revocation` + `Evidence` (o JWS) + `AuditEvent` com `human_summary` em português. É irreversível: "desfazer" é emitir um mandato novo.

### 11.6 Consulta, cache e latência

| Caminho | Fonte | Cache | Autoritativo? |
|---|---|---|---|
| Pré-voo / UI / rascunho do agente | Réplica de leitura | Permitido, ≤ 5 s | **Não** — marcado como `advisory` na resposta |
| Ponto de autorização (Passo 8) | Tabela primária | Não | Sim |
| **Commit point (Passo 11)** | Tabela primária, dentro da transação | **Proibido** | Sim |

Latência aceitável de revogação = **zero decisões**, não zero milissegundos. O requisito da Seção 12 é "efeito na próxima decisão, sem restart". Qualquer TTL no caminho de commit é uma janela em que o jurado revoga e a compra seguinte passa — é o risco 16 e provavelmente a forma mais provável de perder o critério nº 1.

Alvo operacional: revogação visível para a próxima decisão em < 100 ms local; p99 do commit point < 300 ms incluindo a leitura fresca.

### 11.7 Indisponibilidade: fail-closed, sem exceção

| Situação | Resposta |
|---|---|
| Tabela/serviço de revogação indisponível | `503 revocation_unavailable`, `Retry-After` |
| Leitura de revogação com timeout | `503`, nunca "assume ativo" |
| Réplica de pré-voo indisponível | Degrada só a UI; o commit point não usa réplica |

**Não existe `REVOCATION_ENFORCEMENT=warn`** em nenhum ambiente, ao contrário do flag de assinatura da Seção 9.3 (C14). O motivo é assimetria de dano: uma verificação de assinatura frouxa deixa passar um impostor num ambiente de desenvolvimento sem dinheiro; uma revogação frouxa é exatamente o cenário que o desafio manda tratar.

### 11.8 Revogação em voo

O caso difícil é a revogação que chega **depois** do commit e **antes** da resposta do adaptador de liquidação.

| Estado no momento da revogação | Ação |
|---|---|
| `Reservation = PENDING` (ainda dentro da transação) | Commit falha; `RELEASED`; `aval.mandate_revoked` |
| `Reservation = COMMITTED`, liquidação em voo | **Nada muda nesta transação.** Mandato vira `REVOKED`; próxima tentativa é rejeitada |
| `Reservation = COMMITTED`, liquidação falhou | `RELEASED`; o mandato já revogado impede nova tentativa |
| `Reservation = SETTLED` | Fora do escopo da revogação: reversal/refund/dispute |

A tentação de "cancelar a transação em voo" é o erro a evitar: a chamada externa não participa da transação ACID local, então cancelar viraria uma segunda operação distribuída com seus próprios modos de falha. O commit point existe justamente para tornar essa fronteira explícita e defensável.

### 11.9 `AuthorizationProof` — prova curta de uso único

Depois do commit, o AVAL emite um artefato assinado que substitui novas consultas ao registry no restante do fluxo. É o mesmo padrão do *OCSP stapling*: em vez de cada verificador consultar o status, o status viaja com a requisição, assinado e com validade curta.

```json
{
  "v": 1,
  "reservation_id": "rsv_01JAV…",
  "mandate_ref": "b64u(SHA-256(mandate_id || salt_epoch))",
  "transaction_hash": "b64u(…)",
  "amount": { "amount": 80000, "currency": "BRL", "scale": 2 },
  "decision": "COMMITTED",
  "policy_version": 7,
  "revocation_epoch": 0,
  "iat": 1756487000,
  "exp": 1756487060,
  "jti": "prf_01JAV…"
}
```

**Invariantes:**

1. **Emitida depois** de `Reservation = COMMITTED`, nunca antes. Uma prova pré-commit com qualquer TTL reintroduz exatamente a corrida que ela deveria eliminar (risco 20).
2. TTL ≤ 60 s e ≤ `maxTimeoutSeconds` do trilho.
3. Uso único: `jti` é consumido na mesma tabela de idempotência da C4.
4. Não é pré-autorização e não pode ser reapresentada para uma segunda transação.
5. Carrega `policy_version` e `revocation_epoch`, então uma mudança de política invalida provas em voo por comparação, não por consulta.

### 11.10 Múltiplos verificadores concorrentes

A Seção 10.3 escolheu SQLite + WAL com **escritor único serializado**. A consequência precisa estar escrita: nessa configuração **não há suporte a múltiplos processadores concorrentes** consumindo o mesmo mandato a partir de processos distintos. Para a demo isso é adequado e é uma escolha, não uma omissão.

Se o cenário de N verificadores for exigido:

| Opção | Serialização | Custo |
|---|---|---|
| SQLite + escritor único (demo) | Processo | Nenhum; não escala |
| Postgres + `SELECT … FOR UPDATE` | Linha do mandato | Dependência de infra |
| Registry como ponto único de commit | Serviço | Vira SPOF e observa toda transação (11.11) |

Em qualquer opção, o `AuthorizationProof` é o que evita N consultas: só o commit é serializado; a verificação a jusante é offline.

### 11.11 Privacidade

Há uma tensão real e ela precisa ficar registrada, porque um jurado pode perguntar: **um registry que é o commit point atômico de toda transação observa, por construção, todas as compras do usuário.** Não dá para ter simultaneamente (a) commit atômico em serviço externo e (b) registry que não rastreia.

A resolução no AVAL é topológica: **o commit point fica dentro do núcleo**, que já é dono do ledger e não aprende nada novo. Se um registry externo existir, ele carrega **apenas status**, nunca commits.

Controles:

| Controle | Efeito |
|---|---|
| `revocation_id` opaco, sem derivação de PII | Registry não liga mandato a pessoa |
| `mandate_ref` = hash salgado por época no `AuthorizationProof` | Verificador a jusante não correlaciona mandatos entre transações |
| Status list agregada (bitstring) em vez de consulta por mandato | Consulta não revela *qual* mandato interessa |
| Registry não recebe valor, merchant nem itens | Nem com log completo reconstrói a cesta |
| Retenção separada: `AuditLedger` completo, registry mínimo | Trilha de auditoria não vaza pelo canal de status |

### 11.12 Replay

| Vetor | Controle | Onde |
|---|---|---|
| Reapresentar o mesmo mandato fechado | Key binding `{aud, nonce, transaction_id}` | Passo 9 |
| Repetir o `complete_checkout` | `Idempotency-Key`, tabela única | C4 |
| Reapresentar o `AuthorizationProof` | `jti` de uso único na mesma tabela | 11.9 |
| Retry virando compra nova | Chave amarrada a `(mandate_id, transaction_hash)`; retry reusa a mesma `Reservation` | Passo 11 |
| Replay no trilho x402 | `nonce` de 32 bytes registrado como `(x402, nonce)` | C4, 8.4 |

Regra única: **um retry nunca cria uma segunda `Reservation`.** Se a chave de idempotência chega com corpo diferente, é `422`, não uma compra nova.

### 11.13 O que reutilizar em vez de inventar

O objetivo não é criar criptografia nova. Quase tudo já existe:

| Necessidade | Componente existente | Uso no AVAL |
|---|---|---|
| Status de credencial revogável | **W3C Bitstring Status List** | Formato do registry em produção; consulta agregada preserva privacidade |
| Status em tempo real assinado | **OCSP** e, sobretudo, **OCSP stapling** (RFC 6960) | Precedente direto do `AuthorizationProof` (11.9) |
| Revogação de autorização delegada | **RFC 7009** (OAuth Token Revocation) | Forma do endpoint de revogação |
| Consulta de status de autorização | **RFC 7662** (Token Introspection) | Forma do endpoint de status |
| Autorização contínua, sinais de mudança | **OpenID Shared Signals Framework / CAEP** | Modelo conceitual de "autorização contínua" — é o que separa o AVAL dos quatro protocolos de atestação |
| Prova de posse ligada à requisição | **RFC 9449 (DPoP)** | Binding do proof ao verificador |
| Log append-only à prova de equivocação | **RFC 9162 (Certificate Transparency)** | Caminho de produção contra registry que censura |
| Anti-replay em liquidação | **EIP-3009 `nonce`** | Já usado no trilho x402 |
| Separação autorização/captura | **ISO 8583** (authorization vs. clearing) | Precedente do commit point em pagamentos tradicionais |

O único componente genuinamente novo é a **composição**: uma camada de autorização contínua posicionada na fronteira de liquidação, agnóstica de trilho, com o mandato AP2 como evidência. É isso que se defende no pitch — não uma criptografia inédita.

### 11.14 Threat model

| # | Ameaça | Vetor | Controle | Teste |
|---|---|---|---|---|
| T1 | Agente usa mandato revogado | Reapresenta mandato válido | Leitura fresca no commit point | 3 |
| T2 | Corrida revogação × compra | Revoga entre autorização e captura | Mesmo lock de `mandate_id`, mesma transação | 16 |
| T3 | Retry vira compra nova | Reenvia sem a mesma chave | Idempotência por `(mandate_id, transaction_hash)` | 19 |
| T4 | Replay do `AuthorizationProof` | Reusa prova em segunda transação | `jti` de uso único, TTL 60 s | 20 |
| T5 | Bypass do gate | Aciona adaptador direto | Nenhum adaptador sem `Reservation = COMMITTED` | 18 |
| T6 | Revogação forjada / DoS | `POST` aberto; `R` vazado | Revogação assinada por `RevocationAuthority` | 21 |
| T7 | Registry censura ou equivoca | Responde `ACTIVE` para um, `REVOKED` para outro | Fora do MVP; CT-like em produção (11.13) | — |
| T8 | Rastreamento pelo registry | Correlaciona compras do usuário | Commit dentro do núcleo; `mandate_ref` salgado | — |
| T9 | Relógio adulterado | Estende validade | `ClockService` único, skew 5 s (C9) | 2 |
| T10 | Fail-open por indisponibilidade | Serviço cai e o sistema "assume ativo" | `503`, sem modo warn | 22 |
| T11 | Mandato irrevogável | Emitido sem autoridade de revogação | Bloqueio na emissão (Passo 1) | 23 |
| T12 | Revogação tardia sem status protocolar | Recusa depois de `complete_in_progress` | `CAPTURING → REJECTED → canceled` + `aval.mandate_revoked` (403) | 17 |

### 11.15 MVP versus produção

| Dimensão | MVP (hackathon) | Produção |
|---|---|---|
| Armazenamento | Tabela `revocations` no mesmo banco | Serviço replicado + status list publicada |
| Mecanismo | JWS ES256 por `RevocationAuthority` | Idem + commitment opcional para privacidade |
| Registry | Interno ao núcleo | Externo, append-only, auditável (CT-like) |
| Consulta | Leitura direta, sem cache | Status list + `AuthorizationProof` stapled |
| Serialização | SQLite WAL, escritor único | Postgres `FOR UPDATE` ou registry como ponto de commit |
| Indisponibilidade | `503` | `503` + réplica quente + orçamento de erro |
| Privacidade | `revocation_id` opaco | Status list agregada, `mandate_ref` salgado por época |
| Escopos | `mandate`, `budget:zero` | Todos os quatro de 11.5 |
| Prova | `AuthorizationProof` com TTL 60 s | Idem + DPoP binding ao verificador |

**Linha de corte:** o MVP inteiro desta seção cabe no bloco T+5 → T+8 do plano, porque é majoritariamente a transação que a Seção 10.2 já descreve mais uma tabela e um verificador de JWS. O que **não** entra no prazo: registry externo, status list, CT, DPoP. Esses ficam documentados como caminho de produção e são material de defesa técnica, não de implementação.

---

## 12. Plano de implementação com linha de corte

Referência temporal: T-ZERO = sáb. 29/08, 12:30. Code freeze = dom. 30/08, 12:30.

| Janela | Entrega | Critério de pronto |
|---|---|---|
| **T+0 → T+2** | Esqueleto: domínio, banco, `Money`, `ClockService`, seed determinístico | Teste de `Money` passa; migração roda em ambiente limpo |
| **T+2 → T+5** | **Criptografia primeiro.** `KeyCustody`, RFC 9421 (`r\|\|s`, bytes crus), JCS, SD-JWT atrás de `MandateSigner`/`MandateVerifier` | Vetor de teste de assinatura e round-trip JCS passam |
| **T+5 → T+8** | `AuthorizationCore`: mandatos, **camada de revogação da Seção 11** (tabela, JWS por autoridade, commit point, `AuthorizationProof`), política viva, ledger, locks, idempotência | Cenários 1-3 passam; testes 16, 19 e 22 passam |
| **T+8 → T+11** | UCP: discovery, checkout REST, extensão AP2, `merchant_authorization`, merchant mock | Fluxo autorizado ponta a ponta funciona |
| **T+11 → T+13** | ACP `delegate_payment` + cofre + `Allowance` derivada | Agente nunca vê PAN; token escopado |
| **T+13 → T+15** | Captura, PSP mock, recibos, `AuditLedger` | Teste de concorrência passa |
| **T+15 → T+17** | **UI: três visões** (humano, merchant, auditor) | Demonstrável sem terminal |
| ⛔ **LINHA DE CORTE T+17** | *Tudo acima precisa estar verde. Nada abaixo começa antes.* | |
| **T+17 → T+19** | x402: facilitator mock, trilho de micropagamento | Duas linhas no mesmo ledger |
| **T+19 → T+20** | Endpoint de operador para o *trial by fire* (limite, escopo, validade, **revogação**), autenticado por token e auditado como `operator` | Mudança de limite e revogação têm efeito na decisão seguinte, sem restart |
| **T+20 → T+22** | Ensaio: pitch 7 min, demo, trial by fire com entradas desconhecidas | Time consegue explicar alternativas rejeitadas |
| **T+22 → T+24** | Diagrama PDF, README, decision log exportado, checklist do repo | Checklist de pronto completo |

**Se o time atrasar:** cortar nesta ordem — (1) x402, (2) fluxo completo de disputa, (3) ACP `delegate_payment` (substituir por cofre simples com a mesma semântica de `Allowance`), (4) UI de merchant (fundir com a de auditor). **Nunca cortar:** revogação (Seção 11, coluna MVP de 11.15), concorrência, verificação de assinatura, escalonamento humano. **Do MVP de revogação, nada é cortável** — é o item que o *trial by fire* testa primeiro.

---

## 13. Suíte de testes obrigatória

| # | Teste | Cenário do desafio | Protocolo exercitado |
|---|---|---|---|
| 1 | Compra válida ponta a ponta com cadeia, `aud`, `nonce`, constraints e recibos | Demo principal | UCP + AP2 + ACP |
| 2 | Mandato expirado antes da reserva | Expirado | AP2 + AVAL |
| 3 | Mandato revogado após emissão, recusado na captura | **Revogação ao vivo** | AVAL |
| 4 | Duas capturas concorrentes → exatamente uma consome | Integridade | AVAL |
| 5 | Fora de constraints: valor, merchant, instrumento ou item | Fora do mandato | AP2 + AVAL |
| 6 | JWT adulterado | Impostor | UCP + AP2 |
| 7 | `aud`/`nonce` incorretos | Replay | AP2 |
| 8 | Limite alterado entre aprovação e captura | **Trial by fire** | AVAL |
| 9 | Recibo com referência desconhecida | Disputa | AP2 |
| 10 | Requisição sem assinatura RFC 9421 | Impostor | UCP |
| 11 | Perfil de agente fora do registry → `profile_not_trusted` | Impostor | UCP |
| 12 | `complete_checkout` sem `ap2.checkout_mandate` → `mandate_required` | Lock de sessão | UCP AP2 ext |
| 13 | Round-trip JCS com acentuação e emoji | Correção criptográfica | UCP AP2 ext |
| 14 | Conversão de escala x402 ↔ `Money` | Correção monetária | x402 |
| 15 | Item de catálogo com prompt injection | Bônus adversarial | LLM gateway |
| 16 | Revogação e captura concorrentes no mesmo mandato → exatamente um vence | Corrida (T2) | AVAL |
| 17 | Revogação chegando **durante** a chamada de liquidação → transação já `COMMITTED` prossegue; próxima tentativa é rejeitada | Commit point (T12) | AVAL |
| 18 | Mandato revogado → micropagamento x402 também é bloqueado | Trilho agnóstico (T5) | x402 + AVAL |
| 19 | Retry com a mesma `Idempotency-Key` não cria segunda `Reservation`; corpo diferente → `422` | Idempotência (T3) | UCP + ACP |
| 20 | `AuthorizationProof` reapresentado em segunda transação → recusado; prova expirada → recusada | Replay (T4) | AVAL |
| 21 | Revogação sem assinatura de `RevocationAuthority` → recusada | Autenticação (T6) | AVAL |
| 22 | Armazenamento de revogação indisponível → `503`, nunca aprovação | Fail-closed (T10) | AVAL |
| 23 | Emissão de mandato sem autoridade de revogação → recusada | Revogabilidade (T11) | AVAL |

Os testes 1-8 são os que o próprio documento de AP2 do time já listou como mínimo obrigatório. Os 9-15 vêm da adição de UCP, ACP e x402. Os **16-23 vêm da camada de revogação da Seção 11** e são os que respondem ao *trial by fire*; se o tempo apertar, eles têm precedência sobre 9-15.

---

## 14. Entradas propostas para o Flight Log

Prontas para colar no portal quando o time ratificar.

**Protocol composition model**
*Options considered:* Implement each protocol as an independent module · Compose all protocols over a single deterministic authorization core · Pick one protocol and ignore the others
*What we chose:* Compose all protocols as edge adapters over a single AVAL authorization core that owns all state and policy.
*Why:* The four protocols occupy different planes of the same transaction; letting any of them hold state would create competing sources of truth that fail under live rule changes.

**Primary commerce protocol**
*Options considered:* ACP as the primary checkout surface · UCP as the primary checkout surface · Both in parallel
*What we chose:* UCP as the primary surface; ACP limited to delegated payment tokenization.
*Why:* UCP natively hosts the AP2 mandates extension, defines `requires_escalation` with `continue_url` for the human-approval path, and specifies RFC 9421 message signatures for agent authenticity. Running both checkout surfaces would duplicate cart state with no scoring benefit.

**Payment credential handling**
*Options considered:* Pass card data to the agent · Custom token format · ACP delegate payment with a derived Allowance
*What we chose:* ACP delegate payment shape, with `Allowance` computed as `min(live balance, mandate ceiling, checkout total)` at tokenization time.
*Why:* It satisfies the "no raw card to the agent" requirement using a published standard, and computing the allowance rather than storing it prevents a stale second policy source.

**x402 scope**
*Options considered:* Use x402 as the main settlement rail · Exclude x402 entirely · Isolated second rail behind the same capture service, after the core is green
*What we chose:* Isolated second rail with a mock facilitator, demonstrating rail-agnostic mandates via agent micropayments for decision data.
*Why:* x402 pays for HTTP resources, not carts — putting it in the card path would be a category error. As a separate rail it proves the mandate governs heterogeneous settlement without risking the primary demo. Real-chain settlement was rejected because gas, faucets, and RPC latency add failure modes with no scoring value.

**Live authorization controls (reafirmação)**
*Options considered:* Rely on protocol constraints · Implement in the LLM prompt · Deterministic AVAL controls
*What we chose:* Revocation, durable counters, locks, and capture-time revalidation in AVAL.
*Why:* None of UCP, ACP, AP2 or x402 defines revocation, live budget, or concurrent-spend protection. All four are attestation protocols; continuous authorization is the product.

**Commit point placement**
*Options considered:* Gate immediately before the card network · Gate at the settlement adapter boundary · Revalidate only at authorization time
*What we chose:* One commit point at the `SettlementAdapter` boundary, with a separate earlier authorization point that can escalate to a human.
*Why:* A gate placed at the card network cannot escalate — by then the UCP session has passed `complete_in_progress` — and it leaves non-card rails such as x402 outside revocation. Two decision points with one commit point satisfy both the "refuse or escalate" requirement and rail agnosticism.

**Revocation state machine**
*Options considered:* Mandate transitions `ACTIVE → COMMITTED | REVOKED` · Reservation holds the commit transition · Both
*What we chose:* The mandate status is monotonic (`ACTIVE → REVOKED`); only the `Reservation` transitions to `COMMITTED`.
*Why:* An open mandate funds many purchases, so a mandate-level commit state is wrong by construction. Keeping both would give us two state machines answering the same question, which diverge under concurrency. The revocation-versus-purchase race is settled by a shared row lock, not by a state machine.

**Revocation proof mechanism**
*Options considered:* Commit-reveal `SHA256(secret)` · Signed revocation by a registered revocation key · Both
*What we chose:* Signed revocation (JWS ES256) by a registered `RevocationAuthority` as the primary mechanism; the hash commitment kept as an optional privacy feature on the production path.
*Why:* A hash commitment does not address the real registry failure modes — censorship and equivocation — and it cannot express partial scope, multiple revokers, or delegation. It also breaks the trial-by-fire path: a judge revoking without the user's secret would force us to hold the secret ourselves, at which point the commitment buys nothing over a database row.

**Revocation availability policy**
*Options considered:* Fail-open with a warning flag · Fail-closed with 503 · Cached last-known status
*What we chose:* Fail-closed. No `REVOCATION_ENFORCEMENT=warn` in any environment, and no cache on the commit path.
*Why:* The damage is asymmetric. A loose signature check in development risks an impostor with no money at stake; a loose revocation check is precisely the scenario the challenge asks us to handle. Any cache TTL on the commit path is a window where a live revocation is ignored.

---

## 15. Conclusão

A resposta curta à pergunta "como colocá-los no projeto com alta integração e sem conflito" é: **invertendo a pergunta**. Não se integram quatro protocolos entre si — isso produziria seis pares de acoplamento e um sistema frágil. Integra-se cada protocolo, uma vez, contra um núcleo único que é a autoridade sobre estado, política e dinheiro.

Feito assim, os conflitos aparentes desaparecem por construção:

- **Não há duas sessões de checkout** porque só existe um `CheckoutIntent`.
- **Não há três limites de gasto** porque `Allowance` e constraints são funções do orçamento vivo.
- **Não há quatro custódias de chave** porque há um `KeyCustodyService` e quatro codificações.
- **Não há disputa entre trilhos de liquidação** porque a reserva acontece no ledger antes de qualquer adaptador.
- **Não há módulos isolados** porque nenhum adaptador tem estado que justifique isolamento.
- **Não há dois lugares onde uma transação é comprometida** porque existe um único commit point, na fronteira do `SettlementAdapter`, e ele vale igualmente para cartão e para x402.

E o ponto que vale o pitch: os quatro protocolos, juntos, ainda **não resolvem o desafio 01**. Eles provam consentimento passado. Nenhum revoga, nenhum conta orçamento, nenhum impede double-spend, nenhum decide captura. O que os jurados vão testar no *trial by fire* é precisamente a lacuna comum aos quatro — e essa lacuna é o produto AVAL. A **Seção 11** é a especificação dela: uma camada de autorização e revogação em tempo real, posicionada imediatamente antes da execução do pagamento, agnóstica de trilho, com o mandato AP2 como evidência e o commit point como fronteira formal entre o que ainda pode ser retirado e o que já não pode.

---

## 16. Referências

**UCP**
- Especificação: `ucp.dev/latest/specification/overview/` (versão `2026-08-25`)
- Extensão AP2 Mandates: `ucp.dev/latest/specification/payment/extensions/ap2-mandates/`
- Message Signatures: `ucp.dev/latest/specification/signatures/`
- Repositório: `github.com/Universal-Commerce-Protocol/ucp` · Samples: `.../samples` · SDK Python: `.../python-sdk`
- Anúncio técnico: Google Developers Blog, 11/01/2026

**ACP**
- Repositório e specs: `github.com/agentic-commerce-protocol/agentic-commerce-protocol`
- Checkout: `spec/2026-04-17/openapi/openapi.agentic_checkout.yaml`
- Delegate Payment: `spec/2026-04-17/openapi/openapi.delegate_payment.yaml`
- Delegate Authentication: `spec/2026-04-17/openapi/openapi.delegate_authentication.yaml`
- Binding MCP: `docs/mcp-binding.md`

**AP2**
- Especificação v0.2: `ap2-protocol.org/ap2/specification/` · Fluxos: `.../ap2/flows/`
- Checkout Mandate: `.../ap2/checkout_mandate/` · Payment Mandate: `.../ap2/payment_mandate/`
- Repositório fixado no commit `e1ea56db72a6385bce3e5c1112b3a56ce60acb43`
- Doado à FIDO Alliance em 28/04/2026

**x402**
- Especificação v2: `github.com/coinbase/x402` → `specs/x402-specification-v2.md`
- Transporte HTTP: `specs/transports-v2/http.md`
- Scheme `exact`: `specs/schemes/exact/` · Scheme `upto`: `specs/schemes/upto/scheme_upto.md`
- x402 Foundation sob Linux Foundation desde 02/04/2026

**Revogação e autorização contínua** (Seção 11)
- W3C Bitstring Status List v1.0 — status revogável de credenciais verificáveis
- RFC 6960 — OCSP, e o padrão de *stapling* que inspira o `AuthorizationProof`
- RFC 7009 — OAuth 2.0 Token Revocation
- RFC 7662 — OAuth 2.0 Token Introspection
- RFC 9449 — DPoP (prova de posse ligada à requisição)
- RFC 9162 — Certificate Transparency (log append-only à prova de equivocação)
- OpenID Shared Signals Framework / CAEP — autorização contínua e sinais de mudança
- ISO 8583 — separação entre autorização e clearing, precedente do commit point

**RFCs relevantes**
- RFC 9421 — HTTP Message Signatures
- RFC 9530 — Digest Fields (`Content-Digest`)
- RFC 8785 — JSON Canonicalization Scheme (JCS)
- RFC 7515 Apêndice F — JWS com payload destacado
- RFC 7517 — JSON Web Key
- RFC 8941 — Structured Field Values (parsing do header `UCP-Agent`)

**Documentos internos**
- `docs/ap2-aval-integration-decision.md`
- `docs/hackathon-rules.md`
- `docs/decision-log.md`
