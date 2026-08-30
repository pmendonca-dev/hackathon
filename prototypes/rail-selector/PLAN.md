# Plan — deterministic rail selector prototype

## Problem

Explore rail-selection semantics without touching AVAL authorization, payment
execution, persistence, HTTP surfaces, UI, E2E contracts, or the decision log.
The result must separate checkout orchestration from delegated tokenization and
keep x402 unavailable while Task 12 is not green.

## Approach

- Build one pure in-process module with a single public `select_rail` interface.
- Model checkout rail, credential mode, and x402 status as separate result axes.
- Parse CLI JSON into typed immutable inputs and emit a JSON result.
- Treat unknown or malformed inputs as fail-closed decisions with explicit
  reason codes.
- Keep x402 hard-disabled; feature flags cannot override the current Task 12
  gate.
- Use only the Python standard library at runtime and perform no I/O inside the
  selector.

## Rejected alternatives

- A single `selected_rail` enum: conflates UCP/AP2 checkout with ACP delegated
  tokenization.
- Importing AVAL contracts: couples the prototype to files concurrently being
  changed by other laptops.
- Using amount as spending authorization: selection is not an authorization
  authority.
- HTTP, database, blockchain, x402, wallets, tokens, or LLM integration: outside
  the approved scope.
- A flag that enables x402: Task 12 is currently red, so the prototype must fail
  closed regardless of caller-controlled flags.

## Scope

Every changed file must remain under `prototypes/rail-selector/`. The prototype
contains its own package, CLI, tests, and README and does not integrate with the
AVAL runtime.

## Verification

- Run the prototype unit tests from its local project directory.
- Exercise CLI success, malformed input, and x402-disabled cases.
- Confirm every branch diff path starts with `prototypes/rail-selector/`.
- Run `git diff --check origin/main...HEAD` after commit.
- Confirm the worktree is clean before and after push.
