# Task 12 E2E Evidence

## Status

**GREEN ON THE REAL SAME-ORIGIN FASTAPI DELIVERY.** `origin/main` commit
`b7e94dddc50f05addd71fafe3ce02a2a3312f44a` after PR #16 serves the production SPA and the
browser BFF on `http://127.0.0.1:8000`. Laptop B consumes only `/ui-api/v1/`,
keeps CSRF in transient React memory, and ships no fixture, payment credential,
proof value, signing implementation, agent route, or persistent-storage API in
the production artifact.

## Browser-safe BFF final validation after PR #16

### Public HTTP and routing evidence

| Scenario | Observed result |
|---|---|
| `GET /` | `200 text/html`; production SPA delivered |
| Invalid `POST /ui-api/v1/session/login` | `401 {"detail":{"code":"ui_login_invalid"}}`; proves the request reaches the BFF |
| Unknown `/ui-api/v1/does-not-exist` | `404 application/json`, never `index.html` |
| Unsigned `GET /audit/mandates/mandate_01` | `422 {"detail":{"code":"ucp_agent_invalid"}}` |
| UI audit without a session | `401 {"detail":{"code":"ui_session_required"}}` |
| Operator revocation without CSRF | `403 {"detail":{"code":"csrf_invalid"}}` |
| Browser operator revocation | `202`; subsequent audit contains `mandate.revoked` |
| Merchant, holder, auditor, and operator projections | `200`, role-scoped and redacted |

The local-HTTP login response contained only `role`, `csrf_token`, and
`expires_at`. Its cookie was named `aval_ui_session` with `HttpOnly`,
`SameSite=Strict`, and `Path=/`; `Secure` was absent only because
`AVAL_UI_LOCAL_HTTP=true`. The existing secure-mode integration test confirms
that `Secure` is present otherwise. The response body contained no session
value, credential, key, JWS, proof value, PAN, or payment token.

### Real browser evidence

The production build was served by FastAPI, not Vite Preview. The browser
completed login/logout for merchant, holder, auditor, and operator. Merchant
saw only `merchant_01` and its mandate projection. Holder and auditor saw the
authorized timeline and dispute. Operator submitted only mandate id and an
idempotency key; the server returned accepted revocation, the command inputs
were cleared, auditor subsequently saw `MANDATE.REVOKED`, and holder saw the
canonical mandate status `revoked`.

The final DOM and every role projection had zero matches for PAN, payment-token
values, proof values, compact JWS, private-key material, session-cookie name,
CSRF field, or local credential. The browser console contained zero entries.
The login credential input was `type=password`, `autocomplete=off`, and empty
after success, failure, and logout. The invalid-login error contained only the
stable `UI_LOGIN_INVALID` presentation and did not retain the submitted value.
FastAPI access logs showed only same-origin asset and `/ui-api/v1/` paths and
statuses; they contained no request body, credential, cookie, CSRF, or signing
material.

The browser-control boundary intentionally does not read cookie or browser
storage contents. Cookie attributes were verified from the redacted HTTP
response metadata, while source and artifact regressions prove there is no
Local Storage, Session Storage, IndexedDB, or Cache Storage usage.

### Production artifact evidence

The clean Vite build emitted `assets/index-CJqA_K19.js`,
`assets/index-DxkVL6f_.css`, and `index.html`. A byte-level scan found zero
`vt_` occurrences. The artifact-level test also found no `mockAvalGateway`,
synthetic proof value, compact JWS, private-key marker, browser signing code,
agent endpoint, or persistent browser storage API. The development fixture no
longer models vault tokens or authorization-proof references.

### Verification matrix

| Command | Result |
|---|---|
| `uv run alembic upgrade head` | PASS |
| `uv run pytest tests/integration/e2e -q` | PASS, 15/15 |
| `uv run python -m pytest -q` | PASS, 539/539 |
| `uv run python scripts/demo_smoke.py` | PASS, 9/9 |
| `npm --prefix web test` | PASS, 27/27 |
| `npm run build` | PASS |
| `npm run lint` | PASS, zero warnings and errors |

### Operational status

No ASGI dependency blocker remains. The real-browser gate used the declared
runtime dependency through
`uv run python -m uvicorn aval.main:app --host 127.0.0.1 --port 8000`, without
`uv run --with` or any browser authentication bypass.

## Historical validation on `3191d3e`

## Validation boundary

