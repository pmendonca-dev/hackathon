# AVAL Core Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden persisted authorization, revocation, proof, and capture semantics before any protocol adapter work.

**Architecture:** `AuthorizationCore` remains the sole writer of business state. SQLite repositories own isolated persistence concerns under a `BEGIN IMMEDIATE` transaction; settlement remains outside that transaction and receives only committed reservations and a persisted proof.

**Tech Stack:** Python 3.13, SQLAlchemy, Alembic, SQLite WAL, `cryptography`, pytest.

**Spec:** `docs/aval-integration-architecture.md`; `docs/superpowers/plans/2026-08-29-aval-implementation.md` Tasks 4–5.

## Global Constraints

- Use integer `Money` values only; no floats.
- A mandate never has a `COMMITTED` state; a reservation owns that transition.
- Revocation and idempotency storage failures fail closed as `503`-equivalent core outcomes.
- Key custody exposes signing and public JWK operations, never private-key access.
- Authorization proofs are persisted post-commit, expire within 60 seconds, bind the committed transaction, and consume their `jti` durably.
- Adapters remain out of scope and may not write business state.

---

### Task 1: Make the migration history incremental

**Files:**
- Modify: `alembic/versions/0001_initial_core.py`
- Create: `alembic/versions/0002_authorization_hardening.py`
- Test: `tests/integration/test_database_migrations.py`

- [ ] Write an upgrade-from-`0001` test that asserts new mandate columns and durable unique constraints exist.
- [ ] Run the test and observe failure with the metadata-driven migration.
- [ ] Freeze the historical `0001` schema and add an explicit SQLite-safe `0002` upgrade.
- [ ] Run the focused migration suite and commit the change.

### Task 2: Encapsulate ES256 custody and durable proofs

**Files:**
- Modify: `src/aval/security/key_custody.py`, `src/aval/security/jws.py`, `src/aval/security/authorization_proof.py`
- Modify: `src/aval/infrastructure/sqlite/idempotency_repository.py`, `src/aval/infrastructure/sqlite/models.py`
- Test: `tests/unit/security/test_key_custody.py`, `tests/integration/application/test_authorization_proof_replay.py`

- [ ] Write tests proving consumers cannot retrieve private material and that proof replay is rejected across a new core/proof-service instance.
- [ ] Run the tests and observe the current public private-key and process-local-`jti` behavior fail.
- [ ] Replace key access with custody signing/public-key operations and atomically consume proof JTIs in durable idempotency storage.
- [ ] Run the focused suite and commit the change.

### Task 3: Enforce signed, scoped, fail-closed revocation

**Files:**
- Modify: `src/aval/application/authorization_core.py`, `src/aval/infrastructure/sqlite/revocation_repository.py`
- Create: `src/aval/infrastructure/sqlite/lock_repository.py`
- Test: `tests/integration/application/test_capture_revalidates_revocation.py`, `tests/integration/application/test_revocation_storage_failure.py`

- [ ] Write failing tests for each permitted scope and authority, primary-store failure, and a revocation that wins before reservation commit.
- [ ] Run them and confirm the current mandate-wide/status-only implementation does not satisfy the contract.
- [ ] Make revocation authority/scopes explicit, retain fresh reads inside the write transaction, and translate storage errors to fail-closed outcomes.
- [ ] Run focused tests and commit the change.

### Task 4: Complete capture durability and append-only audit

**Files:**
- Modify: `src/aval/application/authorization_core.py`, repositories and models as required
- Create: `src/aval/infrastructure/sqlite/audit_repository.py`
- Test: `tests/integration/application/test_capture_idempotency.py`, `tests/integration/application/test_concurrent_capture.py`, `tests/integration/application/test_idempotency_storage_failure.py`

- [ ] Add failing tests for exact replay response, changed request rejection, in-flight duplicate, storage failure, only-one settlement, capture-attempt ordering, and audit append.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Implement the minimum transaction choreography and isolated repository boundaries.
- [ ] Run the affected suites, update the decision log for material choices, and commit.

### Task 5: Verify and publish

- [ ] Run all focused suites, Alembic upgrade from a clean database, and `uv run pytest -q`.
- [ ] Review the requirement matrix and working tree.
- [ ] Push `codex/aval-core-hardening`, merge it into `main`, push `main`, and re-run the full suite on `main`.
