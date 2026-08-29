# AVAL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a demonstrable, deterministic agentic-payment system in which verifiable mandates authorize a purchase only while AVAL's live policy permits it.

**Architecture:** `AuthorizationCore` owns every durable business fact and every authorization decision. UCP, AP2, ACP Delegate Payment, the card PSP mock, and the optional x402 rail are stateless edge adapters that translate requests or evidence to and from the core; adapters never import a database session or own policy. The primary path is Human-Not-Present: an authorized agent creates a UCP checkout, AP2 evidence proves consent, and the core commits a transactional `Reservation` before any settlement adapter can run; that commit point is the final revocation boundary.

**Tech Stack:** **Hypothesis to ratify in Task 1:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, SQLite in WAL mode, `pytest`, `cryptography`, an RFC 8785/JCS library, and server-rendered HTML with HTMX. Pin package versions only after the official-compatibility gate; vendor any AP2 material only from commit `e1ea56db72a6385bce3e5c1112b3a56ce60acb43` with attribution. This is the smallest stack that aligns with AP2's Python implementation while avoiding a separate frontend build.

**Spec:** `docs/aval-integration-architecture.md`; supporting constraints: `docs/hackathon-rules.md`, `docs/decision-log.md`, and historical `docs/ap2-aval-integration-decision.md` at git commit `6be0154` (the file was deleted when its content was consolidated into the architecture document).

**Architecture baseline:** Git commit `2efe2eb` (`Update due to the revocation study`). This plan incorporates UCP-primary checkout, RFC 9421 identity boundary, ACP Delegate Payment-only scope, the unified capture/ledger model, a signed fail-closed revocation layer with one settlement-boundary commit point, and a post-core isolated x402 rail.

## Global Constraints

- `AuthorizationCore` is the only source of truth: it alone writes mandates, revocation authorities and records, policy, checkout intents, reservations, authorization proofs, capture attempts, idempotency records, evidence, and audit events.
- `src/aval/adapters/**` may call application ports and serialize/verify protocol data, but may not import `sqlalchemy`, repository implementations, or a database session.
- A decision checks, in order: revocation, server-clock validity, live AVAL policy, AP2 static evidence/constraints, then available ledger balance. Capture repeats the complete check.
- The LLM, if added after this plan, may only read catalog data, prepare a draft, and submit a server-created request id. It never receives keys, PAN, mandate authority, policy authority, or capture authority.
- Exclude Gemini, ADK, A2A, MCP, Web3, AP2 sample applications, and real settlement networks. x402 uses an isolated local facilitator mock only.
- Monetary arithmetic uses `Money(minor_units: int, currency: str, scale: int)`; no float is permitted. Conversions between protocol scales are explicit boundary functions.
- Every mutable operational rule is a database record applied to the next decision with no restart. Immutable mandate changes create a new mandate version.
- Every POST requires an idempotency key at the AVAL boundary. A missing or unavailable idempotency store fails closed; a replay returns its original serialized response.
- The core has two decision moments: `evaluate()` may authorize, escalate, or reject while checkout is open; `capture()` may only commit or reject. The one commit point is `Reservation.PENDING → COMMITTED`, atomically inside the capture transaction and before the `SettlementAdapter` boundary.
- `Mandate` is monotonic (`ACTIVE → REVOKED` or `ACTIVE → EXPIRED`) and never becomes `COMMITTED`; only a per-transaction `Reservation` transitions `PENDING → COMMITTED → SETTLED` or `RELEASED`.
- Every mandate contains signed `aval.revocation` metadata and at least one registered `RevocationAuthority`. Revocations are signed JWS ES256 requests by a permitted holder, guardian, issuer, or authenticated demo operator; an open revocation endpoint is forbidden.
- Revocation reads are fresh from the primary store at both authorization and commit point. Cache is allowed only for advisory UI/pre-flight data, never in an authorization decision; a revocation-store timeout or outage returns `503 revocation_unavailable` with no warn/fail-open mode.
- `AuthorizationProof` is issued only after a reservation is committed, has TTL at most 60 seconds and no longer than the settlement timeout, binds reservation/transaction/policy/revocation epoch, and consumes a one-use `jti` in the shared idempotency store.
- A revocation after commit never cancels that in-flight settlement; it blocks future attempts. The auditor UI must distinguish this from reversal, refund, or dispute.
- Use TDD for every task: first add the named failing test, run its exact command, write only the minimum implementation, run the focused test and then the affected suite.
- Keep the demo runnable without public internet. Use deterministic seed data, test keys, and mock card data only; never commit real payment data or private production keys.
- Treat protocol versions, wire formats, header grammar, schemas, package APIs, and SDK behavior as unverified until Task 1 records an official-source validation. Do not copy a sample or use a version merely because it appears in the architecture document.
- x402 is forbidden until the core-complete gate in Task 13 has passed. If time becomes constrained, cut x402 first, then the automated dispute verdict, then ACP tokenization UI; never cut signature verification, live revocation, concurrent-capture protection, or human escalation.

---

## Delivery order and gates

1. Tasks 1-3 establish an executable, persisted canonical domain and cryptographic primitives.
2. Tasks 4-6 make the core enforceable, concurrent-safe, and auditable before any protocol endpoint exists.
3. Tasks 7-10 expose the primary UCP + AP2 + ACP + card-PSP demo path.
4. Tasks 11-12 make the result explainable to all three actors and mutable for trial by fire.
5. Task 13 is optional and may start only after its documented green gate. Task 14 is the end-to-end rehearsal and regression gate.

## Architecture revision reconciliation

`87b735a` introduced the consolidated protocol architecture; `2efe2eb` adds its Section 11 revocation study. The new material is assigned as follows: signed `RevocationAuthority` and `aval.revocation` issuance (Tasks 3-4); one lock-shared revocation-versus-capture transaction and the `Reservation` commit point (Task 5); post-commit, one-use `AuthorizationProof` (Tasks 3 and 5); the authenticated operator as a first-class revoker, not an admin bypass (Task 11); explicit auditor treatment of in-flight/post-commit revocation (Tasks 9-10); and eight new revocation/commit regression scenarios (Task 12). The commit-point placement, reservation-only commit state, signed revocation mechanism, and fail-closed availability policy are material choices consolidated by the architecture; copy-ready Flight Log entries appear below.

## File and directory map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `.env.example` | Runtime/test tooling and reproducible, non-secret configuration. |
| `src/aval/main.py` | FastAPI composition root; injects adapters into application services. |
| `src/aval/domain/` | Immutable business types and pure policy/transition logic; no HTTP or ORM imports. |
| `src/aval/application/ports.py` | Stable typed ports consumed by services and implemented by infrastructure/adapters. |
| `src/aval/application/services/` | `AuthorizationCore`, mandate/revocation, checkout, capture/commit, vault, receipt, and audit use cases. |
| `src/aval/infrastructure/sqlite/` | SQLAlchemy models, migrations, repositories, transaction runner, WAL setup, deterministic seed. |
| `src/aval/security/` | Clock, key custody, JWS/RFC 9421/JCS/AP2/revocation-proof crypto façades; key material remains private here. |
| `src/aval/adapters/ucp/` | UCP discovery, RFC 9421 authentication, checkout/AP2 projection; no persistent state. |
| `src/aval/adapters/acp/` | ACP Delegate Payment request/response projection and scoped token façade. |
| `src/aval/adapters/settlement/` | `MockCardPSP` and, only later, `X402FacilitatorMock`; returns results to capture service. |
| `src/aval/api/` | HTTP routers and raw-body middleware; routers call services, never repositories directly. |
| `src/aval/web/` | HTML view models/templates for human, merchant, and auditor views. |
| `tests/unit/` | Pure domain, crypto, projection, and service unit tests. |
| `tests/integration/` | SQLite, HTTP, concurrency, and end-to-end contract tests. |
| `tests/fixtures/` | Deterministic keys, raw signed HTTP fixtures, AP2 fixtures, catalog, and seed clock values. |
| `docs/protocol-validation.md` | Evidence that official protocol specs/SDK versions and formats were checked before adoption. |
| `docs/adr/` | Ratified implementation decisions only; no speculative stack decision is written here before ratification. |
| `docs/demo-runbook.md` | Repeatable primary demo and trial-by-fire commands. |

