from __future__ import annotations

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
