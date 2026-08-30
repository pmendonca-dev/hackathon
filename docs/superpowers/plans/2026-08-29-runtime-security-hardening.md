# Runtime Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the live payment runtime into conformance with the published runtime API contract before Task 12 E2E gating.

**Architecture:** `AuthorizationCore` stays the sole mutable authorization and settlement authority. Checkout completion verifies AP2 evidence but only marks a checkout ready for capture; `POST /payment-captures` performs the sole Core commit and PSP settlement. Every contract route authenticates through the existing RFC 9421 verifier over the raw request bytes.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/SQLite, Alembic, pytest, RFC 9421, JWS/JCS.

**Spec:** `docs/contracts/aval-payment-runtime-api.md`

## Global Constraints

- Do not add x402, Web3, a real PSP, or a second policy engine.
- Preserve the published `POST /payment-captures` input shape; reject caller-supplied mandate, merchant, and amount.
- Never return an AuthorizationProof, PAN, or signed revocation evidence.
- Keep all POST idempotency durable and fail closed if it is unavailable.
- Do not create a pull request or merge this branch.

---

### Task 1: Stable operational boundary errors and capture rejection tests

**Files:**
- Modify: `src/aval/main.py`, `src/aval/api/routers/payment_capture.py`
- Test: `tests/integration/api/test_live_payment_runtime.py`

**Interfaces:**
- Consumes: RFC 9421 `authenticate_rfc9421`, `PaymentRuntime.capture`.
- Produces: stable `request_invalid`, `revocation_unavailable`, and `transaction_already_captured` HTTP responses.

- [ ] **Step 1: Write failing HTTP tests** for extra capture scope fields, AP2 failures, unavailable revocation, and second capture with a new idempotency key.
- [ ] **Step 2: Run those tests** and verify the pre-change response codes or side effects differ from the contract.
- [ ] **Step 3: Implement minimal handlers and response mapping** so Pydantic validation yields `{"detail":{"code":"request_invalid"}}`, revocation storage failure yields 503, and a second capture yields 409.
- [ ] **Step 4: Run the focused tests** and verify no PSP/receipt/settlement event is created on AP2 failure.

### Task 2: Signed mandate revocation HTTP boundary

**Files:**
- Modify: `src/aval/application/authorization_core.py`, `src/aval/api/routers/revocation.py`, `src/aval/main.py`
- Test: `tests/integration/api/test_live_payment_runtime.py`

**Interfaces:**
- Consumes: `AuthorizationCore.submit_signed_revocation(token)` and durable SQLite idempotency records.
- Produces: `POST /mandates/{mandate_id}/revocations`, 202 replayable response, and `mandate.revoked` audit event.

- [ ] **Step 1: Write failing signed HTTP revocation tests** for required signatures, mandate mismatch, replay header, pre-commit denial, and post-commit preservation.
- [ ] **Step 2: Run the revocation tests** and verify the route is absent.
- [ ] **Step 3: Add an idempotent Core-backed revocation service and authenticated router** which preserves the signed JWS only as internal evidence and maps stable errors.
- [ ] **Step 4: Run the focused tests** and verify status, audit event, delegation, and capture behavior.

### Task 3: Checkout-completion/settlement semantic separation

**Files:**
- Modify: `src/aval/application/services/checkout.py`, `src/aval/api/routers/ucp_checkout.py`, `docs/contracts/aval-payment-runtime-api.md`, `docs/contracts/aval-checkout-api.md`, `docs/decision-log.md`
- Test: `tests/integration/api/test_ucp_checkout.py`, `tests/integration/api/test_ucp_runtime.py`

**Interfaces:**
- Consumes: canonical checkout and AP2 closed-checkout verifier.
- Produces: an AP2-verified checkout completion response that never commits or settles a reservation.

- [ ] **Step 1: Write failing tests** asserting complete reports readiness, does not call Core capture, and leaves settlement exclusively to `POST /payment-captures`.
- [ ] **Step 2: Run the focused completion tests** and verify they fail because completion currently invokes `core.capture`.
- [ ] **Step 3: Replace completion capture with an AP2 verification result** and document the precise readiness status.
- [ ] **Step 4: Run checkout and payment-runtime integration tests** to verify completion followed by capture settles exactly once.

### Task 4: Verification and publication

**Files:**
- Modify: `docs/decision-log.md`, `docs/contracts/aval-payment-runtime-api.md`

- [ ] **Step 1: Update the API contract** for revocation authentication/error semantics, double-capture conflict, and completion/capture separation.
- [ ] **Step 2: Run Alembic, API/application suites, requested E2E suite if present, complete pytest, and demo smoke.**
- [ ] **Step 3: Rebase against `origin/main`, rerun affected and full tests, verify a clean working tree, commit, and push the existing branch.**
