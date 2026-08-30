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

## Incremental authorization-schema evolution

**Decision:** Alembic strategy for authorization-core schema hardening

**Options considered (one per line):**

Keep `0001_initial_core` coupled to current SQLAlchemy metadata
Reset migrated demo databases when the schema changes
Freeze the historical initial schema and apply a forward-only incremental migration

**What we chose:** Preserve `0001_initial_core` as the original schema and add `0002_authorization_hardening` for persisted mandate fields and uniqueness constraints.

**Why:** A metadata-driven initial migration silently leaves an existing database stamped at `0001` without subsequent columns or constraints. An explicit forward migration upgrades both clean and already-migrated databases without treating a reset as a correctness mechanism.

## Authorization-proof replay storage

**Decision:** Storage boundary for one-use AuthorizationProof JTIs

**Options considered (one per line):**

Keep consumed JTIs in each process memory
Create a separate replay datastore for authorization proofs
Consume proof JTIs atomically in the shared durable idempotency store

**What we chose:** Store and atomically consume each AuthorizationProof JTI in the existing durable idempotency store under its own scope.

**Why:** Replay must remain blocked across new AuthorizationCore instances and process restarts. Reusing the transactionally protected idempotency store keeps one anti-replay authority instead of introducing a second, independently failing state source.

## Parallel implementation ownership

**Decision:** Work partition across two independent implementation laptops

**Options considered (one per line):**

Split work by arbitrary features across both laptops
Give both laptops access to all files and resolve conflicts later
Assign disjoint protocol/core and payments/UI ownership boundaries with a committed handoff contract

**What we chose:** Laptop A owns UCP/AP2 protocol and checkout work, while Laptop B owns ACP, settlement/receipts/audit and web work; shared files change only through an explicit handoff commit.

**Why:** The partition minimizes simultaneous edits to the same persistence and application files while allowing ACP, PSP, audit, and UI work to proceed independently of UCP checkout implementation. A committed API contract gives the UI a stable integration target without creating a second business authority.

## Durable retry retention

**Decision:** Retention boundary for durable idempotency records

**Options considered (one per line):**

Keep completed retries indefinitely
Delete retries opportunistically without a persisted deadline
Persist a retention deadline of at least 24 hours and clean up only after it expires

**What we chose:** Persist `retained_until` for every idempotency record with a minimum 24-hour retention period.

**Why:** A durable deadline preserves deterministic replay through process restarts while making deletion explicit and auditable instead of relying on memory or implicit database cleanup.

## Shared mandate serialization

**Decision:** Serialization boundary for capture and signed revocation

**Options considered (one per line):**

Rely only on SQLite's database-wide writer lock
Use separate capture and revocation synchronization paths
Persist and acquire one lock record per mandate inside the shared write transaction

**What we chose:** Use one durable `mandate_locks` record per mandate, acquired by both capture and signed revocation in their `BEGIN IMMEDIATE` transactions.

**Why:** The explicit shared resource documents and enforces the commit race boundary independently of the current SQLite implementation, so a revocation and a capture cannot make conflicting pre-commit decisions.

## Payment runtime authority boundary

**Decision:** Authority and composition boundary for ACP delegation and card settlement

**Options considered (one per line):**

Let ACP allowance and vault state become a second payment-policy source
Create a parallel demo capture flow outside the AuthorizationCore
Compose ACP, capture, PSP, receipts, and audit around live AuthorizationCore decisions

**What we chose:** Compose the runtime around AuthorizationCore as the exclusive authority; ACP projects a fresh allowance, and capture commits a Core reservation before the PSP receives a single-use proof.

**Why:** This preserves live revocation, canonical checkout scope, budget enforcement, durable retry behavior, and the post-commit settlement boundary without copying policy into adapters or allowing protocol-specific state to authorize a purchase.

## Settlement evidence persistence

**Decision:** When AP2 receipts become durable runtime facts

**Options considered (one per line):**

Issue receipts when a payment token is delegated
Issue receipts when the Core reservation is committed
Issue and persist receipts only after the mock PSP approves settlement

**What we chose:** Issue checkout and payment receipts only after approved settlement, then persist them under the settled reservation identifier.

**Why:** A committed reservation can still be released when settlement declines. Tying immutable receipt issuance to the approved settlement result prevents the audit trail from claiming payment completion before the PSP outcome is known.

## Runtime seed preservation

**Decision:** Startup behavior for already persisted demo mandates

**Options considered (one per line):**

Rewrite the seed mandate every time the FastAPI runtime starts
Create the seed mandate only when its identifier is absent
Keep the mandate only in process memory

**What we chose:** Seed the demo mandate only on an empty durable runtime and preserve it unchanged on subsequent starts.

**Why:** Rewriting a persisted mandate would silently extend expiry or replace policy/revocation facts after a restart, which contradicts continuous authorization and durable audit requirements.

## Operational request authentication

