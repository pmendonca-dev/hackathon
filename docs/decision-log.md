# Decision Log

The decisions below are the ones that hold up the challenge's invariants —
mandate, verification, limits, revocation, audit and dispute — and the ones that
trade one real alternative for another. The complete Flight Log export, including
the operational decisions (migrations, packaging, work partition, test gates), is
in [`decision-log-full.md`](decision-log-full.md).

---

# Authority: who may spend, how much, and how many times

## Live authorization outcomes

**Decision:** Outcome for checkout policy violations before the capture commit point

**Options considered (one per line):**

Reject every policy violation immediately
Escalate recoverable scope and budget violations to a human while rejecting expired or revoked mandates
Allow protocol adapters to decide the outcome independently

**What we chose:** Escalate merchant-scope and budget violations to human approval, and reject missing, expired, or revoked mandates deterministically.

**Why:** This preserves the UCP `requires_escalation` path for consent that can be renewed while never silently authorizing a mandate that has lost validity or been revoked.

## Frequency as authority, not preference

**Decision:** where *"up to 3 times a month"* lives

**Options considered (one per line):**

In the agent, next to the target price, as a purchase preference
In the core, as a hard refusal with no approval path
In the core, on the ladder, approvable like the budget

**What we chose:** in the core, between the ceiling and the budget, with escalation
possible.

**Why:** frequency says *how many times* the agent may act, the same way the budget
says *how much* — it is authority, and authority does not live in the agent. Being
approvable is the right call: a human can say yes to a fourth purchase, while the
ceiling remains the only limit with no button. A use is burned by money actually held,
so a card declined by the processor does not eat one of the buyer's allowed purchases.

## The holder's key lives in the browser

**Decision:** how a judge produces a holder ES256 JWS from a page

**Options considered (one per line):**

Embed a trusted runtime key in a Vite variable
Have the server sign as `operator` on the holder's behalf
Have the browser generate and hold its own non-extractable key

**What we chose:** a P-256 pair generated in the browser with `extractable: false`, the
handle kept in IndexedDB, the public JWK registered as the mandate's authority at
creation.

**Why:** Vite variables are public assets, so the first option publishes the key. The
second gives the operator exactly the power the security model denies it — and would
break that model at the very point where it is being demonstrated. Keeping the
`CryptoKey` in IndexedDB is the only way to persist a non-extractable key: the browser
holds the material, the page holds a handle that signs and cannot read. There is no
export path in the module, and a structural test fails if one appears.

## Payment runtime authority boundary

**Decision:** Authority and composition boundary for ACP delegation and card settlement

**Options considered (one per line):**

Let ACP allowance and vault state become a second payment-policy source
Create a parallel demo capture flow outside the AuthorizationCore
Compose ACP, capture, PSP, receipts, and audit around live AuthorizationCore decisions

**What we chose:** Compose the runtime around AuthorizationCore as the exclusive authority; ACP projects a fresh allowance, and capture commits a Core reservation before the PSP receives a single-use proof.

**Why:** This preserves live revocation, canonical checkout scope, budget enforcement, durable retry behavior, and the post-commit settlement boundary without copying policy into adapters or allowing protocol-specific state to authorize a purchase.

## Authorization state persistence boundary

**Decision:** Persistence ownership for live authorization state

**Options considered (one per line):**

Keep authorization state in process memory
Let protocol adapters maintain separate persistent state
Persist core state through SQLite repositories owned and orchestrated exclusively by AuthorizationCore

**What we chose:** Persist mandates, live policy, and signed revocations in isolated SQLite repositories that are invoked only by AuthorizationCore.

**Why:** A process-local store loses live authority after restart, while adapter-owned state would create competing policy and revocation sources. The repository boundary keeps SQLite replaceable without allowing an adapter to become an alternate writer.

---

# Real-time revocation and the capture point

## Capture commit and retry boundary

**Decision:** Transaction boundary for capture, revocation, and retries

**Options considered (one per line):**

Commit a mandate when a capture starts
Call settlement before recording a committed reservation
Atomically commit a reservation in the core before settlement, with durable idempotency

**What we chose:** Under the SQLite immediate-write transaction, the core checks fresh revocation, claims idempotency, commits a reservation, and persists its capture attempt before calling settlement outside the lock.

**Why:** This gives revocation and capture one serial decision boundary, prevents an adapter from receiving an uncommitted reservation, retains a recoverable pending attempt during external I/O, and makes retries deterministic across process restarts.

## Shared mandate serialization

**Decision:** Serialization boundary for capture and signed revocation

**Options considered (one per line):**

Rely only on SQLite's database-wide writer lock
Use separate capture and revocation synchronization paths
Persist and acquire one lock record per mandate inside the shared write transaction

**What we chose:** Use one durable `mandate_locks` record per mandate, acquired by both capture and signed revocation in their `BEGIN IMMEDIATE` transactions.