## Canonical interfaces

All names below are contracts to create in the listed order. Concrete protocol DTOs stay inside their adapters.

```python
type MandateId = NewType("MandateId", str)
type CheckoutIntentId = NewType("CheckoutIntentId", str)
type ReservationId = NewType("ReservationId", str)
type CaptureAttemptId = NewType("CaptureAttemptId", str)
type RevocationId = NewType("RevocationId", str)
type AuthorizationProofId = NewType("AuthorizationProofId", str)

@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str
    scale: int

class AuthorizationDecision(Enum):
    AUTHORIZED = "authorized"
    AWAITING_HUMAN = "awaiting_human"
    REJECTED = "rejected"

class ReservationStatus(Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    SETTLED = "settled"
    RELEASED = "released"

class MandateSigner(Protocol):
    def issue_open(self, mandate: Mandate) -> Evidence: ...
    def issue_closed(self, mandate: Mandate, checkout: CheckoutIntent, challenge: MerchantChallenge) -> Evidence: ...

class MandateVerifier(Protocol):
    def verify(self, evidence: Evidence, checkout: CheckoutIntent, challenge: MerchantChallenge) -> VerifiedMandate: ...

class RevocationVerifier(Protocol):
    def verify(self, request: SignedRevocation, authority: RevocationAuthority) -> VerifiedRevocation: ...

class AuthorizationProofIssuer(Protocol):
    def issue(self, committed: Reservation, transaction_hash: str, policy_version: int, revocation_epoch: int) -> AuthorizationProof: ...

class AuthorizationCore(Protocol):
    def evaluate(self, command: AuthorizationCommand) -> AuthorizationResult: ...
    def capture(self, command: CaptureCommand) -> CaptureResult: ...

class SettlementAdapter(Protocol):
    def authorize(self, reservation: Reservation, proof: AuthorizationProof) -> SettlementResult: ...

class AuditLedger(Protocol):
    def append(self, event: AuditEventDraft) -> AuditEvent: ...
    def timeline_for(self, mandate_id: MandateId) -> Sequence[AuditEvent]: ...
```

`AuthorizationResult` always contains a structured reason code, a Portuguese `human_summary`, a checkout status, and a `continue_url` when its decision is `AWAITING_HUMAN`. `CaptureResult` always contains the original cached response on an idempotent replay.

## Phases and tasks

### Task 1: Foundation, official compatibility gate, and SQLite persistence

**Files:**

- Create: `pyproject.toml`, `.env.example`, `src/aval/__init__.py`, `src/aval/main.py`, `src/aval/infrastructure/sqlite/engine.py`, `src/aval/infrastructure/sqlite/models.py`, `src/aval/infrastructure/sqlite/transaction.py`, `src/aval/infrastructure/sqlite/seed.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial_core.py`, `docs/protocol-validation.md`
- Create: `tests/integration/test_database_bootstrap.py`, `tests/unit/test_protocol_validation_document.py`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: none.
- Produces: `create_engine_from_settings() -> Engine`, `run_in_write_transaction(fn) -> T`, `seed_demo_data() -> None`, and the initial tables `mandates`, `revocation_authorities`, `revocations`, `policy_rules`, `checkout_intents`, `reservations`, `authorization_proofs`, `capture_attempts`, `idempotency_records`, `evidence`, `audit_events`, `agent_profiles`, `vault_tokens`.

- [ ] **Step 1: Write failing bootstrap and validation-document tests.** Assert a fresh database enables `journal_mode=WAL`, migrations create exactly the listed core tables, `reservations` has a `PENDING|COMMITTED|SETTLED|RELEASED` status constraint, and `docs/protocol-validation.md` has rows for UCP, AP2, ACP, x402, RFC 9421, RFC 9530, RFC 8785, RFC 7515, RFC 8941, and the official JWS/continuous-authorization references used by the revocation design.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/integration/test_database_bootstrap.py tests/unit/test_protocol_validation_document.py -q`. Expected: failure because the project, schema, and validation record do not exist.
- [ ] **Step 3: Validate before pinning.** Open the official UCP specification and AP2 specification/repository at the required AP2 SHA; inspect official ACP Delegate Payment and x402 v2 transport specifications. Record the exact observed status vocabulary, header grammar, required fields, wire encoding, key/signature requirements, and package/SDK API used. If any architecture-document value conflicts with an official source, retain the canonical core contract and update only the edge-adapter plan/validation record before implementation.
- [ ] **Step 4: Implement the minimum executable foundation.** Create the Python package and FastAPI health route; configure SQLite with WAL, foreign keys, a short busy timeout, and `BEGIN IMMEDIATE` for write transactions. Add the initial migration and deterministic local seed. Pin only packages proven compatible in Step 3 into `pyproject.toml` and generate `uv.lock`.
- [ ] **Step 5: Re-run focused tests and migration in a clean database.** Run: `uv run alembic upgrade head` and `uv run pytest tests/integration/test_database_bootstrap.py tests/unit/test_protocol_validation_document.py -q`. Expected: PASS.
- [ ] **Step 6: Commit.** Suggested commit: `chore: bootstrap aval persistence and protocol validation gate`.

**Acceptance:** A new clone can create the schema and seed locally; WAL and transaction mode are test-proven; no protocol version, external SDK, or header format is used without a dated official-source entry in `docs/protocol-validation.md`.

### Task 2: Canonical domain model and single status mapping

**Files:**

- Create: `src/aval/domain/money.py`, `src/aval/domain/entities.py`, `src/aval/domain/enums.py`, `src/aval/domain/errors.py`, `src/aval/domain/checkout_status.py`, `src/aval/domain/evidence.py`
- Create: `tests/unit/domain/test_entities.py`, `tests/unit/domain/test_checkout_status.py`

**Interfaces:**

- Consumes: Task 1 package/tooling only.
- Produces: immutable `Principal`, `AgentIdentity`, `Mandate`, `RevocationAuthority`, `Revocation`, `CheckoutIntent`, `Reservation`, `AuthorizationProof`, `CaptureAttempt`, `Evidence`, `AuditEvent`; `AvalCheckoutStatus`; total functions `to_ucp_status(AvalCheckoutStatus) -> str` and `to_acp_status(AvalCheckoutStatus) -> str`.

- [ ] **Step 1: Write failing domain tests.** Assert a checkout cannot exist without its mandate id; a mandate cannot be created without signed `aval.revocation` metadata and at least one authority; a mandate has no `COMMITTED` transition; a reservation alone performs `PENDING → COMMITTED → SETTLED` or `RELEASED`; an audit event cannot be edited; and every AVAL checkout status maps to exactly one validated UCP and ACP status. Assert an unknown enum value raises a domain error rather than falling back to a string.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/domain/test_entities.py tests/unit/domain/test_checkout_status.py -q`. Expected: failure because no canonical types or mapping exist.
- [ ] **Step 3: Implement minimum immutable domain records.** Use frozen dataclasses/value objects and one centrally defined mapping table. Model `Mandate` as monotonic active/revoked/expired, `Reservation` as the only commit state machine, `RevocationAuthority` by public key/role/scope, and a post-commit `AuthorizationProof`. Persist protocol identifiers only as optional projections/references; do not add UCP, ACP, AP2, or x402 state fields that can become competing truth.
- [ ] **Step 4: Re-run focused tests.** Run: `uv run pytest tests/unit/domain/test_entities.py tests/unit/domain/test_checkout_status.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: define canonical aval domain model`.

