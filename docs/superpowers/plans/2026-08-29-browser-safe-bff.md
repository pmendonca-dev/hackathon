# Browser-Safe BFF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide live browser views and an operator revocation command through a same-origin session-authenticated BFF, without browser-held signing keys or a weaker agent API boundary.

**Architecture:** Existing UCP, ACP, capture, receipt, audit, and revocation endpoints remain agent APIs protected by RFC 9421 and raw-body integrity. New `/ui-api/v1/` routes authenticate opaque server-side sessions using an HttpOnly cookie and require an in-memory CSRF token for browser writes; the BFF calls the existing application services and `AuthorizationCore`, never an agent HTTP route. The browser receives safe role projections only, while the server signs an operator revocation with `KeyCustodyService`.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite WAL, pytest, React, TypeScript, Vite, npm test.

**Spec:** `docs/superpowers/specs/2026-08-29-browser-safe-bff-design.md`

## Global Constraints

- Do not place private keys, JWS values, AP2 credentials, authorization proofs, PAN, vault tokens, session tokens, or CSRF tokens in browser bundles, storage, console output, logs, receipts, or audit summaries.
- Agent APIs retain RFC 9421, `Content-Digest`, and their existing contracts; `/ui-api/v1/` is a separate browser BFF namespace and must not bypass or redefine them.
- `AuthorizationCore` remains the only authority for mandate, policy, checkout, reservation, revocation, and audit state.
- UI session records contain only a token hash, role, merchant scope when applicable, issued/expiry/revocation timestamps, and CSRF-token hash.
- Browser writes require a valid session and CSRF token. A browser must never submit a signed revocation JWS.
- Use only explicit local-demo environment credentials. Never mint or print an operator/session credential at startup.
- The production web artifact must not contain the fixture module or synthetic `vt_`/`proof_` literals.
- x402, Web3, smart contracts, external IdP/OAuth, real PSPs, and browser RFC signing are out of scope.

---

## Ownership and delivery sequence

| Worker | Owns | Depends on |
| --- | --- | --- |
| Laptop A | sessions, migration, BFF service/routers, runtime composition, token-log removal, Python tests | BFF contract commit in Task 1 |
| Laptop B | typed BFF gateway, login/session UI, projection/Trial Console wiring, production-bundle test, browser E2E | Task-1 route contract |

Laptop A publishes the BFF API contract first. Laptop B may build its client from that commit but must not make direct calls to protected agent endpoints. Each worker uses a separate branch and no worker merges to `main`.

### Task 1: Define the BFF contract and durable session store (Laptop A)

**Files:**
- Create: `docs/contracts/aval-browser-bff-api.md`
- Create: `alembic/versions/0006_browser_ui_sessions.py`
- Create: `src/aval/infrastructure/sqlite/ui_session_repository.py`
- Modify: `src/aval/infrastructure/sqlite/models.py`
- Create: `tests/integration/application/test_ui_session_repository.py`

**Interfaces:**
- Produces `UiSessionRecord(id, token_hash, csrf_hash, role, merchant_id, issued_at, expires_at, revoked_at)`.
- Produces `SqliteUiSessionRepository.create(record)`, `get_active_by_token_hash(token_hash, now)`, `revoke(id, now)`, and `rotate_csrf(id, csrf_hash)`.
- The contract defines `POST /ui-api/v1/session/login`, `POST /ui-api/v1/session/logout`, `GET /ui-api/v1/workspace`, `GET /ui-api/v1/mandates/{mandate_id}/audit`, `GET /ui-api/v1/mandates/{mandate_id}/dispute`, and `POST /ui-api/v1/mandates/{mandate_id}/revocations`.

- [ ] **Step 1: Write the BFF contract before implementation.**

Document the cookie name, `X-Aval-CSRF` request header, all safe request/response DTOs, `401 ui_session_required`, `403 ui_role_not_authorized`, `403 csrf_invalid`, session expiry behavior, and the statement that agent endpoints remain RFC 9421-only.

- [ ] **Step 2: Commit and publish the contract handoff.**

```bash
git add docs/contracts/aval-browser-bff-api.md
git commit -m "docs: publish browser BFF API contract"
git push --set-upstream origin codex/laptop-a-browser-bff
```

- [ ] **Step 3: Write failing repository tests.**

