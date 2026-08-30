"""Every escalation the ladder opens must be one a human can actually close.

The case's rule is that nothing passes in silence. Its mirror image is just as bad: a
purchase stopped, escalated, approved by the holder with their own key — and refused
anyway by the same rung that opened it. The escalation closes as APPROVED, so there is
nothing left to retry, and the person is told yes while the money never moves.

Frequency and a zeroed budget both did exactly that. The refusals that are genuinely
never approvable — the ceiling, a revoked mandate, an expiry — are *rejected* on the
ladder rather than escalated, and this file holds that line too.
"""

from __future__ import annotations

from aval.application.authorization_core import APPROVABLE_REASONS
from aval.security.jws import sign_compact_jws

from tests.integration.api.conftest import Harness
from tests.integration.api.test_escalation_api import approval_token, decide

MONTH_SECONDS = 30 * 24 * 3600
SMALL = {"minor_units": 1000, "currency": "USD", "scale": 2}


def buy(harness: Harness, mandate_id: str, tag: str) -> dict:
    return harness.capture(
        harness.purchase(
            mandate_id, checkout_id=f"chk_{tag}", total=SMALL, idempotency_key=f"cap_{tag}"
        )
    ).json()


def test_approving_a_frequency_escalation_completes_the_purchase(harness: Harness) -> None:
    """The case's own bonus: "up to 3 times a month", and a human saying yes to a fourth."""
    mandate_id = harness.create_mandate(
        usage_limit={"max_uses": 3, "window_seconds": MONTH_SECONDS},
        limit={"minor_units": 100000, "currency": "USD", "scale": 2},
    )
    for index in range(3):
        assert buy(harness, mandate_id, f"ok{index}")["approved"] is True

    fourth = buy(harness, mandate_id, "fourth")
    assert fourth["reason_code"] == "usage_limit_exceeded"
    handle = fourth["escalation_id"]

    response = decide(
        harness,
        handle,
        "approve",
        approval_token(harness, handle, mandate_id, amount=SMALL["minor_units"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["capture"]["approved"] is True
    assert response.json()["capture"]["reason_code"] == "settled"


def test_denying_a_frequency_escalation_still_buys_nothing(harness: Harness) -> None:
    mandate_id = harness.create_mandate(
        usage_limit={"max_uses": 1, "window_seconds": MONTH_SECONDS},
        limit={"minor_units": 100000, "currency": "USD", "scale": 2},
    )
    assert buy(harness, mandate_id, "first")["approved"] is True
    handle = buy(harness, mandate_id, "second")["escalation_id"]
    spent_before = harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"]

    response = decide(
        harness,
        handle,
        "deny",
        approval_token(
            harness, handle, mandate_id, decision="deny", amount=SMALL["minor_units"]
        ),
    )

    assert response.json()["capture"] is None
    after = harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"]
    assert after == spent_before


def test_the_ceiling_is_refused_outright_and_never_escalated(harness: Harness) -> None:
    """The one bound with no approval path at all still has none."""
    mandate_id = harness.create_mandate(
        limit={"minor_units": 100000, "currency": "USD", "scale": 2},
        ceiling={"minor_units": 5000, "currency": "USD", "scale": 2},
    )

    refused = harness.capture(
        harness.purchase(
            mandate_id,
            checkout_id="chk_over_ceiling",
            total={"minor_units": 9000, "currency": "USD", "scale": 2},
            idempotency_key="cap_over_ceiling",
        )
    ).json()

    assert refused["approved"] is False
    assert refused["reason_code"] == "mandate_ceiling"
    assert refused["escalation_id"] is None
    assert "mandate_ceiling" not in APPROVABLE_REASONS


def test_a_revoked_mandate_is_refused_outright_and_never_escalated(harness: Harness) -> None:
    mandate_id = harness.create_mandate()
    harness.client.post(
        f"/mandates/{mandate_id}/revocation",
        json={
            "token": sign_compact_jws(
                {
                    "mandate_id": mandate_id,
                    "scope": "mandate",
                    "reason": "holder_request",
                    "epoch": 1,
                },
                harness.custody,
                harness.HOLDER_KID,
            )
        },
    )

    refused = buy(harness, mandate_id, "after_revocation")

    assert refused["reason_code"] == "mandate_revoked"
    assert refused["escalation_id"] is None
    assert "mandate_revoked" not in APPROVABLE_REASONS
