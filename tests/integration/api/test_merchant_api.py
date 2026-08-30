from __future__ import annotations

from datetime import timedelta

from aval.security.jcs import canonicalize
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk


def offers(harness) -> list[dict]:
    response = harness.client.get("/merchant/offers")
    assert response.status_code == 200, response.text
    return response.json()["offers"]


def pick(harness, sku: str) -> dict:
    return next(offer for offer in offers(harness) if offer["item"]["sku"] == sku)


def test_the_catalog_is_signed_by_the_merchant(harness):
    offer = pick(harness, "FL-SAO-COR-0917")
    jwks = harness.client.get("/merchant/.well-known/jwks.json").json()

    claims = verify_compact_jws(
        offer["merchant_authorization"], public_key_from_jwk(jwks["keys"][0])
    )

    assert claims["merchant_id"] == "vuelaya"
    assert claims["total"]["minor_units"] == 13000


def test_the_terms_hash_is_the_hash_of_the_canonical_offer(harness):
    import base64
    import hashlib

    offer = pick(harness, "FL-SAO-COR-0917")
    payload = {key: value for key, value in offer.items() if key not in ("merchant_authorization", "terms_hash")}

    digest = hashlib.sha256(canonicalize(payload)).digest()

    assert offer["terms_hash"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_every_offer_carries_a_fresh_nonce(harness):
    first = pick(harness, "FL-SAO-COR-0917")
    second = pick(harness, "FL-SAO-COR-0917")

    assert first["nonce"] != second["nonce"]


def test_a_purchase_bound_to_a_signed_offer_settles(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")

    response = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_offer"))

    assert response.status_code == 200, response.text
    assert response.json()["approved"] is True


def test_an_offer_signed_by_nobody_is_refused(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    header, payload, signature = offer["merchant_authorization"].split(".")
    offer["merchant_authorization"] = f"{header}.{('A' if payload[0] != 'A' else 'B')}{payload[1:]}.{signature}"

    response = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_forged"))

    assert response.status_code == 401
    assert response.json()["reason_code"] == "offer_signature_invalid"


def test_an_offer_whose_amount_was_edited_is_refused(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    body = harness.purchase_from_offer(mandate_id, offer, "cap_edited")
    body["total"] = {"minor_units": 100, "currency": "USD", "scale": 2}

    response = harness.capture(body)

    assert response.status_code == 409
    assert response.json()["reason_code"] == "offer_mismatch"


def test_an_expired_offer_is_refused(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")

    harness.clock.advance(timedelta(hours=1))

    response = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_stale"))

    assert response.status_code == 409
    assert response.json()["reason_code"] == "offer_expired"


def test_the_same_offer_cannot_be_spent_twice(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    first = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_once"))

    second = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_twice"))

    assert first.json()["approved"] is True
    assert second.status_code == 409
    assert second.json()["reason_code"] == "offer_replayed"


def test_the_merchant_verifies_the_purchase_it_took_part_in(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    settled = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_verify"))
    proof = settled.json()["authorization_proof"]

    response = harness.client.post(
        "/merchant/verify",
        json={"authorization_proof": proof, "merchant_authorization": offer["merchant_authorization"]},
    )

    body = response.json()
    assert body["accepted"] is True, body
    assert all(check["passed"] for check in body["checks"])
    assert {check["name"] for check in body["checks"]} == {
        "offer_signature_valid",
        "offer_within_validity",
        "authorization_proof_valid",
        "terms_hash_matches",
        "authority_still_valid",
    }


def test_the_merchant_verification_never_returns_the_mandate_or_the_buyer(harness):
    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    settled = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_privacy"))

    response = harness.client.post(
        "/merchant/verify",
        json={
            "authorization_proof": settled.json()["authorization_proof"],
            "merchant_authorization": offer["merchant_authorization"],
        },
    )

    assert mandate_id not in response.text
    assert "usr_marta" not in response.text


def test_a_proof_paired_with_a_different_offer_fails_the_terms_check(harness):
    mandate_id = harness.create_mandate()
    bought = pick(harness, "FL-SAO-COR-0917")
    settled = harness.capture(harness.purchase_from_offer(mandate_id, bought, "cap_swap"))
    other = pick(harness, "FL-SAO-BUE-1020")

    response = harness.client.post(
        "/merchant/verify",
        json={
            "authorization_proof": settled.json()["authorization_proof"],
            "merchant_authorization": other["merchant_authorization"],
        },
    )

    body = response.json()
    assert body["accepted"] is False
    failed = {check["name"] for check in body["checks"] if not check["passed"]}
    assert "terms_hash_matches" in failed


def test_verification_fails_once_the_mandate_is_revoked(harness):
    from aval.security.jws import sign_compact_jws

    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    settled = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_revoked"))
    harness.client.post(
        f"/mandates/{mandate_id}/revocation",
        json={
            "token": sign_compact_jws(
                {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder", "epoch": 1},
                harness.custody,
                harness.HOLDER_KID,
            )
        },
    )

    response = harness.client.post(
        "/merchant/verify",
        json={
            "authorization_proof": settled.json()["authorization_proof"],
            "merchant_authorization": offer["merchant_authorization"],
        },
    )

    body = response.json()
    assert body["accepted"] is False
    failed = {check["name"] for check in body["checks"] if not check["passed"]}
    assert "authority_still_valid" in failed


def test_a_lodging_offer_escalates_under_a_travel_only_mandate(harness):
    mandate_id = harness.create_mandate()
    hotel = pick(harness, "HT-COR-CENTRO")

    response = harness.authorize(harness.purchase_from_offer(mandate_id, hotel, None))

    assert response.json()["decision"] == "awaiting_human"
    assert response.json()["reason_code"] == "category_not_allowed"


def test_the_canonical_offer_is_kept_with_the_checkout(harness):
    from sqlalchemy import select

    from aval.infrastructure.sqlite.models import checkout_intents

    mandate_id = harness.create_mandate()
    offer = pick(harness, "FL-SAO-COR-0917")
    harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_canonical"))

    with harness.runtime.engine.connect() as connection:
        stored = connection.execute(select(checkout_intents.c.canonical_payload)).scalar_one()

    assert offer["offer_id"] in stored
    assert "FL-SAO-COR-0917" in stored
