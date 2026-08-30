from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from aval.main import create_app


def test_application_exposes_a_health_route():
    app = create_app()

    assert any(getattr(route, "path", None) == "/health" for route in app.routes)


def test_create_app_uses_the_configured_durable_database_path(monkeypatch, tmp_path: Path):
    """The factory and the ASGI entrypoint must use the same persistence setting."""
    database = tmp_path / "configured.sqlite3"
    monkeypatch.setenv("AVAL_DATABASE_PATH", str(database))

    app = create_app()

    assert Path(app.state.runtime.engine.url.database).resolve() == database.resolve()


def _bootstrap_module(environment: dict[str, str], program: str) -> subprocess.CompletedProcess[str]:
    """Import the real ASGI module in a fresh interpreter so module startup is observable."""
    return subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[2],
        env=environment,
        text=True,
    )


def test_module_bootstrap_never_prints_a_generated_operator_token(tmp_path: Path):
    """A generated operator credential in stdout would be exposed to process log readers."""
    environment = os.environ.copy()
    environment.pop("AVAL_OPERATOR_TOKEN", None)
    environment["AVAL_DATABASE_PATH"] = str(tmp_path / "runtime.sqlite3")

    completed = _bootstrap_module(environment, "import aval.main")

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_module_bootstrap_uses_an_explicit_operator_token_without_printing_it(tmp_path: Path):
    """Configuration must remain available without placing its value in process output."""
    secret = "operator-token-never-for-stdout"
    environment = os.environ.copy() | {
        "AVAL_DATABASE_PATH": str(tmp_path / "runtime.sqlite3"),
        "AVAL_OPERATOR_TOKEN": secret,
    }

    completed = _bootstrap_module(
        environment,
        "import os; import aval.main; print(aval.main.app.state.runtime.operator_token == os.environ['AVAL_OPERATOR_TOKEN'])",
    )

    assert completed.returncode == 0
    assert completed.stdout == "True\n"
    assert secret not in f"{completed.stdout}{completed.stderr}"
