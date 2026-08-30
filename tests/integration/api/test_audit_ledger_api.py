from __future__ import annotations

from sqlalchemy import select, update

from aval.infrastructure.sqlite.models import evidence
from aval.security.jws import sign_compact_jws


def settled_purchase(harness) -> str:
    mandate_id = harness.create_mandate()
    response = harness.capture(harness.purchase(mandate_id) | {"idempotency_key": "cap_ledger"}
    )
    assert response.json()["approved"] is True, response.text
    return mandate_id


def auditor_entries(harness, mandate_id: str) -> list[dict]:
    response = harness.client.get("/ledger", params={"mandate_id": mandate_id, "view": "auditor"})
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def test_registering_a_mandate_opens_its_trail(harness):
    mandate_id = harness.create_mandate()

    entries = auditor_entries(harness, mandate_id)

    assert [entry["event_type"] for entry in entries] == ["mandate_registered"]
    assert entries[0]["sequence"] == 1


def test_a_settled_purchase_leaves_an_ordered_trail(harness):
    mandate_id = settled_purchase(harness)

    types = [entry["event_type"] for entry in auditor_entries(harness, mandate_id)]

    assert types == ["mandate_registered", "purchase_committed", "purchase_settled"]


def test_a_refused_purchase_is_recorded_and_never_silent(harness):
    mandate_id = harness.create_mandate()

    harness.authorize(harness.purchase(mandate_id, merchant_id="other_shop"))

    entries = auditor_entries(harness, mandate_id)
    assert entries[-1]["event_type"] == "purchase_escalated"
    assert entries[-1]["detail"]["reason_code"] == "merchant_out_of_scope"


def test_a_rejected_purchase_is_recorded_too(harness):
    mandate_id = harness.create_mandate()

    harness.authorize(harness.purchase(
            mandate_id, total={"minor_units": 90000, "currency": "USD", "scale": 2}
        ),
    )

    entries = auditor_entries(harness, mandate_id)
    assert entries[-1]["event_type"] == "purchase_rejected"
    assert entries[-1]["detail"]["reason_code"] == "mandate_ceiling"


def test_a_live_limit_change_is_recorded(harness):
    mandate_id = harness.create_mandate()

    harness.change_limit(mandate_id, 10000)

    entries = auditor_entries(harness, mandate_id)
    assert entries[-1]["event_type"] == "mandate_limit_replaced"
    assert entries[-1]["detail"]["limit_minor_units"] == 10000


def test_a_revocation_is_recorded(harness):
    mandate_id = harness.create_mandate()
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder_request", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )

    harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": token})

    entries = auditor_entries(harness, mandate_id)
    assert entries[-1]["event_type"] == "mandate.revoked"
    assert entries[-1]["detail"]["reason"] == "holder_request"
    assert entries[-1]["detail"]["scope"] == "mandate"


def test_the_auditor_trail_is_a_hash_chain_that_verifies(harness):
    mandate_id = settled_purchase(harness)

    entries = auditor_entries(harness, mandate_id)

    assert entries[0]["previous_sha256"] == "0" * 64
    for earlier, later in zip(entries, entries[1:], strict=False):
        assert later["previous_sha256"] == earlier["sha256"]
    verification = harness.client.get("/ledger/verify", params={"mandate_id": mandate_id})
    assert verification.json() == {"intact": True, "checked": len(entries), "broken_at": None}


def test_a_tampered_trail_stops_verifying(harness):
    mandate_id = settled_purchase(harness)
    with harness.runtime.engine.connect() as connection:
        target = connection.execute(select(evidence.c.id, evidence.c.payload)).mappings().first()
        connection.execute(
            update(evidence)
            .where(evidence.c.id == target["id"])
            .values(payload=target["payload"].replace("mandate_registered", "mandate_forged"))
        )
        connection.commit()

    verification = harness.client.get("/ledger/verify", params={"mandate_id": mandate_id})

    assert verification.json()["intact"] is False
    assert verification.json()["broken_at"] == 1


def test_the_human_view_shows_the_purchase_and_what_is_left(harness):
    mandate_id = settled_purchase(harness)

    response = harness.human_ledger(mandate_id)

    body = response.json()
    assert body["mandate"]["remaining"]["minor_units"] == 7000
    assert body["mandate"]["spent"]["minor_units"] == 13000
    assert any(entry["human_summary"] for entry in body["entries"])


def test_the_merchant_view_never_reveals_the_budget_or_the_buyer(harness):
    mandate_id = settled_purchase(harness)

    response = harness.client.get("/ledger", params={"merchant_id": "vuelaya", "view": "merchant"})

    raw = response.text
    assert response.status_code == 200, raw
    assert mandate_id not in raw
    assert "usr_marta" not in raw
    assert "remaining" not in raw
    assert "spent" not in raw
    assert response.json()["entries"], "the merchant must still see its own sale"
    assert "budget" in " ".join(response.json()["redacted"]).lower()


def test_the_merchant_view_shows_only_its_own_sales(harness):
    settled_purchase(harness)

    response = harness.client.get("/ledger", params={"merchant_id": "other_shop", "view": "merchant"})

    assert response.json()["entries"] == []


def test_the_merchant_view_refuses_to_be_asked_by_mandate(harness):
    mandate_id = settled_purchase(harness)

    response = harness.client.get("/ledger", params={"mandate_id": mandate_id, "view": "merchant"})

    assert response.status_code == 400
    assert response.json()["reason_code"] == "merchant_view_requires_merchant_id"


def test_an_unknown_view_is_refused(harness):
    mandate_id = harness.create_mandate()

    response = harness.client.get("/ledger", params={"mandate_id": mandate_id, "view": "root"})

    assert response.status_code == 422


def test_a_mandate_snapshot_reports_the_live_budget(harness):
    mandate_id = settled_purchase(harness)

    response = harness.read_mandate(mandate_id)

    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["spent"]["minor_units"] == 13000
    assert body["remaining"]["minor_units"] == 7000
    assert body["allowed_categories"] == ["travel"]


def test_the_snapshot_budget_follows_the_live_limit(harness):
    mandate_id = settled_purchase(harness)

    harness.change_limit(mandate_id, 15000)

    body = harness.read_mandate(mandate_id).json()
    assert body["limit"]["minor_units"] == 15000
    assert body["remaining"]["minor_units"] == 2000


def test_an_unknown_mandate_has_no_trail_to_read(harness):
    assert harness.human_ledger("nope").status_code == 404
    assert harness.client.get("/ledger/verify", params={"mandate_id": "nope"}).status_code == 404


def test_one_purchase_does_not_look_like_two_on_the_trail(harness):
    """The decision and the commit are different facts and must read differently.

    Naming both `purchase_authorized` made a single purchase look like two attempts to
    anyone reading the auditor view, which is the one thing that view exists for.
    """
    mandate_id = harness.create_mandate()
    body = harness.purchase(mandate_id)
    harness.authorize(body)
    harness.capture(body | {"idempotency_key": "cap_once_only"})

    types = [entry["event_type"] for entry in auditor_entries(harness, mandate_id)]

    assert types == [
        "mandate_registered",
        "purchase_authorized",
        "purchase_committed",
        "purchase_settled",
    ]