**Acceptance:** All subsequent services accept core types instead of protocol payloads; the only checkout lifecycle mapping is exhaustive and test-proven; the domain makes a mandate-level commit state impossible.

### Task 3: Money, ClockService, KeyCustody, and cryptographic ports

**Files:**

- Create: `src/aval/security/clock.py`, `src/aval/security/key_custody.py`, `src/aval/security/ecdsa.py`, `src/aval/security/content_digest.py`, `src/aval/security/jcs.py`, `src/aval/security/jws.py`, `src/aval/security/revocation_proof.py`, `src/aval/application/ports.py`
- Create: `tests/unit/security/test_money.py`, `tests/unit/security/test_clock.py`, `tests/unit/security/test_ecdsa_raw_signature.py`, `tests/unit/security/test_content_digest.py`, `tests/unit/security/test_jcs.py`, `tests/unit/security/test_key_custody.py`, `tests/unit/security/test_authorization_proof.py`
- Create: `tests/fixtures/crypto/p256-vector.json`, `tests/fixtures/http/raw-unicode-request.bin`, `tests/fixtures/jcs/unicode-and-emoji.json`

**Interfaces:**

- Consumes: `Money`, domain errors from Task 2; protocol-format facts recorded in Task 1.
- Produces: `ClockService.now() -> datetime`, `KeyCustodyService.sign(key_ref: str, payload: bytes) -> bytes`, `KeyCustodyService.public_jwk(key_ref: str) -> Mapping[str, str]`, `der_to_p256_raw(der: bytes) -> bytes`, `p256_raw_to_der(raw: bytes) -> bytes`, `content_digest(raw_body: bytes) -> str`, `canonicalize_json(value: object) -> bytes`, `RevocationVerifier`, `AuthorizationProofIssuer`, and the repository/settlement port declarations.

