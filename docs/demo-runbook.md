# AVAL Live Demo Runbook

## Current gate

The public runtime matrix is green on Laptop A commit `2b1d6f9`: migrations,
11 public E2E scenarios, the 298-test Python suite, and the five-scenario demo
smoke all pass. The browser security gate remains red for two separate reasons:
the production bundle still contains synthetic vault-token/proof fixture
values, and the repository publishes no browser-safe RFC 9421 signing/read
boundary. See `docs/task-12-e2e-evidence.md` for the exact observations.

Do not present the direct browser view as authenticated live evidence. The
public E2E and demo smoke remain valid runtime evidence because they use signed
HTTP clients and never bypass authentication.

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

The current Vite graph also statically imports the development fixture. Even
with `VITE_AVAL_USE_MOCK=false`, the browser loads that module and the
production bundle retains its synthetic `vt_` and `proof_` values. This must be
removed from the production graph before the browser security gate can pass.

## Trial-by-fire behavior while the browser gate is red

- Signed revocation is operational through an authenticated non-browser client,
  but the browser must keep it unavailable until a safe signing boundary is
  defined. Asking the operator to paste a JWS into the browser is not acceptable
  evidence for the final browser gate.
- Limit reduction, scope change, and budget-zero remain unavailable because no
  public administrative endpoints are defined for them.
- No trial command may mutate browser-only state or display a fabricated
  success receipt.
