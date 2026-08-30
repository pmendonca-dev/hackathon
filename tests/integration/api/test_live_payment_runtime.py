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
from aval.infrastructure.sqlite.revocation_repository import SqliteRevocationRepository


def _signed_headers(
    app, body: bytes, *, path: str, key: str, method: str = "POST",
    profile: str = "https://agent.aval.local/.well-known/ucp", signing_kid: str = "agent-key",
    include_idempotency_key: bool = True,
) -> dict[str, str]:
    headers = {
        "ucp-agent": f'profile="{profile}"',
        "content-digest": content_digest_sha256(body),
        "content-type": "application/json",
    }
    if include_idempotency_key:
        headers["idempotency-key"] = key
    components = '"@method" "@authority" "@path" "ucp-agent"'
    if include_idempotency_key:
        components += ' "idempotency-key"'
    components += ' "content-digest" "content-type"'
    signature_input = (
        f'sig1=({components});keyid="{signing_kid}";alg="ES256"'
        f';created={int(app.state.runtime.clock.now().timestamp())};nonce="{secrets.token_hex(16)}"'
    )
    request = SignedRequest(
        method=method, authority="merchant.aval.local", path=path,
        headers={**headers, "signature-input": signature_input}, body=body,
    )
    signature = base64.b64encode(
        app.state.runtime.custody.sign_es256(signing_kid, signature_base(request))
    ).decode()
    return {**headers, "signature-input": signature_input, "signature": f"sig1=:{signature}:"}