- [ ] **Step 1: Write failing primitive tests.** Assert `Money` rejects floats, mismatched currencies, and scale changes without an explicit converter; assert frozen time is deterministic; assert an ES256 signature is exactly 64 raw `r||s` bytes and round-trips through DER; assert two semantically equal but byte-different JSON bodies produce different `Content-Digest`; assert JCS canonicalization of accented text, `R$`, and emoji matches an RFC 8785 fixture; assert a signed `AuthorizationProof` is rejected when issued before commit, after 60 seconds, or with a modified reservation/transaction/policy/epoch binding.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/security -q`. Expected: failure because no primitives or ports exist.
- [ ] **Step 3: Implement only deterministic primitives.** Inject the clock; retain private test keys inside the custody implementation and expose operations/public JWKs only. Compute RFC 9530 digest over captured raw bytes. Use the Task-1-validated JCS implementation rather than a JSON `sort_keys` substitute. Verify signed revocations against a registered authority; issue only post-commit proofs with `jti`, TTL ≤60 seconds, and all required bindings. Keep AP2 signing behind local ports so an unstable SDK can fall back to a local JWS-compatible implementation.
- [ ] **Step 4: Re-run focused tests.** Run: `uv run pytest tests/unit/security -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: add monetary clock and cryptographic foundations`.

**Acceptance:** Tests prove no DER/r||s confusion, no raw-body reserialization for digest, no pseudo-JCS, no float arithmetic, and no direct key-material access outside custody.

### Task 4: Mandates, revocation, live policy, and authorization evaluation

**Files:**

- Create: `src/aval/application/services/mandates.py`, `src/aval/application/services/revocations.py`, `src/aval/application/services/policy.py`, `src/aval/application/services/authorization.py`, `src/aval/infrastructure/sqlite/mandate_repository.py`, `src/aval/infrastructure/sqlite/policy_repository.py`, `src/aval/infrastructure/sqlite/revocation_repository.py`
- Create: `tests/unit/application/test_authorization_order.py`, `tests/integration/application/test_mandate_lifecycle.py`, `tests/integration/application/test_live_revocation.py`, `tests/integration/application/test_signed_revocation.py`, `tests/integration/application/test_out_of_mandate.py`, `tests/integration/application/test_expired_mandate.py`

**Interfaces:**

- Consumes: Tasks 1-3 repositories/ports; `MandateSigner` and `MandateVerifier` ports.
- Produces: `MandateService.create(command) -> Mandate`, `RevocationService.revoke(command: SignedRevocationCommand) -> Revocation`, `PolicyService.replace_rule(rule) -> PolicyRule`, `AuthorizationCore.evaluate(command) -> AuthorizationResult`.

- [ ] **Step 1: Write failing authorization tests in the required order.** Assert issuance rejects a mandate missing an authority or `aval.revocation`; a revoked mandate returns `REJECTED/aval.mandate_revoked` and HTTP 403 even if it has balance; an untrusted/invalid signed revocation is rejected; holder/guardian/issuer/operator scopes are enforced; an expired mandate returns `REJECTED/mandate_expired`; a merchant/item/value/instrument outside scope returns `AWAITING_HUMAN/unresolved_constraint` with a non-empty continuation URL; and changing a persisted limit changes the next evaluation without restart.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/application/test_authorization_order.py tests/integration/application/test_mandate_lifecycle.py tests/integration/application/test_live_revocation.py tests/integration/application/test_signed_revocation.py tests/integration/application/test_out_of_mandate.py tests/integration/application/test_expired_mandate.py -q`. Expected: failure because authority issuance, revocation verification, evaluation, and repositories do not exist.
- [ ] **Step 3: Implement the minimum authority path.** Store immutable mandate versions, registered authority keys/scopes, append-only signed revocations, and versioned live rules. Bind the authoritative mandate record to signed `aval.revocation` metadata; start at epoch 0 and increment it for a policy/revocation change that invalidates a proof. Implement exactly one `evaluate` method whose tested order is fresh revocation → server-clock expiry → current policy → cryptographic/static evidence → balance. Return structured reasons and Portuguese human summaries; do not allow an adapter to decide escalation.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: enforce live mandate authorization policy`.

**Acceptance:** The first three mandatory adverse scenarios are green, with live revocation and policy edits demonstrably independent of any protocol projection.

### Task 5: Ledger, reservations, locks, idempotency, and capture orchestration

**Files:**

- Create: `src/aval/application/services/ledger.py`, `src/aval/application/services/capture.py`, `src/aval/infrastructure/sqlite/ledger_repository.py`, `src/aval/infrastructure/sqlite/idempotency_repository.py`, `src/aval/infrastructure/sqlite/capture_repository.py`, `src/aval/infrastructure/sqlite/lock_repository.py`
- Create: `tests/integration/application/test_capture_idempotency.py`, `tests/integration/application/test_concurrent_capture.py`, `tests/integration/application/test_revocation_commit_race.py`, `tests/integration/application/test_authorization_proof_replay.py`, `tests/integration/application/test_capture_revalidates_revocation.py`, `tests/integration/application/test_revocation_storage_failure.py`, `tests/integration/application/test_idempotency_storage_failure.py`

**Interfaces:**

- Consumes: `AuthorizationCore.evaluate`, transaction runner, `SettlementAdapter`, `AuditLedger` port.
- Produces: `Ledger.reserve(mandate_id, amount, operation_kind) -> Reservation`, `Ledger.commit(reservation_id) -> Reservation`, `Ledger.release(reservation_id) -> None`, `CaptureService.capture(command: CaptureCommand) -> CaptureResult`, `IdempotencyStore.get_or_claim(surface, key, request_hash) -> Claim`, `AuthorizationProofIssuer.issue(committed, transaction_hash, policy_version, revocation_epoch) -> AuthorizationProof`.

- [ ] **Step 1: Write failing capture tests.** Assert two simultaneous captures for one mandate/transaction produce exactly one settlement call; revocation and capture contend for the same mandate lock and exactly one wins; if revocation commits first capture is rejected/released, while if reservation commits first that in-flight settlement proceeds and the next attempt is rejected; a proof emitted before commit or replayed by `jti` is rejected; a same-key/same-body retry returns the original response and no second reservation; a same key with a changed body is rejected; an in-flight duplicate is rejected; a revocation-store outage produces `503 revocation_unavailable`; and an idempotency-write failure produces a closed `503` response.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/integration/application/test_capture_idempotency.py tests/integration/application/test_concurrent_capture.py tests/integration/application/test_revocation_commit_race.py tests/integration/application/test_authorization_proof_replay.py tests/integration/application/test_capture_revalidates_revocation.py tests/integration/application/test_revocation_storage_failure.py tests/integration/application/test_idempotency_storage_failure.py -q`. Expected: failure because capture transaction handling, commit point, proof, and fail-closed revocation handling do not exist.
- [ ] **Step 3: Implement minimum transaction choreography.** In one short `BEGIN IMMEDIATE` write transaction acquire the shared `mandate_id` lock, claim idempotency, read primary revocation state without cache, invoke full revalidation, create `Reservation(PENDING)`, persist `CaptureAttempt(PENDING)`, atomically transition the reservation to `COMMITTED`, and only then issue/store the one-use `AuthorizationProof`. This transition is the sole commit point. Call the settlement adapter outside the lock with the committed reservation/proof. In a new transaction settle or release the reservation, persist final attempt/response/idempotency record, and append audit data. A revocation after commit does not cancel this external call; it affects only future transactions. Retain idempotency for at least 24 hours; map adapter-facing semantics to 400 missing key, 409 in-flight, and 422 body mismatch only after Task 1 confirms ACP/UCP details.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: add transactional capture and idempotency core`.

**Acceptance:** The double-spend and revocation-versus-capture races are proven under one shared lock; retries are deterministic; no adapter runs before `COMMITTED`; fresh pre-commit revocation defeats capture; and post-commit revocation cannot create a second settlement or retroactively cancel the committed attempt.

### Task 6: UCP authentication, raw-body middleware, and local trusted registry

**Files:**

- Create: `src/aval/adapters/ucp/http_signatures.py`, `src/aval/adapters/ucp/registry.py`, `src/aval/api/middleware/raw_body.py`, `src/aval/api/routers/ucp_discovery.py`, `src/aval/infrastructure/sqlite/agent_registry_repository.py`
- Create: `tests/unit/adapters/ucp/test_http_signatures.py`, `tests/unit/adapters/ucp/test_ucp_agent_header.py`, `tests/integration/api/test_ucp_authentication.py`, `tests/integration/api/test_ucp_discovery.py`

**Interfaces:**

- Consumes: raw crypto primitives from Task 3, `AgentIdentity` from Task 2, registry repository from Task 1.
- Produces: `RawBodyContext.body: bytes`, `TrustedAgentRegistry.resolve(profile_url: str) -> AgentIdentity | None`, `Rfc9421Verifier.verify(request: SignedRequest) -> VerifiedAgent`, and `GET /.well-known/ucp` projection.

- [ ] **Step 1: Write failing UCP-auth tests.** Assert a request without an RFC 9421 signature is rejected; a valid request with DER-form signature is rejected; a signature over reserialized JSON is rejected; an unknown profile returns `profile_not_trusted`; an unknown key returns `key_not_found`; and the discovery document publishes only Task-1-validated capabilities and local signing keys.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/adapters/ucp/test_http_signatures.py tests/unit/adapters/ucp/test_ucp_agent_header.py tests/integration/api/test_ucp_authentication.py tests/integration/api/test_ucp_discovery.py -q`. Expected: failure because middleware, registry, and verifier do not exist.
- [ ] **Step 3: Implement the minimum border check.** Capture `await request.body()` before parsing, validate the RFC 8941 `UCP-Agent` grammar and HTTPS profile, require the validated signed components including method, authority, path, idempotency key, digest, and content type, and verify against a seeded local registry only. Do not fetch arbitrary profile URLs and do not store a protocol session in the adapter.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: verify ucp agent identity from local registry`.

**Acceptance:** The impostor-agent scenario is demonstrably rejected on the trust boundary, using raw HTTP bytes and local trusted keys rather than a claim in the request body.

### Task 7: UCP checkout and AP2 mandate extension

**Files:**

- Create: `src/aval/application/services/checkout.py`, `src/aval/adapters/ucp/checkout_projection.py`, `src/aval/adapters/ucp/ap2_extension.py`, `src/aval/adapters/ap2/mandates.py`, `src/aval/adapters/ap2/merchant_authorization.py`, `src/aval/infrastructure/sqlite/checkout_repository.py`
- Create: `tests/unit/adapters/ap2/test_merchant_authorization.py`, `tests/integration/api/test_ucp_checkout.py`, `tests/integration/api/test_ap2_checkout_lock.py`, `tests/integration/api/test_ap2_replay_binding.py`, `tests/fixtures/ap2/open-mandate.json`, `tests/fixtures/ap2/closed-mandate.json`

**Interfaces:**

- Consumes: verified agent from Task 6; checkout status mappings Task 2; `MandateSigner/Verifier`, `AuthorizationCore.evaluate`, and JCS/JWS ports Task 3.
- Produces: `CheckoutService.create(command) -> CheckoutIntent`, `CheckoutService.complete(command) -> CaptureResult | AuthorizationResult`, `MerchantAuthorizationSigner.sign(checkout) -> Evidence`, `MerchantAuthorizationVerifier.verify(checkout, proof) -> None`, UCP checkout request/response projections.

- [ ] **Step 1: Write failing checkout/AP2 tests.** Assert negotiated AP2 capability security-locks the checkout; `complete_checkout` without an AP2 checkout mandate returns `mandate_required`; a changed total/item after merchant signing returns `mandate_scope_mismatch`; a missing/invalid merchant authorization is rejected; a tampered JWS is rejected before constraints are used; incorrect `aud` or nonce is rejected; and an out-of-scope checkout becomes `requires_escalation` with `continue_url` rather than silently completing.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/adapters/ap2/test_merchant_authorization.py tests/integration/api/test_ucp_checkout.py tests/integration/api/test_ap2_checkout_lock.py tests/integration/api/test_ap2_replay_binding.py -q`. Expected: failure because checkout, AP2 evidence, and UCP projection are absent.
- [ ] **Step 3: Implement the minimum primary protocol path.** Create one canonical `CheckoutIntent` and freeze its totals after merchant authorization. Derive the UCP response from it; produce detached JWS over the Task-3-validated JCS representation of the complete checkout excluding only the spec-required AP2 field. Verify merchant proof, SD-JWT/key binding, challenge audience, nonce, expiry, and one-delegation chain through local ports before calling the core. Translate core decisions to the total status map.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: add ucp checkout with ap2 mandate enforcement`.

**Acceptance:** The main UCP + AP2 flow is cryptographically bound, totals cannot drift, and the escalation path is protocol-visible while policy remains core-owned.

### Task 8: ACP Delegate Payment vault and derived Allowance

**Files:**

- Create: `src/aval/application/services/vault.py`, `src/aval/adapters/acp/delegate_payment.py`, `src/aval/infrastructure/sqlite/vault_repository.py`, `src/aval/security/tokenization.py`, `src/aval/api/routers/delegate_payment.py`
- Create: `tests/unit/application/test_derived_allowance.py`, `tests/integration/api/test_delegate_payment.py`, `tests/integration/security/test_pan_redaction.py`

**Interfaces:**

- Consumes: `AuthorizationCore.evaluate`, `Money`, mandate/checkout repositories, Task-1 official ACP contract record.
- Produces: `VaultService.delegate(command) -> DelegatedPayment`, `derive_allowance(live_balance: Money, mandate_ceiling: Money, checkout_total: Money, merchant_id: str, expires_at: datetime) -> Allowance`, and an opaque `vt_*` token reference.

- [ ] **Step 1: Write failing vault tests.** Assert the returned token payload never contains the supplied test PAN; allowance is `min(live_balance, mandate ceiling, checkout total)` with matching currency/scale; its merchant, checkout id, and expiry are scoped to the request; a current policy-limit decrease changes a newly generated allowance; and an expired/revoked mandate cannot produce a token.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/application/test_derived_allowance.py tests/integration/api/test_delegate_payment.py tests/integration/security/test_pan_redaction.py -q`. Expected: failure because vault and projection are absent.
- [ ] **Step 3: Implement minimum tokenization.** Store only a one-way/opaque local test credential reference; log redacted fingerprints only. Call the core first, compute `derived_allowance` from the core result rather than stored ACP state, and serialize the Task-1-validated ACP Delegate Payment shape. Use one-time tokens; recurring behavior remains in AVAL mandates, not ACP allowance state.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: add scoped acp delegate payment tokens`.

**Acceptance:** The agent receives only a scoped `vt_*` identifier, and the ACP projection demonstrably cannot override current AVAL policy.

### Task 9: PSP mock, AP2 receipts, Audit Ledger, and dispute reconstruction

**Files:**

- Create: `src/aval/adapters/settlement/mock_card_psp.py`, `src/aval/application/services/receipts.py`, `src/aval/application/services/audit.py`, `src/aval/adapters/ap2/receipts.py`, `src/aval/infrastructure/sqlite/audit_repository.py`, `src/aval/api/routers/audit.py`
- Create: `tests/unit/adapters/settlement/test_mock_card_psp.py`, `tests/integration/application/test_receipt_ordering.py`, `tests/integration/application/test_audit_timeline.py`, `tests/integration/application/test_dispute_reconstruction.py`

**Interfaces:**

- Consumes: Task 5 `CaptureService`/`SettlementAdapter`, Task 7 closed mandate evidence, Task 3 signing ports.
- Produces: `MockCardPSP.authorize(reservation, proof) -> SettlementResult`, `ReceiptService.issue_after_capture(attempt_id) -> Sequence[Evidence]`, `AuditLedger.append(draft) -> AuditEvent`, `DisputeService.reconstruct(mandate_id) -> DisputeVerdict`.

- [ ] **Step 1: Write failing settlement/audit tests.** Assert the mock PSP refuses any non-committed reservation or invalid proof; a payment receipt cannot issue before a settled capture; each audit event is append-only and contains a Portuguese `human_summary`, structured reason, evidence hash/reference, actor, commit-point timestamp, and revocation epoch; an auditor can reconstruct open mandate → signed revocation authority → closed mandate → checkout hash → committed reservation/proof → merchant authorization → payment receipt; an in-flight revocation is explained as applying only to future purchases; and an unknown receipt reference produces an inconclusive/invalid dispute verdict rather than a false approval.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/adapters/settlement/test_mock_card_psp.py tests/integration/application/test_receipt_ordering.py tests/integration/application/test_audit_timeline.py tests/integration/application/test_dispute_reconstruction.py -q`. Expected: failure because settlement, receipt, and ledger implementations do not exist.
- [ ] **Step 3: Implement minimum evidence and audit path.** The PSP mock returns a result only and requires a valid committed reservation/proof; it never writes ledger rows. After reconciliation, issue checkout/payment receipts through local AP2 ports, hash/store immutable evidence, and append events. Implement a read-only dispute reconstruction endpoint/service that distinguishes pre-commit revocation from post-commit reversal/refund/dispute; automated fault attribution is a bonus, but the evidence chain and legible verdict are not optional.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: record settlement receipts and audit evidence`.

**Acceptance:** Capture, receipts, and audit rows are ordered correctly; a human, merchant, and auditor can see the same underlying facts, and the dispute scenario can be explained from evidence.

### Task 10: Human, merchant, and auditor UI

**Files:**

- Create: `src/aval/web/routes.py`, `src/aval/web/view_models.py`, `src/aval/web/templates/base.html`, `src/aval/web/templates/human.html`, `src/aval/web/templates/merchant.html`, `src/aval/web/templates/auditor.html`, `src/aval/web/static/aval.css`
- Create: `tests/integration/web/test_human_view.py`, `tests/integration/web/test_merchant_view.py`, `tests/integration/web/test_auditor_view.py`

**Interfaces:**

- Consumes: mandate, checkout, capture, and `AuditLedger.timeline_for`; no repository directly.
- Produces: `GET /human/mandates/{id}`, `GET /merchant/checkouts/{id}`, `GET /auditor/mandates/{id}` and role-specific immutable view models.

- [ ] **Step 1: Write failing UI contract tests.** Assert the human page shows mandate scope, live status, revocation authority, purchased items, and no PAN; the merchant page shows verified agent/profile, signature result, mandate decision, commit-point state, and capture result; the auditor page shows ordered events, hashes/evidence links, both machine reason and Portuguese summary, including revocation/dispute events, commit time, and the rule that a post-commit revocation requires reversal/refund/dispute rather than cancellation.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/integration/web -q`. Expected: failure because no presentation routes/templates exist.
- [ ] **Step 3: Implement minimal server-rendered views.** Build view models from application service read methods and render three focused pages. Do not reconstruct policy in templates or introduce a UI-owned cache/state. Add explicit empty/error views for rejected and awaiting-human checkouts.
- [ ] **Step 4: Re-run focused tests.** Run: `uv run pytest tests/integration/web -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: add human merchant and auditor views`.

