from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass, field
from itertools import count
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
    # mandate_id -> the instrument token that mandate names.
    instruments: dict[str, str] = field(default_factory=dict)

    HOLDER_KID = "usr_marta_k1"
    AGENT_KID = "agent_travel_k1"
    OPERATOR_TOKEN = "test-operator-token"

    @property
    def operator(self) -> dict[str, str]:
        return {"X-Aval-Operator": self.OPERATOR_TOKEN}

    def creation_token(
        self, payload: dict[str, Any], *, kid: str | None = None, **claim_overrides: Any
    ) -> str:
        """The holder's signature over the mandate they are asking for.

        Signed with the payload's own holder key, so a test that swaps the authorities
        keeps producing a proof the mandate names. `claim_overrides` is how the attack
        tests sign one set of terms and send another.
        """
        holder = next(
            (
                authority
                for authority in payload["authorities"]
                if authority.get("role") == "holder"
            ),
            None,
        )
        claims: dict[str, Any] = {
            "purpose": "mandate_creation",
            "principal_id": payload["principal"]["id"],
            "allowed_merchant_ids": sorted(payload["allowed_merchant_ids"]),
            "allowed_categories": sorted(payload["allowed_categories"]),
            "limit_minor_units": payload["limit"]["minor_units"],
            "currency": payload["limit"]["currency"],
            "scale": payload["limit"]["scale"],
            "ceiling_minor_units": (
                None if payload.get("ceiling") is None else payload["ceiling"]["minor_units"]
            ),
            "max_uses": (
                None if payload.get("usage_limit") is None else payload["usage_limit"]["max_uses"]
            ),
            "usage_window_seconds": (
                None
                if payload.get("usage_limit") is None
                else payload["usage_limit"]["window_seconds"]
            ),
            "expires_at": payload["expires_at"],
            "creation_nonce": f"mcn_{secrets.token_hex(8)}",
        }
        claims.update(claim_overrides)
        signing_kid = kid or (holder["kid"] if holder else self.HOLDER_KID)
        return sign_compact_jws(claims, self.custody, signing_kid)

    # A mandate is authority to spend; an instrument is the means. Since the core
    # stopped letting a mandate without a payment method settle, the default fixture
    # carries one — a test that wants the no-card case now says so by passing
    # `payment_method=None`, instead of getting it by accident.
    #
    # A token and four digits, never a number: the card is typed on the processor's
    # own page, so by the time a mandate hears about it there is nothing to tokenize.
    TEST_CARD = {"token": "pm_test_fixture", "label": "•••• 4242"}
    _cards = count(1)

    def mandate_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            # Unique per mandate, the way a real vaulted card is: two mandates sharing
            # one token would hide an instrument check that compared nothing.
            "payment_method": {**self.TEST_CARD, "token": f"pm_test_{next(self._cards)}"},
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
        # Signed last, over whatever the overrides made this mandate: a proof built
        # from the defaults would refuse every test that changes a term.
        payload.setdefault("creation_jws", self.creation_token(payload))
        return payload

    def create_mandate(self, **overrides: Any) -> str:
        response = self.client.post("/mandates", json=self.mandate_payload(**overrides))
        assert response.status_code == 201, response.text
        body = response.json()
        # The token is only ever handed back once, inside the revocation scope. Kept
        # here so `purchase()` can present the very instrument the mandate names.
        scope = body.get("instrument_revocation_scope")
        if scope:
            self.instruments[body["mandate_id"]] = scope.removeprefix("instrument:")
        return body["mandate_id"]

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
        if mandate_id in self.instruments:
            body["instrument_id"] = self.instruments[mandate_id]
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
        if mandate_id in self.instruments:
            body["instrument_id"] = self.instruments[mandate_id]
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        return body

    def read_token(self, principal_id: str = "usr_marta", *, kid: str | None = None) -> str:
        """The holder's authorization to *see* their own listings.

        Scoped by the key, so it answers for the mandates that key actually holds and
        for nothing else — a principal id is a guessable name, never an entitlement.
        """
        return sign_compact_jws(
            {"principal_id": principal_id}, self.custody, kid or self.HOLDER_KID
        )

    #: A assinatura de leitura viaja em cabeçalho: URL vai para log, histórico e
    #: `Referer`, e este JWS é prova portável de autoridade sobre o mandato.
    AUTHORIZATION_HEADER = "X-Aval-Authorization"

    def read_headers(self, principal_id: str = "usr_marta", *, kid: str | None = None):
        return {self.AUTHORIZATION_HEADER: self.read_token(principal_id, kid=kid)}

    def list_mandates(self, principal_id: str = "usr_marta", **overrides: Any):
        params = {"principal_id": principal_id}
        headers = self.read_headers(principal_id)
        if "authorization_jws" in overrides:
            token = overrides.pop("authorization_jws")
            headers = {} if token is None else {self.AUTHORIZATION_HEADER: token}
        params.update(overrides)
        return self.client.get("/mandates", params=params, headers=headers)

    def list_escalations(self, principal_id: str = "usr_marta", **overrides: Any):
        params = {"principal_id": principal_id}
        headers = self.read_headers(principal_id)
        if "authorization_jws" in overrides:
            token = overrides.pop("authorization_jws")
            headers = {} if token is None else {self.AUTHORIZATION_HEADER: token}
        params.update(overrides)
        return self.client.get("/escalations", params=params, headers=headers)

    def read_mandate(
        self, mandate_id: str, *, principal_id: str = "usr_marta", kid: str | None = None
    ):
        """One mandate, read the way its holder reads it: with a signature.

        The id alone stopped being enough — it names limits, spend and history, and it
        was never a secret."""
        return self.client.get(
            f"/mandates/{mandate_id}", headers=self.read_headers(principal_id, kid=kid)
        )

    def human_ledger(
        self, mandate_id: str, *, principal_id: str = "usr_marta", kid: str | None = None
    ):
        return self.client.get(
            "/ledger",
            params={"mandate_id": mandate_id, "view": "human"},
            headers=self.read_headers(principal_id, kid=kid),
        )

    def policy_version(self, mandate_id: str) -> int:
        return int(self.read_mandate(mandate_id).json()["policy_version"])

    def limit_token(
        self,
        mandate_id: str,
        minor_units: int,
        *,
        kid: str | None = None,
        policy_version: int | None = None,
    ) -> str:
        """The holder's authorization to move the budget.

        `policy_version` defaults to the live one, which is what a real holder signs.
        Passing an older one is how the replay test builds a token that must be refused.
        """
        return sign_compact_jws(
            {
                "mandate_id": mandate_id,
                "limit_minor_units": minor_units,
                "currency": "USD",
                "scale": 2,
                "policy_version": (
                    self.policy_version(mandate_id) if policy_version is None else policy_version
                ),
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