```python
def test_active_session_requires_matching_token_hash_and_unexpired_record(): ...
def test_revoked_or_expired_session_is_not_returned(): ...
def test_csrf_rotation_invalidates_the_previous_hash(): ...
```

- [ ] **Step 4: Run the focused test and confirm failure.**

Run: `uv run pytest tests/integration/application/test_ui_session_repository.py -q`

- [ ] **Step 5: Add forward migration and repository implementation.**

Create `browser_ui_sessions` with a primary-key session id, unique token hash, CSRF hash, role, nullable merchant scope, issued/expiry timestamps, nullable revoked timestamp, and indexes for active lookup. Hash tokens with SHA-256 before persistence; store no plaintext session or CSRF value.

- [ ] **Step 6: Re-run focused test and migration.**

Run: `uv run alembic upgrade head && uv run pytest tests/integration/application/test_ui_session_repository.py -q`

- [ ] **Step 7: Commit.**

```bash
git add alembic/versions/0006_browser_ui_sessions.py src/aval/infrastructure/sqlite/models.py src/aval/infrastructure/sqlite/ui_session_repository.py tests/integration/application/test_ui_session_repository.py
git commit -m "feat: persist browser UI sessions"
```

### Task 2: Implement server-side browser authentication and remove stdout secrets (Laptop A)

**Files:**
- Create: `src/aval/application/services/ui_sessions.py`
- Create: `src/aval/api/routers/ui_sessions.py`
- Modify: `src/aval/main.py`
- Modify: `src/aval/runtime.py`
- Create: `tests/integration/api/test_ui_session_api.py`
- Create: `tests/unit/application/test_ui_sessions.py`

**Interfaces:**
- Produces `UiSessionService.login(role: str, credential: str) -> IssuedUiSession`, `authenticate(cookie_value: str) -> UiPrincipal`, `validate_csrf(principal, csrf_value) -> None`, and `logout(principal) -> None`.
- `IssuedUiSession` contains an opaque cookie value and CSRF value only at issuance; neither is logged or serialized after the login response.
- `UiPrincipal` contains role and merchant scope, not a credential or signing key.

- [ ] **Step 1: Write failing service tests.**

```python
def test_login_issues_opaque_cookie_and_csrf_without_persisting_plaintext(): ...
def test_expired_session_returns_ui_session_required(): ...
def test_mutation_with_wrong_csrf_returns_csrf_invalid(): ...
def test_runtime_startup_does_not_print_operator_or_session_secret(capsys): ...
```

- [ ] **Step 2: Run focused tests and confirm failure.**

Run: `uv run pytest tests/unit/application/test_ui_sessions.py -q`

- [ ] **Step 3: Implement local-demo credential resolution.**

Use explicit role-scoped environment credentials such as `AVAL_UI_MERCHANT_CREDENTIAL`, `AVAL_UI_HOLDER_CREDENTIAL`, `AVAL_UI_AUDITOR_CREDENTIAL`, and `AVAL_UI_OPERATOR_CREDENTIAL`. Compare with `hmac.compare_digest`; a missing credential disables that role rather than creating or printing a fallback secret. Remove the startup print of the operator token and do not expose any replacement token endpoint.

- [ ] **Step 4: Implement login/logout routes.**

Set an HttpOnly, SameSite=Strict cookie with `Secure` outside documented local HTTP demo mode. Return the CSRF value only in the successful login response. Logout revokes the server session and emits a clearing cookie. Return stable BFF errors for invalid login, expired session, and invalid CSRF.

- [ ] **Step 5: Add HTTP tests.**

Test successful login, absent cookie, expired/revoked cookie, cookie attributes, logout, incorrect credential, CSRF failure, and an assertion that neither response body nor captured stdout contains a credential/token.

- [ ] **Step 6: Run focused tests.**

Run: `uv run pytest tests/unit/application/test_ui_sessions.py tests/integration/api/test_ui_session_api.py -q`

- [ ] **Step 7: Commit.**

```bash
git add src/aval/application/services/ui_sessions.py src/aval/api/routers/ui_sessions.py src/aval/main.py src/aval/runtime.py tests/unit/application/test_ui_sessions.py tests/integration/api/test_ui_session_api.py
git commit -m "feat: add browser-safe UI sessions"
```

