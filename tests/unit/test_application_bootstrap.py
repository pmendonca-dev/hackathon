from __future__ import annotations

from aval.main import create_app


def test_application_exposes_a_health_route():
    app = create_app()

    assert any(getattr(route, "path", None) == "/health" for route in app.routes)
