# Decision Log

## Technical coverage objective

**Decision:** Primary product objective for the hackathon solution

**Options considered (one per line):**
Prioritize a distinctive business proposition
Prioritize the strongest technical capability with broad, efficient case coverage

**What we chose:** Prioritize building the tool with the strongest technical capability, designed to handle the largest practical set of cases efficiently, without business differentiation as the objective.

**Why:** The team selected technical breadth, robustness, and efficient handling of varied scenarios as the success criteria for the project. Business differentiation will not drive product decisions within this scope.

## Runtime and persistence foundation

**Decision:** Runtime and persistence foundation for the AVAL demonstration

**Options considered (one per line):**

Use the locally available Python 3.13 runtime with FastAPI, SQLAlchemy, Alembic, and SQLite WAL
Adopt an AP2 reference application or SDK as the application foundation
Introduce a separate service or frontend stack before the authorization core exists

**What we chose:** Use Python 3.13 with FastAPI, SQLAlchemy, Alembic, and SQLite WAL, with AVAL-owned domain and persistence code.

**Why:** The historical AP2 review identified Python as the compatible ecosystem while explicitly excluding its sample applications. SQLite WAL with `BEGIN IMMEDIATE` and a single writer is the documented demo boundary; it keeps durable authorization state local and leaves repositories isolatable for a later Postgres migration.

## Live authorization outcomes

**Decision:** Outcome for checkout policy violations before the capture commit point

**Options considered (one per line):**

Reject every policy violation immediately
Escalate recoverable scope and budget violations to a human while rejecting expired or revoked mandates
Allow protocol adapters to decide the outcome independently

**What we chose:** Escalate merchant-scope and budget violations to human approval, and reject missing, expired, or revoked mandates deterministically.

**Why:** This preserves the UCP `requires_escalation` path for consent that can be renewed while never silently authorizing a mandate that has lost validity or been revoked.

## Authorization state persistence boundary

**Decision:** Persistence ownership for live authorization state

**Options considered (one per line):**

Keep authorization state in process memory
Let protocol adapters maintain separate persistent state
Persist core state through SQLite repositories owned and orchestrated exclusively by AuthorizationCore

**What we chose:** Persist mandates, live policy, and signed revocations in isolated SQLite repositories that are invoked only by AuthorizationCore.

**Why:** A process-local store loses live authority after restart, while adapter-owned state would create competing policy and revocation sources. The repository boundary keeps SQLite replaceable without allowing an adapter to become an alternate writer.

## Capture commit and retry boundary

**Decision:** Transaction boundary for capture, revocation, and retries

**Options considered (one per line):**

Commit a mandate when a capture starts
Call settlement before recording a committed reservation
Atomically commit a reservation in the core before settlement, with durable idempotency

**What we chose:** Under the SQLite immediate-write transaction, the core checks fresh revocation, claims idempotency, commits a reservation, and persists its capture attempt before calling settlement outside the lock.

**Why:** This gives revocation and capture one serial decision boundary, prevents an adapter from receiving an uncommitted reservation, retains a recoverable pending attempt during external I/O, and makes retries deterministic across process restarts.

## Human channel for mandates and escalation

**Decision:** Interface through which the human creates mandates, approves escalations and revokes authority

**Options considered (one per line):**

Build a web dashboard as the only human surface
Use a Telegram bot as the human channel, with the web surface reserved for merchant and auditor views
Expose the authorization API directly and leave the human interface out of scope

**What we chose:** A Telegram bot is the human channel for mandate creation, escalation approval, revocation and purchase receipts; the web application serves the merchant and auditor views.

**Why:** An escalation must reach the person, not wait for them to be watching a dashboard. Telegram delivers the approval request as a push to a device the human already carries, which is what makes `awaiting_human` a real round trip rather than a dead end. Long polling also removes the inbound webhook requirement, so the bot runs from a laptop with only outbound connectivity and no tunnel to fail during the live evaluation.

## Trust boundary for the language model

**Decision:** Position of the purchasing agent's language model relative to the authorization decision

**Options considered (one per line):**

Let the model decide whether a purchase is permitted, constrained by prompt instructions
Let the model discover and propose purchases while the deterministic core decides authorization
Avoid a language model and script the agent's purchasing behaviour

**What we chose:** The language model discovers offers and proposes purchases; every authorization decision is made by `AuthorizationCore` from persisted mandate state, and the model is never in the trust path.

**Why:** A defence implemented as prompt instructions fails against the next jailbreak and cannot be audited. Keeping the model outside the trust boundary means an adversarial instruction can be attempted honestly and still refused deterministically, with a reason code and a ledger entry. It also converts the adversarial-agent bonus into a property of the architecture rather than a feature to be built separately.

## Judge interaction surface during trial by fire

