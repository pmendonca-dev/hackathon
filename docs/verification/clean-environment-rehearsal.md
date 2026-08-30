# AVAL clean-environment rehearsal

Delivery status: pre-gate

This checklist prescribes a reproducible final gate. It does not assert that the
final delivery gate has passed. Record command output, the tested commit, and
the browser observations only when the candidate is actually rehearsed.

## 1. Start from an isolated checkout

```powershell
git clone https://github.com/pmendonca-dev/hackathon.git
cd hackathon
git fetch origin
$candidateCommit = git rev-parse origin/main
git worktree add ..\aval-release-candidate $candidateCommit
cd ..\aval-release-candidate
git rev-parse HEAD
```

Use a disposable worktree or clone for the rehearsal. Do not reset, overwrite,
or migrate a shared `var/aval.db` as part of this procedure.

## 2. Install dependencies

```powershell
uv sync
npm --prefix web ci
```

On Windows folders synchronized by OneDrive may reject `uv` hardlinks with OS
error 396. The equivalent fallback is:

```powershell
uv sync --link-mode=copy
```

The fallback changes only installation mechanics; it does not weaken tests or
modify the lockfile.

## 3. Provide local configuration without printing it

Supply these names from the local environment or a secure local secret store;
do not put their values in command history, source files, screenshots, logs, or
issue text:

- `AVAL_UI_MERCHANT_CREDENTIAL`
- `AVAL_UI_HOLDER_CREDENTIAL`
- `AVAL_UI_AUDITOR_CREDENTIAL`
- `AVAL_UI_OPERATOR_CREDENTIAL`
- `AVAL_OPERATOR_AUTHORITY_SEED`

For an HTTP-only local browser rehearsal, also set
`AVAL_UI_LOCAL_HTTP=true`. This is local-only: the normal session cookie remains
HttpOnly, `SameSite=Strict`, and `Secure`. Set `AVAL_DATABASE_PATH` to a
disposable path when a file-backed runtime is required. Do not echo any of these
values. `AVAL_OPERATOR_TOKEN`, if an operator-only legacy surface is rehearsed,
is handled by the same rule.

## 4. Migrate a clean database

```powershell
uv run alembic upgrade head
uv run alembic heads
```

The expected schema destination is the single Alembic head. This command is a
gate to run, not a claimed result in this document.

## 5. Exercise the legacy-schema repair on a disposable fixture

Migration `0013_repair_legacy_mandate_frequency` repairs a database marked at
the prior Alembic head when `mandates.max_uses` is absent. The regression fixture
creates that copy under `pytest` temporary storage, upgrades it without reset,
checks the `max_uses` backfill, and boots FastAPI through
`AVAL_DATABASE_PATH`.

```powershell
uv run python -m pytest tests/integration/test_database_migrations.py -q
```

Never point this rehearsal at or directly mutate `var/aval.db`.

## 6. Run automated gates

```powershell
uv run python -m pytest -q
uv run python -m pytest tests/integration/e2e -q
uv run python scripts/demo_smoke.py
npm --prefix web test
npm --prefix web run build
npm --prefix web run lint
```

Use `uv run python -m pytest` when App Control blocks `pytest.exe`; it executes
the same installed test package. The smoke script and E2E suite cover the
non-x402 flow. x402 is disabled for this delivery: do not add Web3, a chain,
or a facilitator during the rehearsal.

## 7. Inspect the Browser BFF on the FastAPI origin

After the production build is present, start the ASGI application from the same
configured environment:

```powershell
uv run uvicorn aval.main:app --host 127.0.0.1 --port 8000
```

Perform a browser inspection on that origin:

- `GET /` renders the production SPA and a hashed asset loads;
- login and logout use `/ui-api/v1/session/login` and `/ui-api/v1/session/logout`;
- merchant, holder, auditor, and operator projections enforce their roles;
- the operator revocation mutation requires `X-AVAL-CSRF` and does not ask the
  browser to submit a JWS;
- an unknown `/ui-api/v1/` path returns API JSON, not the SPA fallback;
- an agent endpoint without RFC 9421 remains rejected;
- DevTools network, console, DOM, and static assets show no credential, session
  bearer, PAN, vault token, authorization proof, raw JWS, or private key.

## 8. Collect release evidence

Attach the exact candidate commit, command outputs, any lint warnings, the
legacy-schema regression output, and the browser inspection notes to the final
review. Stop and repair a concrete failure before claiming completion.