### Task 3: Add role-scoped BFF projections and operator revocation (Laptop A)

**Files:**
- Create: `src/aval/application/services/ui_projections.py`
- Create: `src/aval/application/services/ui_operator_revocation.py`
- Create: `src/aval/api/routers/ui_workspace.py`
- Modify: `src/aval/main.py`
- Create: `tests/integration/api/test_ui_projection_api.py`
- Create: `tests/integration/api/test_ui_operator_revocation_api.py`

**Interfaces:**
- Produces `UiProjectionService.workspace(principal)`, `audit(principal, mandate_id)`, and `dispute(principal, mandate_id)`.
- Produces `UiOperatorRevocationService.revoke(principal, mandate_id, idempotency_key)`.
- Operator revocation signs the canonical server-side request through `KeyCustodyService` and calls the existing Core revocation path; raw JWS is never accepted from `/ui-api/v1/`.

- [ ] **Step 1: Write failing role-projection tests.**

```python
def test_merchant_cannot_read_another_merchants_projection(): ...
def test_holder_and_auditor_read_the_allowed_projection_without_credentials(): ...
def test_workspace_never_serializes_pan_token_proof_or_raw_jws(): ...
def test_operator_revocation_requires_session_csrf_and_idempotency(): ...
```

- [ ] **Step 2: Run focused tests and confirm failure.**

Run: `uv run pytest tests/integration/api/test_ui_projection_api.py tests/integration/api/test_ui_operator_revocation_api.py -q`

- [ ] **Step 3: Implement safe serializers and routes.**

Reuse existing checkout, receipt, audit, and dispute serializers. Remove receipt JWTs, payment tokens, proofs, and raw AP2 material from browser projections. Require the session dependency on every `/ui-api/v1/` route and require CSRF plus `Idempotency-Key` on the operator revocation route.

- [ ] **Step 4: Implement server-signed revocation.**

Use the operator custody key inside `KeyCustodyService` to construct the revocation accepted by `AuthorizationCore.submit_signed_revocation_idempotent`. Persist the existing append-only event with actor `operator_01`; return only mandate id and revoked status.

- [ ] **Step 5: Prove direct agent APIs remain isolated.**

Add an assertion that a cookie-authenticated browser request to `/audit/mandates/{id}` without RFC 9421 still returns the RFC authentication error, while the equivalent `/ui-api/v1/` request succeeds only with its session.

- [ ] **Step 6: Run affected backend suites.**

Run: `uv run pytest tests/integration/api/test_ui_projection_api.py tests/integration/api/test_ui_operator_revocation_api.py tests/integration/e2e -q`

- [ ] **Step 7: Commit and publish Laptop-A handoff.**

```bash
git add src/aval/application/services/ui_projections.py src/aval/application/services/ui_operator_revocation.py src/aval/api/routers/ui_workspace.py src/aval/main.py tests/integration/api/test_ui_projection_api.py tests/integration/api/test_ui_operator_revocation_api.py
git commit -m "feat: add role-scoped browser BFF"
git push
```

### Task 4: Replace direct agent calls with the BFF gateway and remove fixtures from production build (Laptop B)

**Files:**
- Create: `web/src/gateways/uiBffGateway.ts`
- Modify: `web/src/gateways/createAvalGateway.ts`
- Modify: `web/src/contracts/avalGateway.ts`
- Modify: `web/src/state/AvalProvider.tsx`
- Modify: `web/src/pages/HumanView.tsx`
- Modify: `web/src/pages/MerchantView.tsx`
- Modify: `web/src/pages/AuditorView.tsx`
- Modify: `web/src/pages/TrialConsole.tsx`
- Create: `web/tests/ui-bff-gateway.test.mjs`
- Create: `web/tests/production-bundle-safety.test.mjs`

**Interfaces:**
- Consumes the exact contract from `docs/contracts/aval-browser-bff-api.md`.
- Produces `UiBffGateway.login`, `logout`, `loadWorkspace`, `loadAudit`, `loadDispute`, and `revokeMandate`.
- CSRF exists only in React memory; browser fetch sends credentials with `credentials: "same-origin"`.

- [ ] **Step 1: Write failing gateway tests.**

```js
test('mutations send the in-memory CSRF header and same-origin credentials', async () => {});
test('the gateway never calls an RFC 9421 agent endpoint from the browser', async () => {});
test('logout clears in-memory role and CSRF state', async () => {});
```

