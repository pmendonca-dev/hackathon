# AVAL final delivery evidence — command rehearsal

## Scope and candidate

This record contains only commands actually executed against
`c919b65c468acca54393d7be88b4cd0cb1761e3d` on 2026-08-30. The candidate is
`fix: align migration target and guard stale BFF sessions` from `origin/main`.
The rehearsal used a disposable linked worktree and did not modify the shared
`var/aval.db`.

This is evidence for final review, not a declaration that delivery is complete,
a PR is approved, or a merge has occurred.

## Executed gates

| Command | Result |
| --- | --- |
| `uv sync` | Did not complete: OneDrive rejected hardlinks with OS error 396. |
| `uv sync --link-mode=copy` | Passed; 14 packages installed. |
| `uv run alembic upgrade head` | Did not start: App Control blocked the `alembic` executable with OS error 4551. |
| `uv run python -m alembic upgrade head` | Passed; a new local database upgraded through `0013_repair_legacy_mandate_frequency`. |
| `uv run alembic heads` | Did not start: the same App Control policy blocked the executable. |
| `uv run python -m alembic heads` | Passed; exactly one head: `0013_repair_legacy_mandate_frequency`. |
| `uv run python -m pytest -q` | Passed: 554 tests, 49.45 seconds. |
| `uv run python -m pytest tests/integration/e2e -q` | Passed: 15 tests, 3.40 seconds. |
| `uv run python scripts/demo_smoke.py` | Passed: 9 tests, 2.35 seconds. Output states that x402 is intentionally excluded. |
| `npm --prefix web ci` | Passed; 46 packages audited, 0 vulnerabilities reported. |
| `npm --prefix web test` | Passed: 39 tests. |
| `npm --prefix web run build` | Passed; 1,837 modules transformed. |
| `npm --prefix web run lint` | Passed. |

The initial direct `uv sync` and Alembic commands are retained above because
they were requested and actually attempted. The copy-link installation and
`python -m alembic` executions are documented as fallbacks, rather than being
represented as success of the blocked wrapper executables.

## Database and environment handling

Alembic was invoked only inside the disposable worktree, so its default SQLite
file was local to that copy. A before-and-after hash check confirmed that the
shared `var/aval.db` was unchanged. No migration was edited, downgraded, or run
against the shared database. No credential, token, JWS, proof, PAN, or key was
provided in command output.

On a Windows checkout synchronized by OneDrive, use `uv sync --link-mode=copy`
when OS error 396 prevents hardlinks. On an environment where App Control
allows the Alembic executable, repeat the documented direct `uv run alembic`
commands; where it blocks only the executable launcher, use the recorded
`uv run python -m alembic` equivalent and retain the policy message as evidence.

## Remaining limitation

The requested command gates passed through their recorded fallbacks. A manual
browser inspection on a running FastAPI origin was not performed in this
command-only rehearsal. It remains necessary to observe the Browser BFF items
listed in `clean-environment-rehearsal.md` section 7; the automated suite is
not represented as a replacement for that observation.

x402 remains intentionally disabled and outside this delivery evidence. No
Web3, smart contract, or x402 component was started or modified.

## Rollback

This branch contains documentation evidence only. Before integration, rollback
means leaving the branch unmerged. After integration, revert the evidence
commit; no database downgrade or runtime rollback is needed. Once no process
uses the rehearsal worktree, remove that disposable worktree through Git to
discard its local SQLite file. Never use rollback to reset, overwrite, delete,
or migrate the shared `var/aval.db`.