**Decision:** Authentication boundary for payment runtime HTTP surfaces

**Options considered (one per line):**

Accept an unsigned local runtime header for ACP and capture calls
Apply RFC 9421 only to the original UCP checkout routes
Require RFC 9421 signatures over the raw request body on every operational payment POST and authenticated reader requests

**What we chose:** Reuse the trusted RFC 9421 agent registry and raw-body Content-Digest verifier for delegation, capture, receipt reads, and audit/dispute reads.

**Why:** Reusing the existing trust registry prevents a second identity authority and makes body tampering, unknown profiles, and signature failures fail before tokenization, Core authorization, or evidence disclosure.

## Canonical capture binding

**Decision:** Source of capture mandate, merchant, and amount

**Options considered (one per line):**

Trust mandate, merchant, and amount supplied by the capture caller
Duplicate those values into a payment-specific request policy
Load all capture scope from the persisted canonical checkout and validate its AP2 evidence before Core commit

**What we chose:** Capture accepts only a checkout identifier, opaque token, key-binding inputs, and AP2 closed checkout evidence; it derives authoritative scope from the canonical checkout.

**Why:** A caller-controlled total or merchant would create a second authorization representation. Verifying merchant authorization JCS/JWS and closed AP2 evidence against the persisted checkout blocks divergent values before a reservation, PSP call, receipt, or settlement audit event exists.
## Browser runtime source selection

**Decision:** Default browser data source for the live demo

**Options considered (one per line):**

Keep the fixture gateway as the default until all runtime endpoints are merged
Fall back silently from HTTP to fixtures when the runtime is unavailable
Use HTTP by default and permit fixtures only behind an explicit development-only flag

**What we chose:** `HttpAvalGateway` is the default. The fixture gateway is selected only when Vite is in development mode and `VITE_AVAL_USE_MOCK=true`; the UI then renders a persistent mock-data provenance strip.

**Why:** A silent or default fixture can make presentation data look like canonical state and can make a demo appear successful while the runtime is unavailable. An explicit development gate keeps fixtures useful for layout work without weakening live-demo evidence.

## Trial command availability

**Decision:** Administrative commands exposed by the browser

**Options considered (one per line):**

Simulate unsupported limit, scope, and budget commands locally
Invent HTTP endpoints that are not in the published runtime contract
Enable only commands backed by authenticated, idempotent, audited runtime endpoints

**What we chose:** The browser will enable signed mandate revocation after the runtime is integrated. Limit reduction, scope change, and budget-zero remain visibly unavailable because the published contract does not define those APIs.

**Why:** Local mutation would create a second authority and speculative endpoints would couple the UI to an imaginary protocol. The signed revocation endpoint is the only published administrative seam that can provide a real authenticated and auditable effect.

## Live workspace composition

**Decision:** Projection strategy for human, merchant, and auditor views

**Options considered (one per line):**

Populate missing live fields with fixture literals or browser-derived policy
Require an undocumented aggregate workspace endpoint
Compose only the published capture, receipt, audit, and dispute responses and render unavailable fields as unavailable

**What we chose:** The live UI will compose documented read-only runtime responses identified by configured mandate and capture IDs, without synthesizing mandate limits, private budgets, identity, or authorization state.

**Why:** The payment runtime contract intentionally exposes no aggregate workspace or mandate-detail response. Rendering only returned facts preserves `AuthorizationCore` as the sole source of truth and prevents merchant-visible leakage of private fields.

## Task 12 runtime conformance gate

**Decision:** When Task 12 may be reported green

**Options considered (one per line):**

Treat Laptop A's focused integration tests as sufficient E2E evidence
Adapt Laptop B tests to the current implementation even when it diverges from the published contract
Keep public E2E assertions red until the integrated runtime implements the published authentication, AP2, revocation, and audit boundaries

**What we chose:** Task 12 stays red until tests in `tests/integration/e2e/` pass against `origin/main` after the Laptop A merge, using public HTTP calls and stable contract responses.

**Why:** Runtime commit `9904b06` currently accepts unauthenticated delegation, omits the signed revocation route, and rejects the contract's capture `ap2` object. Weakening the tests would turn implementation drift into a second de facto contract and would make the demo evidence misleading.

## Direct Task 12 validation target

**Decision:** Git base for the corrected runtime validation

**Options considered (one per line):**

Wait for the runtime PR to merge into main
Merge the runtime branch into Laptop B locally
Rebase Laptop B directly onto the exact published runtime commit requested by the user

**What we chose:** Rebase onto
`origin/codex/laptop-a-live-payments` at
`3191d3e647e52180fe2367bf0d1a2e3740ea2ad0` without merging main.

**Why:** This validates the precise corrected artifact while preserving a linear,
reviewable Laptop B history and respecting the instruction not to merge or open
the final PR yet.

## Public E2E evidence boundary

**Decision:** How Task 12 proves absence of downstream payment effects

**Options considered (one per line):**

