from __future__ import annotations

import re

from fastapi.testclient import TestClient

from aval.main import create_app


ROLE_CREDENTIALS = {
    "merchant": "merchant-ui-credential",
    "holder": "holder-ui-credential",
    "auditor": "auditor-ui-credential",
    "operator": "operator-ui-credential",
}

FORBIDDEN_BROWSER_EVIDENCE = (
    "authorizationproof",
    "private_key",
    "signed_revocation",
    "payment_token",
    "proof_",
    "vt_",
    "eyj",
)


def _app(monkeypatch, tmp_path):
    for role, credential in ROLE_CREDENTIALS.items():
        monkeypatch.setenv(f"AVAL_UI_{role.upper()}_CREDENTIAL", credential)
    monkeypatch.setenv("AVAL_OPERATOR_AUTHORITY_SEED", "browser-e2e-operator-seed")
    return create_app(database_path=tmp_path / "browser-bff-e2e.sqlite3")


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://ui.aval.local")


def _login(client: TestClient, role: str) -> str:
    response = client.post(
        "/ui-api/v1/session/login",
        json={"role": role, "credential": ROLE_CREDENTIALS[role]},
    )
    assert response.status_code == 200, response.text
    assert "aval_ui_session" not in response.text
    return response.json()["csrf_token"]


def _assert_safe_projection(rendered: str) -> None:
    normalized = rendered.lower()
    for forbidden in FORBIDDEN_BROWSER_EVIDENCE:
        assert forbidden not in normalized
    assert re.search(r"(?<!\d)\d{12,19}(?!\d)", rendered) is None


def test_ui_audit_requires_session_but_agent_audit_still_requires_rfc9421(
    monkeypatch, tmp_path
) -> None:
    client = _client(_app(monkeypatch, tmp_path))

    missing_session = client.get("/ui-api/v1/mandates/mandate_01/audit")
    assert missing_session.status_code == 401
    assert missing_session.json() == {"detail": {"code": "ui_session_required"}}

    _login(client, "auditor")
    browser_projection = client.get("/ui-api/v1/mandates/mandate_01/audit")
    unsigned_agent_request = client.get("/audit/mandates/mandate_01")

    assert browser_projection.status_code == 200, browser_projection.text
    assert unsigned_agent_request.status_code == 422
    assert unsigned_agent_request.json() == {
        "detail": {"code": "ucp_agent_invalid"}
    }


def test_ui_operator_revocation_requires_csrf_and_creates_audit_event(
    monkeypatch, tmp_path
) -> None:
    app = _app(monkeypatch, tmp_path)
    operator = _client(app)
    csrf = _login(operator, "operator")

    missing_csrf = operator.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={"Idempotency-Key": "browser-e2e-revoke-missing-csrf"},
        json={},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json() == {"detail": {"code": "csrf_invalid"}}

    revoked = operator.post(
        "/ui-api/v1/mandates/mandate_01/revocations",
        headers={
            "Idempotency-Key": "browser-e2e-revoke",
            "X-AVAL-CSRF": csrf,
        },
        json={},
    )
    assert revoked.status_code == 202, revoked.text
    assert revoked.json() == {"mandate_id": "mandate_01", "status": "revoked"}
    _assert_safe_projection(revoked.text)

    auditor = _client(app)
    _login(auditor, "auditor")
    audit = auditor.get("/ui-api/v1/mandates/mandate_01/audit")

    assert audit.status_code == 200, audit.text
    assert any(
        event["event_type"] == "mandate.revoked"
        for event in audit.json()["timeline"]
    )
    _assert_safe_projection(audit.text)


def test_browser_projection_redacts_pan_token_proof_and_raw_jws(
    monkeypatch, tmp_path
) -> None:
    app = _app(monkeypatch, tmp_path)
    rendered_projections: list[str] = []

    for role in ROLE_CREDENTIALS:
        client = _client(app)
        _login(client, role)
        workspace = client.get("/ui-api/v1/workspace")
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()["role"] == role
        rendered_projections.append(workspace.text)

        if role in {"holder", "auditor"}:
            audit = client.get("/ui-api/v1/mandates/mandate_01/audit")
            dispute = client.get("/ui-api/v1/mandates/mandate_01/dispute")
            assert audit.status_code == 200, audit.text
            assert dispute.status_code == 200, dispute.text
            rendered_projections.extend((audit.text, dispute.text))

    _assert_safe_projection("".join(rendered_projections))


def test_unsigned_browser_request_cannot_operate_an_agent_endpoint(
    monkeypatch, tmp_path
) -> None:
    client = _client(_app(monkeypatch, tmp_path))
    _login(client, "operator")

    unsigned_capture = client.post(
        "/payment-captures",
        headers={"Idempotency-Key": "unsigned-browser-capture"},
        json={
            "mandate_id": "mandate_01",
            "checkout_id": "checkout_browser",
            "merchant_id": "merchant_01",
            "total": {"amount": 100, "currency": "BRL", "exponent": 2},
        },
    )

    assert unsigned_capture.status_code == 422
    assert unsigned_capture.json() == {"detail": {"code": "ucp_agent_invalid"}}
    _assert_safe_projection(unsigned_capture.text)
