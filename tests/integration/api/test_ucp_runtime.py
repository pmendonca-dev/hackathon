from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient

from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY
from aval.adapters.ucp.http_signatures import SignedRequest, signature_base
from aval.main import create_app
from aval.security.content_digest import content_digest_sha256
from aval.security.jws import sign_compact_jws


def _signed_headers(
    app, body: bytes, *, path: str, idempotency_key: str = "create-1"
) -> dict[str, str]:
    headers = {
        "ucp-agent": 'profile="https://agent.aval.local/.well-known/ucp"',
        "idempotency-key": idempotency_key,
        "content-digest": content_digest_sha256(body),
        "content-type": "application/json",
    }
    signature_input = (
        'sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" '
        '"content-digest" "content-type");keyid="agent-key";alg="ES256"'
    )
    request = SignedRequest(
        method="POST",
        authority="merchant.aval.local",
        path=path,
        headers={**headers, "signature-input": signature_input},
        body=body,
    )
    signature = base64.b64encode(app.state.runtime.custody.sign_es256("agent-key", signature_base(request))).decode()
    return {**headers, "signature-input": signature_input, "signature": f"sig1=:{signature}:"}


def _checkout_body(checkout_id: str = "chi_runtime_1") -> bytes:
    return json.dumps(
        {
            "id": checkout_id,
            "mandate_id": "mandate_01",
            "merchant_id": "merchant_01",
            "total": {"amount": 500, "currency": "BRL", "scale": 2},
            "line_items": [{"id": "coffee", "quantity": 1, "amount": 500}],
            "capabilities": ["dev.ucp.shopping.checkout", AP2_MANDATE_CAPABILITY],
        },
        separators=(",", ":"),
    ).encode()


def _b64url_sha256(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _closed_mandate(app, merchant_authorization: str, *, audience: str, nonce: str) -> str:
    now = datetime.now(UTC)
    issuer_jwt = sign_compact_jws(
        {
            "vct": "mandate.checkout.1",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "checkout_hash": _b64url_sha256(merchant_authorization),
        },
        app.state.runtime.custody,
        "issuer-key",
    )
    kb_jwt = sign_compact_jws(
        {"aud": audience, "nonce": nonce, "sd_hash": _b64url_sha256(issuer_jwt)},
        app.state.runtime.custody,
        "holder-key",
    )
    return f"{issuer_jwt}~{kb_jwt}"


def _create_checkout(client: TestClient, app, checkout_id: str = "chi_runtime_1") -> dict[str, object]:
    body = _checkout_body(checkout_id)
    response = client.post(
        "/checkout-sessions",
        content=body,
        headers=_signed_headers(app, body, path="/checkout-sessions"),
    )
    assert response.status_code == 201
    return response.json()


def test_mounted_ucp_discovery_and_authenticated_checkout_creation() -> None:
    """Catches a composition root that leaves the tested UCP routers or RFC 9421 boundary unmounted."""
    app = create_app()
    body = _checkout_body()

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        discovery = client.get("/.well-known/ucp")
        created = client.post(
            "/checkout-sessions",
            content=body,
            headers=_signed_headers(app, body, path="/checkout-sessions"),
        )

    assert discovery.status_code == 200
    assert discovery.json()["ucp"] == {"version": "2026-08-25"}
    assert created.status_code == 201
    assert created.json()["id"] == "chi_runtime_1"
    assert created.json()["ap2"]["merchant_authorization"].count(".") == 2


def test_mounted_completion_loads_persisted_checkout_and_captures() -> None:
    """Catches a runtime whose completion path relies on an in-memory checkout instead of SQLite."""
    app = create_app()
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app)
        body = json.dumps(
            {
                "audience": "merchant_01",
                "nonce": "challenge-1",
                "ap2": {
                    "checkout_mandate": _closed_mandate(
                        app,
                        checkout["ap2"]["merchant_authorization"],
                        audience="merchant_01",
                        nonce="challenge-1",
                    )
                },
            },
            separators=(",", ":"),
        ).encode()
        response = client.post(
            "/checkout-sessions/chi_runtime_1/complete",
            content=body,
            headers=_signed_headers(
                app, body, path="/checkout-sessions/chi_runtime_1/complete", idempotency_key="complete-1"
            ),
        )

    assert response.status_code == 200
    assert response.json()["approved"] is True
    # The merged runtime carries a settlement adapter, so an approved capture runs one
    # step further than when the core had no processor behind it: committed and then
    # settled. `approved` is the guarantee this test is about.
    assert response.json()["reason_code"] == "settled"


def test_checkout_persists_when_the_runtime_is_recreated(tmp_path) -> None:
    """Catches a checkout store that loses the canonical session when FastAPI is rebuilt over the same SQLite file."""
    database_path = tmp_path / "aval.sqlite3"
    first_app = create_app(database_path=database_path)
    with TestClient(first_app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, first_app)

    second_app = create_app(database_path=database_path, custody=first_app.state.runtime.custody)
    body = json.dumps(
        {
            "audience": "merchant_01",
            "nonce": "challenge-1",
            "ap2": {
                "checkout_mandate": _closed_mandate(
                    second_app,
                    checkout["ap2"]["merchant_authorization"],
                    audience="merchant_01",
                    nonce="challenge-1",
                )
            },
        },
        separators=(",", ":"),
    ).encode()
    with TestClient(second_app, base_url="https://merchant.aval.local") as client:
        response = client.post(
            "/checkout-sessions/chi_runtime_1/complete",
            content=body,
            headers=_signed_headers(
                second_app, body, path="/checkout-sessions/chi_runtime_1/complete", idempotency_key="complete-1"
            ),
        )

    assert response.status_code == 200
    assert response.json()["approved"] is True