**Decision:** How judges operate the system during the unrehearsed live evaluation

**Options considered (one per line):**

The team drives the system while judges request changes verbally
Judges operate the Telegram bot directly from their own devices
Provide judges with a separate administrative console

**What we chose:** Judges use the Telegram bot from their own phones to create mandates, change limits, revoke authority and instruct the agent in free text.

**Why:** The evaluation rules require the system to react to unrehearsed judge input without manual intervention from the team. Handing judges the same channel the principal uses removes the team from the loop entirely, and lets a judge phrase an attack in their own words rather than choosing from a rehearsed menu. This requires that live limit and revocation reads are never cached, which is already the behaviour of `replace_live_limit` and the in-transaction revocation read.

## Merchant offer authenticity

**Decision:** Whether a merchant offer carries its own signature

**Options considered (one per line):**

Publish a plain price catalogue the agent quotes back to the authorization layer
Have the merchant sign each offer, with the terms hash computed over its canonical form
Let the authorization layer own the catalogue and price list

**What we chose:** The merchant signs each offer as a compact JWS over the offer payload, and the terms hash is the SHA-256 of its RFC 8785 canonical serialization, stored as the checkout intent's canonical payload.

**Why:** A merchant that cannot verify anything is not verifying: the mandatory requirement is that the merchant confirms the purchase before accepting it, which needs an artefact bound to price, item and expiry. Canonical serialization is what lets merchant and core agree byte for byte on what was agreed, and `rfc8785` is already a project dependency for exactly this. It also makes the terms hash meaningful evidence in a later dispute rather than an opaque string.

## Payment credential scope

**Decision:** Form of the payment credential the purchasing agent holds

**Options considered (one per line):**

Store the card in a vault and give the agent a reusable vault token
Issue a credential scoped to a single mandate, checkout, merchant, ceiling and expiry
Let the agent hold the payment method directly

**What we chose:** Issue a per-checkout scoped credential carrying mandate, checkout intent, merchant, maximum amount and expiry, matching the existing `vault_tokens` schema.

**Why:** A reusable vault token still authorizes value outside the transaction it was issued for, so a leaked token remains dangerous. Binding the credential to one checkout and one merchant with its own ceiling means a stolen credential authorizes nothing new. This satisfies the challenge requirement of never handing over the raw card in a stronger form: the card is not protected within the system, it is never present in it.

## Settlement failure semantics

**Decision:** System behaviour when the payment processor gives no definitive response

**Options considered (one per line):**

Treat a timeout as a decline and release the reserved budget
Leave the reservation committed and the capture attempt pending until reconciliation resolves it
Retry settlement inline until it answers

**What we chose:** A settlement timeout leaves the reservation committed, the capture attempt pending and the idempotency claim held, with a separate reconciliation pass completing the attempt once the processor answers.

**Why:** Releasing budget on a timeout can release funds for a payment that settled on the other side, which is the double-spend this design exists to prevent. The current `capture` implementation already produces this state when the adapter raises, because the completion step never runs; what was missing is the reconciler, not the fail-closed behaviour. Inline retries would hold the write transaction open across external I/O, which the capture boundary deliberately avoids.

## Protocol integration surface

**Decision:** Where multi-protocol support lives in the system

**Options considered (one per line):**

The purchasing agent discovers each merchant protocol and adapts its own requests
The authorization layer exposes protocol-specific ingress adapters over one canonical core
Each supported protocol gets its own store service with its own state

**What we chose:** The authorization layer decodes and encodes each protocol at its HTTP edge over a single canonical core, and selects the encoder from the merchant profile rather than from a request parameter.

**Why:** The integration architecture already established that no protocol may carry its own state, policy or source of truth, and three artefacts were built on that premise: the UCP and ACP status projections in `checkout_status.py`, the per-surface namespace in `IdempotencyStore.get_or_claim`, and the seeded UCP discovery profile. Agent-side routing would leave all three without a reason to exist and would move the work into a component that does not exist yet. Reading the protocol from the merchant profile keeps routing data-driven, so adding a second store is a row and a service rather than a refactor.

## Merchant offer signature form

**Decision:** Wire form of the merchant authorization over an offer

**Options considered (one per line):**

Reuse the existing attached compact JWS helper at no implementation cost
Implement the detached form over the RFC 8785 canonical payload as recorded in the protocol validation

**What we chose:** Detached JWS, protected header and signature with the payload omitted, signed over the JCS serialization of the offer.

**Why:** The protocol validation record already states that the AP2 merchant authorization is detached over JCS. A code path that contradicts a published validation record costs more in technical defence than the small amount of code the detached form requires, and the raw ES256 helpers it needs already exist. The attached compact JWS keeps its own separate role, where its payload encoding is deliberately not JCS.
