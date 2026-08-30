# Task 12 E2E Evidence

## Status

**RED — not complete.** This file records observed evidence; it is not a claim
that Task 12 passes. Green status requires every required scenario to execute
against the Laptop A runtime after that runtime is merged into `origin/main`.

## Runtime inspected

- Base: PR #5 merge on `origin/main`, commit `fa2731a`.
- Payment contract: Laptop A commit `b7fb4f7`.
- First live runtime publication tested: Laptop A commit `9904b06`.
- Laptop B runs the runtime branch only in a detached verification worktree and
  does not copy or modify Laptop A implementation code.

## Red tracer bullets observed

### Signed revocation API

Public call:

```text
POST /mandates/mandate_01/revocations
Idempotency-Key: invalid-revocation-1
{"signed_revocation":"not-a-valid-jws"}
```

Expected: `422 {"detail":{"code":"revocation_invalid"}}` from the published
endpoint. Observed on both `origin/main` and runtime commit `9904b06`: `404 Not
Found`. The route is not mounted.

### Authenticated agent boundary

After a valid RFC 9421-signed UCP checkout, Laptop B called ACP delegation with
no actor authentication and a valid idempotency key.

Expected: `401` or `403`, with no vault token. Observed on runtime commit
`9904b06`: `201 Created` and a `vt_*` token. The endpoint does not yet enforce
the authenticated actor required by the contract.

## Additional contract gaps blocking required scenarios

- The published capture request requires `ap2.checkout_mandate` and
  `ap2.payment_mandate`; runtime commit `9904b06` declares the request model with
  `extra="forbid"` and no `ap2` field.
- The contract names no concrete authentication header/signature scheme for
  ACP, capture, receipts, audit, dispute, or revocation. Laptop A must publish
  or consistently reuse a public actor-authentication mechanism before
  impostor, invalid-signature, and tampered-body E2E tests can assert stable
  behavior without inventing a protocol.
- Expiry and revocation-store-unavailable scenarios require a deterministic
  runtime setup seam. No public demo control or injectable application-factory
  seam is published yet.

## Required scenario ledger

| Scenario | Current evidence |
|---|---|
| Valid complete purchase | Blocked by capture/AP2 contract drift |
| Amount or merchant outside mandate → escalation, no capture | Pending integrated runtime |
| Expired mandate | Blocked by deterministic clock/setup seam |
| Revocation before commit | Blocked by missing revocation endpoint |
| Revocation unavailable → 503 fail-closed | Blocked by deterministic failure seam |
| Impostor agent | Red: unauthenticated delegation returns 201 |
| Invalid signature and tampered body | Pending published payment auth scheme |
| Capture/proof replay or race | Pending integrated authenticated capture API |
| Receipt, timeline, and dispute | Pending integrated runtime |
| Post-commit revocation blocks future authority only | Blocked by missing revocation endpoint |

The ledger must be replaced with actual passing request/response evidence before
the status changes to green.
