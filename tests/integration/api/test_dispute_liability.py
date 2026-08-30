"""Not "was this authorized?" but "who answers for it?".

The case asks four questions and the fourth is *who answers for the dispute: the human,
the agent, the merchant?* Resolving a dispute to MANDATE_HELD answers a different one —
whether authority existed — and leaves the money question to a human reading prose.

The verdict here is derived, never stored: the evidence it reads is append-only, so
recomputing it must always give the same answer, and a stored verdict that drifted from
its own evidence would be worse than none.
"""

from __future__ import annotations

from aval.security.jws import sign_compact_jws


def set_psp(harness, mode: str):
    assert harness.client.post(
        "/admin/psp", headers=harness.operator, json={"mode": mode}
    ).status_code == 200


def buy(harness, mandate_id: str, key: str = "cap_liab", **overrides):
    return harness.capture(harness.purchase(mandate_id, **overrides) | {"idempotency_key": key})


def dispute(harness, reservation_id: str) -> dict:
    opened = harness.client.post(
        "/disputes", json={"reservation_id": reservation_id, "reason": "Eu nunca autorizei isso"}
    )
    assert opened.status_code == 201, opened.text
    resolved = harness.client.post(f"/disputes/{opened.json()['dispute_id']}/resolution")
    assert resolved.status_code == 200, resolved.text
    return resolved.json()


def test_a_purchase_inside_the_mandate_answers_to_the_holder(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]

    verdict = dispute(harness, reservation_id)["liability"]

    assert verdict["verdict"] == "HOLDER_LIABLE"
    assert verdict["liable_party"] == "holder"


def test_the_verdict_cites_the_proof_that_carries_it(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]

    verdict = dispute(harness, reservation_id)["liability"]

    assert any("prova" in line.lower() for line in verdict["basis"])


def test_a_purchase_the_processor_refused_leaves_nobody_liable(harness):
    """Nothing was charged, so there is nothing to answer for. Naming a liable party
    here would invent a loss that never happened."""
    mandate_id = harness.create_mandate()
    set_psp(harness, "decline")
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]

    verdict = dispute(harness, reservation_id)["liability"]

    assert verdict["verdict"] == "NO_CHARGE"
    assert verdict["liable_party"] == "nobody"


def test_a_purchase_the_holder_approved_by_signature_answers_to_the_holder(harness):
    """The strongest possible answer to "I never authorized this" is the person's own
    signature over this exact purchase."""
    mandate_id = harness.create_mandate()
    escalated = buy(
        harness,
        mandate_id,
        key="cap_esc",
        merchant_id="andesair",
        total={"minor_units": 13000, "currency": "USD", "scale": 2},
    ).json()
    handle = escalated["escalation_id"]
    harness.client.post(
        f"/escalations/{handle}/decision",
        json={
            "decision": "approve",
            "approval_jws": sign_compact_jws(
                {
                    "decision_handle": handle,
                    "mandate_id": mandate_id,
                    "decision": "approve",
                    "amount_minor_units": 13000,
                },
                harness.custody,
                harness.HOLDER_KID,
            )
        },
    )

    verdict = dispute(harness, _settled_reservation(harness, mandate_id))["liability"]

    assert verdict["verdict"] == "HOLDER_LIABLE"
    assert verdict["mandate_repudiation"] == "refuted"


def test_a_mandate_with_no_holder_signature_cannot_refute_repudiation(harness):
    """An honest limit, declared instead of hidden: mandate creation is not signed in
    this build, so the trail can prove the agent stayed inside the mandate and cannot
    prove the person created it."""
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]

    verdict = dispute(harness, reservation_id)["liability"]

    assert verdict["mandate_repudiation"] == "unproven"
    assert verdict["repudiation_note"]


def test_a_revocation_is_a_holder_signature_that_refutes_repudiation(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
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

    verdict = dispute(harness, reservation_id)["liability"]

    assert verdict["mandate_repudiation"] == "refuted"


def test_the_verdict_is_the_same_when_it_is_read_again(harness):
    """Derived, not stored. Reading it twice reads the same evidence twice."""
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    at_resolution = dispute(harness, reservation_id)["liability"]

    listed = harness.client.get("/disputes", params={"mandate_id": mandate_id}).json()

    assert listed["disputes"][0]["liability"] == at_resolution


def test_the_verdict_is_written_into_the_auditor_trail(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    dispute(harness, reservation_id)

    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]

    assert entries[-1]["detail"]["liability"]["verdict"] == "HOLDER_LIABLE"


def test_the_merchant_never_reads_who_answers_for_the_buyer(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    dispute(harness, reservation_id)

    raw = harness.client.get(
        "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
    ).text

    assert "HOLDER_LIABLE" not in raw


def _settled_reservation(harness, mandate_id: str) -> str:
    """The reservation the resumed capture committed, read back from the trail."""
    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]
    committed = [
        entry for entry in entries if entry["event_type"] == "purchase_committed"
    ]
    assert committed, "the approved escalation must have committed a purchase"
    return committed[-1]["detail"]["reservation_id"]