- Branch under test: `origin/codex/laptop-a-live-payments` at `3191d3e`.
- Laptop B branch was rebased directly onto that commit without merging main.
- Operational setup and observations use `TestClient` against the composed
  public HTTP application. Requests use real RFC 9421 signatures over the raw
  request body and real AP2/JWS credentials issued by the local runtime.
- The only direct SQLite action is the fault injection that renames the
  `revocations` table. The expected result is still observed only through
  `POST /payment-captures`; SQLite is not used to verify business outcomes.
- Dynamic vault tokens, authorization credentials, compact revocation JWSs,
  and signatures are redacted from this document.
- x402 is intentionally absent.

## Passing public scenarios

| Scenario | Evidence |
|---|---|
| Delegation without RFC 9421 | `422 {"detail":{"code":"ucp_agent_invalid"}}`; no token |
| Capture without RFC 9421 | `422 {"detail":{"code":"signature_missing"}}` |
| Missing/invalid AP2; divergent audience and nonce | `422` stable mandate codes; audit timeline unchanged; the same token then completes one valid `201` capture |
| Merchant/value outside the mandate | Checkout is `requires_escalation` with `continue_url`; delegation returns `403 merchant_out_of_scope` or `403 budget_exceeded`; no token |
| Deterministic expiry | Runtime restart at a fixed clock returns `403 mandate_expired` |
| Impostor, invalid signature, altered raw body | `403 profile_not_trusted`, `422 signature_invalid`, and `422 content_digest_invalid` |
| Valid purchase and evidence | Capture is `201 settled`; signed reads return capture, both compact-JWS receipts, audit timeline, and dispute; PAN, vault token, and raw AP2 credential are absent |

## Contract failures

### 1. Signed revocation route is not mounted

Authenticated request shape (dynamic cryptographic values redacted):

```http
POST /mandates/mandate_01/revocations
UCP-Agent: profile="https://holder.aval.local/.well-known/ucp"
Idempotency-Key: revoke-holder-1
Content-Type: application/json
Content-Digest: sha-256=:<digest>:
Signature-Input: sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" "content-digest" "content-type");keyid="holder-key";alg="ES256"
Signature: sig1=:<valid holder ES256 signature>:

{"signed_revocation":"<valid holder ES256 compact JWS>"}
```

Expected:

```http
202
{"mandate_id":"mandate_01","status":"revoked"}
```

Observed:

```http
404
{"detail":"Not Found"}
```

The same endpoint without RFC 9421 also returns `404 {"detail":"Not Found"}`
instead of authenticating and returning `422 ucp_agent_invalid`. This proves
the route is absent, not merely rejecting the authority or JWS.

### 2. Divergent merchant/total errors do not use the stable envelope

Adding either forbidden `merchant_id` or `total` to the corrected canonical
capture request returns `422` before Core, PSP, receipts, or audit mutation.
However, the response is FastAPI's validation list instead of the contract's
stable error envelope. The merchant response is exactly:

```json
{"detail":[{"type":"extra_forbidden","loc":["body","merchant_id"],"msg":"Extra inputs are not permitted","input":"merchant_other"}]}
```

The total response has the same shape with `loc` ending in `total` and the
submitted money object as `input`. A later canonical capture with the same
token succeeds once, proving the rejected requests had no downstream effect.

### 3. Revocation-store outage has the right code but wrong HTTP status

After a signed checkout and delegation, the test makes the durable revocation
table unavailable and sends:

```http
POST /payment-captures
UCP-Agent: profile="https://agent.aval.local/.well-known/ucp"
Idempotency-Key: capture-revocation-down
Content-Type: application/json
Content-Digest: sha-256=:<digest>:
Signature-Input: sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" "content-digest" "content-type");keyid="agent-key";alg="ES256"
Signature: sig1=:<valid agent ES256 signature>:

{"checkout_session_id":"chi_revocation_down","token":"<redacted vt_ token>","audience":"merchant_01","nonce":"capture-nonce","ap2":{"checkout_mandate":"<redacted issuer-jwt~kb-jwt>"}}
```

Expected `503`; observed exactly:

```http
403
{"detail":{"code":"revocation_unavailable"}}
```

The decision fails closed, but the public status contradicts the contract.

### 4. Capture replay response and double-capture code drift

For the same signed `POST /payment-captures` body:

- First key `capture-replay`: `201 settled`.
- Same key and body: `201` with the identical response, but the required
  `Idempotent-Replayed: true` header is absent.
