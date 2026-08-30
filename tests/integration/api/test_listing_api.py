"""Listing surfaces for the human interfaces.

The bot and the browser need to answer "what mandates do I hold?" and "what is waiting
for me?" without knowing an id in advance. Both listings are **scoped to a principal**
on purpose: an unscoped dump would hand any caller every buyer in the system, their
limits and their pending purchases — the exact disclosure the merchant view exists to
prevent. There is no global listing, and the tests below are what keeps it that way.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness


def other_principal(harness: Harness) -> str:
    return harness.create_mandate(
        principal={"id": "usr_bruno", "display_name": "Bruno Alves"}
    )


def test_the_mandates_of_a_principal_are_listed_with_their_live_budget(harness: Harness) -> None:
    first = harness.create_mandate()
    second = harness.create_mandate()

    response = harness.client.get("/mandates", params={"principal_id": "usr_marta"})

    assert response.status_code == 200, response.text
    listed = response.json()["mandates"]
    assert {item["mandate_id"] for item in listed} == {first, second}
    assert listed[0]["limit"] == {"minor_units": 20000, "currency": "USD", "scale": 2}
    assert listed[0]["remaining"] == {"minor_units": 20000, "currency": "USD", "scale": 2}
    assert listed[0]["status"] == "ACTIVE"


def test_listing_mandates_without_a_principal_is_refused(harness: Harness) -> None:
    """No global dump. Every buyer in the system is not a public listing."""
    harness.create_mandate()

    response = harness.client.get("/mandates")

    assert response.status_code == 422, response.text


def test_a_mandate_listing_never_carries_another_principal(harness: Harness) -> None:
    mine = harness.create_mandate()
    theirs = other_principal(harness)

    response = harness.client.get("/mandates", params={"principal_id": "usr_marta"})

    listed = {item["mandate_id"] for item in response.json()["mandates"]}
    assert mine in listed
    assert theirs not in listed
    assert "usr_bruno" not in response.text


def test_an_unknown_principal_lists_nothing_rather_than_failing(harness: Harness) -> None:
    """A holder with no mandates yet is an empty inbox, not an error."""
    response = harness.client.get("/mandates", params={"principal_id": "usr_nobody"})

    assert response.status_code == 200, response.text
    assert response.json()["mandates"] == []


def test_pending_escalations_are_listed_for_a_principal_across_mandates(
    harness: Harness,
) -> None:
    first = harness.create_mandate()
    second = harness.create_mandate()
    for mandate_id in (first, second):
        harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.client.get("/escalations", params={"principal_id": "usr_marta"})

    assert response.status_code == 200, response.text
    escalations = response.json()["escalations"]
    assert {item["mandate_id"] for item in escalations} == {first, second}
    assert all(item["reason_code"] == "merchant_out_of_scope" for item in escalations)


def test_listing_escalations_without_any_scope_is_refused(harness: Harness) -> None:
    """Pending approvals name what somebody is about to buy. They are not a feed."""
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.client.get("/escalations")

    assert response.status_code == 422, response.text


def test_escalations_of_another_principal_are_not_listed(harness: Harness) -> None:
    mine = harness.create_mandate()
    theirs = other_principal(harness)
    harness.authorize(harness.purchase(mine, merchant_id="despegar"))
    harness.authorize(harness.purchase(theirs, merchant_id="despegar"))

    response = harness.client.get("/escalations", params={"principal_id": "usr_marta"})

    listed = {item["mandate_id"] for item in response.json()["escalations"]}
    assert listed == {mine}


def test_listing_escalations_by_mandate_still_answers_the_single_mandate(
    harness: Harness,
) -> None:
    """The existing per-mandate query keeps working; the principal filter is additive."""
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id, merchant_id="despegar"))

    response = harness.client.get("/escalations", params={"mandate_id": mandate_id})

    assert response.status_code == 200, response.text
    assert [item["mandate_id"] for item in response.json()["escalations"]] == [mandate_id]
