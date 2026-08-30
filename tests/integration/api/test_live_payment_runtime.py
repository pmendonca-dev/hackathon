from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY
from aval.adapters.ucp.http_signatures import SignedRequest, signature_base
from aval.main import create_app
from aval.security.content_digest import content_digest_sha256
from aval.security.jws import sign_compact_jws
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import audit_events, payment_runtime_captures, reservations


def _signed_headers(
    app, body: bytes, *, path: str, key: str, method: str = "POST",
    profile: str = "https://agent.aval.local/.well-known/ucp", signing_kid: str = "agent-key",
) -> dict[str, str]:
    headers = {
        "ucp-agent": f'profile="{profile}"',
        "idempotency-key": key,
        "content-digest": content_digest_sha256(body),
        "content-type": "application/json",
    }
    signature_input = (
        'sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" '
        f'"content-digest" "content-type");keyid="{signing_kid}";alg="ES256"'
        # The lane requires a freshness stamp and a nonce; a fresh nonce per call keeps
        # a legitimate retry legitimate while a byte-identical replay is refused.
        f';created={int(app.state.runtime.clock.now().timestamp())};nonce="{secrets.token_hex(8)}"'
    )
    request = SignedRequest(
        method=method, authority="merchant.aval.local", path=path,
        headers={**headers, "signature-input": signature_input}, body=body,
    )
    signature = base64.b64encode(
        app.state.runtime.custody.sign_es256(signing_kid, signature_base(request))
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
    return response.json()


def _b64url_sha256(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _closed_checkout_mandate(app, merchant_authorization: str, *, audience: str = "merchant_01", nonce: str = "capture-nonce") -> str:
    now = datetime.now(UTC)
    issuer = sign_compact_jws(
        {"vct": "mandate.checkout.1", "exp": int((now + timedelta(minutes=5)).timestamp()),
         "checkout_hash": _b64url_sha256(merchant_authorization)},
        app.state.runtime.custody, "issuer-key",
    )
    binding = sign_compact_jws(
        {"aud": audience, "nonce": nonce, "sd_hash": _b64url_sha256(issuer)},
        app.state.runtime.custody, "holder-key",
    )
    return f"{issuer}~{binding}"


def _post_operational(client: TestClient, app, path: str, payload: dict[str, object], key: str):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return client.post(path, content=body, headers=_signed_headers(app, body, path=path, key=key))


def _get_operational(
    client: TestClient, app, path: str, key: str, *,
    profile: str = "https://agent.aval.local/.well-known/ucp", signing_kid: str = "agent-key",
):
    return client.get(path, headers=_signed_headers(
        app, b"", path=path, key=key, method="GET", profile=profile, signing_kid=signing_kid,
    ))


def test_runtime_delegation_derives_live_allowance_redacts_pan_and_replays(tmp_path) -> None:
    """Removing live Core lookup, durable replay, or PAN redaction breaks this HTTP contract."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    request = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_live_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app)
        first = _post_operational(client, app, "/agentic_commerce/delegate_payment", request, "delegate-1")
        replay = _post_operational(client, app, "/agentic_commerce/delegate_payment", request, "delegate-1")

    assert first.status_code == 201
    assert first.json()["token"].startswith("vt_")
    assert first.json()["allowance"]["max_amount"] == 500
    assert "4242424242424242" not in first.text
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()


def test_operational_posts_require_rfc9421_authentication(tmp_path) -> None:
    """Removing the runtime auth dependency would allow an unsigned agent to delegate a card."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    payload = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_auth_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app, "chi_auth_1")
        response = client.post("/agentic_commerce/delegate_payment", content=body, headers={
            "Idempotency-Key": "unsigned", "ucp-agent": 'profile="https://agent.aval.local/.well-known/ucp"',
            "Content-Digest": content_digest_sha256(body), "Content-Type": "application/json",
        })
        capture = client.post("/payment-captures", content=b"{}", headers={
            "Idempotency-Key": "unsigned-capture", "ucp-agent": 'profile="https://agent.aval.local/.well-known/ucp"',
            "Content-Digest": content_digest_sha256(b"{}"), "Content-Type": "application/json",
        })

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "signature_missing"}}
    assert capture.status_code == 422
    assert capture.json() == {"detail": {"code": "signature_missing"}}