def test_mounted_completion_requires_ap2_mandate_and_idempotency_key() -> None:
    """Catches an AP2 downgrade or completion request that can bypass its required idempotency header."""
    app = create_app()
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app)
        body = b'{"audience":"merchant_01","nonce":"challenge-1","ap2":{}}'
        locked = client.post(
            "/checkout-sessions/chi_runtime_1/complete",
            content=body,
            headers=_signed_headers(
                app, body, path="/checkout-sessions/chi_runtime_1/complete", idempotency_key="complete-1"
            ),
        )
        missing_idempotency_headers = {
            "ucp-agent": 'profile="https://agent.aval.local/.well-known/ucp"',
            "content-digest": content_digest_sha256(body),
            "content-type": "application/json",
            "signature-input": (
                'sig1=("@method" "@authority" "@path" "ucp-agent" "content-digest" '
                '"content-type");keyid="agent-key";alg="ES256"'
            ),
            "signature": "sig1=:AA==:",
        }
        missing_idempotency = client.post(
            "/checkout-sessions/chi_runtime_1/complete",
            content=body,
            headers=missing_idempotency_headers,
        )

    assert locked.status_code == 422
    assert locked.json() == {"detail": {"code": "mandate_required"}}
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json() == {"detail": {"code": "signature_components_missing"}}


def test_mounted_ucp_boundary_rejects_an_invalid_raw_signature() -> None:
    """Catches a mounted route that accepts a forged RFC 9421 ES256 signature after raw-body capture."""
    app = create_app()
    body = _checkout_body()
    headers = _signed_headers(app, body, path="/checkout-sessions")
    headers["signature"] = headers["signature"][:-3] + "A:"

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        response = client.post("/checkout-sessions", content=body, headers=headers)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "signature_invalid"}}


def test_mounted_ucp_boundary_hashes_the_original_raw_body_bytes() -> None:
    """Catches a route that verifies Content-Digest over reserialized JSON instead of the received byte stream."""
    app = create_app()
    signed_body = _checkout_body()
    delivered_body = (
        b'{"mandate_id":"mandate_01","id":"chi_runtime_1","merchant_id":"merchant_01",'
        b'"total":{"amount":500,"currency":"BRL","scale":2},'
        b'"line_items":[{"id":"coffee","quantity":1,"amount":500}],'
        b'"capabilities":["dev.ucp.shopping.checkout","dev.ucp.common.payment.ap2_mandate"]}'
    )
    headers = _signed_headers(app, signed_body, path="/checkout-sessions")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        response = client.post("/checkout-sessions", content=delivered_body, headers=headers)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "content_digest_invalid"}}


def test_mounted_ucp_boundary_rejects_der_encoded_es256_signature() -> None:
    """Catches a mounted RFC 9421 verifier that accidentally accepts cryptography's DER ECDSA output."""
    app = create_app()
    body = _checkout_body()
    headers = _signed_headers(app, body, path="/checkout-sessions")
    raw_signature = base64.b64decode(headers["signature"].removeprefix("sig1=:").removesuffix(":"))
    der_signature = encode_dss_signature(
        int.from_bytes(raw_signature[:32], "big"), int.from_bytes(raw_signature[32:], "big")
    )
    headers["signature"] = f"sig1=:{base64.b64encode(der_signature).decode()}:"

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        response = client.post("/checkout-sessions", content=body, headers=headers)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "signature_invalid"}}


def test_mounted_completion_rejects_invalid_ap2_audience_and_nonce() -> None:
    """Catches a mounted completion route that ignores AP2 key-binding audience or nonce claims."""
    app = create_app()
    with TestClient(app, base_url="https://merchant.aval.local") as client:
        checkout = _create_checkout(client, app)
        merchant_authorization = checkout["ap2"]["merchant_authorization"]
        for claim, expected_code in (("audience", "mandate_audience_invalid"), ("nonce", "mandate_nonce_invalid")):
            audience = "wrong-merchant" if claim == "audience" else "merchant_01"
            nonce = "old-challenge" if claim == "nonce" else "challenge-1"
            body = json.dumps(
                {
                    "audience": "merchant_01",
                    "nonce": "challenge-1",
                    "ap2": {"checkout_mandate": _closed_mandate(app, merchant_authorization, audience=audience, nonce=nonce)},
                },
                separators=(",", ":"),
            ).encode()
            response = client.post(
                "/checkout-sessions/chi_runtime_1/complete",
                content=body,
                headers=_signed_headers(
                    app,
                    body,
                    path="/checkout-sessions/chi_runtime_1/complete",
                    idempotency_key=f"complete-{claim}",
                ),
            )
            assert response.status_code == 422
            assert response.json() == {"detail": {"code": expected_code}}
