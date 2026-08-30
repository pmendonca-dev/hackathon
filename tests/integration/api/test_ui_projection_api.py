from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.main import SEED_INSTRUMENT_TOKEN
from aval.application.authorization_core import CaptureCommand
from aval.main import create_app


def _client(monkeypatch, tmp_path) -> tuple[TestClient, object]:
    monkeypatch.setenv("AVAL_UI_MERCHANT_CREDENTIAL", "merchant-ui-credential")
    monkeypatch.setenv("AVAL_UI_HOLDER_CREDENTIAL", "holder-ui-credential")
    monkeypatch.setenv("AVAL_UI_AUDITOR_CREDENTIAL", "auditor-ui-credential")
    monkeypatch.setenv("AVAL_UI_OPERATOR_CREDENTIAL", "operator-ui-credential")
    app = create_app(database_path=tmp_path / "ui.sqlite3")
    return TestClient(app, base_url="https://ui.aval.local"), app


def _login(client: TestClient, role: str) -> dict[str, str]:
    response = client.post(
        "/ui-api/v1/session/login", json={"role": role, "credential": f"{role}-ui-credential"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _other_merchant_mandate(app) -> None:
    app.state.runtime.core.register_mandate(
        Mandate(
            id="mandate_other_merchant",
            principal=Principal("principal_other", "Other holder"),
            allowed_merchant_ids=frozenset({"merchant_other"}),
            allowed_categories=frozenset({"travel"}),
            limit=Money(100, "BRL", 2),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            policy_version=1,
            revocation_metadata={"revocation_id": "rev_other", "epoch": 0},
            authorities=(
                RevocationAuthority(
                    id="authority_other",
                    kid="holder-key",
                    role=RevocationRole.HOLDER,
                    public_jwk=app.state.runtime.custody.public_jwk("holder-key"),
                    allowed_scopes=frozenset({"mandate"}),
                ),
            ),
        )
    )


def test_merchant_cannot_read_another_merchants_projection(monkeypatch, tmp_path) -> None:
    client, app = _client(monkeypatch, tmp_path)
    _other_merchant_mandate(app)
    _login(client, "merchant")

    response = client.get("/ui-api/v1/mandates/mandate_other_merchant/audit")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "ui_role_not_authorized"}}


def test_holder_and_auditor_read_allowed_projection_without_sensitive_evidence(monkeypatch, tmp_path) -> None:
    holder_client, _ = _client(monkeypatch, tmp_path)
    _login(holder_client, "holder")
    holder = holder_client.get("/ui-api/v1/mandates/mandate_01/audit")

    auditor_client, _ = _client(monkeypatch, tmp_path)
    _login(auditor_client, "auditor")
    auditor = auditor_client.get("/ui-api/v1/mandates/mandate_01/dispute")

    assert holder.status_code == 200
    assert auditor.status_code == 200
    rendered = f"{holder.text}{auditor.text}"
    for forbidden in ("vt_", "proof_", "eyJ", "private_key", "csrf_token", "signed_revocation"):
        assert forbidden not in rendered


def test_audit_projection_never_reflects_untrusted_ledger_human_summary(monkeypatch, tmp_path) -> None:
    client, app = _client(monkeypatch, tmp_path)
    pan = "4242424242424242"
    capture = app.state.runtime.core.capture(
        CaptureCommand(
            mandate_id="mandate_01",
            checkout_id="checkout_sensitive_reason",
            merchant_id="merchant_01",
            total=Money(100, "BRL", 2),
            category="travel",
            idempotency_key="capture_sensitive_reason",
            instrument_id=SEED_INSTRUMENT_TOKEN,
        )
    )
    assert capture.reservation is not None
    app.state.runtime.core.open_dispute(
        reservation_id=capture.reservation.id,
        reason=f"reason-{pan}-vt_leak-eyJ.leak",
    )
    _login(client, "auditor")

    response = client.get("/ui-api/v1/mandates/mandate_01/audit")

    assert response.status_code == 200
    assert pan not in response.text
    assert "vt_leak" not in response.text
    assert "eyJ.leak" not in response.text


def test_workspace_and_agent_audit_keep_browser_and_agent_boundaries_separate(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path)
    _login(client, "merchant")

    workspace = client.get("/ui-api/v1/workspace")
    direct_agent_audit = client.get("/audit/mandates/mandate_01")

    assert workspace.status_code == 200
    assert workspace.json()["role"] == "merchant"
    assert workspace.json()["mandates"][0]["merchant_id"] == "merchant_01"
    assert "available_amount" not in workspace.text
    assert direct_agent_audit.status_code == 422
    assert direct_agent_audit.json()["detail"]["code"] in {
        "signature_invalid",
        "profile_not_trusted",
        "key_not_found",
        "ucp_agent_invalid",
    }