**Why:** The explicit shared resource documents and enforces the commit race boundary independently of the current SQLite implementation, so a revocation and a capture cannot make conflicting pre-commit decisions.

## Canonical capture binding

**Decision:** Source of capture mandate, merchant, and amount

**Options considered (one per line):**

Trust mandate, merchant, and amount supplied by the capture caller
Duplicate those values into a payment-specific request policy
Load all capture scope from the persisted canonical checkout and validate its AP2 evidence before Core commit

**What we chose:** Capture accepts only a checkout identifier, opaque token, key-binding inputs, and AP2 closed checkout evidence; it derives authoritative scope from the canonical checkout.

**Why:** A caller-controlled total or merchant would create a second authorization representation. Verifying merchant authorization JCS/JWS and closed AP2 evidence against the persisted checkout blocks divergent values before a reservation, PSP call, receipt, or settlement audit event exists.

## Settlement evidence persistence

**Decision:** When AP2 receipts become durable runtime facts

**Options considered (one per line):**

Issue receipts when a payment token is delegated
Issue receipts when the Core reservation is committed
Issue and persist receipts only after the mock PSP approves settlement

**What we chose:** Issue checkout and payment receipts only after approved settlement, then persist them under the settled reservation identifier.

**Why:** A committed reservation can still be released when settlement declines. Tying immutable receipt issuance to the approved settlement result prevents the audit trail from claiming payment completion before the PSP outcome is known.

---

# Agent identity and the impostor agent

## Operational request authentication

**Decision:** Authentication boundary for payment runtime HTTP surfaces

**Options considered (one per line):**

Accept an unsigned local runtime header for ACP and capture calls
Apply RFC 9421 only to the original UCP checkout routes
Require RFC 9421 signatures over the raw request body on every operational payment POST and authenticated reader requests

**What we chose:** Reuse the trusted RFC 9421 agent registry and raw-body Content-Digest verifier for delegation, capture, receipt reads, and audit/dispute reads.

**Why:** Reusing the existing trust registry prevents a second identity authority and makes body tampering, unknown profiles, and signature failures fail before tokenization, Core authorization, or evidence disclosure.

## Authorization-proof replay storage

**Decision:** Storage boundary for one-use AuthorizationProof JTIs

**Options considered (one per line):**

Keep consumed JTIs in each process memory
Create a separate replay datastore for authorization proofs
Consume proof JTIs atomically in the shared durable idempotency store

**What we chose:** Store and atomically consume each AuthorizationProof JTI in the existing durable idempotency store under its own scope.

**Why:** Replay must remain blocked across new AuthorizationCore instances and process restarts. Reusing the transactionally protected idempotency store keeps one anti-replay authority instead of introducing a second, independently failing state source.

## Browser-safe UI authentication boundary

**Decision:** Authentication mechanism for live browser views and operator actions

**Options considered (one per line):**

Embed trusted RFC 9421 private keys in browser assets
Treat an unsigned browser cookie as equivalent to an agent signature on existing APIs
Add a same-origin session-authenticated BFF while preserving RFC 9421 for agent APIs

**What we chose:** Add a same-origin BFF with server-side role sessions and CSRF protection for browser views and operator commands; retain RFC 9421 and raw-body verification for agent-facing APIs.

**Why:** Browser assets cannot safely hold runtime signing keys, while an unsigned cookie does not satisfy the agent identity contract. A role-scoped BFF keeps private signing material in `KeyCustodyService`, applies the existing Core services without creating another policy authority, and enables an authenticated operator revocation without asking the browser to handle a JWS.

---

# Audit trail, dispute, and what each role can see

## The evaluation trace and who may read it

**Decision:** publishing the ladder the core walked, and to whom

**Options considered (one per line):**

Keep returning only the first refusal reason
Publish the trace in every response, including the merchant's
Publish the trace on the agent and holder surfaces, never on the merchant's

**What we chose:** `evaluation_trace` in `/authorize` and `/agent/purchase`; absent
from `/merchant/verify`, with a test that fails if it appears there.

**Why:** the ladder's order is the rule — authority before money — and returning only
the first reason made that order invisible. But the trace names limit, ceiling and
spend: a merchant that learned them would learn the buyer's budget from a receipt it
has every right to check.

## Mandatory scope on listings

**Decision:** how `GET /mandates` and `GET /escalations` answer without a known id

**Options considered (one per line):**

Global listing, optionally filterable by holder
Global listing protected by an operator token
Mandatory per-holder scope, with no global variant anywhere

**What we chose:** `principal_id` is required, and no global query exists anywhere in
the stack — the repositories only know how to answer per holder, and the escalations
one reaches its rows by joining the mandate that owns them.

**Why:** an unscoped listing would hand any caller every buyer in the system, their
limits, their spend and their pending purchases — the same disclosure the merchant view
exists to prevent. A holder with no mandates gets an empty list and not a 404, so the
route does not become an oracle of which ids exist.

