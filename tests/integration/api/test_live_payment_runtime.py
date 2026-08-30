from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY
from aval.adapters.ucp.http_signatures import SignedRequest, signature_base
from aval.main import create_app
from aval.security.content_digest import content_digest_sha256
from aval.security.jws import sign_compact_jws


def _signed_headers(app, body: bytes, *, path: str, key: str) -> dict[str, str]:
    headers = {
        "ucp-agent": 'profile="https://agent.aval.local/.well-known/ucp"',
        "idempotency-key": key,
        "content-digest": content_digest_sha256(body),
        "content-type": "application/json",
    }
    signature_input = (
        'sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" '
        '"content-digest" "content-type");keyid="agent-key";alg="ES256"'
    )
    request = SignedRequest(
        method="POST", authority="merchant.aval.local", path=path,
        headers={**headers, "signature-input": signature_input}, body=body,
    )
    signature = base64.b64encode(
        app.state.runtime.custody.sign_es256("agent-key", signature_base(request))
    ).decode()
    return {**headers, "signature-input": signature_input, "signature": f"sig1=:{signature}:"}


def _create_checkout(client: TestClient, app, checkout_id: str = "chi_live_1") -> None:
    body = json.dumps(
        {
            "id": checkout_id, "mandate_id": "mandate_01", "merchant_id": "merchant_01",
            "total": {"amount": 500, "currency": "BRL", "scale": 2},
            "line_items": [{"id": "coffee", "quantity": 1, "amount": 500}],
            "capabilities": ["dev.ucp.shopping.checkout", AP2_MANDATE_CAPABILITY],
        }, separators=(",", ":"),
    ).encode()
    response = client.post("/checkout-sessions", content=body, headers=_signed_headers(
        app, body, path="/checkout-sessions", key="checkout-live-1"
    ))
    assert response.status_code == 201


def test_runtime_delegation_derives_live_allowance_redacts_pan_and_replays(tmp_path) -> None:
    """Removing live Core lookup, durable replay, or PAN redaction breaks this HTTP contract."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    request = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_live_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app)
        first = client.post("/agentic_commerce/delegate_payment", json=request, headers={"Idempotency-Key": "delegate-1"})
        replay = client.post("/agentic_commerce/delegate_payment", json=request, headers={"Idempotency-Key": "delegate-1"})

    assert first.status_code == 201
    assert first.json()["token"].startswith("vt_")
    assert first.json()["allowance"]["max_amount"] == 500
    assert "4242424242424242" not in first.text
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()


def test_runtime_capture_settles_committed_reservation_and_replays(tmp_path) -> None:
    """Removing Core commit/proof wiring would reject PSP settlement or create a second purchase."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegate = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_capture_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app, "chi_capture_1")
        token = client.post("/agentic_commerce/delegate_payment", json=delegate, headers={"Idempotency-Key": "delegate-capture"}).json()["token"]
        body = {
            "mandate_id": "mandate_01", "checkout_session_id": "chi_capture_1", "merchant_id": "merchant_01",
            "token": token, "amount": {"amount": 500, "currency": "BRL", "scale": 2},
        }
        first = client.post("/payment-captures", json=body, headers={"Idempotency-Key": "capture-1"})
        replay = client.post("/payment-captures", json=body, headers={"Idempotency-Key": "capture-1"})
        status = client.get(f"/payment-captures/{first.json()['capture_id']}")

    assert first.status_code == 201
    assert first.json()["status"] == "settled"
    assert first.json()["settlement_reference"].startswith("psp_mock_")
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert status.status_code == 200
    assert status.json()["status"] == "settled"


def test_runtime_issues_receipts_only_after_settlement_and_mounts_audit(tmp_path) -> None:
    """Removing post-settlement receipt persistence or audit composition breaks the runtime evidence boundary."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    request = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_receipt_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app, "chi_receipt_1")
        token = client.post("/agentic_commerce/delegate_payment", json=request, headers={"Idempotency-Key": "delegate-receipt"}).json()["token"]
        capture = client.post("/payment-captures", json={
            "mandate_id": "mandate_01", "checkout_session_id": "chi_receipt_1", "merchant_id": "merchant_01",
            "token": token, "amount": {"amount": 500, "currency": "BRL", "scale": 2},
        }, headers={"Idempotency-Key": "capture-receipt"})
        receipts = client.get(f"/payment-captures/{capture.json()['capture_id']}/receipts")
        audit = client.get("/audit/mandates/mandate_01")

    assert receipts.status_code == 200
    assert receipts.json()["checkout_receipt"].count(".") == 2
    assert receipts.json()["payment_receipt"].count(".") == 2
    assert audit.status_code == 200
    assert audit.json()["timeline"]


def test_runtime_restart_preserves_signed_revocation(tmp_path) -> None:
    """Reseeding a recreated app must not overwrite a durable revocation with an active mandate."""
    database = tmp_path / "runtime.sqlite3"
    first = create_app(database_path=database)
    with TestClient(first, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, first, "chi_restart_1")
    first.state.runtime.core.submit_signed_revocation(sign_compact_jws(
        {"mandate_id": "mandate_01", "scope": "mandate", "reason": "holder", "epoch": 1},
        first.state.runtime.custody, "holder-key",
    ))
    second = create_app(database_path=database, custody=first.state.runtime.custody)
    with TestClient(second, base_url="https://merchant.aval.local") as client:
        response = client.post("/agentic_commerce/delegate_payment", json={
            "mandate_id": "mandate_01", "checkout_session_id": "chi_restart_1", "merchant_id": "merchant_01",
            "payment_method": {"card_number": "4242424242424242"},
        }, headers={"Idempotency-Key": "restart-delegate"})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "mandate_revoked"}}


def test_runtime_restart_does_not_extend_seed_mandate_expiry(tmp_path) -> None:
    """Replacing the persisted seed mandate on startup would silently extend an expired authority."""
    database = tmp_path / "runtime.sqlite3"
    issued_at = datetime(2026, 8, 29, tzinfo=UTC)
    first = create_app(database_path=database, clock=lambda: issued_at)
    with TestClient(first, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, first, "chi_expiry_1")
    second = create_app(
        database_path=database, custody=first.state.runtime.custody,
        clock=lambda: issued_at.replace(day=31),
    )
    with TestClient(second, base_url="https://merchant.aval.local") as client:
        response = client.post("/agentic_commerce/delegate_payment", json={
            "mandate_id": "mandate_01", "checkout_session_id": "chi_expiry_1", "merchant_id": "merchant_01",
            "payment_method": {"card_number": "4242424242424242"},
        }, headers={"Idempotency-Key": "expiry-delegate"})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "mandate_expired"}}
