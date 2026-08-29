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

## Mandate purchase scope

**Decision:** How a mandate expresses what may be bought, not only how much

**Options considered (one per line):**

Carry the category on the signed offer and let the merchant enforce it
Add an allowed category set to the mandate and evaluate it in the authorization core
Treat the merchant allow list as a sufficient proxy for the purchase scope

**What we chose:** The mandate declares a non-empty set of allowed categories, the authorization command carries the category of the purchase, and the core escalates a category outside that set with `category_not_allowed`.

**Why:** The challenge states that a mandate defines what may be bought with limits on amount, category and validity, and names a forbidden category among the cases that must never pass silently. Carrying the category only on the offer would have left it signed, transported and then ignored, because the edge is not allowed to decide. Escalation rather than rejection matches the treatment of an out-of-scope merchant: both are scope violations that a human may still resolve, while integrity and validity failures stay hard rejections.

## Mandate hard ceiling

**Decision:** Whether any amount exists that human approval cannot unlock

**Options considered (one per line):**

Escalate every amount above the live budget and let the principal approve it
Give the mandate a fixed ceiling above which the decision is a rejection with no approval path
Treat the live limit itself as the ceiling

**What we chose:** A mandate may carry an optional ceiling fixed at creation. An amount above it is rejected with `mandate_ceiling` and offers no approval, while an amount within the ceiling but beyond the live budget still escalates.

**Why:** Without a ceiling, an agent that can trigger an approval prompt can eventually reach any amount, which makes the mandate a suggestion rather than an authority. Fixing the ceiling at creation and moving only the budget keeps the live limit useful to a judge without letting a limit change raise the bound: `replace_live_limit` alters the budget and leaves the ceiling untouched, which is covered by a test.

## Authorization proof audience

**Decision:** What the merchant learns from the proof it is asked to verify

**Options considered (one per line):**

Keep the proof bound to the reservation and let the merchant re-query the authorization layer
Bind the offer terms, merchant and amount into the proof while omitting the mandate and the principal
Include the mandate identifier so the merchant can recompute the transaction hash

**What we chose:** The proof payload carries the checkout, merchant, amount, money unit and terms hash, and omits the mandate identifier and the principal.

**Why:** The merchant view of the ledger deliberately hides the mandate and the budget, so a proof that could only be checked with the mandate identifier left the merchant verifying nothing and trusting a response instead. Binding the terms hash lets the merchant confirm that the proof answers the exact offer it signed, at the price it signed, without learning who the buyer is or what remains of their budget. The transaction hash stays in the payload as an opaque commitment that an auditor can bind to the reservation.

## Dispute resolution rule

**Decision:** What decides a later denial of a purchase

**Options considered (one per line):**

Record the dispute and resolve it manually outside the system
Resolve by reading the trail: an authorization proof bound to a committed reservation answers the claim
Treat any dispute as upheld until the merchant produces evidence

**What we chose:** Opening a dispute records it and decides nothing. Resolution reads the trail, and the presence of an authorization proof over a committed or settled reservation resolves the dispute as `MANDATE_HELD`, its absence as `MANDATE_FAILED`.

**Why:** The challenge requires a later dispute to be handled explicitly, and its bonus asks the auditable trail to decide who is right. Making the proof the deciding artefact means the answer is derived from evidence the system already produces at the commit point rather than from a new claim, and it gives the enriched proof payload a second use: the resolution quotes the merchant, amount and terms hash the proof binds.
