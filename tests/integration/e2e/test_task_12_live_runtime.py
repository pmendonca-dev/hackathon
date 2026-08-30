from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY
from aval.adapters.ucp.http_signatures import SignedRequest, signature_base
from aval.main import create_app
from aval.security.content_digest import content_digest_sha256
from aval.security.jws import sign_compact_jws


AGENT_PROFILE = "https://agent.aval.local/.well-known/ucp"
HOLDER_PROFILE = "https://holder.aval.local/.well-known/ucp"
AUDITOR_PROFILE = "https://auditor.aval.local/.well-known/ucp"


class RuntimeHttp:
    """Task 12 client: every observation crosses the authenticated HTTP boundary."""

    identities = {
        "agent": (AGENT_PROFILE, "agent-key"),
        "holder": (HOLDER_PROFILE, "holder-key"),
        "auditor": (AUDITOR_PROFILE, "auditor-key"),
    }

    def __init__(self, app: Any, client: TestClient) -> None:
        self.app = app
        self.client = client

    def headers(
        self,
        body: bytes,
        *,
        method: str,
        path: str,
        key: str,
        identity: str = "agent",
        profile: str | None = None,
    ) -> dict[str, str]:
        default_profile, signing_key = self.identities[identity]
        unsigned = {
            "ucp-agent": f'profile="{profile or default_profile}"',
            "idempotency-key": key,
            "content-digest": content_digest_sha256(body),
            "content-type": "application/json",
        }
        covered = (
            'sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" '
            f'"content-digest" "content-type");keyid="{signing_key}";alg="ES256"'
            # Freshness and a one-shot nonce, both inside the signed parameters.
            f';created={int(self.app.state.runtime.clock.now().timestamp())}'
            f';nonce="{secrets.token_hex(8)}"'
        )
        request = SignedRequest(
            method=method,
            authority="merchant.aval.local",
            path=path,
            headers={**unsigned, "signature-input": covered},
            body=body,
        )
        signature = self.app.state.runtime.custody.sign_es256(
            signing_key, signature_base(request)
        )
        return {
            **unsigned,
            "signature-input": covered,
            "signature": f"sig1=:{base64.b64encode(signature).decode()}:",
        }

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        key: str,
        *,
        identity: str = "agent",
        profile: str | None = None,
        transmitted_body: bytes | None = None,
        signed_body: bytes | None = None,
        corrupt_signature: bool = False,
    ):
        canonical = json.dumps(payload, separators=(",", ":")).encode()
        body_to_sign = signed_body if signed_body is not None else canonical
        body_to_send = transmitted_body if transmitted_body is not None else canonical
        headers = self.headers(
            body_to_sign,
            method="POST",
            path=path,
            key=key,
            identity=identity,
            profile=profile,
        )
        if corrupt_signature:
            headers["signature"] = headers["signature"][:-3] + "A:"
        return self.client.post(path, content=body_to_send, headers=headers)

    def get(self, path: str, key: str, *, identity: str = "agent"):
        return self.client.get(
            path,
            headers=self.headers(
                b"", method="GET", path=path, key=key, identity=identity
            ),
        )

    def checkout(
        self,
        checkout_id: str,
        *,
        merchant_id: str = "merchant_01",
        amount: int = 500,
    ):
        return self.post(
            "/checkout-sessions",
            {
                "id": checkout_id,
                "mandate_id": "mandate_01",
                "merchant_id": merchant_id,
                "total": {"amount": amount, "currency": "BRL", "scale": 2},
                "line_items": [
                    {"id": "coffee", "quantity": 1, "amount": amount}
                ],
                "capabilities": [
                    "dev.ucp.shopping.checkout",
                    AP2_MANDATE_CAPABILITY,
                ],
            },
            f"checkout-{checkout_id}",
        )

    def delegate(
        self,
        checkout_id: str,
        key: str,
        *,
        merchant_id: str = "merchant_01",
    ):
        return self.post(
            "/agentic_commerce/delegate_payment",
            {
                "mandate_id": "mandate_01",
                "checkout_session_id": checkout_id,
                "merchant_id": merchant_id,
            },
            key,
        )