- New key `capture-duplicate`: observed exactly
  `403 {"detail":{"code":"transaction_already_captured"}}`; the E2E contract
  expects the published proof/token replay family to be a `422` evidence
  failure.
- Signed receipts remain readable and audit contains exactly one
  `capture.committed` event, so a second settlement was not created.

The public capture request accepts no authorization proof. Consequently Task
12 cannot independently resubmit a proof by `jti` through an HTTP endpoint;
double capture is the only public trigger for that defense.

### 5. Revocation before commit does not block capture

The valid signed revocation request above returns `404`. The immediately
following valid signed `POST /payment-captures` returns `201 settled` instead
of `403 {"detail":{"code":"mandate_revoked"}}`.

### 6. Post-commit revocation is not represented

Sequence and observed public state:

1. Initial capture: `201 settled`.
2. Valid signed revocation: `404 {"detail":"Not Found"}`.
3. Future checkout: `201`.
4. Future delegation: `201` and a new `vt_` token (value redacted), instead of
   `403 mandate_revoked`.
5. Original capture and receipts: still `200 settled`, which is the correct
   non-retroactive half of the rule.
6. Dispute: `200` with a post-commit note, but no `revocation.*` event in the
   timeline because no revocation was accepted.

## Scenario ledger

| Required scenario | Result |
|---|---|
| Signed, authenticated revocation | **FAIL:** route returns 404 |
| Delegation/capture without RFC 9421 | PASS |
| Missing/invalid AP2 before downstream work | PASS through public audit + later valid capture |
| Audience and nonce divergent | PASS |
| Merchant and total fields divergent | **PARTIAL:** rejected before downstream work, but response lacks stable code envelope |
| Deterministic expiry | PASS |
| Revocation unavailable → 503 | **FAIL:** correct code under HTTP 403 |
| Impostor, invalid signature, tampered raw body | PASS |
| Replay/double capture/proof | **PARTIAL:** no second settlement; replay header/status-code contract fails; proof has no public submission seam |
| Valid purchase, receipts, audit, dispute | PASS |
| Pre-commit revocation | **FAIL:** revocation 404, capture settles |
| Post-commit revocation | **FAIL:** future delegation still succeeds; original settlement correctly remains |

Task 12 stays red until the failing public assertions pass against the real
integrated runtime and every required verification command succeeds.

## Additional upstream regression failure

The full Python suite has one Laptop A test failure outside Laptop B's E2E
directory. The signed request is:

```http
POST /checkout-sessions/chi_runtime_1/complete
Idempotency-Key: complete-1
UCP-Agent: profile="https://agent.aval.local/.well-known/ucp"
Content-Type: application/json
Content-Digest: sha-256=:<digest>:
Signature-Input: sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" "content-digest" "content-type");keyid="agent-key";alg="ES256"
Signature: sig1=:<valid agent ES256 signature>:

{"audience":"merchant_01","nonce":"challenge-1","ap2":{"checkout_mandate":"<redacted issuer-jwt~kb-jwt>"}}
```

Observed response, with dynamic identifiers redacted:

```http
200
{"approved":true,"reason_code":"settled","reservation":{"id":"<rsv_ id>","mandate_id":"mandate_01","checkout_intent_id":"chi_runtime_1","amount":{"minor_units":500,"currency":"BRL","scale":2},"status":"SETTLED","transaction_hash":"<hash>"},"settlement_reference":"<psp_mock reference>"}
```

`tests/integration/api/test_ucp_runtime.py::test_mounted_completion_loads_persisted_checkout_and_captures`
expects `reason_code == "committed"`. The public checkout contract does not
currently specify this completion response, so this is an upstream test/runtime
semantic mismatch rather than a Laptop B E2E expectation. Laptop B did not
change either side.

## Verification results

| Command | Result |
|---|---|
| `uv run alembic upgrade head` | PASS |
| `uv run pytest tests/integration/e2e -q` | **FAIL:** 6 failed, 5 passed |
| `uv run pytest -q` | **FAIL:** 7 failed, 101 passed (six E2E plus the completion reason mismatch above) |
| `npm test` | PASS: 24/24 |
| `npm run build` | PASS after TypeScript union narrowing fix |
| `npm run lint` | PASS: 0 warnings, 0 errors |
| `uv run python scripts/demo_smoke.py` | **FAIL:** 1 failed, 4 passed; post-commit revocation route is absent |