**Acceptance:** The mandatory three audiences can understand the complete outcome without terminal access; no UI presents a protocol projection as an independent source of truth.

### Task 11: Administrative trial-by-fire endpoint and operational runbook

**Files:**

- Create: `src/aval/api/routers/admin.py`, `src/aval/application/services/admin_policy.py`, `src/aval/infrastructure/sqlite/admin_audit_repository.py`, `docs/demo-runbook.md`
- Create: `tests/integration/api/test_admin_trial_by_fire.py`, `tests/integration/api/test_trial_by_fire_effect.py`
- Modify: `src/aval/main.py`, `.env.example`

**Interfaces:**

- Consumes: `PolicyService.replace_rule`, `RevocationService.revoke`, audit service, seeded operator authority.
- Produces: protected `PATCH /admin/policy-rules/{id}` and `POST /admin/mandates/{id}/revocations`; the latter builds an operator-authenticated signed revocation command rather than bypassing the revocation service. The operator is a first-class authority, not a bypass, and both routes yield audited responses with an effective timestamp.

- [ ] **Step 1: Write failing trial-by-fire tests.** Assert an authenticated operator can lower a limit, remove a merchant/category, revoke a mandate, or apply `budget:zero`, and the next authorization sees it without restart; the operator revocation is rejected if it is not represented by the registered authority; an unauthenticated caller cannot mutate policy or revoke; and every mutation adds an audit event naming actor, authority role, scope, old/new value, and effective timestamp.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/integration/api/test_admin_trial_by_fire.py tests/integration/api/test_trial_by_fire_effect.py -q`. Expected: failure because admin mutation endpoints do not exist.
- [ ] **Step 3: Implement the minimum safe control plane.** Authenticate a demo-operator secret from environment and map it to the seeded `operator` `RevocationAuthority`; call only core services in one transaction, append audit events, and return current canonical policy/mandate state. Document exact seed/reset/start/demo commands and the four jury interventions: lower limit, revoke mandate, change allowed merchant/item, and set budget to zero.
- [ ] **Step 4: Re-run focused tests.** Run the command in Step 2. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: support live trial by fire policy changes`.

