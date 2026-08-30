# AVAL Browser-Safe BFF API Contract

`/ui-api/v1/` is AVAL's same-origin browser backend-for-frontend (BFF). It is
separate from the agent-facing APIs documented in
`aval-payment-runtime-api.md`: those APIs continue to require RFC 9421
signatures, including raw-body `Content-Digest` validation. A browser never
sends an RFC 9421 signature, a signing key, JWS, AP2 mandate, payment token,
PAN, or AuthorizationProof to this namespace.

The `AuthorizationCore` remains the sole authority for mandates, live limits,
revocation, reservations, and settlement. The BFF only authenticates a local
browser principal, applies role-scoped projections, and invokes application
services.

All timestamps are RFC 3339 UTC timestamps. Amounts are integer minor units.
All error responses use the stable envelope:

```json
{"detail":{"code":"stable_code"}}
```

Framework validation details are never exposed; malformed JSON or payloads
return `422 request_invalid`.

## Browser session and CSRF rules

Successful login sets the opaque `aval_ui_session` cookie. Its value is a
random bearer value stored by the server only as a SHA-256 hash. The cookie is
`HttpOnly`, `Path=/`, and `SameSite=Strict`. It is also `Secure` except when
the explicitly local-only `AVAL_UI_LOCAL_HTTP=true` setting is enabled for a
development HTTP demo. The server never returns a session token in a JSON
body, log, error, or audit projection.

The login response returns a one-time-issued CSRF value. The server stores
only its SHA-256 hash. Every authenticated BFF `POST` requires that value in
the `X-AVAL-CSRF` header; it is compared to the authenticated session, not to
the request body. A missing, changed, expired, or revoked session receives
`401 ui_session_required`; a missing or invalid CSRF header receives
`403 csrf_invalid`.

Local browser credentials are explicit environment configuration:

- `AVAL_UI_MERCHANT_CREDENTIAL`
- `AVAL_UI_HOLDER_CREDENTIAL`
- `AVAL_UI_AUDITOR_CREDENTIAL`
- `AVAL_UI_OPERATOR_CREDENTIAL`

`AVAL_OPERATOR_AUTHORITY_SEED` is a distinct, server-only local configuration
value that enables deterministic KeyCustody signing for browser operator
revocations across restarts. It is never a browser credential and is never
stored, returned, logged, or included in an exception. If it is absent, the
operator login may still succeed but the revocation action fails closed with
`503 revocation_unavailable`.

A role without an explicit configured credential cannot log in. There is no
generated or printed fallback credential. Invalid credentials return
`401 ui_login_invalid` without revealing whether that role is configured.

## Login and logout

`POST /ui-api/v1/session/login`

This endpoint accepts only a role and its local credential:

```json
{"role":"merchant","credential":"configured-local-secret"}
```

`200 OK` sets `aval_ui_session` and returns:

```json
{
  "role":"merchant",
  "csrf_token":"browser-only-csrf-value",
  "expires_at":"2026-08-30T12:00:00Z"
}
```

Allowed roles are `merchant`, `holder`, `auditor`, and `operator`. A merchant
session is restricted to its configured merchant projection. No session value,
credential, signing key, JWS, proof, PAN, or payment token is included in this
or any other BFF response.

`POST /ui-api/v1/session/logout`

Requires a valid session cookie and `X-AVAL-CSRF`. It revokes the server-side
session, expires the browser cookie, and returns `204 No Content`. Calling it
again after logout returns `401 ui_session_required`.

## Workspace projection

`GET /ui-api/v1/workspace`

Requires a valid session cookie. The returned projection is role-scoped:

- `merchant` sees only the configured merchant's canonical checkout and
  capture summaries;
- `holder` sees its mandate and settlement summaries;
- `auditor` sees the authorized, redacted cross-merchant audit summary;
- `operator` sees operational mandate status only.

`200 OK`:

```json
{
  "role":"merchant",
  "mandates":[
    {
      "mandate_id":"mandate_01",
      "merchant_id":"merchant_01",
      "status":"active"
    }
  ]
}
```

Only the holder projection may include the holder's available amount and
currency. Every projection omits raw AP2/merchant authorization evidence,
receipt JWSs, AuthorizationProofs, card data, vault tokens, session values,
CSRF values, credentials, and keys. A valid but unauthorized role receives
`403 ui_role_not_authorized`.

## Audit and dispute projections

`GET /ui-api/v1/mandates/{mandate_id}/audit`

`GET /ui-api/v1/mandates/{mandate_id}/dispute`

Both endpoints require a valid browser session. `merchant` can read only the
projection for its configured merchant; `holder` and `auditor` can read their
authorized mandate projection. `operator` is not granted audit or dispute
read access. The results are append-only, human-readable summaries from a
closed BFF vocabulary; they never reflect raw ledger prose, evidence, or
payment credentials.

Unknown mandates return `404 mandate_not_found`; an inaccessible mandate
returns `403 ui_role_not_authorized`; durable evidence failures return `503
audit_unavailable`.

## Operator mandate revocation

`POST /ui-api/v1/mandates/{mandate_id}/revocations`

Requires an `operator` session, `X-AVAL-CSRF`, and a non-empty
`Idempotency-Key`. The request has no signed revocation JWS and accepts no
client-provided authority, merchant, amount, checkout, key, or proof:

```json
{}
```

The server constructs and signs the canonical revocation with its
`KeyCustodyService`, then submits it to the Core. The browser never receives
the signed result. An accepted request returns `202 Accepted`:

```json
{"mandate_id":"mandate_01","status":"revoked"}
```

The event is append-only. A pre-commit revocation blocks later delegation and
capture; a post-commit revocation blocks future purchases without rewriting a
committed or settled transaction. Same idempotency key and body returns the
original result with `Idempotent-Replayed: true`; reuse with a different body
returns `422 idempotency_key_reused`; an in-flight key returns `409
idempotency_in_flight`; unavailable durable idempotency returns `503
idempotency_unavailable`.

The stable role and CSRF errors above apply before revocation processing.
Core revocation errors retain their runtime codes, including
`mandate_not_found`, `mandate_revoked`, `revocation_invalid`, and
`revocation_unavailable` (`503`). A browser request that includes a
`signed_revocation` field is invalid and returns `422 request_invalid`.

## Stable BFF error codes

| HTTP status | Code | Meaning |
| --- | --- | --- |
| 401 | `ui_login_invalid` | Role credential is absent, invalid, or not enabled. |
| 401 | `ui_session_required` | Cookie is absent, expired, invalid, or revoked. |
| 403 | `csrf_invalid` | A state-changing BFF request lacks a valid session CSRF value. |
| 403 | `ui_role_not_authorized` | The authenticated role is outside the resource projection or action. |
| 422 | `request_invalid` | Request JSON, path/body schema, or forbidden client security material is invalid. |
| 422 | `idempotency_key_reused` | An idempotency key was reused with another request body. |
| 409 | `idempotency_in_flight` | An equivalent request is still executing. |
| 503 | `idempotency_unavailable` | Durable idempotency cannot fail closed. |
| 503 | `audit_unavailable` | Durable audit/dispute evidence cannot be read. |
| 503 | `revocation_unavailable` | Durable revocation state cannot fail closed. |
