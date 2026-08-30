# AVAL Live Demo Runbook

## Current gate

Task 12 is red on Laptop A runtime commit `3191d3e`. Do not present the trial
revocation as operational until the signed revocation route, the fail-closed
503 mapping, and capture replay semantics pass the public E2E suite. See
`docs/task-12-e2e-evidence.md` for exact requests and responses.

## Clean verification

From the repository root in PowerShell 5.1:

```powershell
uv run alembic upgrade head
uv run pytest tests/integration/e2e -q
uv run pytest -q
Set-Location web
npm test
npm run build
npm run lint
Set-Location ..
uv run python scripts/demo_smoke.py
```

The smoke command invokes the real composed FastAPI application and sends
RFC 9421-authenticated HTTP requests. It does not use the browser fixture and
does not invoke Core services directly. x402 is deliberately excluded.

## Public demo journey after the gate is green

1. Create the canonical UCP checkout through `POST /checkout-sessions` using a
   trusted agent RFC 9421 signature.
2. Delegate the card through
   `POST /agentic_commerce/delegate_payment`; keep the PAN out of all later
   requests and projections.
3. Build a closed AP2 checkout mandate bound to the returned merchant
   authorization, audience, and nonce.
4. Capture through `POST /payment-captures` using only the checkout id, opaque
   vault token, audience, nonce, and AP2 evidence.
5. Read the settled capture and receipts, then read the mandate audit and
   dispute projections with signed reader identities.
6. Submit a holder-signed JWS to
   `POST /mandates/{mandate_id}/revocations` and reload canonical state. Never
   emulate the result in browser state.
7. Show that a future delegation is blocked while the earlier settled capture
   and its receipts remain intact; the audit timeline must contain the
   revocation and the dispute must explain the post-commit remedy.

## Browser source modes

The HTTP gateway is the default browser path. A fixture is available only in a
Vite development process with `VITE_AVAL_USE_MOCK=true`; the application then
shows the persistent mock-data provenance strip. Never use that mode as Task
12 evidence.

The runtime requires RFC 9421 on every payment, receipt, audit, dispute, and
revocation endpoint. The repository currently publishes no safe browser
signing bridge, so a direct default browser session receives an unavailable or
authentication error rather than simulated live data. Private runtime signing
keys must not be embedded in Vite variables or shipped to the browser.

## Trial-by-fire behavior while red

- Signed revocation is shown as unavailable because the published route returns
  404 on `3191d3e`.
- Limit reduction, scope change, and budget-zero remain unavailable because no
  public administrative endpoints are defined for them.
- No trial command may mutate browser-only state or display a fabricated
  success receipt.