- [ ] **Step 2: Run focused test and confirm failure.**

Run: `npm test -- ui-bff-gateway.test.mjs`

- [ ] **Step 3: Implement session-aware UI gateway.**

Replace direct calls to `/audit/` and `/payment-captures/` with `/ui-api/v1/` calls. Add a local-demo login form that accepts a credential once, stores only the returned role and CSRF token in React memory, and provides logout. Do not place CSRF or session data in local/session/IndexedDB storage.

- [ ] **Step 4: Replace the JWS Trial Console interaction.**

The operator console submits only the mandate id and Idempotency-Key to the BFF. Remove the JWS input, clear all command input after completion, and render the returned audited status with no secret-bearing debug content.

- [ ] **Step 5: Remove mock code from production artifacts.**

Replace the static fixture import with a development-only dynamic import guarded by Vite's compile-time `import.meta.env.DEV` and `VITE_AVAL_USE_MOCK === "true"`. The production gateway must fail visibly when the BFF is unavailable.

- [ ] **Step 6: Add artifact-level test.**

Build production assets in the test command and assert no `mockAvalGateway`, `vt_`, `proof_`, private-key marker, JWS marker, or signing implementation occurs in `web/dist/assets/*`.

- [ ] **Step 7: Run frontend checks.**

Run: `npm test && npm run build && npm run lint`

- [ ] **Step 8: Commit and publish Laptop-B handoff.**

```bash
git add web/src web/tests
git commit -m "feat: use browser-safe BFF gateway"
git push --set-upstream origin codex/laptop-b-browser-bff-ui
```

### Task 5: Re-run Task 12 with browser inspection (Laptop B)

**Files:**
- Create: `tests/integration/e2e/test_browser_safe_bff.py`
- Modify: `tests/integration/e2e/test_task_12_live_runtime.py`
- Modify: `scripts/demo_smoke.py`
- Modify: `docs/task-12-e2e-evidence.md`

**Interfaces:**
- Consumes the merged Laptop-A BFF routes and Laptop-B gateway.
- Produces the final Task-12 browser-security evidence.

- [ ] **Step 1: Write failing BFF E2E tests.**

```python
def test_ui_audit_requires_session_but_agent_audit_still_requires_rfc9421(): ...
def test_ui_operator_revocation_requires_csrf_and_creates_audit_event(): ...
def test_browser_projection_redacts_pan_token_proof_and_raw_jws(): ...
def test_unsigned_browser_request_cannot_operate_an_agent_endpoint(): ...
```

- [ ] **Step 2: Run focused tests and confirm failure before integration.**

Run: `uv run pytest tests/integration/e2e/test_browser_safe_bff.py -q`

- [ ] **Step 3: Rebase onto the published Laptop-A BFF branch.**

```bash
git fetch origin
git rebase origin/codex/laptop-a-browser-bff
```

- [ ] **Step 4: Implement only UI/test glue needed for the published contract.**

Do not alter backend semantics. If an API divergence is discovered, report the exact request, response, and contract section to Laptop A.

- [ ] **Step 5: Run the complete gate.**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/integration/e2e -q
uv run pytest -q
uv run python scripts/demo_smoke.py
npm test
npm run build
npm run lint
```

- [ ] **Step 6: Perform browser inspection.**

Confirm production build, DOM, visible text, console, Local Storage, Session Storage, IndexedDB, Cache Storage, and retained inputs contain no private key, runtime token, `vt_`, proof, or JWS. Confirm `/ui-api/v1/` works with the BFF session and direct agent endpoints reject unsigned browser calls.

- [ ] **Step 7: Commit evidence.**

```bash
git add tests/integration/e2e scripts/demo_smoke.py docs/task-12-e2e-evidence.md
git commit -m "test: verify browser-safe Task 12 boundary"
git push
```

## Plan self-review

- **Spec coverage:** The tasks implement the approved BFF session, role, CSRF, redaction, operator revocation, fixture-exclusion, and agent-boundary requirements.
- **Isolation:** Laptop A owns all Python persistence and BFF composition; Laptop B owns browser code and E2E evidence. The contract is published before client work.
- **Gate:** Task 12 is not reported green until automated suites and the explicit browser inspection both pass.
