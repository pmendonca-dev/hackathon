# Laptop B Live UI and E2E Plan

## Problem

Tasks 10–12 require the browser to stop presenting fixtures as the normal demo
path and to prove the integrated payment runtime through public HTTP APIs. The
checkout HTTP contract is already on `origin/main`, but the payment/runtime
contract and administrative trial endpoints are not published yet. Implementing
their shapes speculatively would create a competing browser source of truth and
would make the eventual E2E suite test an invented protocol.

The starting checkout contained unrelated user changes. This branch therefore
runs in a clean sibling Git worktree created directly from `origin/main` at the
PR #5 merge commit (`fa2731a`).

## Public seams under test

- Browser transport: the documented UCP Checkout HTTP endpoints and, once
  published, the payment-runtime HTTP endpoints.
- End-to-end runtime: authenticated public HTTP requests observed only through
  their HTTP responses, receipts, audit timeline, and dispute reconstruction.
- No test verifies through application internals or direct database queries.

## Approach

Work in vertical red → green slices:

1. Add a typed `HttpAvalGateway` and tests for the existing create/complete
   checkout contract, including stable protocol error handling.
2. Select HTTP as the default browser gateway. Keep fixtures behind one explicit
   development flag and render a persistent mock-data warning when enabled.
3. Represent an unpublished or unavailable workspace/trial API as unavailable;
   never fabricate a successful administrative command or local state change.
4. When `docs/contracts/aval-payment-runtime-api.md` appears on
   `origin/codex/laptop-a-live-payments`, read it and add each runtime operation
   as a typed transport slice with a failing test first.
5. After Laptop A is merged, rebase on `origin/main`, map the real response
   projections into the human, merchant, auditor, and trial views, and add the
   required public HTTP E2E scenarios one at a time.
6. Make `scripts/demo_smoke.py` exercise the same live API surface and record the
   final Task 12 evidence and operator steps in the owned documentation.

## Rejected approaches

- Guess payment-runtime endpoint names or response fields before the contract is
  published: this would couple Laptop B to an imaginary API.
- Keep the mock gateway as the default until integration: fixture state would
  continue to look live and violate the demo requirement.
- Update browser projections after trial commands without reloading canonical
  state: this would create a second source of truth.
- Implement or mock x402: it is explicitly outside this branch.
- Copy Laptop A implementation code: this branch consumes only its public
  contract and integrated runtime.

## UI design guardrails

Preserve the existing control-room system instead of introducing a new visual
language. Tokens remain graphite `#08090B`/`#15181D`, live authority
`#C6F24E`, human escalation `#F5B942`, denial `#FF5C5C`, and verified evidence
`#4ED8F2`; Inter Tight, Inter, and JetBrains Mono retain their display, body,
and evidence roles.

```text
┌ role navigation ┐┌ persistent source strip: LIVE API | MOCK DATA ┐
│ human            │├───────────────────────────────────────────────┤
│ merchant         ││ canonical projection or explicit unavailable │
│ auditor          ││ state                                         │
│ trial            │└───────────────────────────────────────────────┘
└──────────────────┘
```

The signature element is the persistent source strip: it is operational
provenance, not decoration, and cannot scroll away or be confused with a status
badge inside a projection. The initial mock-only chrome was visually coherent
but hard-coded `MOCK` and `SEM REDE`; replacing those literals with canonical
source metadata is specific to this live-integration brief and avoids a generic
environment banner.

## Scope

Owned implementation files are limited to `web/**`,
`tests/integration/e2e/**`, `scripts/demo_smoke.py`, `docs/demo-runbook.md`, and
Task 12 evidence documentation. This plan and required entries in
`docs/decision-log.md` are documentation-only coordination artifacts. No AVAL
runtime, migration, or payment-runtime contract file will be changed.

## Verification

Each slice starts with an observed failing test. Final verification, after the
Laptop A merge and a final rebase on `origin/main`, is:

1. `npm test` in `web/`
2. `npm run build` in `web/`
3. `npm run lint` in `web/`
4. `uv run pytest tests/integration/e2e -q`
5. `uv run pytest -q`
6. `uv run python scripts/demo_smoke.py`
7. Clean Git status and pushed branch

Task 12 must remain explicitly not green until all listed E2E scenarios use the
real integrated runtime APIs.

## Direct runtime validation amendment — 2026-08-30

The user replaced the earlier wait-for-main gate with a direct validation of
Laptop A commit `3191d3e647e52180fe2367bf0d1a2e3740ea2ad0`. The Laptop B
branch is therefore rebased on `origin/codex/laptop-a-live-payments`, not on
`origin/main`, and no merge to main or final PR is part of this phase.

The corrected capture contract removes client-supplied mandate, merchant,
amount, and payment-mandate fields. E2E now signs the canonical request bytes
with RFC 9421 and proves downstream absence through public audit and later
successful capture, never through database inspection. Direct SQLite access is
limited to creating the required revocation-storage outage.

The validation remains red for contract mismatches. Laptop B will document
their exact public requests and responses and will not patch Laptop A backend
implementation inside this branch.

## Final corrected-runtime validation — 2026-08-30

The final validation target is Laptop A commit
`2b1d6f9c66a84d3771ab1810f3729d1c4a04d589`. Rebase directly on its remote
branch, run migrations and the complete Python/web matrix, and keep this phase
free of backend, migration, and contract changes.

In addition to the public HTTP E2E suite, run the built browser against the
real local runtime and inspect its bundle, browser storage, console, and
network behavior. The browser must contain no private key, vault token, JWS,
or authorization proof, and it must not synthesize or bypass RFC 9421. If the
runtime cannot expose an authenticated browser-safe read boundary, record that
as a separate architecture blocker; do not add a proxy, embedded key, or
signature bypass.
