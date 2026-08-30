from __future__ import annotations

from datetime import timedelta
from typing import Any

from aval.security.jws import sign_compact_jws


def escalate(harness, mandate_id: str, **overrides: Any) -> str:
    response = harness.authorize(harness.purchase(mandate_id, merchant_id="other_shop", **overrides))
    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "awaiting_human"
    handle = response.json()["escalation_id"]
    assert handle.startswith("dh_")
    return handle


def approval_token(
    harness,
    handle: str,
    mandate_id: str,
    *,
    decision: str = "approve",
    amount: int = 13000,
    kid: str | None = None,
) -> str:
    return sign_compact_jws(
        {
            "decision_handle": handle,
            "mandate_id": mandate_id,
            "decision": decision,
            "amount_minor_units": amount,
            "decided_at": harness.clock.instant.isoformat(),
        },
        harness.custody,
        kid or harness.HOLDER_KID,
    )


def decide(harness, handle: str, decision: str, token: str):
    return harness.client.post(
        f"/escalations/{handle}/decision", json={"decision": decision, "approval_jws": token}
    )


def test_a_purchase_outside_the_mandate_opens_an_escalation(harness):
    mandate_id = harness.create_mandate()

    handle = escalate(harness, mandate_id)

    pending = harness.client.get("/escalations", params={"mandate_id": mandate_id}).json()
    assert [item["id"] for item in pending["escalations"]] == [handle]
    assert pending["escalations"][0]["reason_code"] == "merchant_out_of_scope"
    assert pending["escalations"][0]["status"] == "OPEN"


def test_an_approved_escalation_completes_the_purchase(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    response = decide(harness, handle, "approve", approval_token(harness, handle, mandate_id))

    assert response.status_code == 200, response.text
    assert response.json()["resumed"] is True
    assert response.json()["capture"]["approved"] is True


def test_a_denied_escalation_buys_nothing(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    response = decide(
        harness, handle, "deny", approval_token(harness, handle, mandate_id, decision="deny")
    )

    assert response.status_code == 200, response.text
    assert response.json()["resumed"] is False
    assert response.json()["capture"] is None
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_an_approval_signed_by_a_stranger_is_refused(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)
    harness.custody.generate_es256("not_marta_k1")

    response = decide(
        harness, handle, "approve", approval_token(harness, handle, mandate_id, kid="not_marta_k1")
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "approval_authority_unknown"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_an_approval_with_a_tampered_payload_is_refused(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)
    header, payload, signature = approval_token(harness, handle, mandate_id).split(".")
    flipped = ("A" if payload[0] != "A" else "B") + payload[1:]

    response = decide(harness, handle, "approve", f"{header}.{flipped}.{signature}")

    assert response.status_code == 403
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_an_approval_for_another_handle_is_refused(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)
    other = escalate(harness, mandate_id, checkout_id="chk_2")

    response = decide(harness, handle, "approve", approval_token(harness, other, mandate_id))

    assert response.status_code == 403
    assert response.json()["reason_code"] == "approval_handle_mismatch"


def test_an_approval_cannot_quietly_raise_the_amount(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    response = decide(
        harness, handle, "approve", approval_token(harness, handle, mandate_id, amount=90000)
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "approval_amount_mismatch"


def test_the_body_and_the_signature_must_agree_on_the_decision(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    response = decide(
        harness, handle, "approve", approval_token(harness, handle, mandate_id, decision="deny")
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "approval_decision_mismatch"


def test_an_approval_cannot_resurrect_a_revoked_mandate(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)
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

    response = decide(harness, handle, "approve", approval_token(harness, handle, mandate_id))

    assert response.status_code == 200
    assert response.json()["capture"]["approved"] is False
    assert response.json()["capture"]["reason_code"] == "mandate_revoked"


def test_an_approval_cannot_outlive_its_window(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    harness.clock.advance(timedelta(hours=2))

    response = decide(harness, handle, "approve", approval_token(harness, handle, mandate_id))

    assert response.status_code == 409
    assert response.json()["reason_code"] == "escalation_expired"


def test_an_escalation_is_decided_once(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)
    token = approval_token(harness, handle, mandate_id)
    first = decide(harness, handle, "approve", token)

    second = decide(harness, handle, "approve", token)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["reason_code"] == "escalation_already_decided"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 13000


def test_an_unknown_handle_is_refused(harness):
    mandate_id = harness.create_mandate()

    response = decide(harness, "dh_nope", "approve", approval_token(harness, "dh_nope", mandate_id))

    assert response.status_code == 404


def test_the_signed_approval_is_kept_as_evidence_on_the_trail(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    decide(harness, handle, "approve", approval_token(harness, handle, mandate_id))

    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]
    approved = [entry for entry in entries if entry["event_type"] == "escalation_approved"]
    assert len(approved) == 1
    assert approved[0]["detail"]["decision_handle"] == handle
    assert approved[0]["detail"]["approval_jws"].count(".") == 2
    assert approved[0]["actor"] == f"principal:usr_marta"


def test_the_human_view_shows_the_approval_but_not_the_raw_token(harness):
    mandate_id = harness.create_mandate()
    handle = escalate(harness, mandate_id)

    decide(harness, handle, "approve", approval_token(harness, handle, mandate_id))

    body = harness.client.get("/ledger", params={"mandate_id": mandate_id, "view": "human"}).json()
    summaries = [entry["human_summary"] for entry in body["entries"]]
    assert any("aprov" in summary.lower() for summary in summaries)
    assert "approval_jws" not in harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "human"}
    ).text


def test_a_budget_escalation_can_also_be_approved(harness):
    mandate_id = harness.create_mandate()
    harness.capture(harness.purchase(mandate_id) | {"idempotency_key": "cap_first"})
    response = harness.authorize(harness.purchase(mandate_id, checkout_id="chk_2"))
    assert response.json()["reason_code"] == "budget_exceeded"
    handle = response.json()["escalation_id"]

    resumed = decide(harness, handle, "approve", approval_token(harness, handle, mandate_id))

    assert resumed.json()["capture"]["approved"] is True
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 26000


def test_one_approval_covers_the_purchase_even_with_two_rules_in_the_way(harness):
    """The signature names this merchant, this amount, this handle. Having seen it, the
    person approved the purchase — not one of the reasons it was stopped."""
    mandate_id = harness.create_mandate()
    harness.capture(harness.purchase(mandate_id) | {"idempotency_key": "cap_fills_budget"})
    blocked = harness.authorize(
        harness.purchase(
            mandate_id,
            checkout_id="chk_both",
            merchant_id="other_shop",
            total={"minor_units": 15000, "currency": "USD", "scale": 2},
        )
    ).json()
    assert blocked["reason_code"] == "merchant_out_of_scope"

    resumed = decide(
        harness,
        blocked["escalation_id"],
        "approve",
        approval_token(harness, blocked["escalation_id"], mandate_id, amount=15000),
    )

    assert resumed.json()["capture"]["approved"] is True, resumed.text
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 28000


def test_an_approval_still_cannot_reach_above_the_ceiling(harness):
    """Nothing above the ceiling ever produces a handle, so there is nothing to sign."""
    mandate_id = harness.create_mandate()

    refused = harness.authorize(
        harness.purchase(
            mandate_id, total={"minor_units": 90000, "currency": "USD", "scale": 2}
        )
    ).json()

    assert refused["decision"] == "rejected"
    assert refused["escalation_id"] is None
    assert harness.client.get("/escalations", params={"mandate_id": mandate_id}).json()[
        "escalations"
    ] == []
