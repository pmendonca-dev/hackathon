"""An offer is a thing that can be spent once, by every road into the system.

The merchant's whole guarantee is that the proof it accepts covers the offer it signed.
That guarantee is only worth something if the `terms_hash` inside the proof came from an
offer this edge actually verified. When the buyer could name the hash itself, it could
mint a proof for an offer whose nonce was never spent — and `/merchant/verify` accepted
the same signed offer twice, then a third time, with every one of its five checks green.

The offer is bound at the edge or it is not bound at all.
"""

from __future__ import annotations

from typing import Any

from aval.api.offer_binding import unverified_offer_claims
from aval.merchant.offers import terms_hash_of

from tests.integration.api.conftest import Harness


def pick(harness: Harness, sku: str) -> dict[str, Any]:
    offers = harness.client.get("/merchant/offers").json()["offers"]
    return next(offer for offer in offers if offer["item"]["sku"] == sku)


def verify(harness: Harness, proof: str, offer: dict[str, Any]) -> dict[str, Any]:
    return harness.client.post(
        "/merchant/verify",
        json={"authorization_proof": proof, "merchant_authorization": offer["merchant_authorization"]},
    ).json()


def test_the_buyer_cannot_name_the_terms_hash_and_spend_an_offer_twice(harness: Harness) -> None:
    mandate_id = harness.create_mandate(
        limit={"minor_units": 100000, "currency": "USD", "scale": 2}
    )
    offer = pick(harness, "FL-SAO-COR-0917")
    claims = unverified_offer_claims(offer["merchant_authorization"])
    assert claims is not None

    honest = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_honest"))
    assert honest.json()["approved"] is True
    assert verify(harness, honest.json()["authorization_proof"], offer)["accepted"] is True

    # The attack: drop the signed offer so its nonce is never spent, and hand the edge
    # that offer's terms hash directly.
    second = harness.capture(
        {
            "mandate_id": mandate_id,
            "checkout_id": f"chk_{offer['offer_id']}_again",
            "merchant_id": offer["merchant_id"],
            "category": offer["item"]["category"],
            "total": offer["total"],
            "idempotency_key": "cap_second",
            "terms_hash": terms_hash_of(claims),
        }
    )

    # The purchase itself is within the mandate, so it settles — what must not happen is
    # the merchant accepting it as this offer being redeemed a second time.
    assert second.json()["approved"] is True
    verdict = verify(harness, second.json()["authorization_proof"], offer)
    assert verdict["accepted"] is False
    failed = [check["name"] for check in verdict["checks"] if not check["passed"]]
    assert "terms_hash_matches" in failed


def test_a_purchase_that_carries_no_offer_is_not_verifiable_as_one(harness: Harness) -> None:
    """An unbound purchase is recorded as unbound, and says so when a merchant asks."""
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")

    unbound = harness.capture(
        {
            "mandate_id": mandate_id,
            "checkout_id": "chk_unbound",
            "merchant_id": offer["merchant_id"],
            "category": offer["item"]["category"],
            "total": offer["total"],
            "idempotency_key": "cap_unbound",
        }
    )

    assert unbound.json()["approved"] is True
    verdict = verify(harness, unbound.json()["authorization_proof"], offer)
    assert verdict["accepted"] is False
    assert "terms_hash_matches" in [c["name"] for c in verdict["checks"] if not c["passed"]]


def test_the_honest_path_still_binds_the_offer_it_bought(harness: Harness) -> None:
    """The guard must not have been bought by breaking the thing it protects."""
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")

    settled = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_bound"))

    assert settled.json()["approved"] is True
    assert verify(harness, settled.json()["authorization_proof"], offer)["accepted"] is True
