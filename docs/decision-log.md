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
