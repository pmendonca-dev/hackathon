from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from aval.main import create_app


class MutableClock:
    def __init__(self) -> None:
        self.instant = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.instant


def _client(monkeypatch, tmp_path, clock: MutableClock) -> TestClient:
    monkeypatch.setenv("AVAL_UI_MERCHANT_CREDENTIAL", "merchant-secret-not-for-output")
    monkeypatch.setenv("AVAL_UI_HOLDER_CREDENTIAL", "holder-secret-not-for-output")
    monkeypatch.delenv("AVAL_UI_LOCAL_HTTP", raising=False)
    return TestClient(
        create_app(database_path=tmp_path / "ui.sqlite3", clock=clock),
        base_url="https://ui.aval.local",
    )


def _login(client: TestClient):
    return client.post(
        "/ui-api/v1/session/login",
        json={"role": "merchant", "credential": "merchant-secret-not-for-output"},
    )


def test_login_sets_secure_httponly_strict_cookie_and_returns_only_csrf(monkeypatch, tmp_path, capsys) -> None:
    clock = MutableClock()
    client = _client(monkeypatch, tmp_path, clock)

    response = _login(client)
    captured = capsys.readouterr()

    assert response.status_code == 200
    assert response.json()["role"] == "merchant"
    assert response.json()["csrf_token"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "aval_ui_session" not in response.json()
    assert "merchant-secret-not-for-output" not in f"{response.text}{captured.out}{captured.err}"


def test_session_routes_reject_missing_expired_and_revoked_cookies(monkeypatch, tmp_path) -> None:
    clock = MutableClock()
    client = _client(monkeypatch, tmp_path, clock)

    missing = client.post("/ui-api/v1/session/logout")
    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "ui_session_required"}}
    login = _login(client)
    csrf = login.json()["csrf_token"]
    logout = client.post("/ui-api/v1/session/logout", headers={"X-AVAL-CSRF": csrf})
    assert logout.status_code == 204
    assert client.post("/ui-api/v1/session/logout", headers={"X-AVAL-CSRF": csrf}).json() == {
        "detail": {"code": "ui_session_required"}
    }

    second = _login(client)
    clock.instant = clock.instant + timedelta(hours=9)
    expired = client.post(
        "/ui-api/v1/session/logout", headers={"X-AVAL-CSRF": second.json()["csrf_token"]}
    )
    assert expired.status_code == 401
    assert expired.json() == {"detail": {"code": "ui_session_required"}}


def test_login_and_logout_fail_closed_for_credentials_and_csrf(monkeypatch, tmp_path) -> None:
    clock = MutableClock()
    client = _client(monkeypatch, tmp_path, clock)

    invalid = client.post(
        "/ui-api/v1/session/login", json={"role": "merchant", "credential": "not-the-secret"}
    )
    assert invalid.status_code == 401
    assert invalid.json() == {"detail": {"code": "ui_login_invalid"}}

    login = _login(client)
    csrf = login.json()["csrf_token"]
    invalid_csrf = client.post("/ui-api/v1/session/logout", headers={"X-AVAL-CSRF": f"{csrf}-changed"})
    assert invalid_csrf.status_code == 403
    assert invalid_csrf.json() == {"detail": {"code": "csrf_invalid"}}
