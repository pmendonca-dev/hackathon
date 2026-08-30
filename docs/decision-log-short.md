# Decision Log — the twelve

The decisions we expect to be asked to defend, four lines each. The full argument
for every one of these is in [`decision-log.md`](decision-log.md); the complete
Flight Log export is in [`decision-log-full.md`](decision-log-full.md).

## Authority

### Outcomes for a purchase that breaks the mandate

- **Decision** — what happens before money moves.
- **Chose** — scope and budget violations escalate to the human; missing, expired or revoked mandates are refused outright.
- **Instead of** — refusing everything; letting each protocol adapter decide.
- **Why** — consent that can still be renewed deserves a human. Validity that has ended is not a question anyone can answer yes to.

### Frequency as authority, not preference

- **Decision** — where *"up to 3 times a month"* lives.
- **Chose** — in the core, on the ladder between the ceiling and the budget, approvable like the budget.
- **Instead of** — in the agent as a purchase preference; in the core as a hard refusal with no approval path.
- **Why** — frequency says *how many times*, as the budget says *how much*: authority, and authority does not live in the agent. A use is burned by money actually held, so a declined card does not eat one of the buyer's purchases.

### The holder's key lives in the browser

- **Decision** — how a judge produces a holder-signed ES256 JWS from a page.
- **Chose** — a P-256 pair generated in the browser with `extractable: false`, the handle in IndexedDB, the public JWK registered as the mandate's authority.
- **Instead of** — a runtime key in a Vite variable; the server signing as `operator` on the holder's behalf.
- **Why** — Vite variables are public assets. And an operator that can sign as the holder breaks the security model at the exact point where it is being demonstrated.

### One authority, not one per adapter

- **Decision** — who decides a purchase once ACP, the PSP, receipts and audit exist.
- **Chose** — `AuthorizationCore` alone: ACP projects a fresh allowance, capture commits a reservation, and only then does the PSP see a single-use proof.
- **Instead of** — letting ACP allowance and vault state become a second policy source; a parallel demo capture path.
- **Why** — policy copied into an adapter is a second answer to the same question, and it is the one nobody revokes.

## Revocation and the capture point

### The commit boundary shared by capture and revocation

- **Decision** — the transaction boundary for capture, revocation and retries.
- **Chose** — inside one immediate-write transaction: check fresh revocation, claim idempotency, commit the reservation, persist the attempt — then call settlement outside the lock.
- **Instead of** — committing the mandate when capture starts; calling settlement before recording the reservation.
- **Why** — revocation and capture need one serial decision point, or a revocation lands mid-purchase and nobody can say which one won.

### Capture reads its scope, it does not accept it

- **Decision** — where capture gets the mandate, merchant and amount.
- **Chose** — from the persisted canonical checkout; the caller supplies only a checkout id, an opaque token, key-binding inputs and AP2 evidence.
- **Instead of** — trusting the values the caller sends; duplicating them into a payment-side policy.
- **Why** — a caller-controlled total is a second authorization representation, and the cheaper of the two to forge.

## Agent identity

### Every operational call is signed

- **Decision** — who may call the payment surfaces.
- **Chose** — RFC 9421 signatures over the raw body on every operational POST and authenticated read, through the existing agent registry.
- **Instead of** — an unsigned local runtime header; signing only the original checkout routes.
- **Why** — one trust registry, not two. Body tampering, unknown profiles and bad signatures fail before tokenization, authorization or any disclosure.

## Audit and dispute

### The evaluation trace, and who may read it

- **Decision** — publishing the ladder the core walked, and to whom.
- **Chose** — `evaluation_trace` on the agent and holder surfaces; absent from `/merchant/verify`, with a test that fails if it appears there.
- **Instead of** — returning only the first refusal reason; returning the trace to everyone.
- **Why** — the order of the ladder is the rule, authority before money. But the trace names limit, ceiling and spend: a merchant checking a receipt it has every right to check would learn the buyer's budget.

### A revocation is auditable before any purchase exists

- **Decision** — what the audit shows for a mandate revoked before any capture.
- **Chose** — the append-only revocation timeline, returned as an explicitly inconclusive evidence chain.
- **Instead of** — hiding the timeline until a receipt exists; synthesising a settlement receipt for the reader.
- **Why** — a signed revocation is itself a durable authorization fact. The absence of a receipt has to stay visible as absence.

### The tampering tool that cannot be left on

- **Decision** — how to demonstrate that the chain catches its own editor.
- **Chose** — a route that is not mounted unless `AVAL_DEMO_TAMPER` is set — a real 404, absent from OpenAPI — and that still requires an operator token.
- **Instead of** — always mounted behind the operator token; always mounted, refusing with 403 when the variable is unset.
- **Why** — a permission check can be misconfigured open; a route that was never registered cannot be. There is deliberately no counterpart that repairs the chain.

## Live demo

### The demo clock only moves forward

- **Decision** — which direction `POST /admin/clock` may move time.
- **Chose** — forward only; negative and zero refused with an explicit 422.
- **Instead of** — advance and rewind, so the team can re-stage the demo; accept a negative value and silently treat it as zero.
- **Why** — advancing only takes authority away. Rewinding revives an expired mandate: an operator handing back spending power that the holder's own validity had already ended.

### A real model in the half that proposes

- **Decision** — whether a real LLM goes into the buying agent.
- **Chose** — `AVAL_LLM_AGENT=1` plus a credential turn it on; any failure falls back to the rules, and unconfigured means rules.
- **Instead of** — rules only, with no key and no risk on stage; the model as a hard requirement to run the case.
- **Why** — the case describes an agent that *hallucinates a purchase*, and a rule reader cannot hallucinate. A real model proposes genuinely wrong things and is refused just the same — and it is never told the limit, the ceiling or the balance.