**Acceptance:** A juror can alter a rule through the UI/API and observe the next decision change immediately, with no code change, restart, or manual database edit.

### Task 12: Primary demo end-to-end regression and required scenarios

**Files:**

- Create: `tests/integration/e2e/test_authorized_purchase.py`, `tests/integration/e2e/test_required_adversarial_scenarios.py`, `tests/integration/e2e/test_audit_readability.py`, `scripts/demo_smoke.py`
- Modify: `docs/demo-runbook.md`, `README.md`

**Interfaces:**

- Consumes: all Tasks 1-11 through public HTTP/service interfaces.
- Produces: one reproducible demo-seed journey and a regression command used as the x402 entry gate.

- [ ] **Step 1: Write the end-to-end tests first.** Encode: valid purchase with agent authentication, AP2 evidence, delegated token, capture and receipts; out-of-mandate escalation; expiration; real-time revocation; impostor signature/profile; dispute reconstruction; auditor-readable timeline; simultaneous revocation/capture with exactly one winner; revocation during settlement after `COMMITTED`; changed-body idempotency rejection; proof replay/expiry; invalid revocation signature; revocation-store `503`; and mandate issuance without revocation authority. Defer the x402 counterpart to Task 13 so it cannot delay the core gate. Assert that each result has a stable reason code and Portuguese human summary.
- [ ] **Step 2: Run the failing regression.** Run: `uv run pytest tests/integration/e2e -q`. Expected: any missing cross-layer behavior fails and identifies the public contract at fault.
- [ ] **Step 3: Add only integration glue or fix contract gaps.** Do not add a second source of truth to make a test pass. Amend an earlier task's service/adapter only when the end-to-end test demonstrates its public contract is incomplete; preserve the core-first write rule.
- [ ] **Step 4: Re-run regression and smoke script.** Run: `uv run pytest tests/integration/e2e -q` and `uv run python scripts/demo_smoke.py`. Expected: PASS and a concise report listing the mandatory scenarios plus the seven non-x402 revocation/commit outcomes.
- [ ] **Step 5: Commit.** Suggested commit: `test: lock down aval primary demo scenarios`.

**Acceptance:** This exact command is green before any x402 work starts. It covers every mandatory challenge scenario and can be demonstrated from a clean seed.

### Task 13: Isolated x402 facilitator mock — only after the core-complete gate

**Prerequisite gate:** Task 12's two commands must pass on a clean database; record their command output and commit in the pull request/implementation notes. If the gate is not green, do not start this task.

**Files:**

- Create: `src/aval/adapters/settlement/x402.py`, `src/aval/adapters/x402/transport.py`, `src/aval/api/routers/x402_resource.py`, `tests/unit/adapters/x402/test_money_conversion.py`, `tests/integration/api/test_x402_mock.py`, `tests/integration/application/test_x402_ledger_integration.py`
- Modify: `src/aval/application/services/capture.py`, `src/aval/application/ports.py`, `docs/demo-runbook.md`

**Interfaces:**

- Consumes: `SettlementAdapter`, `CaptureService`, idempotency store, `Money` conversion functions, official x402 facts in Task 1 record.
- Produces: `X402FacilitatorMock.authorize(reservation) -> SettlementResult`, a resource route returning validated `402` payment requirements, and an isolated x402 capture command with `operation_kind="decision_data"`.

