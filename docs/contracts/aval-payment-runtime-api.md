# AVAL Payment Runtime HTTP Contract

This contract is the stable runtime boundary for ACP delegation, AVAL capture,
settlement, AP2 receipts, and audit. `AuthorizationCore` is the sole authority
for mandate state, revocation, live limits, reservations, idempotency, and
settlement state. Protocol adapters serialize Core decisions; they do not keep
policy, balances, or checkout state.

Amounts are integer minor units. No endpoint accepts floating-point amounts.
All timestamps are RFC 3339 UTC timestamps.

## Authentication and safety

Every endpoint requires a trusted RFC 9421 identity. The signature covers the
received raw body through `Content-Digest`, plus `@method`, `@authority`,
`@path`, `ucp-agent`, and `content-type`; a `POST` additionally signs
`idempotency-key`. The runtime rejects missing/invalid signatures, altered
bodies, unknown keys, and untrusted profiles before any operational service
executes. The local roles are `agent_01` (the only delegation/capture writer),
`holder_01`, and `auditor_01`. The latter two can read the authorized
cross-merchant audit projection; the agent can read only `merchant_01` facts.

Every `POST` requires a non-empty `Idempotency-Key` header. The key is durable
for at least 24 hours and is scoped to the endpoint. Repeating the same key
and body returns the original response with `Idempotent-Replayed: true`.
Reusing a key with a different body returns `422 idempotency_key_reused`; an
in-flight request returns `409 idempotency_in_flight`; unavailable durable
idempotency storage returns `503 idempotency_unavailable`.

PAN, CVV/CVC, card expiry, authorization-proof JWTs, private keys, and signed
revocation JWS payloads are never returned, placed in receipts, included in
audit summaries, or logged. Raw AP2 mandate credentials are never sent to the
PSP or placed in receipts or audit summaries. A vault token is opaque, begins
with `vt_`, and is not a card credential.

All errors use:

```json
{"detail":{"code":"stable_code"}}
```

Schema or JSON payload validation returns `422 request_invalid`; no framework
validation details are exposed.

## Delegate payment (preserved)

`POST /agentic_commerce/delegate_payment`

Requires a trusted agent authentication context and `Idempotency-Key`.

```json
{
  "mandate_id": "mandate_01",
  "checkout_session_id": "chi_01",
  "merchant_id": "merchant_01",
  "payment_method": {"card_number": "4242424242424242"}
}
```

`201 Created`:

```json
{
  "token": "vt_local_opaque_value",
  "allowance": {
    "reason": "one_time",
    "max_amount": 500,
    "currency": "brl",
    "checkout_session_id": "chi_01",
    "merchant_id": "merchant_01",
    "expires_at": "2026-08-30T12:00:00Z"
  }
}
```

The allowance is derived at request time exclusively from the current Core
mandate, canonical checkout, live policy limit, committed balance, expiry, and
revocation state. It is not a persistent policy copy.

Stable authorization errors are `mandate_not_found`, `mandate_revoked`,
`mandate_expired`, `merchant_out_of_scope`, `merchant_revoked`,
`checkout_not_found`, `checkout_mandate_mismatch`,
`checkout_merchant_mismatch`, `budget_exceeded`, `budget_revoked`,
`policy_denied`, and `revocation_unavailable`. They fail closed (`403`, except
storage failures, which are `503`). Invalid payment-method syntax is `422`.

## Capture and settlement

`POST /payment-captures`

Requires a trusted merchant/agent authentication context and
`Idempotency-Key`.

```json
{
  "checkout_session_id": "chi_01",
  "token": "vt_local_opaque_value",
  "audience": "merchant_01",
  "nonce": "merchant-capture-challenge",
  "ap2": {
    "checkout_mandate": "issuer-jwt~kb-jwt"
  }
}
```

`mandate_id`, `merchant_id`, and amount are deliberately not accepted here.
The runtime loads these values from `checkout_session_id`'s canonical persisted
checkout and validates the vault-token scope against them. Before Core commit,
it re-verifies the canonical merchant-authorization JCS/JWS and the closed AP2
checkout mandate's issuer signature, holder key binding, audience, nonce,
expiry, `sd_hash`, and checkout hash. The verified merchant authorization
therefore binds canonical checkout ID, merchant, line items, and total; any
divergence fails before a reservation, PSP call, receipt, or settlement event.

