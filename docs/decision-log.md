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
