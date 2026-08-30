"""The demonstration that the trail catches its own editor.

`/ledger/verify` already walks the hash chain and names the position where it breaks;
until now that could only be shown by a test reaching into SQLite. This route lets a
judge break a link themselves and watch the auditor view point at it.

It is a tool for corrupting an audit log, so its whole security story is that it does
not exist unless somebody deliberately turned it on. `AVAL_DEMO_TAMPER` is not a
permission check that can be argued with — without it the route is never registered,
so a normal deployment answers 404 and does not even advertise the capability in its
OpenAPI document. The operator token is required on top of that.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aval.api.app import create_app
from aval.runtime import build_runtime
from tests.integration.api.conftest import Harness, MutableClock, _generated
from datetime import UTC, datetime

from aval.security.key_custody import KeyCustodyService


def tamper_harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setenv("AVAL_DEMO_TAMPER", "1")
    clock = MutableClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    custody = KeyCustodyService()
    custody.generate_es256(Harness.HOLDER_KID)
    runtime = build_runtime(now_provider=clock, operator_token=Harness.OPERATOR_TOKEN)
    harness = Harness(
        client=TestClient(create_app(runtime)), clock=clock, custody=custody, runtime=runtime
    )
    harness.client.post(
        "/agents",
        headers=harness.operator,
        json={
            "id": "agent_travel",
            "profile_url": "https://agents.aval.local/agent_travel",
            "public_jwk": _generated(custody, Harness.AGENT_KID),
            "trusted": True,
        },
    )
    return harness


def test_the_tamper_route_does_not_exist_without_the_flag(harness: Harness) -> None:
    """Not a 403 that could be argued with: the capability is simply not mounted."""
    mandate_id = harness.create_mandate()

    response = harness.client.post(
        f"/admin/ledger/{mandate_id}/tamper", headers=harness.operator, json={"sequence": 1}
    )

    assert response.status_code == 404, response.text
    assert "/admin/ledger" not in harness.client.get("/openapi.json").text


def test_tampering_breaks_the_chain_at_the_edited_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = tamper_harness(monkeypatch)
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id))
    harness.authorize(harness.purchase(mandate_id, checkout_id="chk_2"))
    assert harness.client.get("/ledger/verify", params={"mandate_id": mandate_id}).json()[
        "intact"
    ] is True

    edited = harness.client.post(
        f"/admin/ledger/{mandate_id}/tamper", headers=harness.operator, json={"sequence": 1}
    )

    assert edited.status_code == 200, edited.text
    verdict = harness.client.get("/ledger/verify", params={"mandate_id": mandate_id}).json()
    assert verdict["intact"] is False
    assert verdict["broken_at"] == 1


def test_the_auditor_view_reports_the_same_break(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = tamper_harness(monkeypatch)
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id))
    harness.client.post(
        f"/admin/ledger/{mandate_id}/tamper", headers=harness.operator, json={"sequence": 1}
    )

    auditor = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()

    assert auditor["chain"]["intact"] is False
    assert auditor["chain"]["broken_at"] == 1


def test_tampering_still_requires_the_operator_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = tamper_harness(monkeypatch)
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id))

    response = harness.client.post(
        f"/admin/ledger/{mandate_id}/tamper", json={"sequence": 1}
    )

    assert response.status_code == 401, response.text
    assert harness.client.get("/ledger/verify", params={"mandate_id": mandate_id}).json()[
        "intact"
    ] is True


def test_tampering_an_absent_event_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = tamper_harness(monkeypatch)
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id))

    response = harness.client.post(
        f"/admin/ledger/{mandate_id}/tamper", headers=harness.operator, json={"sequence": 99}
    )

    assert response.status_code == 404, response.text
    assert harness.client.get("/ledger/verify", params={"mandate_id": mandate_id}).json()[
        "intact"
    ] is True