def _b64url_digest(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _checkout_credential(
    app: Any,
    merchant_authorization: str,
    *,
    audience: str = "merchant_01",
    nonce: str = "capture-nonce",
) -> str:
    issuer = sign_compact_jws(
        {
            "vct": "mandate.checkout.1",
            "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
            "checkout_hash": _b64url_digest(merchant_authorization),
        },
        app.state.runtime.custody,
        "issuer-key",
    )
    holder = sign_compact_jws(
        {
            "aud": audience,
            "nonce": nonce,
            "sd_hash": _b64url_digest(issuer),
        },
        app.state.runtime.custody,
        "holder-key",
    )
    return f"{issuer}~{holder}"


def _capture_payload(
    app: Any,
    checkout: dict[str, Any],
    token: str,
    *,
    checkout_id: str,
    audience: str = "merchant_01",
    request_nonce: str = "capture-nonce",
    credential_audience: str = "merchant_01",
    credential_nonce: str = "capture-nonce",
) -> dict[str, Any]:
    return {
        "checkout_session_id": checkout_id,
        "token": token,
        "audience": audience,
        "nonce": request_nonce,
        "ap2": {
            "checkout_mandate": _checkout_credential(
                app,
                checkout["ap2"]["merchant_authorization"],
                audience=credential_audience,
                nonce=credential_nonce,
            )
        },
    }


def _revocation_jws(app: Any, *, epoch: int = 1) -> str:
    return sign_compact_jws(
        {
            "mandate_id": "mandate_01",
            "scope": "mandate",
            "reason": "holder_request",
            "epoch": epoch,
        },
        app.state.runtime.custody,
        "holder-key",
    )


def _settlement_setup(api: RuntimeHttp, checkout_id: str):
    checkout_response = api.checkout(checkout_id)
    assert checkout_response.status_code == 201, checkout_response.text
    delegation = api.delegate(checkout_id, f"delegate-{checkout_id}")
    assert delegation.status_code == 201, delegation.text
    return checkout_response.json(), delegation.json()["token"]


def test_signed_revocation_is_mounted_authenticated_and_accepted(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        payload = {"signed_revocation": _revocation_jws(app)}
        anonymous = client.post(
            "/mandates/mandate_01/revocations",
            json=payload,
            headers={"Idempotency-Key": "revoke-anonymous"},
        )
        accepted = api.post(
            "/mandates/mandate_01/revocations",
            payload,
            "revoke-holder-1",
            identity="holder",
        )

    assert {
        "anonymous": (anonymous.status_code, anonymous.json()),
        "authenticated": (accepted.status_code, accepted.json()),
    } == {
        "anonymous": (422, {"detail": {"code": "ucp_agent_invalid"}}),
        "authenticated": (
            202,
            {"mandate_id": "mandate_01", "status": "revoked"},
        ),
    }


def test_delegation_and_capture_without_rfc9421_are_rejected(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        assert api.checkout("chi_unsigned").status_code == 201
        delegation = client.post(
            "/agentic_commerce/delegate_payment",
            json={
                "mandate_id": "mandate_01",
                "checkout_session_id": "chi_unsigned",
                "merchant_id": "merchant_01",
            },
            headers={"Idempotency-Key": "unsigned-delegation"},
        )
        capture_body = b"{}"
        capture = client.post(
            "/payment-captures",
            content=capture_body,
            headers={
                "Idempotency-Key": "unsigned-capture",
                "ucp-agent": f'profile="{AGENT_PROFILE}"',
                "Content-Digest": content_digest_sha256(capture_body),
                "Content-Type": "application/json",
            },
        )

    assert (delegation.status_code, delegation.json()) == (
        422,
        {"detail": {"code": "ucp_agent_invalid"}},
    )
    assert (capture.status_code, capture.json()) == (
        422,
        {"detail": {"code": "signature_missing"}},
    )


def test_ap2_and_canonical_capture_fields_fail_before_any_settlement(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        checkout, token = _settlement_setup(api, "chi_evidence")
        audit_path = "/audit/mandates/mandate_01"
        before = api.get(audit_path, "audit-before", identity="auditor").json()[
            "timeline"
        ]
        base = {
            "checkout_session_id": "chi_evidence",
            "token": token,
            "audience": "merchant_01",
            "nonce": "capture-nonce",
        }
        missing = api.post("/payment-captures", base, "capture-missing-ap2")
        malformed = api.post(
            "/payment-captures",
            {**base, "ap2": {"checkout_mandate": "not-a-mandate"}},
            "capture-malformed-ap2",
        )
        wrong_audience = api.post(
            "/payment-captures",
            _capture_payload(
                app,
                checkout,
                token,
                checkout_id="chi_evidence",
                audience="merchant_other",
            ),
            "capture-wrong-audience",
        )
        wrong_nonce = api.post(
            "/payment-captures",
            _capture_payload(
                app,
                checkout,
                token,
                checkout_id="chi_evidence",
                request_nonce="unexpected-nonce",
            ),
            "capture-wrong-nonce",
        )
        extra_merchant = api.post(
            "/payment-captures",
            {
                **_capture_payload(
                    app, checkout, token, checkout_id="chi_evidence"
                ),
                "merchant_id": "merchant_other",
            },
            "capture-extra-merchant",
        )
        extra_total = api.post(
            "/payment-captures",
            {
                **_capture_payload(
                    app, checkout, token, checkout_id="chi_evidence"
                ),
                "total": {"amount": 1, "currency": "BRL", "scale": 2},
            },
            "capture-extra-total",
        )
        after_invalid = api.get(
            audit_path, "audit-after-invalid", identity="auditor"
        ).json()["timeline"]
        valid = api.post(
            "/payment-captures",
            _capture_payload(app, checkout, token, checkout_id="chi_evidence"),
            "capture-valid-after-invalid",
        )

    assert (missing.status_code, missing.json()) == (
        422,
        {"detail": {"code": "mandate_required"}},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"].startswith("mandate_")
    assert (wrong_audience.status_code, wrong_audience.json()) == (
        422,
        {"detail": {"code": "mandate_audience_invalid"}},
    )
    assert (wrong_nonce.status_code, wrong_nonce.json()) == (
        422,
        {"detail": {"code": "mandate_nonce_invalid"}},
    )
    assert extra_merchant.status_code == 422
    assert extra_total.status_code == 422
    for response in (extra_merchant, extra_total):
        detail = response.json().get("detail")
        assert isinstance(detail, dict) and isinstance(detail.get("code"), str)
    assert after_invalid == before
    assert valid.status_code == 201, valid.text


def test_out_of_scope_merchant_and_total_escalate_without_a_token(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        merchant_checkout = api.checkout(
            "chi_merchant_escalation", merchant_id="merchant_other"
        )
        total_checkout = api.checkout("chi_total_escalation", amount=20_000)
        merchant_delegate = api.delegate(
            "chi_merchant_escalation",
            "delegate-merchant-escalation",
            merchant_id="merchant_other",
        )
        total_delegate = api.delegate(
            "chi_total_escalation", "delegate-total-escalation"
        )

    for response in (merchant_checkout, total_checkout):
        assert response.status_code == 201
        assert response.json()["status"] == "requires_escalation"
        assert response.json()["continue_url"]
    assert (merchant_delegate.status_code, merchant_delegate.json()) == (
        403,
        {"detail": {"code": "merchant_out_of_scope"}},
    )
    assert (total_delegate.status_code, total_delegate.json()) == (
        403,
        {"detail": {"code": "budget_exceeded"}},
    )
    assert "token" not in merchant_delegate.json()
    assert "token" not in total_delegate.json()


def test_mandate_expiry_is_deterministic_across_runtime_restart(tmp_path) -> None:
    database = tmp_path / "runtime.sqlite3"
    issued_at = datetime(2026, 8, 29, 12, tzinfo=UTC)
    first = create_app(database_path=database, clock=lambda: issued_at)

    with TestClient(first, base_url="https://merchant.aval.local") as client:
        assert RuntimeHttp(first, client).checkout("chi_expired").status_code == 201

    expired = create_app(
        database_path=database,
        custody=first.state.runtime.custody,
        clock=lambda: issued_at + timedelta(days=2),
    )
    with TestClient(expired, base_url="https://merchant.aval.local") as client:
        response = RuntimeHttp(expired, client).delegate(
            "chi_expired", "delegate-expired"
        )

    assert (response.status_code, response.json()) == (
        403,
        {"detail": {"code": "mandate_expired"}},
    )


def test_revocation_store_unavailability_is_503_fail_closed(tmp_path) -> None:
    database = tmp_path / "runtime.sqlite3"
    app = create_app(database_path=database)

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        checkout, token = _settlement_setup(api, "chi_revocation_down")
        with sqlite3.connect(database) as connection:
            connection.execute(
                "ALTER TABLE revocations RENAME TO revocations_unavailable"
            )
        response = api.post(
            "/payment-captures",
            _capture_payload(
                app, checkout, token, checkout_id="chi_revocation_down"
            ),
            "capture-revocation-down",
        )

    assert (response.status_code, response.json()) == (
        503,
        {"detail": {"code": "revocation_unavailable"}},
    )


def test_impostor_invalid_signature_and_raw_body_tampering_are_rejected(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    payload = {
        "mandate_id": "mandate_01",
        "checkout_session_id": "chi_auth_attacks",
        "merchant_id": "merchant_01",
    }
    canonical = json.dumps(payload, separators=(",", ":")).encode()

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        assert api.checkout("chi_auth_attacks").status_code == 201
        impostor = api.post(
            "/agentic_commerce/delegate_payment",
            payload,
            "delegate-impostor",
            profile="https://impostor.aval.local/.well-known/ucp",
        )
        invalid = api.post(
            "/agentic_commerce/delegate_payment",
            payload,
            "delegate-invalid-signature",
            corrupt_signature=True,
        )
        tampered = api.post(
            "/agentic_commerce/delegate_payment",
            payload,
            "delegate-tampered-body",
            signed_body=canonical,
            transmitted_body=canonical + b" ",
        )

    assert (impostor.status_code, impostor.json()) == (
        403,
        {"detail": {"code": "profile_not_trusted"}},
    )
    assert (invalid.status_code, invalid.json()) == (
        422,
        {"detail": {"code": "signature_invalid"}},
    )
    assert (tampered.status_code, tampered.json()) == (
        422,
        {"detail": {"code": "content_digest_invalid"}},
    )


def test_capture_replay_and_double_capture_never_create_a_second_settlement(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        checkout, token = _settlement_setup(api, "chi_replay")
        payload = _capture_payload(app, checkout, token, checkout_id="chi_replay")
        first = api.post("/payment-captures", payload, "capture-replay")
        replay = api.post("/payment-captures", payload, "capture-replay")
        duplicate = api.post("/payment-captures", payload, "capture-duplicate")
        receipts = api.get(
            f"/payment-captures/{first.json()['capture_id']}/receipts",
            "receipts-replay",
        )
        timeline = api.get(
            "/audit/mandates/mandate_01", "audit-replay", identity="auditor"
        ).json()["timeline"]

    assert {
        "first": (first.status_code, first.json()["status"]),
        "replay": (
            replay.status_code,
            replay.headers.get("Idempotent-Replayed"),
            replay.json() == first.json(),
        ),
        "duplicate": (duplicate.status_code, duplicate.json()),
        "receipts": receipts.status_code,
        "settled_events": sum(
            event["event_type"] == "capture.settled" for event in timeline
        ),
    } == {
        "first": (201, "settled"),
        "replay": (201, "true", True),
        "duplicate": (
            409,
            {"detail": {"code": "transaction_already_captured"}},
        ),
        "receipts": 200,
        "settled_events": 1,
    }


def test_valid_purchase_exposes_receipts_audit_and_dispute_without_secrets(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        checkout, token = _settlement_setup(api, "chi_complete")
        credential = _checkout_credential(
            app, checkout["ap2"]["merchant_authorization"]
        )
        capture = api.post(
            "/payment-captures",
            {
                "checkout_session_id": "chi_complete",
                "token": token,
                "audience": "merchant_01",
                "nonce": "capture-nonce",
                "ap2": {"checkout_mandate": credential},
            },
            "capture-complete",
        )
        capture_id = capture.json()["capture_id"]
        status = api.get(f"/payment-captures/{capture_id}", "status-complete")
        receipts = api.get(
            f"/payment-captures/{capture_id}/receipts", "receipts-complete"
        )
        audit = api.get(
            "/audit/mandates/mandate_01", "audit-complete", identity="auditor"
        )
        dispute = api.get(
            "/audit/mandates/mandate_01/dispute",
            "dispute-complete",
            identity="holder",
        )

    assert capture.status_code == 201
    assert capture.json()["status"] == "settled"
    assert status.status_code == 200
    assert receipts.status_code == 200
    assert receipts.json()["checkout_receipt"].count(".") == 2
    assert receipts.json()["payment_receipt"].count(".") == 2
    assert audit.status_code == 200 and audit.json()["timeline"]
    assert dispute.status_code == 200 and dispute.json()["timeline"]
    exposed = "\n".join((receipts.text, audit.text, dispute.text))
    for secret in ("4242424242424242", token, credential):
        assert secret not in exposed


def test_revocation_before_commit_blocks_capture_without_receipts(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        checkout, token = _settlement_setup(api, "chi_revoke_before")
        revoked = api.post(
            "/mandates/mandate_01/revocations",
            {"signed_revocation": _revocation_jws(app)},
            "revoke-before",
            identity="holder",
        )
        capture = api.post(
            "/payment-captures",
            _capture_payload(
                app, checkout, token, checkout_id="chi_revoke_before"
            ),
            "capture-after-revocation",
        )

    assert {
        "revocation": (revoked.status_code, revoked.json()),
        "capture": (capture.status_code, capture.json()),
    } == {
        "revocation": (
            202,
            {"mandate_id": "mandate_01", "status": "revoked"},
        ),
        "capture": (403, {"detail": {"code": "mandate_revoked"}}),
    }


def test_post_commit_revocation_blocks_future_purchase_without_rewriting_settlement(
    tmp_path,
) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        api = RuntimeHttp(app, client)
        checkout, token = _settlement_setup(api, "chi_before_revoke")
        settled = api.post(
            "/payment-captures",
            _capture_payload(
                app, checkout, token, checkout_id="chi_before_revoke"
            ),
            "capture-before-revoke",
        )
        capture_id = settled.json()["capture_id"]
        revoked = api.post(
            "/mandates/mandate_01/revocations",
            {"signed_revocation": _revocation_jws(app)},
            "revoke-after-commit",
            identity="holder",
        )
        future_checkout = api.checkout("chi_after_revoke")
        future_delegation = api.delegate(
            "chi_after_revoke", "delegate-after-revoke"
        )
        original_status = api.get(
            f"/payment-captures/{capture_id}", "status-after-revoke"
        )
        original_receipts = api.get(
            f"/payment-captures/{capture_id}/receipts",
            "receipts-after-revoke",
        )
        dispute = api.get(
            "/audit/mandates/mandate_01/dispute",
            "dispute-after-revoke",
            identity="holder",
        )

    assert {
        "settled": (settled.status_code, settled.json()["status"]),
        "revocation": (revoked.status_code, revoked.json()),
        "future_checkout": future_checkout.status_code,
        "future_delegation": (
            future_delegation.status_code,
            future_delegation.json(),
        ),
        "original_status": (
            original_status.status_code,
            original_status.json()["status"],
        ),
        "original_receipts": original_receipts.status_code,
        "dispute": (
            dispute.status_code,
            bool(dispute.json()["post_commit_note"]),
            any(
                event["event_type"] == "mandate.revoked"
                for event in dispute.json()["timeline"]
            ),
        ),
    } == {
        "settled": (201, "settled"),
        "revocation": (
            202,
            {"mandate_id": "mandate_01", "status": "revoked"},
        ),
        "future_checkout": 201,
        "future_delegation": (
            403,
            {"detail": {"code": "mandate_revoked"}},
        ),
        "original_status": (200, "settled"),
        "original_receipts": 200,
        "dispute": (200, True, True),
    }