`201 Created` on approved settlement:

```json
{
  "capture_id": "cap_01",
  "reservation_id": "rsv_01",
  "status": "settled",
  "settlement_reference": "psp_mock_abc123",
  "receipt_url": "/payment-captures/cap_01/receipts"
}
```

`202 Accepted` is permitted only for a durably recorded settlement attempt
awaiting reconciliation. The PSP receives only a `Reservation.COMMITTED` and
a valid, single-use AuthorizationProof; it never receives a PAN or vault
token. A revoked or expired mandate, divergent merchant/checkout, missing or
invalid token, policy denial, invalid AP2 evidence, or unavailable revocation
store is rejected before settlement. Stable errors include
`transaction_already_captured`, `reservation_not_committed`, `authorization_proof_invalid`,
`authorization_proof_replayed`, `vault_token_invalid`, `vault_token_expired`,
`vault_token_scope_mismatch`, `settlement_declined`, and the delegation errors
above. A capture for an already captured canonical transaction with a new key
returns `409 transaction_already_captured`. `reservation_not_committed`, proof,
token, and evidence failures are `422`; policy/revocation failures are `403`;
unavailable durable dependencies (including `revocation_unavailable`) are
`503`.

`GET /payment-captures/{capture_id}` returns the durable capture state:

```json
{
  "capture_id": "cap_01",
  "reservation_id": "rsv_01",
  "status": "settled",
  "settlement_reference": "psp_mock_abc123"
}
```

Unknown captures return `404 capture_not_found`. This is the settlement status
endpoint; it is read-only and has no idempotency header, but does require the
RFC 9421 reader signature above.

## Receipts

`GET /payment-captures/{capture_id}/receipts`

Requires a signed trusted reader. The merchant identity can read only a capture
whose canonical checkout belongs to that merchant; holder and auditor identities
can read the authorized cross-merchant projection. It returns receipts only
after approved settlement:

```json
{
  "capture_id": "cap_01",
  "checkout_receipt": "eyJ...",
  "payment_receipt": "eyJ..."
}
```

Before settlement it returns `409 receipts_not_available`; unknown captures
return `404 capture_not_found`. Receipt claims contain AP2 references and the
PSP confirmation only; they never contain payment credentials or a Core proof.

## Audit and dispute (preserved)

`GET /audit/mandates/{mandate_id}` and
`GET /audit/mandates/{mandate_id}/dispute` require a signed trusted reader. A
merchant receives only its merchant projection; holder and auditor receive the
authorized mandate projection. An anonymous or unauthorized reader receives
`422` with an RFC authentication code or `403 reader_not_authorized`. They
return the append-only, human-readable timeline and the dispute verdict. They
return `404 mandate_not_found` when the mandate is unknown and `503
audit_unavailable` if durable evidence cannot be read. A
revocation after a committed reservation is recorded in this timeline but does
not rewrite the settled capture; the dispute result states that reversal,
refund, or dispute is the available remedy.

## Signed revocation

`POST /mandates/{mandate_id}/revocations` requires an authenticated registered
authority and `Idempotency-Key`. Its RFC 9421 signing key must match the key
named by the signed revocation JWS and that JWS must validate against a
registered mandate authority. Its body contains the already signed revocation
JWS:

```json
{"signed_revocation":"eyJ..."}
```

`202 Accepted` returns `{"mandate_id":"mandate_01","status":"revoked"}`.
Malformed, unauthorised, mismatched, or disallowed revocations return `422`
with `revocation_invalid`, `revocation_authority_unknown`,
`revocation_mandate_mismatch`, or `revocation_scope_not_allowed`. The JWS is
stored as protected audit evidence but never returned by this API. An accepted
mandate revocation appends `mandate.revoked`; it blocks later delegation and
capture but never rewrites an already committed or settled reservation.

## Local seed examples

The local runtime seeds `mandate_01`, `merchant_01`, and trusted
`agent_01`. Create canonical checkout `chi_01` through the checkout contract,
then delegate a local test PAN to receive a `vt_` token. Use that exact token
with a `500 BRL` capture for `merchant_01`. The seed is intentionally limited
to a BRL 100.00 mandate and expires one day after runtime initialization; no
seed PAN, vault token, proof, or receipt is stable across runtime instances.
