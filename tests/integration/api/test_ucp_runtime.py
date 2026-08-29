from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from aval.adapters.ucp.http_signatures import SignedRequest, signature_base
from aval.main import create_app
from aval.security.content_digest import content_digest_sha256


def _signed_headers(app, body: bytes, *, idempotency_key: str = "create-1") -> dict[str, str]:
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
        path="/checkout-sessions",
        headers={**headers, "signature-input": signature_input},
        body=body,
    )
    signature = base64.b64encode(app.state.runtime.custody.sign_es256("agent-key", signature_base(request))).decode()
    return {**headers, "signature-input": signature_input, "signature": f"sig1=:{signature}:"}


def test_mounted_ucp_discovery_and_authenticated_checkout_creation() -> None:
    """Catches a composition root that leaves the tested UCP routers or RFC 9421 boundary unmounted."""
    app = create_app()
    body = json.dumps(
        {
            "id": "chi_runtime_1",
            "mandate_id": "mandate_01",
            "merchant_id": "merchant_01",
            "total": {"amount": 500, "currency": "BRL", "scale": 2},
            "line_items": [{"id": "coffee", "quantity": 1, "amount": 500}],
            "capabilities": ["dev.ucp.shopping.checkout", "dev.ucp.common.payment.ap2_mandate"],
        },
        separators=(",", ":"),
    ).encode()

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        discovery = client.get("/.well-known/ucp")
        created = client.post("/checkout-sessions", content=body, headers=_signed_headers(app, body))

    assert discovery.status_code == 200
    assert discovery.json()["ucp"] == {"version": "2026-08-25"}
    assert created.status_code == 201
    assert created.json()["id"] == "chi_runtime_1"
    assert created.json()["ap2"]["merchant_authorization"].count(".") == 2