def _create_checkout(
    client: TestClient, app, checkout_id: str = "chi_live_1", *, amount: int = 500,
) -> dict[str, object]:
    body = json.dumps(
        {
            "id": checkout_id, "mandate_id": "mandate_01", "merchant_id": "merchant_01",
            "total": {"amount": amount, "currency": "BRL", "scale": 2},
            "line_items": [{"id": "coffee", "quantity": 1, "amount": amount}],
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


def _post_as(
    client: TestClient, app, path: str, payload: dict[str, object], key: str, *,
    profile: str, signing_kid: str,
):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return client.post(path, content=body, headers=_signed_headers(
        app, body, path=path, key=key, profile=profile, signing_kid=signing_kid,
    ))


def _get_operational(
    client: TestClient, app, path: str, key: str, *,
    profile: str = "https://agent.aval.local/.well-known/ucp", signing_kid: str = "agent-key",
):
    return client.get(path, headers=_signed_headers(
        app, b"", path=path, key=key, method="GET", profile=profile, signing_kid=signing_kid,
        include_idempotency_key=False,
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


def test_delegate_and_capture_accept_only_the_authenticated_agent_role(tmp_path) -> None:
    """A holder or auditor profile may read its projection but cannot operate payment surfaces."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_role_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_role_1")
        holder_delegate = _post_as(
            client, app, "/agentic_commerce/delegate_payment", delegation, "holder-delegate",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "agent-delegate").json()["token"]
        holder_capture = _post_as(
            client, app, "/payment-captures", {
                "checkout_session_id": "chi_role_1", "token": token,
                "audience": "merchant_01", "nonce": "capture-nonce",
                "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
            }, "holder-capture",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )

    assert holder_delegate.status_code == 403
    assert holder_delegate.json() == {"detail": {"code": "agent_not_authorized"}}
    assert holder_capture.status_code == 403
    assert holder_capture.json() == {"detail": {"code": "agent_not_authorized"}}


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


def test_capture_and_revocation_reject_tampered_bytes_invalid_signatures_and_impostor_profiles(tmp_path) -> None:
    """Each operational POST rejects body substitution and identities before any Core-side mutation."""
    database = tmp_path / "runtime.sqlite3"
    app = create_app(database_path=database)
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_post_auth_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_post_auth_1")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-post-auth").json()["token"]
        capture_payload = {
            "checkout_session_id": "chi_post_auth_1", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }
        capture_body = json.dumps(capture_payload, separators=(",", ":")).encode()
        capture_tampered = client.post("/payment-captures", content=capture_body + b" ", headers=_signed_headers(
            app, capture_body, path="/payment-captures", key="capture-tampered",
        ))
        capture_invalid_headers = _signed_headers(app, capture_body, path="/payment-captures", key="capture-invalid")
        capture_invalid_headers["signature"] = capture_invalid_headers["signature"][:-3] + "A:"
        capture_invalid = client.post("/payment-captures", content=capture_body, headers=capture_invalid_headers)
        capture_impostor = client.post("/payment-captures", content=capture_body, headers=_signed_headers(
            app, capture_body, path="/payment-captures", key="capture-impostor",
            profile="https://impostor.aval.local/.well-known/ucp",
        ))
        revocation_payload = {"signed_revocation": sign_compact_jws(
            {"mandate_id": "mandate_01", "scope": "mandate", "reason": "holder", "epoch": 1},
            app.state.runtime.custody, "holder-key",
        )}
        revocation_body = json.dumps(revocation_payload, separators=(",", ":")).encode()
        revocation_tampered = client.post("/mandates/mandate_01/revocations", content=revocation_body + b" ", headers=_signed_headers(
            app, revocation_body, path="/mandates/mandate_01/revocations", key="revoke-tampered",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        ))
        revocation_impostor = client.post("/mandates/mandate_01/revocations", content=revocation_body, headers=_signed_headers(
            app, revocation_body, path="/mandates/mandate_01/revocations", key="revoke-impostor",
            profile="https://impostor.aval.local/.well-known/ucp", signing_kid="holder-key",
        ))

    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        reservation_count = connection.execute(select(func.count()).select_from(reservations)).scalar_one()
    assert capture_tampered.json() == {"detail": {"code": "content_digest_invalid"}}
    assert capture_invalid.json() == {"detail": {"code": "signature_invalid"}}
    assert capture_impostor.json() == {"detail": {"code": "profile_not_trusted"}}
    assert revocation_tampered.json() == {"detail": {"code": "content_digest_invalid"}}
    assert revocation_impostor.json() == {"detail": {"code": "profile_not_trusted"}}
    assert reservation_count == 0


def test_runtime_maps_unavailable_revocation_storage_to_503(tmp_path, monkeypatch) -> None:
    """A live revocation read failure must fail closed as a service-unavailable condition."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_revocation_down", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_revocation_down")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-before-revocation-down").json()["token"]
        monkeypatch.setattr(
            SqliteRevocationRepository, "is_revoked", lambda *_args: (_ for _ in ()).throw(OSError("down")),
        )
        capture = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_revocation_down", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }, "capture-revocation-down")

    assert capture.status_code == 503
    assert capture.json() == {"detail": {"code": "revocation_unavailable"}}


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
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert status.status_code == 200
    assert status.json()["status"] == "settled"


def test_capture_rejects_caller_controlled_scope_with_the_stable_validation_envelope(tmp_path) -> None:
    """A caller must not smuggle mandate, merchant, or amount around canonical checkout scope."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_scope_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_scope_1")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-scope").json()["token"]
        response = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_scope_1", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
            "mandate_id": "attacker-mandate", "merchant_id": "attacker-merchant", "amount": 1,
        }, "capture-scope")

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request_invalid"}}


def test_second_capture_with_a_new_key_is_a_stable_conflict(tmp_path) -> None:
    """A new idempotency key must not turn one canonical checkout into a second settlement."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_double_1", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_double_1")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-double").json()["token"]
        payload = {
            "checkout_session_id": "chi_double_1", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }
        first = _post_operational(client, app, "/payment-captures", payload, "capture-double-1")
        second = _post_operational(client, app, "/payment-captures", payload, "capture-double-2")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {"detail": {"code": "transaction_already_captured"}}


def test_capture_rejects_a_changed_ap2_envelope_reusing_the_same_idempotency_key(tmp_path) -> None:
    """A key only replays the exact capture body, including its AP2 key-binding inputs."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_capture_idem_body", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_capture_idem_body")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-capture-idem-body").json()["token"]
        first = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_capture_idem_body", "token": token,
            "audience": "merchant_01", "nonce": "nonce-one",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, checkout["ap2"]["merchant_authorization"], nonce="nonce-one",
            )},
        }, "capture-same-key")
        changed = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_capture_idem_body", "token": token,
            "audience": "merchant_01", "nonce": "nonce-two",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, checkout["ap2"]["merchant_authorization"], nonce="nonce-two",
            )},
        }, "capture-same-key")

    assert first.status_code == 201
    assert changed.status_code == 422
    assert changed.json() == {"detail": {"code": "idempotency_key_reused"}}


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


def test_capture_rejects_invalid_ap2_signature_and_checkout_bindings_before_settlement(tmp_path) -> None:
    """Every AP2 signature, nonce, merchant, and total binding is checked against the canonical checkout."""
    database = tmp_path / "runtime.sqlite3"
    app = create_app(database_path=database)
    delegation = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_ap2_bindings", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_ap2_bindings")
        total_variant = _create_checkout(client, app, "chi_ap2_total_variant", amount=501)
        merchant_variant_body = json.dumps({
            "id": "chi_ap2_merchant_variant", "mandate_id": "mandate_01", "merchant_id": "merchant_02",
            "total": {"amount": 500, "currency": "BRL", "scale": 2},
            "line_items": [{"id": "coffee", "quantity": 1, "amount": 500}],
            "capabilities": ["dev.ucp.shopping.checkout", AP2_MANDATE_CAPABILITY],
        }, separators=(",", ":")).encode()
        merchant_variant = client.post("/checkout-sessions", content=merchant_variant_body, headers=_signed_headers(
            app, merchant_variant_body, path="/checkout-sessions", key="checkout-merchant-variant",
        ))
        assert merchant_variant.status_code == 201
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", delegation, "delegate-bindings").json()["token"]
        base = {"checkout_session_id": "chi_ap2_bindings", "token": token, "audience": "merchant_01", "nonce": "capture-nonce"}
        valid = _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])
        issuer, binding = valid.split("~")
        issuer_header, issuer_payload, issuer_signature = issuer.split(".")
        tampered_signature = ("A" if issuer_signature[0] != "A" else "B") + issuer_signature[1:]
        invalid_signature = _post_operational(client, app, "/payment-captures", {
            **base, "ap2": {"checkout_mandate": f"{issuer_header}.{issuer_payload}.{tampered_signature}~{binding}"},
        }, "capture-invalid-ap2-signature")
        invalid_nonce = _post_operational(client, app, "/payment-captures", {
            **base, "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, checkout["ap2"]["merchant_authorization"], nonce="stale-nonce",
            )},
        }, "capture-invalid-ap2-nonce")
        total_mismatch = _post_operational(client, app, "/payment-captures", {
            **base, "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, total_variant["ap2"]["merchant_authorization"],
            )},
        }, "capture-invalid-ap2-total")
        merchant_mismatch = _post_operational(client, app, "/payment-captures", {
            **base, "ap2": {"checkout_mandate": _closed_checkout_mandate(
                app, merchant_variant.json()["ap2"]["merchant_authorization"],
            )},
        }, "capture-invalid-ap2-merchant")

    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        reservation_count = connection.execute(select(func.count()).select_from(reservations)).scalar_one()
        receipt_count = connection.execute(select(func.count()).select_from(payment_runtime_captures)).scalar_one()
        settlement_events = connection.execute(select(func.count()).select_from(audit_events).where(
            audit_events.c.event_type.in_(("capture.committed", "capture.settled"))
        )).scalar_one()
    assert invalid_signature.json() == {"detail": {"code": "mandate_invalid_signature"}}
    assert invalid_nonce.json() == {"detail": {"code": "mandate_nonce_invalid"}}
    assert total_mismatch.json() == {"detail": {"code": "mandate_scope_mismatch"}}
    assert merchant_mismatch.json() == {"detail": {"code": "mandate_scope_mismatch"}}
    assert (reservation_count, receipt_count, settlement_events) == (0, 0, 0)


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
    assert any(event["event_type"] == "capture.settled" for event in audit.json()["timeline"])
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


def test_authenticated_readers_receive_contractual_not_found_errors(tmp_path) -> None:
    """Authentication must not turn documented unknown-capture and unknown-mandate responses into 403s."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        capture = _get_operational(client, app, "/payment-captures/unknown", "read-unknown-capture")
        receipt = _get_operational(client, app, "/payment-captures/unknown/receipts", "read-unknown-receipt")
        audit = _get_operational(
            client, app, "/audit/mandates/unknown", "read-unknown-mandate",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )

    assert capture.status_code == 404
    assert capture.json() == {"detail": {"code": "capture_not_found"}}
    assert receipt.status_code == 404
    assert receipt.json() == {"detail": {"code": "capture_not_found"}}
    assert audit.status_code == 404
    assert audit.json() == {"detail": {"code": "mandate_not_found"}}


def test_signed_revocation_is_authenticated_idempotent_and_audited(tmp_path) -> None:
    """A holder's registered JWS revokes the mandate once and creates the canonical audit fact."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    signed_revocation = sign_compact_jws(
        {"mandate_id": "mandate_01", "scope": "mandate", "reason": "holder_request", "epoch": 1},
        app.state.runtime.custody, "holder-key",
    )
    body = {"signed_revocation": signed_revocation}
    unsigned_body = json.dumps(body, separators=(",", ":")).encode()
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        unsigned = client.post("/mandates/mandate_01/revocations", content=unsigned_body, headers={
            "Idempotency-Key": "revoke-unsigned", "Content-Type": "application/json",
            "ucp-agent": 'profile="https://holder.aval.local/.well-known/ucp"',
            "Content-Digest": content_digest_sha256(unsigned_body),
        })
        first = _post_as(
            client, app, "/mandates/mandate_01/revocations", body, "revoke-1",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )
        replay = _post_as(
            client, app, "/mandates/mandate_01/revocations", body, "revoke-1",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )
        audit = _get_operational(
            client, app, "/audit/mandates/mandate_01", "revoke-audit",
            profile="https://auditor.aval.local/.well-known/ucp", signing_kid="auditor-key",
        )

    assert unsigned.status_code == 422
    assert unsigned.json() == {"detail": {"code": "signature_missing"}}
    assert first.status_code == 202
    assert first.json() == {"mandate_id": "mandate_01", "status": "revoked"}
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert any(event["event_type"] == "mandate.revoked" for event in audit.json()["timeline"])


def test_revocation_rejects_unknown_authority_and_path_mismatch(tmp_path) -> None:
    """The HTTP path cannot redirect a valid JWS and unregistered JWS keys fail closed."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    unknown = sign_compact_jws(
        {"mandate_id": "mandate_01", "scope": "mandate", "reason": "unknown", "epoch": 1},
        app.state.runtime.custody, "auditor-key",
    )
    mismatched = sign_compact_jws(
        {"mandate_id": "another_mandate", "scope": "mandate", "reason": "wrong_path", "epoch": 1},
        app.state.runtime.custody, "holder-key",
    )
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        unknown_response = _post_as(
            client, app, "/mandates/mandate_01/revocations", {"signed_revocation": unknown}, "revoke-unknown",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )
        mismatch_response = _post_as(
            client, app, "/mandates/mandate_01/revocations", {"signed_revocation": mismatched}, "revoke-mismatch",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )

    # 403, not 422. Both refusals are about *authority*: the caller is understood, and
    # is not allowed. A key that is not an authority on this mandate, and a token aimed
    # at another mandate, are answers to "may you", not "is this well formed".
    #
    # These read 422 while the coarser of the two revocation routers was the mounted one
    # — it funnelled every core refusal into a single status. The router that survived
    # carries the team's own code table, and that table already said 403.
    assert unknown_response.status_code == 403
    assert unknown_response.json() == {"detail": {"code": "revocation_authority_unknown"}}
    assert mismatch_response.status_code == 403
    assert mismatch_response.json() == {"detail": {"code": "revocation_mandate_mismatch"}}


def test_revocation_before_capture_blocks_settlement(tmp_path) -> None:
    """Revocation before the Core commit makes the delegated token unusable for capture."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    before_delegate = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_before_revoke", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_before_revoke")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", before_delegate, "delegate-before-revoke").json()["token"]
        revoke = _post_as(
            client, app, "/mandates/mandate_01/revocations", {
                "signed_revocation": sign_compact_jws(
                    {"mandate_id": "mandate_01", "scope": "mandate", "reason": "holder", "epoch": 1},
                    app.state.runtime.custody, "holder-key",
                )
            }, "revoke-before-capture",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )
        blocked_capture = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_before_revoke", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }, "capture-after-revoke")

    assert revoke.status_code == 202
    assert blocked_capture.status_code == 403
    assert blocked_capture.json() == {"detail": {"code": "mandate_revoked"}}


def test_revocation_after_settlement_preserves_receipt_and_blocks_future_purchase(tmp_path) -> None:
    """An append-only revocation cannot rewrite a settled capture, but closes the mandate for new work."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    first_delegate = {
        "mandate_id": "mandate_01", "checkout_session_id": "chi_settled_before_revoke", "merchant_id": "merchant_01",
        "payment_method": {"card_number": "4242424242424242"},
    }
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app, "chi_settled_before_revoke")
        token = _post_operational(client, app, "/agentic_commerce/delegate_payment", first_delegate, "delegate-settled-before-revoke").json()["token"]
        capture = _post_operational(client, app, "/payment-captures", {
            "checkout_session_id": "chi_settled_before_revoke", "token": token,
            "audience": "merchant_01", "nonce": "capture-nonce",
            "ap2": {"checkout_mandate": _closed_checkout_mandate(app, checkout["ap2"]["merchant_authorization"])},
        }, "capture-settled-before-revoke")
        revoke = _post_as(
            client, app, "/mandates/mandate_01/revocations", {
                "signed_revocation": sign_compact_jws(
                    {"mandate_id": "mandate_01", "scope": "mandate", "reason": "holder", "epoch": 1},
                    app.state.runtime.custody, "holder-key",
                )
            }, "revoke-after-capture",
            profile="https://holder.aval.local/.well-known/ucp", signing_kid="holder-key",
        )
        status = _get_operational(
            client, app, f"/payment-captures/{capture.json()['capture_id']}", "read-settled-after-revoke",
        )
        _create_checkout(client, app, "chi_blocked_after_revoke")
        future = _post_operational(client, app, "/agentic_commerce/delegate_payment", {
            "mandate_id": "mandate_01", "checkout_session_id": "chi_blocked_after_revoke", "merchant_id": "merchant_01",
            "payment_method": {"card_number": "4242424242424242"},
        }, "delegate-after-revoke")

    assert capture.status_code == 201
    assert revoke.status_code == 202
    assert status.status_code == 200
    assert status.json() == {
        "capture_id": capture.json()["capture_id"], "reservation_id": capture.json()["reservation_id"],
        "status": "settled", "settlement_reference": capture.json()["settlement_reference"],
    }
    assert future.status_code == 403
    assert future.json() == {"detail": {"code": "mandate_revoked"}}


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
