"""Server entrypoint.

    uvicorn aval.main:app --reload

The database is a file by default so a restart does not erase the demo. Set
`AVAL_DATABASE_PATH=:memory:` for a throwaway instance — which is also what a judge
gets when the team resets between runs.

The operator surfaces (`/agents`, `/admin/psp`, `/reconcile`) need a token. Set
`AVAL_OPERATOR_TOKEN`, or let one be minted and read it off the startup line: a default
deployment starts closed rather than open.
"""

from __future__ import annotations

import os
from pathlib import Path

from aval.api.app import create_app
from aval.runtime import build_runtime

__all__ = ["app", "create_app", "database_path"]


def database_path() -> Path | None:
    configured = os.environ.get("AVAL_DATABASE_PATH", "var/aval.db").strip()
    if configured.lower() in ("", ":memory:"):
        return None
    return Path(configured)


_runtime = build_runtime(database_path=database_path())
app = create_app(_runtime)

if not os.environ.get("AVAL_OPERATOR_TOKEN", "").strip():
    print(f"[aval] operator token for this process: {_runtime.operator_token}")
