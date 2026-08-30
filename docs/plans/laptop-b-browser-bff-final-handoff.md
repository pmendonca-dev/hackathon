# Laptop B Browser BFF Final Handoff

## Problem

The browser-safe BFF and same-origin FastAPI delivery are integrated on the Laptop A handoff, but the production web artifact must prove that no `vt_` literal or browser security material survives bundling. The final handoff also needs real-browser evidence against FastAPI rather than Vite Preview.

## Approach

1. Rebase the Laptop B UI branch onto the published same-origin FastAPI commit and preserve both branches' decision history.
2. Add an artifact-level regression that fails on any `vt_` occurrence in emitted production assets, then remove the fixture literal with the smallest UI-only change.
3. Run frontend, public E2E, full Python, and demo smoke gates.
4. Start FastAPI with explicit environment-only local credentials and the real `web/dist`; validate login/logout, every role projection, operator revocation, audit/dispute, API routing, agent isolation, DOM, console, network, and retained inputs.
5. Record exact evidence, commit, and publish only `codex/laptop-b-browser-bff-ui`.

## Rejected approaches

- Vite Preview: it is a different origin and correctly does not route `/ui-api/v1/*` to the BFF.
- Browser-held signing or payment material: this violates the BFF contract and RFC 9421 separation.
- A fixture fallback in production: it would create a second, misleading source of truth.
- Backend or contract changes without an observed mismatch: Laptop B owns only UI and evidence for this handoff.

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

## Outcome

All automated gates and the real same-origin browser journey passed. The
production artifact contains zero `vt_` occurrences and the browser completed
all four role sessions plus operator revocation and post-revocation audit. The
only remaining operational gap is that the documented `uv run uvicorn` command
requires an undeclared executable; validation used an ephemeral `--with
uvicorn` dependency without changing backend files.