- [ ] **Step 1: Write failing x402 tests.** Assert an x402 resource returns the official validated header encoding rather than a body substitute; a second request with the same nonce cannot settle; an atomic-unit string converts explicitly to `Money` using the asset scale; a revoked mandate cannot commit an x402 reservation; the x402 payment consumes a committed reservation/proof in the same AVAL ledger as the cart but uses a separate rail/endpoint; and the card checkout never invokes x402 code.
- [ ] **Step 2: Run the failing tests.** Run: `uv run pytest tests/unit/adapters/x402/test_money_conversion.py tests/integration/api/test_x402_mock.py tests/integration/application/test_x402_ledger_integration.py -q`. Expected: failure because x402 adapter and conversion boundary do not exist.
- [ ] **Step 3: Implement minimum local rail.** Form only the Task-1-validated v2 `PaymentRequired` and payment-signature shapes; use fixed mock verification/settlement with no RPC, gas, blockchain wallet, Web3 dependency, or external network. Register its nonce in the same idempotency table under surface `x402`; invoke `CaptureService` so fresh revocation, commit, and proof precede facilitator work; append the same style of audit event.
- [ ] **Step 4: Re-run focused tests and primary regression.** Run: `uv run pytest tests/unit/adapters/x402/test_money_conversion.py tests/integration/api/test_x402_mock.py tests/integration/application/test_x402_ledger_integration.py tests/integration/e2e -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `feat: add isolated x402 facilitator mock rail`.

**Acceptance:** The optional decision-data micropayment is visible as a second ledger line under the same mandate, while the primary card demo remains unaffected and independently green.

### Task 14: Final verification, demo rehearsal, and delivery artifacts

**Files:**

- Create: `docs/verification/aval-test-evidence.md`, `docs/verification/architecture-traceability.md`
- Create: `tests/unit/test_delivery_docs.py`
- Modify: `README.md`, `docs/demo-runbook.md`, `docs/decision-log.md`

**Interfaces:**

- Consumes: all prior public routes, demo seed, and tests.
- Produces: reproducible evidence of tests/demo, documented cut line, README entry points, and only ratified Flight Log additions.

- [ ] **Step 1: Write a failing verification check.** Add a markdown-validation test that requires the runbook to name the clean start command, primary journey, all six required adverse/visibility scenarios, the authenticated revocation/commit-point race demonstration, trial-by-fire commands, fallback scripted-agent path, and x402-off degradation statement.
- [ ] **Step 2: Run it first.** Run: `uv run pytest tests/unit/test_delivery_docs.py -q`. Expected: failure until the delivery artifacts are complete.
- [ ] **Step 3: Execute the full suite and a clean-environment rehearsal.** Run: `uv run pytest -q`; reset only the named demo database through the documented seed command; start the app; perform the full human/merchant/auditor journey; execute one unseen-limit and one revocation intervention. Capture command output and screenshots/links as evidence.
- [ ] **Step 4: Complete docs and re-run the check.** Add exact results, known demo limitations, and whether Task 13 was intentionally omitted. Run: `uv run pytest tests/unit/test_delivery_docs.py -q` and `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Suggested commit: `docs: finalize aval verification and demo runbook`.

**Acceptance:** A reviewer can clone, seed, execute tests, demonstrate the core scenarios, and understand exactly what is or is not included without relying on a team member's memory.

## Explicit coverage of mandatory scenarios

| Required scenario | Core behavior | Plan tasks | Primary verification |
| --- | --- | --- | --- |
| Purchase outside mandate | Core returns `AWAITING_HUMAN/unresolved_constraint`; UCP projects `requires_escalation` and a continuation URL; never silently capture. | 4, 7, 12 | `test_out_of_mandate.py`, `test_ucp_checkout.py`, `test_required_adversarial_scenarios.py` |
| Expired mandate | Server clock rejects expiration before reservation and again at capture. | 3, 4, 5, 12 | `test_expired_mandate.py`, `test_capture_revalidates_revocation.py`, E2E scenario |
| Real-time revocation | Signed authority writes an append-only revocation; a fresh primary read happens at authorization and under the same capture lock before `Reservation → COMMITTED`. | 3, 4, 5, 11, 12 | `test_signed_revocation.py`, `test_revocation_commit_race.py`, `test_revocation_storage_failure.py`, `test_trial_by_fire_effect.py` |
| Impostor agent | Local trusted-profile registry and RFC 9421 raw-body verification reject unsigned/unknown/tampered requests. | 3, 6, 12 | `test_http_signatures.py`, `test_ucp_authentication.py`, E2E scenario |
| Dispute | Read-only reconstruction verifies the evidence/receipt chain and returns a legible verdict. | 9, 10, 12 | `test_dispute_reconstruction.py`, E2E scenario |
| Readable audit | Append-only events hold machine reason, Portuguese summary, actor, timestamp, and evidence reference; three views render it. | 5, 9, 10, 12 | `test_audit_timeline.py`, UI tests, `test_audit_readability.py` |

## Requirements traceability matrix

| Architecture/rule requirement | Plan tasks | Verification test(s) |
| --- | --- | --- |
| Authorization Core is only source of truth; adapters have no policy/state | 2, 4, 5, 7, 8, 9 | domain mapping tests; authorization-order tests; end-to-end regression |
| UCP is primary checkout and AP2 extension security-locks session | 6, 7 | `test_ucp_discovery.py`, `test_ap2_checkout_lock.py` |
| RFC 9421 defends agent identity | 3, 6 | `test_ecdsa_raw_signature.py`, `test_http_signatures.py`, `test_ucp_authentication.py` |
| Raw bytes are used for Content-Digest | 3, 6 | `test_content_digest.py`, `test_http_signatures.py` |
| AP2 is cryptographic evidence, not live policy | 3, 4, 7, 9 | authorization-order; AP2 checkout lock; receipt ordering |
| Human-Not-Present mandates and key binding | 4, 7 | `test_ap2_replay_binding.py`, primary E2E |
| ACP never exposes card and Allowance is derived | 8 | `test_derived_allowance.py`, `test_pan_redaction.py` |
| Capture reserves before settlement and prevents double spend | 5, 9 | `test_concurrent_capture.py`, `test_capture_idempotency.py` |
| One commit point protects every settlement rail | 2, 5, 9, 13 | `test_revocation_commit_race.py`, `test_authorization_proof_replay.py`, `test_x402_ledger_integration.py` |
| Mandate revocation is signed, scoped, and fail-closed | 3, 4, 5, 11, 12 | `test_signed_revocation.py`, `test_revocation_storage_failure.py`, `test_admin_trial_by_fire.py` |
| AuthorizationProof is post-commit, bounded, and one-use | 3, 5, 9, 12 | `test_authorization_proof.py`, `test_authorization_proof_replay.py` |
| Idempotency is durable and fail-closed | 5 | `test_capture_idempotency.py`, `test_idempotency_storage_failure.py` |
| Receipts/audit are append-only and human-readable | 9, 10 | `test_receipt_ordering.py`, `test_audit_timeline.py`, UI tests |
| Trial by fire affects next decision without restart | 4, 11, 12 | `test_admin_trial_by_fire.py`, `test_trial_by_fire_effect.py` |
| x402 is isolated and deferred | 12, 13 | Task-13 prerequisite output; x402 integration tests; primary E2E regression |
| No Gemini, ADK, A2A, MCP, or Web3 scope creep | 1, 13, 14 | dependency/README review; x402 mock tests; delivery-doc check |

## Technical risks and cut lines

