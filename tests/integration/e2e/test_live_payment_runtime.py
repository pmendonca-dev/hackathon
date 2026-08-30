from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY
from aval.adapters.ucp.http_signatures import SignedRequest, signature_base
from aval.main import create_app
from aval.security.content_digest import content_digest_sha256


def _checkout_body(checkout_id: str) -> bytes:
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


def _ucp_signed_headers(app, body: bytes, *, path: str, idempotency_key: str) -> dict[str, str]:
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
    signed_request = SignedRequest(
        method="POST",
        authority="merchant.aval.local",
        path=path,
        headers={**headers, "signature-input": signature_input},
        body=body,
    )
    signature = base64.b64encode(
        app.state.runtime.custody.sign_es256("agent-key", signature_base(signed_request))
    ).decode()
    return {
        **headers,
        "signature-input": signature_input,
        "signature": f"sig1=:{signature}:",
    }


def _create_checkout(client: TestClient, app, checkout_id: str) -> None:
    body = _checkout_body(checkout_id)
    response = client.post(
        "/checkout-sessions",
        content=body,
        headers=_ucp_signed_headers(
            app,
            body,
            path="/checkout-sessions",
            idempotency_key=f"create-{checkout_id}",
        ),
    )
    assert response.status_code == 201, response.text


def test_signed_revocation_is_a_real_public_runtime_endpoint(tmp_path) -> None:
    """An invalid signed command is rejected by the endpoint, never hidden by a 404."""
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        response = client.post(
            "/mandates/mandate_01/revocations",
            json={"signed_revocation": "not-a-valid-jws"},
            headers={"Idempotency-Key": "invalid-revocation-1"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "revocation_invalid"}}


def test_delegate_payment_rejects_a_request_without_authenticated_agent(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "runtime.sqlite3")

    with TestClient(app, base_url="https://merchant.aval.local") as client:
        _create_checkout(client, app, "chi_auth_01")
        response = client.post(
            "/agentic_commerce/delegate_payment",
            json={
                "mandate_id": "mandate_01",
                "checkout_session_id": "chi_auth_01",
                "merchant_id": "merchant_01",
                "payment_method": {"card_number": "4242424242424242"},
            },
            headers={"Idempotency-Key": "delegate-without-agent"},
        )

    assert response.status_code in {401, 403}, response.text
    assert "token" not in response.json()
