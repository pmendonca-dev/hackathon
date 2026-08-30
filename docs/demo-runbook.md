# AVAL Live Demo Runbook

## Current gate

The public runtime, browser-BFF HTTP matrix, and real browser flow are green on
`origin/main` commit `b7e94ddd` after PR #16: migrations, 15 public E2E
scenarios, the 539-test Python suite, the nine-scenario demo smoke, and all 27
web tests pass. FastAPI
serves the production SPA and `/ui-api/v1/` from the same origin. The emitted
artifact contains no fixture module, `vt_` prefix, proof value, signing
material, agent route, or persistent-storage API.

Do not use Vite Preview as authenticated live evidence: it intentionally does
not route `/ui-api/v1/`. Use the FastAPI origin described below.

## Clean verification

From the repository root in PowerShell 5.1:

```powershell
uv run alembic upgrade head
uv run pytest tests/integration/e2e -q
uv run python -m pytest -q
Set-Location web
npm test
npm run build
npm run lint
Set-Location ..
uv run python scripts/demo_smoke.py
```

The smoke command invokes the real composed FastAPI application, exercises
cookie/CSRF-protected browser-BFF routes, and sends RFC 9421-authenticated agent
requests. It does not use the browser fixture or invoke Core services directly.
x402 is deliberately excluded.

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

The same-origin BFF gateway is the default browser path. A fixture is available
only in a Vite development process with `VITE_AVAL_USE_MOCK=true`; the
application then shows the persistent mock-data provenance strip. Production
ignores that flag and its emitted artifact contains no fixture module or
synthetic token/proof values. Never use mock mode as Task 12 evidence.

The browser authenticates only through `/ui-api/v1/session/login`; its opaque
session is an HttpOnly Strict cookie, and the returned CSRF value stays in React
memory. The browser never calls agent payment, receipt, audit, dispute, or
revocation endpoints. Those routes still require RFC 9421, and private signing
keys must not be embedded in Vite variables or shipped to the browser.

Before a live browser demo, build `web/dist`, set the four role credentials and
`AVAL_OPERATOR_AUTHORITY_SEED` only in the server environment, set
`AVAL_UI_LOCAL_HTTP=true`, and serve `aval.main:app` on `127.0.0.1:8000`.
`uvicorn` is a declared runtime dependency. On managed Windows hosts, use
`uv run python -m uvicorn aval.main:app --host 127.0.0.1 --port 8000` to avoid
launcher-policy differences. Never use `uv run --with`, a cross-origin cookie
flow, an unsigned proxy, an embedded operator credential, or a signing bypass.

## Trial-by-fire behavior

- Operator revocation is operational through the cookie/CSRF BFF, creates
  audit evidence, and is available from the FastAPI-served production UI. The
  UI never asks for or receives a JWS.
- Limit reduction, scope change, and budget-zero remain unavailable because no
  public administrative endpoints are defined for them.
- No trial command may mutate browser-only state or display a fabricated
  success receipt.
