# AVAL Checkout HTTP Contract

This contract is the stable UI boundary for the UCP/AP2 checkout path. UI clients render returned state and send user or agent evidence; they never evaluate policy, calculate authorization, or create settlement state.

## Create a checkout

`POST /checkout-sessions`

Request body:

```json
{
  "id": "chi_01",
  "mandate_id": "mandate_01",
  "merchant_id": "merchant_01",
  "total": {"amount": 500, "currency": "BRL", "scale": 2},
  "line_items": [{"id": "coffee", "quantity": 1, "amount": 500}],
  "capabilities": ["dev.ucp.shopping.checkout", "dev.ucp.common.payment.ap2_mandate"]
}
```

Success is `201` with a canonical UCP projection. Amounts are integer minor units; no float is accepted.

```json
{
  "id": "chi_01",
  "merchant_id": "merchant_01",
  "line_items": [{"id": "coffee", "quantity": 1, "amount": 500}],
  "totals": [{"type": "total", "amount": 500, "currency": "BRL"}],
  "status": "ready_for_complete",
  "ap2": {"merchant_authorization": "eyJ... ..signature"}
}
```

The only status values are `ready_for_complete`, `requires_escalation`, and `canceled` at this boundary. A `requires_escalation` response additionally contains a non-empty `continue_url`.

When the AP2 capability is negotiated, every response contains `ap2.merchant_authorization`, a detached ES256 JWS (`<protected>..<signature>`) over JCS of the complete response excluding only `ap2`.

## Complete a checkout

`POST /checkout-sessions/{checkout_id}/complete`

Required header: `Idempotency-Key`.

```json
{
  "audience": "merchant_01",
  "nonce": "merchant-challenge-value",
  "ap2": {"checkout_mandate": "issuer-jwt~kb-jwt"}
}
```

For an AP2-locked checkout, `checkout_mandate` is mandatory. The service verifies the merchant authorization, closed-checkout AP2 evidence, `aud`, nonce, expiry, `sd_hash`, and `checkout_hash`, then returns:

```json
{"checkout_id":"chi_01","status":"ready_for_capture"}
```

Completion means only that the canonical checkout and AP2 evidence are ready
for the payment runtime. It creates no Core reservation, PSP authorization,
settlement, or receipt. `POST /payment-captures` is the sole settlement
boundary and performs the later live Core authorization. Completion responses
are durably idempotent: same key and body returns the original response with
`Idempotent-Replayed: true`.

## Error body

All protocol errors use this body:

```json
{"detail": {"code": "mandate_required"}}
```

Stable codes: `mandate_required`, `mandate_invalid_signature`, `mandate_expired`, `mandate_scope_mismatch`, `mandate_audience_invalid`, `mandate_nonce_invalid`, `merchant_authorization_missing`, `merchant_authorization_invalid`, `idempotency_key_reused`, `idempotency_in_flight`, `idempotency_unavailable`, `profile_not_trusted`, `key_not_found`, and `signature_invalid`.

`403` is used for untrusted profile/key identity. Validation and evidence failures are `422`; an in-flight key is `409`, and unavailable durable idempotency is `503`. The client must display an escalation response but must never reinterpret it as a successful payment.
