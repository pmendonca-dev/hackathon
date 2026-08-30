# Laptop B Payments and UI Plan

## Problem

Advance AVAL Tasks 8–11 without creating a second authority beside
`AuthorizationCore`. The branch must add ACP delegated-payment tokenization,
the card PSP boundary, receipt/audit/dispute projections, and a browser-ready
three-role experience while Laptop A's checkout contract is still pending.

## Confirmed public seams

- `derive_allowance(...)` and `VaultService.delegate(...)` are the ACP seam.
- `MockCardPSP.authorize(reservation, proof)` is the settlement seam.
- Receipt, audit timeline, and dispute reconstruction services are the
  evidence seam; append-only facts remain owned by the core/repositories.
- The existing React application under `web/` is the presentation seam. Until
  Laptop A publishes `docs/contracts/aval-checkout-api.md`, it consumes only
  fixtures explicitly labelled `mock` and never computes policy, balance,
  revocation, authorization, or capture decisions.

## Approach

Work in four vertical TDD slices, each with a failing public-contract test,
minimal implementation, focused verification, and a small commit:

1. ACP allowance projection and opaque one-time `vt_*` tokenization with no PAN
   persistence or response leakage.
2. Stateless PSP mock gated by a committed reservation and a cryptographically
   valid, correctly bound `AuthorizationProof`.
3. Post-settlement AP2 receipt projection plus append-only audit timeline and
   read-only dispute reconstruction.
4. Human, merchant, auditor, and trial-by-fire UI built on clearly marked mock
   fixtures and a replaceable transport boundary for Laptop A's future HTTP
   contract.

## Rejected approaches

- Editing `ports.py`, `main.py`, migrations, or `AuthorizationCore`: shared
  contracts require a coordinated commit and are outside Laptop B ownership.
- Persisting ACP `Allowance`: it would become stale policy. It is derived for
  every token issuance from live core-approved inputs.
- Letting adapters write ledger or audit rows: settlement adapters return
  results only; application services/core own writes.
- Browser-side policy simulation: mock fixtures may describe outcomes, but the
  UI will only render server-shaped facts and request commands.
- x402, real PSP/network, Gemini, ADK, A2A, MCP, Web3: explicitly outside scope.

## Scope and ownership

Edits are limited to Laptop B-owned ACP/settlement/AP2 receipt adapters,
vault/receipt/dispute services, ACP/audit routers, corresponding tests, and
`web/**`. This plan file is the required work record. Existing unowned files are
read-only.

## Verification

- Observe red then green for every focused Python seam.
- Run all affected ACP/PSP/audit Python tests and the complete Python suite.
- Run every verification command declared in `web/package.json`.
- Inspect the UI at desktop and mobile widths, including keyboard focus and
  reduced-motion behavior.
- Before delivery: fetch, rebase on `origin/main`, repeat verification, inspect
  `git status --short`, and push only `codex/laptop-b-payments-ui`.

## Contract dependencies and temporary mocks

The only temporary integration asset is `web/src/domain/mockData.ts` (and any
adjacent fixture module explicitly named/labelled as mock). It must expose a
single replacement boundary. Laptop A's future
`docs/contracts/aval-checkout-api.md` remains the dependency for live checkout,
agent-authentication, mandate completion, policy mutation, and capture command
transport.
