from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aval.api.app import create_app
from aval.runtime import build_runtime
from aval.security.http_signature import build_params, signature_base
from aval.security.content_digest import content_digest_sha256
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


class MutableClock:
    """A clock the test moves by hand, so validity is never wall-clock flaky."""

    def __init__(self, start: datetime) -> None:
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, delta: timedelta) -> None:
        self.instant = self.instant + delta


@dataclass
class Harness:
    client: TestClient
    clock: MutableClock
    custody: KeyCustodyService
    runtime: Any

    HOLDER_KID = "usr_marta_k1"
    AGENT_KID = "agent_travel_k1"
    OPERATOR_TOKEN = "test-operator-token"

    @property
    def operator(self) -> dict[str, str]:
        return {"X-Aval-Operator": self.OPERATOR_TOKEN}

    def mandate_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "principal": {"id": "usr_marta", "display_name": "Marta Silva"},
            "allowed_merchant_ids": ["vuelaya"],
            "allowed_categories": ["travel"],
            "limit": {"minor_units": 20000, "currency": "USD", "scale": 2},
            "ceiling": {"minor_units": 50000, "currency": "USD", "scale": 2},
            "expires_at": "2026-09-30T23:59:59Z",
            "authorities": [
                {
                    "id": "auth_holder",
                    "kid": self.HOLDER_KID,
                    "role": "holder",
                    "public_jwk": self.custody.public_jwk(self.HOLDER_KID),
                    "allowed_scopes": ["mandate"],
                }
            ],
        }
        payload.update(overrides)
        return payload

    def create_mandate(self, **overrides: Any) -> str:
        response = self.client.post("/mandates", json=self.mandate_payload(**overrides))
        assert response.status_code == 201, response.text
        return response.json()["mandate_id"]

    def register_agent(self, agent_id: str, kid: str, *, trusted: bool = True) -> None:
        self.custody.generate_es256(kid)
        response = self.client.post(
            "/agents",
            headers=self.operator,
            json={
                "id": agent_id,
                "profile_url": f"https://agents.aval.local/{agent_id}",
                "public_jwk": self.custody.public_jwk(kid),
                "trusted": trusted,
            },
        )
        assert response.status_code == 201, response.text

    def purchase(self, mandate_id: str, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "mandate_id": mandate_id,
            "checkout_id": "chk_1",
            "merchant_id": "vuelaya",
            "category": "travel",
            "total": {"minor_units": 13000, "currency": "USD", "scale": 2},
        }
        body.update(overrides)
        return body

    def purchase_from_offer(
        self, mandate_id: str, offer: dict[str, Any], idempotency_key: str | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "mandate_id": mandate_id,
            "checkout_id": f"chk_{offer['offer_id']}",
            "merchant_id": offer["merchant_id"],
            "category": offer["item"]["category"],
            "total": offer["total"],
            "merchant_authorization": offer["merchant_authorization"],
        }
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        return body

    def limit_token(self, mandate_id: str, minor_units: int, *, kid: str | None = None) -> str:
        return sign_compact_jws(
            {
                "mandate_id": mandate_id,
                "limit_minor_units": minor_units,
                "currency": "USD",
                "scale": 2,
            },
            self.custody,
            kid or self.HOLDER_KID,
        )

    def change_limit(self, mandate_id: str, minor_units: int):
        """Move the live budget the way a holder does: signed."""
        return self.client.patch(
            f"/mandates/{mandate_id}/limit",
            json={
                "limit": {"minor_units": minor_units, "currency": "USD", "scale": 2},
                "authorization_jws": self.limit_token(mandate_id, minor_units),
            },
        )

    def signed_post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        kid: str | None = None,
        announce_kid: str | None = None,
        created: int | None = None,
        nonce: str | None = None,
        tamper: dict[str, Any] | None = None,
        cover_body: bool = True,
    ):
        """Sign like the agent does, with seams the attack tests need.

        `announce_kid` claims one key id while signing with another; `tamper` sends a
        different body than the one that was signed; `cover_body` drops content-digest
        from the covered components.
        """
        signing_kid = kid or self.AGENT_KID
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        digest = content_digest_sha256(raw)
        params = build_params(
            keyid=announce_kid or signing_kid,
            # The runtime clock, not the raw provider: once the demo clock has been
            # advanced, a signature stamped from the un-offset instant is genuinely
            # stale and the edge is right to refuse it.
            created=created if created is not None else int(self.runtime.clock.now().timestamp()),
            nonce=nonce or secrets.token_hex(8),
        )
        if not cover_body:
            params = params.replace(' "content-digest"', "", 1)
        signature = self.custody.sign_es256(
            signing_kid,
            signature_base(method="POST", path=path, content_digest=digest, raw_params=params),
        )
        headers = {
            "Content-Digest": digest,
            "Signature-Input": f"sig1={params}",
            "Signature": f"sig1=:{base64.b64encode(signature).decode('ascii')}:",
            "Content-Type": "application/json",
        }
        sent = raw if tamper is None else json.dumps(tamper, separators=(",", ":")).encode("utf-8")
        return self.client.post(path, content=sent, headers=headers)

    def authorize(self, body: dict[str, Any], **signing: Any):
        return self.signed_post("/authorize", body, **signing)

    def capture(self, body: dict[str, Any], **signing: Any):
        return self.signed_post("/capture", body, **signing)


@pytest.fixture
def harness() -> Harness:
    clock = MutableClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    custody = KeyCustodyService()
    custody.generate_es256(Harness.HOLDER_KID)
    runtime = build_runtime(now_provider=clock, operator_token=Harness.OPERATOR_TOKEN)
    harness = Harness(
        client=TestClient(create_app(runtime)), clock=clock, custody=custody, runtime=runtime
    )
    response = harness.client.post(
        "/agents",
        headers=harness.operator,
        json={
            "id": "agent_travel",
            "profile_url": "https://agents.aval.local/agent_travel",
            "public_jwk": _generated(custody, Harness.AGENT_KID),
            "trusted": True,
        },
    )
    assert response.status_code == 201, response.text
    return harness


def _generated(custody: KeyCustodyService, kid: str) -> dict[str, str]:
    custody.generate_es256(kid)
    return custody.public_jwk(kid)