| Risk | Preventive design and failing-first test | Operational line of cut |
| --- | --- | --- |
| ECDSA DER instead of raw `r||s` | Convert explicitly at the RFC 9421 boundary; fixture asserts 64-byte P-256 signatures. | Never downgrade signature verification for the demo. |
| Digest computed from reserialized JSON | Middleware retains raw request bytes; unicode/order fixture requires a mismatch when bytes differ. | No proxy that mutates body bytes; use local/pass-through networking. |
| JCS implemented as `sort_keys` | Use a validated RFC 8785 library and accent/emoji fixture. | Do not ship merchant authorization if the JCS vector is red. |
| Concurrent capture/double spend | SQLite WAL + `BEGIN IMMEDIATE`, unique transaction/attempt constraints, reservation-before-network test. | SQLite is demo-only with one process writer; migration boundary stays isolated for later Postgres. |
| Idempotency race or data-store failure | Composite `(surface, key)` record, request hash, in-flight status, and closed 503 on store error. | Do not omit idempotency to unblock a demo. |
| Revocation race, stale cache, or fail-open | Shared `mandate_id` transaction lock, fresh primary-store lookup at commit, signed authority test, and 503 on any revocation-store error. | No cache or warn mode on the authorization/commit path; revocation MVP is never cut. |
| Commit point outside a settlement rail | `Reservation.PENDING → COMMITTED` precedes every adapter call; adapter rejects an uncommitted reservation/proof. | Do not place the gate at the card network or create a rail-specific commit path. |
| Proof replay or pre-commit proof | Post-commit issuance, ≤60-second TTL, bound fields, and one-use `jti` in idempotency storage. | Do not allow a proof to act as pre-authorization or a reusable bearer token. |
| Monetary scale mismatch | Integer `Money`, explicit currency/scale converter, x402 atomic-string test. | Never coerce USD/USDC or different scales implicitly. |
| Protocol drift or unstable SDK | Task-1 official validation plus local `MandateSigner`/`Verifier` façades and AP2 SHA pin. | If SDK fails, use the validated local JWS fallback behind the same port; do not change domain semantics. |
| Allowance becomes stale policy | Derive it each issuance from core result; policy-change test. | Cut ACP UI before duplicating policy or delaying the core. |
| Totals change after consent | Freeze canonical checkout and re-consent on any change; tampering test. | Refuse completion rather than recalculating a signed checkout. |
| UI hides evidence | Audit event has structured + Portuguese fields and three rendering tests. | Merchant UI may merge into auditor UI only after auditor readability remains green. |
| x402 consumes core time or adds external failure | Task 13 gate, facilitator mock, no Web3/RPC/network. | First feature to cut; the card path must remain green without it. |

## Flight Log handling

The external Flight Log form is not available in this workspace. This plan does **not** treat its proposed stack as a finalized decision, so it creates no stack entry. The following are the material decisions already consolidated by the architecture and may be pasted one at a time **only if the team ratifies them**; do not log them merely because this plan exists.

### Protocol composition model

**Decision:** Protocol composition model

**Options considered (one per line):**

Implement each protocol as an independent stateful module
Compose all protocols as edge adapters over one deterministic authorization core
Use only one protocol and omit the others

**What we chose:** Compose UCP, AP2, ACP Delegate Payment, and optional x402 as edge adapters over one AVAL authorization core that owns state and policy.

**Why:** The protocols represent different transaction planes. Competing protocol state would fail under live rule changes and contradict the required single authority.

### Primary commerce protocol

**Decision:** Primary commerce protocol

**Options considered (one per line):**

ACP as the primary checkout surface
UCP as the primary checkout surface
Run UCP and ACP checkout surfaces in parallel

**What we chose:** Use UCP as the primary checkout surface and limit ACP to delegated-payment tokenization.

**Why:** UCP hosts the AP2 mandate extension, offers a protocol-visible escalation path, and signs agent requests. Parallel checkout state would duplicate authority without improving the required demo.

### Payment credential handling

**Decision:** Payment credential handling

**Options considered (one per line):**

Give card data to the agent
Create an AVAL-specific token without a protocol projection
Use an ACP Delegate Payment-shaped token with an Allowance derived from AVAL

**What we chose:** Return an opaque delegated-payment token and derive its Allowance from AVAL's live balance, mandate ceiling, and canonical checkout total.

**Why:** The agent never receives raw card data, and a derived Allowance cannot become a second policy authority after a live rule changes.

### Live authorization controls

**Decision:** Live authorization controls

**Options considered (one per line):**

Rely only on protocol constraints
Put revocation and budget logic in the LLM prompt
Implement deterministic AVAL revocation, transactional budget accounting, locks, and capture-time revalidation

**What we chose:** Keep live authorization controls in deterministic AVAL services with durable transactional state.

**Why:** Static protocol evidence cannot provide real-time revocation, policy updates, or concurrent-spend protection.

### Commit point placement

**Decision:** Commit point placement

**Options considered (one per line):**

Gate immediately before the card network
Commit at the settlement-adapter boundary after an earlier authorization decision
Revalidate only when the checkout is first authorized

**What we chose:** Use one commit point at the `SettlementAdapter` boundary, while retaining an earlier checkout authorization point that can escalate to a human.

**Why:** A card-network gate is too late to escalate a UCP checkout and excludes non-card rails such as x402. The reservation commit protects every settlement rail under the same revocation boundary.

### Reservation commit state

**Decision:** State machine that records a committed transaction

**Options considered (one per line):**

Add `COMMITTED` to the mandate state
Keep commit state only on each reservation
Maintain commit state on both mandate and reservation

**What we chose:** Keep the mandate monotonic and place `COMMITTED` only on the per-transaction `Reservation`.

**Why:** One open mandate can fund multiple purchases. Two state machines for consumption would diverge under concurrent revocation and capture; the shared mandate lock resolves that race.

### Revocation proof mechanism

**Decision:** Revocation authentication mechanism

**Options considered (one per line):**

Commit-reveal with a SHA-256 secret
Signed JWS ES256 revocation by a registered authority
Use both as mandatory mechanisms

**What we chose:** Use signed JWS ES256 revocation by a registered `RevocationAuthority`; retain a hash commitment only as an optional production privacy feature.

**Why:** Signed authorities support roles, scope, rotation, and the trial-by-fire operator. Commit-reveal does not address registry censorship or equivocation and cannot safely support operator revocation without retaining the user secret.

### Revocation availability policy

**Decision:** Revocation-store availability behavior

**Options considered (one per line):**

Fail open with a warning mode
Use cached last-known status at commit
Fail closed with `503 revocation_unavailable`

**What we chose:** Fail closed, with no cache or warn mode on the authorization or commit path.

**Why:** Any stale or unavailable status can approve exactly the revoked purchase the challenge requires AVAL to stop. Advisory UI data may be cached, but authority decisions use the primary store.

### x402 scope

**Decision:** x402 scope

**Options considered (one per line):**

Use x402 as the card-purchase settlement rail
Exclude x402 from the demo
Add a mock x402 rail after the primary core is green

**What we chose:** Add x402 only as an isolated mock rail for optional decision-data micropayments after the core-complete gate passes.

**Why:** It demonstrates rail-agnostic mandates without putting blockchain, network, or facilitator risk in the primary card path.

## Plan self-review

- **Specification coverage:** The plan maps the architecture's canonical entities, single-writer rule, UCP/RFC 9421 boundary, AP2 evidence, ACP tokenization, signed revocation authorities, one reservation commit point, post-commit proof, capture ordering, audit/dispute, live trial-by-fire control, and isolated x402 rail to concrete tasks and tests. All six mandatory challenge scenarios and the new Section 11 revocation cases are explicitly covered above.
- **No placeholders:** Every task lists exact file paths, interfaces, failing-first test scope, command, smallest implementation objective, acceptance criterion, and commit message. Values that require an external authority are deliberately gated by Task 1 rather than presented as facts.
- **Type/interface consistency:** `Money`, immutable entities, `RevocationAuthority`, `AuthorizationProof`, `AuthorizationCore`, `MandateSigner`/`MandateVerifier`, `RevocationVerifier`, `SettlementAdapter`, and `AuditLedger` are introduced before their consumers. Protocol DTOs remain adapter-local, while later tasks use only the named core contracts.
- **Scope consistency:** Gemini, ADK, A2A, MCP, Web3, real PSPs, and real chains have no planned dependency. x402 is gated after complete core regression and remains removable without affecting the primary demo.
