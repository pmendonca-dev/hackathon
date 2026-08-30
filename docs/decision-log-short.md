# Decision Log — the twelve

The decisions we expect to be asked to defend, in the four fields the Flight Log
asks for. The full argument for every one of them is in
[`decision-log.md`](decision-log.md); the complete export is in
[`decision-log-full.md`](decision-log-full.md) and at the repository root as
[`DECISION_LOG.md`](../DECISION_LOG.md).

## Authority

### Outcomes for a purchase that breaks the mandate

**Decision:** what happens before money moves

**Options considered (one per line):**

Escalating recoverable violations while refusing invalid mandates
Refusing everything
Letting each protocol adapter decide

**What we chose:** scope and budget violations escalate to the human; missing, expired or revoked mandates are refused outright.

**Why:** consent that can still be renewed deserves a human. Validity that has ended is not a question anyone can answer yes to.

### Frequency as authority, not preference

**Decision:** where *"up to 3 times a month"* lives

**Options considered (one per line):**

In the core, on the ladder, approvable
In the agent as a purchase preference
In the core as a hard refusal with no approval path

**What we chose:** in the core, on the ladder between the ceiling and the budget, approvable like the budget.

**Why:** frequency says *how many times*, as the budget says *how much*: authority, and authority does not live in the agent. A use is burned by money actually held, so a declined card does not eat one of the buyer's purchases.

### The holder's key lives in the browser

**Decision:** how a judge produces a holder-signed ES256 JWS from a page

**Options considered (one per line):**

A non-extractable key the browser generates and keeps
A runtime key in a Vite variable
The server signing as `operator` on the holder's behalf

**What we chose:** a P-256 pair generated in the browser with `extractable: false`, the handle in IndexedDB, the public JWK registered as the mandate's authority.

**Why:** Vite variables are public assets. And an operator that can sign as the holder breaks the security model at the exact point where it is being demonstrated.

### One authority, not one per adapter

**Decision:** who decides a purchase once ACP, the PSP, receipts and audit exist

**Options considered (one per line):**

AuthorizationCore as the only decider
Letting ACP allowance and vault state become a second policy source
A parallel demo capture path

**What we chose:** `AuthorizationCore` alone: ACP projects a fresh allowance, capture commits a reservation, and only then does the PSP see a single-use proof.

**Why:** policy copied into an adapter is a second answer to the same question, and it is the one nobody revokes.

## Revocation and the capture point

### The commit boundary shared by capture and revocation

**Decision:** the transaction boundary for capture, revocation and retries

**Options considered (one per line):**

One transaction that checks revocation, claims idempotency and commits the reservation
Committing the mandate when capture starts
Calling settlement before recording the reservation

**What we chose:** inside one immediate-write transaction: check fresh revocation, claim idempotency, commit the reservation, persist the attempt — then call settlement outside the lock.

**Why:** revocation and capture need one serial decision point, or a revocation lands mid-purchase and nobody can say which one won.

### Capture reads its scope, it does not accept it

**Decision:** where capture gets the mandate, merchant and amount

**Options considered (one per line):**

Deriving the scope from the persisted canonical checkout
Trusting the values the caller sends
Duplicating them into a payment-side policy

**What we chose:** from the persisted canonical checkout; the caller supplies only a checkout id, an opaque token, key-binding inputs and AP2 evidence.

**Why:** a caller-controlled total is a second authorization representation, and the cheaper of the two to forge.

## Agent identity

### Every operational call is signed

**Decision:** who may call the payment surfaces

**Options considered (one per line):**

RFC 9421 on every operational POST and authenticated read
An unsigned local runtime header
Signing only the original checkout routes

**What we chose:** RFC 9421 signatures over the raw body on every operational POST and authenticated read, through the existing agent registry.

**Why:** one trust registry, not two. Body tampering, unknown profiles and bad signatures fail before tokenization, authorization or any disclosure.

## Audit and dispute

### The evaluation trace, and who may read it

**Decision:** publishing the ladder the core walked, and to whom

**Options considered (one per line):**

The trace on the agent and holder surfaces only
Returning only the first refusal reason
Returning the trace to everyone

**What we chose:** `evaluation_trace` on the agent and holder surfaces; absent from `/merchant/verify`, with a test that fails if it appears there.

**Why:** the order of the ladder is the rule, authority before money. But the trace names limit, ceiling and spend: a merchant checking a receipt it has every right to check would learn the buyer's budget.

### A revocation is auditable before any purchase exists

**Decision:** what the audit shows for a mandate revoked before any capture

**Options considered (one per line):**

The revocation timeline, returned as inconclusive evidence
Hiding the timeline until a receipt exists
Synthesising a settlement receipt for the reader

**What we chose:** the append-only revocation timeline, returned as an explicitly inconclusive evidence chain.

**Why:** a signed revocation is itself a durable authorization fact. The absence of a receipt has to stay visible as absence.

### The tampering tool that cannot be left on

**Decision:** how to demonstrate that the chain catches its own editor

**Options considered (one per line):**

A route that is not mounted unless a variable is set
Always mounted behind the operator token
Always mounted, refusing with 403 when the variable is unset

**What we chose:** a route that is not mounted unless `AVAL_DEMO_TAMPER` is set — a real 404, absent from OpenAPI — and that still requires an operator token.

**Why:** a permission check can be misconfigured open; a route that was never registered cannot be. There is deliberately no counterpart that repairs the chain.

## Live demo

### The demo clock only moves forward

**Decision:** which direction `POST /admin/clock` may move time

**Options considered (one per line):**

Forward only, refusing the rest with 422
Advance and rewind, so the team can re-stage the demo
Accept a negative value and silently treat it as zero

**What we chose:** forward only; negative and zero refused with an explicit 422.

**Why:** advancing only takes authority away. Rewinding revives an expired mandate: an operator handing back spending power that the holder's own validity had already ended.

### A real model in the half that proposes

**Decision:** whether a real LLM goes into the buying agent

**Options considered (one per line):**

An optional model with automatic fallback to the rules
Rules only, with no key and no risk on stage
The model as a hard requirement to run the case

**What we chose:** `AVAL_LLM_AGENT=1` plus a credential turn it on; any failure falls back to the rules, and unconfigured means rules.

**Why:** the case describes an agent that *hallucinates a purchase*, and a rule reader cannot hallucinate. A real model proposes genuinely wrong things and is refused just the same — and it is never told the limit, the ceiling or the balance.
