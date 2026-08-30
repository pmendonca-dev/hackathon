from __future__ import annotations

from fastapi.testclient import TestClient

from aval.main import create_app


def _client(monkeypatch, tmp_path) -> tuple[TestClient, object]:
    monkeypatch.setenv("AVAL_UI_MERCHANT_CREDENTIAL", "merchant-ui-credential")
    monkeypatch.setenv("AVAL_UI_OPERATOR_CREDENTIAL", "operator-ui-credential")
    app = create_app(database_path=tmp_path / "ui.sqlite3")
    return TestClient(app, base_url="https://ui.aval.local"), app


def _login(client: TestClient, role: str) -> dict[str, str]:
    response = client.post(
        "/ui-api/v1/session/login", json={"role": role, "credential": f"{role}-ui-credential"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_operator_revocation_requires_session_csrf_and_idempotency_and_is_server_signed(monkeypatch, tmp_path) -> None:
    client, app = _client(monkeypatch, tmp_path)
    operator = _login(client, "operator")

    missing_csrf = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations", headers={"Idempotency-Key": "ui-revoke-01"}, json={}
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json() == {"detail": {"code": "csrf_invalid"}}

    response = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "ui-revoke-01", "X-AVAL-CSRF": operator["csrf_token"]},
        json={},
    )
    replay = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "ui-revoke-01", "X-AVAL-CSRF": operator["csrf_token"]},
        json={},
    )

    assert response.status_code == 202, response.text
    assert response.json() == {"mandate_id": "mandate_01", "status": "revoked"}
    assert "signed_revocation" not in response.text
    assert replay.status_code == 202
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert app.state.runtime.core.mandate("mandate_01").status.value == "REVOKED"
    assert app.state.runtime.core.timeline_for("mandate_01")[-1].actor == "operator_01"


def test_operator_route_rejects_browser_jws_and_non_operator_roles(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path)
    merchant = _login(client, "merchant")
    denied = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "not-operator", "X-AVAL-CSRF": merchant["csrf_token"]},
        json={},
    )
    assert denied.status_code == 403
    assert denied.json() == {"detail": {"code": "ui_role_not_authorized"}}

    operator = _login(client, "operator")
    smuggled = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "no-browser-jws", "X-AVAL-CSRF": operator["csrf_token"]},
        json={"signed_revocation": "eyJ-forbidden"},
    )
    assert smuggled.status_code == 422
    assert smuggled.json() == {"detail": {"code": "request_invalid"}}
