# Laptop B Browser BFF Final Handoff

## Problem

The browser-safe BFF and same-origin FastAPI delivery are integrated on the Laptop A handoff, but the production web artifact must prove that no `vt_` literal or browser security material survives bundling. The final handoff also needs real-browser evidence against FastAPI rather than Vite Preview.

After PRs #19 and #20 landed, `main` also contains the authority-atlas, attack-scenario, and standing-order browser presentation. Those changes were written for the retired direct-agent browser gateway, while the approved BFF contract still exposes only session, role-scoped workspace, audit/dispute, and operator revocation routes. Rebasing must preserve the new presentation without restoring browser-side signing or pretending that an unpublished BFF command succeeded.

## Approach

1. Rebase the Laptop B UI branch onto the published same-origin FastAPI commit and preserve both branches' decision history.
2. Add an artifact-level regression that fails on any `vt_` occurrence in emitted production assets, then remove the fixture literal with the smallest UI-only change.
3. Run frontend, public E2E, full Python, and demo smoke gates.
4. Start FastAPI with explicit environment-only local credentials and the real `web/dist`; validate login/logout, every role projection, operator revocation, audit/dispute, API routing, agent isolation, DOM, console, network, and retained inputs.
5. Record exact evidence, commit, and publish only `codex/laptop-b-browser-bff-ui`.
6. Adapt the authority atlas and attack scenarios to consume only role-scoped BFF projections. Keep every scenario visible, but represent commands absent from the BFF contract as unavailable rather than calling `/agent/*`.
7. Preserve standing-order capability in the runtime and document the browser-operation gap: registering, listing, ticking, and repricing watches need an explicit BFF contract extension before the browser can expose live controls.

## Rejected approaches

- Vite Preview: it is a different origin and correctly does not route `/ui-api/v1/*` to the BFF.
- Browser-held signing or payment material: this violates the BFF contract and RFC 9421 separation.
- A fixture fallback in production: it would create a second, misleading source of truth.
- Backend or contract changes without an observed mismatch: Laptop B owns only UI and evidence for this handoff.
- Restoring `authorizationGateway.ts` or its WebCrypto wallet: it would reintroduce the browser signing lane prohibited by the approved design.
- Deleting the new authority/scenario presentation: it would make the rebased UI incomplete even though its data model can be safely adapted to BFF projections.
- Calling `/agent/watches`, `/agent/purchase`, or `/admin/catalog/price` from the BFF UI: these are not `/ui-api/v1/` routes and require authority the browser is not allowed to hold.

## Scope

- Allowed: `web/**`, browser-facing regression tests, demo smoke/evidence documentation, and this plan.
- Preserved: backend runtime, BFF routers, migrations, HTTP contracts, x402, and agent APIs.

## Verification

- `npm test`
- `npm run build`
- `npm run lint`
- `uv run pytest tests/integration/e2e -q`
- `uv run python -m pytest -q`
- `uv run python scripts/demo_smoke.py`
- Real browser at `http://127.0.0.1:8000` with FastAPI serving `web/dist`, including HTTP routing checks and negative secret scans of bundle, DOM, console, network, errors, and retained inputs.
- Source and artifact regressions proving the adapted components import no direct-agent gateway, expose no sensitive projection fields, and never label unavailable browser commands as executed.

## Outcome

The rebased UI preserves the authority atlas, all five attack scenarios, and a
visible standing-order explanation without restoring the direct-agent browser
gateway. All automated gates pass: 540 Python tests, 15 public E2E tests, nine
demo-smoke scenarios, 30 web tests, production build, and lint. Real same-
origin browser validation passed for login/logout, every role, operator
revocation, post-revocation audit, retained inputs, DOM, and console against a
fresh migrated QA database.

Two explicit limitations remain. First, live browser standing-order controls
need new role-scoped BFF intent routes; the current contract has none. Second,
the existing local `var/aval.db` reports Alembic head but lacks the
`mandates.max_uses` column and prevents FastAPI startup. A fresh database
migrates and starts correctly, so this is persistent-database migration drift,
not a UI or BFF contract failure; no database was deleted or rewritten here.
