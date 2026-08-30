from __future__ import annotations

from fastapi.testclient import TestClient

from aval.main import create_app


def _client(monkeypatch, tmp_path) -> tuple[TestClient, object]:
    monkeypatch.setenv("AVAL_UI_MERCHANT_CREDENTIAL", "merchant-ui-credential")
    monkeypatch.setenv("AVAL_UI_OPERATOR_CREDENTIAL", "operator-ui-credential")
    monkeypatch.setenv("AVAL_OPERATOR_AUTHORITY_SEED", "operator-authority-test-seed")
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


def test_operator_revocation_uses_the_registered_authority_after_a_runtime_restart(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVAL_UI_OPERATOR_CREDENTIAL", "operator-ui-credential")
    monkeypatch.setenv("AVAL_OPERATOR_AUTHORITY_SEED", "operator-authority-test-seed")
    database = tmp_path / "restart.sqlite3"
    first = create_app(database_path=database)
    second = create_app(database_path=database)
    client = TestClient(second, base_url="https://ui.aval.local")
    operator = _login(client, "operator")

    response = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "restart-operator-revoke", "X-AVAL-CSRF": operator["csrf_token"]},
        json={},
    )

    assert response.status_code == 202, response.text
    assert first.state.runtime.custody.public_jwk("operator-key") == second.state.runtime.custody.public_jwk(
        "operator-key"
    )


def test_operator_revocation_fails_closed_without_an_explicit_authority_seed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AVAL_UI_OPERATOR_CREDENTIAL", "operator-ui-credential")
    monkeypatch.delenv("AVAL_OPERATOR_AUTHORITY_SEED", raising=False)
    app = create_app(database_path=tmp_path / "authority-unconfigured.sqlite3")
    client = TestClient(app, base_url="https://ui.aval.local")
    operator = _login(client, "operator")

    response = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "authority-not-configured", "X-AVAL-CSRF": operator["csrf_token"]},
        json={},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "revocation_unavailable"}}


def test_existing_runtime_adopts_and_rotates_an_explicit_operator_authority_seed(monkeypatch, tmp_path) -> None:
    database = tmp_path / "authority-transition.sqlite3"
    monkeypatch.delenv("AVAL_OPERATOR_AUTHORITY_SEED", raising=False)
    create_app(database_path=database)

    monkeypatch.setenv("AVAL_UI_OPERATOR_CREDENTIAL", "operator-ui-credential")
    monkeypatch.setenv("AVAL_OPERATOR_AUTHORITY_SEED", "operator-authority-seed-one")
    configured = create_app(database_path=database)
    first_jwk = configured.state.runtime.custody.public_jwk("operator-key")

    monkeypatch.setenv("AVAL_OPERATOR_AUTHORITY_SEED", "operator-authority-seed-two")
    rotated = create_app(database_path=database)
    client = TestClient(rotated, base_url="https://ui.aval.local")
    operator = _login(client, "operator")
    response = client.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "authority-rotated", "X-AVAL-CSRF": operator["csrf_token"]},
        json={},
    )

    assert rotated.state.runtime.custody.public_jwk("operator-key") != first_jwk
    assert response.status_code == 202, response.text