def test_delegate_rejects_tampered_body_invalid_signature_and_impostor_profile(tmp_path) -> None:
    """Changing bytes or identity after signing must fail before delegation tokenization."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    payload = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_auth_matrix", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app, "chi_auth_matrix")
        tampered = client.post("/agentic_commerce/delegate_payment", content=body + b" ", headers=_signed_headers(
            app, body, path="/agentic_commerce/delegate_payment", key="tampered"
        ))
        invalid_headers = _signed_headers(app, body, path="/agentic_commerce/delegate_payment", key="invalid")
        invalid_headers["signature"] = invalid_headers["signature"][:-3] + "A:"
        invalid = client.post("/agentic_commerce/delegate_payment", content=body, headers=invalid_headers)
        impostor = client.post("/agentic_commerce/delegate_payment", content=body, headers=_signed_headers(
            app, body, path="/agentic_commerce/delegate_payment", key="impostor",
            profile="https://impostor.aval.local/.well-known/ucp",
        ))

    assert tampered.json() == {"detail": {"code": "content_digest_invalid"}}
    assert invalid.json() == {"detail": {"code": "signature_invalid"}}
    assert impostor.status_code == 403
    assert impostor.json() == {"detail": {"code": "profile_not_trusted"}}


def test_runtime_capture_settles_committed_reservation_and_replays(tmp_path) -> None:
    """Removing Core commit/proof wiring would reject PSP settlement or create a second purchase."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegate = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_capture_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_capture_1")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegate, "delegate-capture").json()["token"]
        body = {
            "checkout_session_id": "chi_capture_1", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }
        first = _post_operational(client, app, "/payment-captures", body, "capture-1")
        replay = _post_operational(client, app, "/payment-captures", body, "capture-1")
        status = _get_operational(client, app, f"/payment-captures/{first.json()['capture_id']}", "read-capture-1")

    assert first.status_code == 201
    assert first.json()["status"] == "settled"
    assert first.json()["settlement_reference"].startswith("psp_mock_")
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert status.status_code == 200
    assert status.json()["status"] == "settled"


def test_capture_rejects_missing_or_mismatched_ap2_evidence_before_settlement(tmp_path) -> None:
    """Removing AP2 revalidation would let altered checkout bindings reach the PSP."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_ap2_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_ap2_1")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-ap2").json()["token"]
        base = {
            "checkout_session_id": "chi_ap2_1", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
        }
        missing = _post_operational(client, app, "/payment-captures", base, "capture-ap2-missing")
        mismatched = _post_operational(client, app, "/payment-captures", {
            **base, "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, checkout["ap2"]["merchant_authorization"], audience="other-merchant"
            )},
        }, "capture-ap2-mismatch")

    assert missing.status_code == 422
    assert missing.json() == {"detail": {"code": "mandate_required"}}
    assert mismatched.status_code == 422
    assert mismatched.json() == {"detail": {"code": "mandate_audience_invalid"}}


def test_invalid_ap2_chain_creates_no_reservation_settlement_receipt_or_audit(tmp_path) -> None:
    """A broken AP2 binding must stop before Core commit and all downstream effects."""
    database = tmp_path / "runtime.sqlite3"
    app = create_app(database_path=database)
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_ap2_stop", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_ap2_stop")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-stop").json()["token"]
        response = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_ap2_stop", "token": token, "audience": "merchant_01", "nonce": "wrong",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, checkout["ap2"]["merchant_authorization"], nonce="expected"
            )},
        }, "capture-stop")

    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        reservation_count = connection.execute(select(func.count()).select_from(reservations)).scalar_one()
        receipt_count = connection.execute(select(func.count()).select_from(payment_runtime_captures)).scalar_one()
        settlement_events = connection.execute(select(func.count()).select_from(audit_events).where(
            audit_events.c.event_type.in_(("capture.committed", "capture.settled"))
        )).scalar_one()
    assert response.json() == {"detail": {"code": "mandate_nonce_invalid"}}
    assert (reservation_count, receipt_count, settlement_events) == (0, 0, 0)


def test_runtime_issues_receipts_only_after_settlement_and_mounts_audit(tmp_path) -> None:
    """Removing post-settlement receipt persistence or audit composition breaks the runtime evidence boundary."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    request = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_receipt_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_receipt_1")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", request, "delegate-receipt").json()["token"]
        capture = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_receipt_1", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }, "capture-receipt")
        receipts = _get_operational(client, app, f"/payment-captures/{capture.json()['capture_id']}/receipts", "read-receipt-1")
        audit = _get_operational(client, app, "/audit/mandates/mandate_01", "read-audit-1")
        holder_audit = _get_operational(
            client, app, "/audit/mandates/mandate_01", "holder-audit-1",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )

    assert receipts.status_code == 200
    assert receipts.json()["checkout_receipt"].count(".") == 2
    assert receipts.json()["payment_receipt"].count(".") == 2
    assert audit.status_code == 200
    assert audit.json()["timeline"]
    assert holder_audit.status_code == 200


def test_receipts_and_audit_require_an_authenticated_reader(tmp_path) -> None:
    """Removing read-side authorization would expose settlement evidence anonymously."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        receipts = client.get("/payment-captures/unknown/receipts")
        audit = client.get("/audit/mandates/mandate_01")

    assert receipts.status_code == 422
    assert audit.status_code == 422
    assert receipts.json() == {"detail": {"code": "ucp_agent_invalid"}}
    assert audit.json() == {"detail": {"code": "ucp_agent_invalid"}}


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
        response = _post_operational(client, second, "/agentic_commerce/delegate_payment", {
            "mandate_id": "mandate_01", "checkout_session_id": "chi_restart_1", "merchant_id": "merchant_01",
            "payment_method": {"card_number": "4242424242424242"},
        }, "restart-delegate")

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
        response = _post_operational(client, second, "/agentic_commerce/delegate_payment", {
            "mandate_id": "mandate_01", "checkout_session_id": "chi_expiry_1", "merchant_id": "merchant_01",
            "payment_method": {"card_number": "4242424242424242"},
        }, "expiry-delegate")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "mandate_expired"}}
