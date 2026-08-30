"""A scoped revocation over the protocol lane is applied *and* reported as applied.

Cancelling the card is not revoking the mandate — that separation is the whole point of
scoped revocation, and the mandate stays ACTIVE on purpose. The router used to judge the
outcome by the mandate's status, so every scoped revocation looked like a token aimed at
some other mandate: the revocation was committed, and the caller was told 403
`revocation_mandate_mismatch`. The worst possible answer, because it invites a retry of
something that already happened.

The check the router actually wants is whether the token names the mandate in the URL.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aval.api.routers.revocations import create_revocation_router
from aval.application.authorization_core import AuthorizationCore
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService

SCOPES = frozenset({"mandate", "instrument:vt_1", "budget:zero"})


@pytest.fixture
def core() -> AuthorizationCore:
    custody = KeyCustodyService()
    custody.generate_es256("holder")
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC))
    core.custody = custody
    for mandate_id in ("m1", "m2"):
        core.register_mandate(
            Mandate(
                mandate_id,
                Principal("p1", "Marta"),
                frozenset({"vuelaya"}),
                frozenset({"travel"}),
                Money(100_000, "USD", 2),
                datetime(2026, 9, 30, tzinfo=UTC),
                1,
                {"revocation_id": f"rev_{mandate_id}", "epoch": 0},
                (
                    RevocationAuthority(
                        f"auth_{mandate_id}",
                        "holder",
                        RevocationRole.HOLDER,
                        custody.public_jwk("holder"),
                        SCOPES,
                    ),
                ),
            )
        )
    return core


@pytest.fixture
def client(core: AuthorizationCore) -> TestClient:
    app = FastAPI()
    app.include_router(create_revocation_router(core))
    return TestClient(app)


def token(core: AuthorizationCore, mandate_id: str, scope: str) -> str:
    return sign_compact_jws(
        {"mandate_id": mandate_id, "scope": scope, "reason": "holder", "epoch": 1},
        core.custody,
        "holder",
    )


def revoke(client, mandate_id: str, signed: str, *, key: str = "idem-1"):
    return client.post(
        f"/mandates/{mandate_id}/revocations",
        json={"signed_revocation": signed},
        headers={"Idempotency-Key": key},
    )


def test_cancelling_the_card_is_accepted_and_leaves_the_mandate_active(client, core) -> None:
    response = revoke(client, "m1", token(core, "m1", "instrument:vt_1"))

    assert response.status_code == 202, response.text
    assert response.json() == {"mandate_id": "m1", "status": "scope_revoked"}
    assert core.mandate("m1").status.value == "ACTIVE"


def test_revoking_the_mandate_still_reports_it_revoked(client, core) -> None:
    response = revoke(client, "m1", token(core, "m1", "mandate"))

    assert response.status_code == 202, response.text
    assert response.json() == {"mandate_id": "m1", "status": "revoked"}
    assert core.mandate("m1").status.value == "REVOKED"


def test_a_token_aimed_at_another_mandate_is_refused_without_revoking_either(client, core) -> None:
    """The guard that mattered has to survive the fix: authority over m2 is not
    authority over m1, whatever the URL says.

    And the refusal has to come *before* anything is applied. The router used to submit
    the token first and compare afterwards, which revoked m2 — irreversibly — on the way
    to telling the caller their request was refused. A caller who is answered 403 must
    be able to believe nothing happened.
    """
    response = revoke(client, "m1", token(core, "m2", "mandate"))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "revocation_mandate_mismatch"
    assert core.mandate("m1").status.value == "ACTIVE"
    assert core.mandate("m2").status.value == "ACTIVE"


def test_a_replayed_key_returns_the_first_answer_rather_than_revoking_twice(client, core) -> None:
    """The same key and the same bytes replay; they do not revoke a second time.

    The token is signed once and sent twice on purpose. ECDSA draws a fresh nonce per
    signature, so re-signing identical claims produces different bytes — and different
    bytes under one idempotency key are a *mismatch*, which is a refusal rather than a
    replay. That is correct, and it is why a caller retrying has to resend what it sent.
    """
    signed = token(core, "m1", "mandate")

    first = revoke(client, "m1", signed, key="same-key")
    second = revoke(client, "m1", signed, key="same-key")

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert second.json() == first.json()


def test_the_running_application_serves_exactly_one_revocations_route() -> None:
    """Two modules once defined this same path and only one of them was mounted, so the
    suite green-lit a router the server never ran.

    Asserted through `openapi()` rather than `app.routes`: FastAPI keeps included
    routers as wrapper objects, and the OpenAPI document is the stable flattened view —
    the same reason `browser_delivery` reads its reserved prefixes from there.
    """
    import importlib.util

    from aval.main import create_app

    paths = create_app(database_path=None).openapi()["paths"]

    assert "post" in paths.get("/mandates/{mandate_id}/revocations", {})
    # The singular twin is gone rather than merely unmounted: a second module defining
    # this path is what let a test pass against code the server never ran.
    assert importlib.util.find_spec("aval.api.routers.revocation") is None