## Browser projection scope for multi-merchant mandates

**Decision:** Merchant access to a mandate whose shared timeline cannot be partitioned safely

**Options considered (one per line):**

Return the complete mandate timeline to every merchant named by the mandate
Filter the current timeline heuristically by merchant fields
Deny merchant audit and dispute reads unless the mandate has exactly that merchant scope

**What we chose:** Deny merchant audit and dispute reads for multi-merchant
mandates; merchant reads are allowed only when the mandate scope is exactly the
merchant session's configured merchant.

**Why:** Current durable audit and dispute reconstruction contains mandate-level
facts and cannot prove that every event is attributable to one merchant. A
heuristic filter could disclose another merchant's checkout or settlement
facts, so the BFF fails closed until a future evidence model provides an
authoritative merchant partition.

## Revocation audit before settlement

**Decision:** Audit projection when a mandate is revoked before any capture

**Options considered (one per line):**

Hide the revocation timeline until a receipt exists
Create a synthetic settlement receipt for the audit reader
Return the append-only revocation timeline as incomplete evidence

**What we chose:** The dispute reader exposes a mandate's recorded revocation events even when no capture exists, returning an inconclusive evidence chain rather than inventing payment facts.

**Why:** A signed revocation is itself a durable authorization fact. It must be auditable immediately, while the absence of a reservation or receipt must remain explicit.

## The audit-trail tampering tool

**Decision:** how to offer the demonstration that the chain catches its own editor

**Options considered (one per line):**

Route always mounted, protected only by the operator token
Route always mounted, refusing with 403 when an environment variable is unset
Route not mounted unless `AVAL_DEMO_TAMPER` is enabled

**What we chose:** conditional mounting — without the variable the route does not exist
(a real 404, absent from OpenAPI), and with it it still requires an operator token.

**Why:** it is a tool for corrupting an audit log. A permission check can be
misconfigured to the permissive side; a route that was never registered cannot be.
There is no counterpart that repairs the chain: a route able to rewrite it into a valid
state would destroy the very property this one exists to prove.

---

# Live demo and trial by fire

## A monotonic demo clock

**Decision:** which direction `POST /admin/clock` may move time

**Options considered (one per line):**

Allow advancing and rewinding, so the team can re-stage the demo
Accept a negative value and silently treat it as zero
Advance only, refusing negative and zero with 422

**What we chose:** monotonic, with an explicit 422.

**Why:** advancing only takes authority away — mandates expire, nothing is granted.
Rewinding would revive an expired mandate, which is an operator handing back spending
authority that the holder's own validity had already ended. Refusing silently would be
worse than refusing loudly: the judge would believe they had rewound time without
having rewound it.

## No fixtures behind the browser

**Decision:** what the page shows when the runtime does not answer

**Options considered (one per line):**

Fall back to fixtures labelled as mock
Keep the last known projection in cache
Say the runtime did not answer, and show nothing else

**What we chose:** an explicit unavailable state; no fixture module survived in
`web/src`.

**Why:** a page that fills itself with invented data when the server goes down is
indistinguishable from one that works, exactly when that difference matters most — in
front of a judge testing the system live. And a network failure rendered as a refusal
would say the mandate said no when it was never asked.

## An LLM in the proposing half, with the rules as the floor

**Decision:** whether a real model goes into the buying agent

**Options considered (one per line):**

Keep rules only — no key, no timeout, no risk on stage
Replace the rules with a model, requiring a credential to run the case
An optional model, with automatic fallback to the rules

**What we chose:** `AVAL_LLM_AGENT=1` plus a credential turn the model on; any failure
falls back to the rules, and the unconfigured default is the rules.

**Why:** the case speaks of an agent that *hallucinates a purchase*, and a rule-based
reader does not hallucinate — the demonstration could only assert that the core would
hold, never show it. A real model proposes genuinely wrong things and is refused just
the same. The model is **not told the limit, the ceiling or the balance**: beyond being
unnecessary for reading a sentence, sending the buyer's budget to a third party would
be the leak the rest of the system avoids, and a prompt-injected model has no private
number to repeat.

---

# Foundation

## Runtime and persistence foundation

**Decision:** Runtime and persistence foundation for the AVAL demonstration

**Options considered (one per line):**

Use the locally available Python 3.13 runtime with FastAPI, SQLAlchemy, Alembic, and SQLite WAL
Adopt an AP2 reference application or SDK as the application foundation
Introduce a separate service or frontend stack before the authorization core exists

**What we chose:** Use Python 3.13 with FastAPI, SQLAlchemy, Alembic, and SQLite WAL, with AVAL-owned domain and persistence code.

**Why:** The historical AP2 review identified Python as the compatible ecosystem while explicitly excluding its sample applications. SQLite WAL with `BEGIN IMMEDIATE` and a single writer is the documented demo boundary; it keeps durable authorization state local and leaves repositories isolatable for a later Postgres migration.