Inspect reservation, receipt, and audit tables after each request
Call Core services directly from the E2E suite
Observe only signed HTTP responses, receipts, audit, and dispute projections

**What we chose:** Use authenticated public HTTP as the assertion boundary.
After invalid AP2 or divergent capture input, compare the signed audit timeline
and prove that the same delegated token can still complete one canonical
capture. Direct SQLite access is permitted only to inject revocation-store
unavailability, never to establish the outcome.

**Why:** Database assertions or direct Core calls would bypass the deployed
composition and could hide missing routers, authentication dependencies, or
response mapping defects.

## Browser signing trust boundary

**Decision:** Behavior when no safe RFC 9421 browser signer is published

**Options considered (one per line):**

Embed local runtime private keys in Vite configuration
Treat cookies as equivalent to the contract's RFC 9421 identity
Keep the live browser state unavailable until a server-side signing bridge or browser-owned registered key is defined

**What we chose:** Do not ship trusted runtime private keys or simulate signed
success in the browser. The HTTP gateway remains the default transport, but a
direct browser session may surface authentication/unavailable state until a
safe signer boundary is published.

**Why:** Vite variables are public client assets, and cookie-only requests do
not satisfy the runtime contract. Either shortcut would weaken the identity
boundary precisely where Task 12 is intended to test it.
## Checkout completion and settlement boundary

**Decision:** Meaning of the UCP checkout completion status

**Options considered (one per line):**

Let checkout completion invoke the Core capture and PSP settlement
Report a settled checkout before the payment-capture endpoint runs
Verify AP2 completion and return a durable ready-for-capture state

**What we chose:** Completion now verifies the canonical AP2 checkout and returns `ready_for_capture`; only `POST /payment-captures` may commit a reservation, call the PSP, settle, or issue receipts.

**Why:** One status must have one lifecycle meaning. Separating evidence readiness from settlement prevents a checkout response from claiming a settled payment before the explicit capture boundary and preserves AuthorizationCore as the sole settlement authority.

## Revocation audit before settlement

**Decision:** Audit projection when a mandate is revoked before any capture

**Options considered (one per line):**

Hide the revocation timeline until a receipt exists
Create a synthetic settlement receipt for the audit reader
Return the append-only revocation timeline as incomplete evidence

**What we chose:** The dispute reader exposes a mandate's recorded revocation events even when no capture exists, returning an inconclusive evidence chain rather than inventing payment facts.

**Why:** A signed revocation is itself a durable authorization fact. It must be auditable immediately, while the absence of a reservation or receipt must remain explicit.

## RFC 9421 idempotency component scope

**Decision:** Signature components for operational reads

**Options considered (one per line):**

Require an idempotency key on every signed request
Allow unsigned GET requests
Require RFC 9421 on all routes while signing idempotency only for POST

**What we chose:** Every route signs method, authority, path, profile, content digest, and content type; POST adds `Idempotency-Key`, while GET does not require it.

**Why:** Reads still receive full identity and raw-body integrity protection without inventing an idempotency requirement for an operation that cannot mutate state. This matches the runtime contract's durable POST retry rule.

## Settlement event naming

**Decision:** Audit event emitted after a capture attempt

**Options considered (one per line):**

Record every approved capture as `capture.committed`
Record every approved capture as `capture.settled`
Distinguish a Core-only commit from a PSP-approved settlement

**What we chose:** The Core emits `capture.committed` only when no settlement adapter runs, and emits `capture.settled` when the PSP returns an approved settlement reference.

**Why:** The audit timeline must not erase the difference between a durable reservation commit and a completed settlement. This aligns the runtime receipt boundary and `status: settled` response with the underlying event.

## Runtime database path consistency

**Decision:** Default persistence used by the application factory

**Options considered (one per line):**

Use a hidden `.aval/runtime.sqlite3` only from the factory
Let the factory and ASGI entrypoint independently select their defaults
Use the configured `AVAL_DATABASE_PATH` in both entrypoints

**What we chose:** `create_app()` now uses the same configured durable database path as the ASGI entrypoint whenever a caller does not explicitly supply one.

**Why:** A restarted runtime must reopen the database that operators migrated and verified. Divergent implicit locations can leave one entrypoint on an obsolete schema and break durable authorization facts.

## Idempotency retention purge boundary

**Decision:** Eligibility for explicit idempotency-record removal

**Options considered (one per line):**

Delete all records past `retained_until`, regardless of state
Delete completed records only after a startup sweep
Delete completed records only when an operator invokes maintenance at or after `retained_until`

**What we chose:** The explicit maintenance operation deletes only `COMPLETED` records with `retained_until <= now` and returns only the count removed.

**Why:** A completed record must remain available for the full replay window, while an `IN_FLIGHT` record protects an unfinished side effect indefinitely. A caller-supplied UTC cutoff makes the operation deterministic and prevents retention cleanup from becoming an implicit startup side effect.
